"""Source-bound candidate activities; coverage never establishes task usefulness."""
import argparse
import copy
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from app.vendor.intake.timeline import reconstruct_timeline

ROLES = {'action', 'failed_attempt', 'preparation', 'cleanup', 'carrying',
         'natural_pause', 'waiting', 'empty_hand_travel', 'unknown'}
OUTCOMES = {'success', 'failure', 'partial', 'unknown', 'not_applicable'}


def validate_json(value):
    active, pending = set(), [(value, 0, False)]
    while pending:
        item, depth, leaving = pending.pop()
        if leaving:
            active.remove(id(item))
            continue
        if depth > 96:
            raise ValueError('JSON nesting exceeds 96 levels')
        if item is None or type(item) in (str, int, bool):
            continue
        if type(item) is float and math.isfinite(item):
            continue
        if type(item) not in (dict, list) or id(item) in active:
            raise ValueError('finite acyclic JSON required')
        if type(item) is dict and any(type(k) is not str for k in item):
            raise ValueError('JSON keys must be strings')
        active.add(id(item))
        pending.append((item, depth, True))
        pending.extend((v, depth + 1, False) for v in (item.values() if type(item) is dict else item))


def fields(value, required, optional=()):
    if type(value) is not dict or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise ValueError('expected fields: ' + ', '.join(sorted(required)))
    return value


def text(value):
    if type(value) is not str or not value or value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('nonempty unpadded text without controls required')
    return value


def integer(value, minimum=None):
    if type(value) is not int or (minimum is not None and value < minimum):
        raise ValueError('integer outside permitted range')
    return value


def ids(value):
    if type(value) is not list:
        raise ValueError('ID array required')
    for item in value:
        text(item)
    if len(set(value)) != len(value):
        raise ValueError('duplicate IDs')
    return value


def sha(value):
    if type(value) is not str or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('lowercase SHA256 required')
    return value


def digest(value):
    validate_json(value)
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def interval(value):
    if type(value) is not list or len(value) != 2:
        raise ValueError('half-open [start_ns,end_ns] required')
    start, end = (integer(x) for x in value)
    if end <= start:
        raise ValueError('positive interval extent required')
    return value


def union(spans):
    merged = []
    for start, end in sorted(interval(s) for s in spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def duration(spans):
    return sum(end - start for start, end in union(spans))


def covered(span, spans):
    return any(start <= span[0] and span[1] <= end for start, end in union(spans))


def evaluate_selection(document):
    validate_json(document)
    fields(document, {'schema', 'selection_id', 'revision', 'parent', 'synthetic',
                      'timeline_report', 'timeline_sha256', 'physical_id', 'target_clock_id', 'spans', 'task_ids'})
    if document['schema'] != 'intake-activity-selection/v1' or type(document['synthetic']) is not bool:
        raise ValueError('selection schema and explicit synthetic flag required')
    for key in ('selection_id', 'physical_id', 'target_clock_id'):
        text(document[key])
    revision = integer(document['revision'], 1)
    parent = document['parent']
    if revision == 1:
        if parent is not None:
            raise ValueError('initial revision cannot have a parent')
    else:
        fields(parent, {'revision', 'sha256'})
        if integer(parent['revision'], 1) != revision - 1:
            raise ValueError('parent must be preceding revision')
        sha(parent['sha256'])
    ids(document['task_ids'])
    report = document['timeline_report']
    if type(report) is not dict or report.get('schema') != 'intake-timeline-report/v1':
        raise ValueError('frozen A03 timeline report required')
    if type(report.get('synthetic')) is not bool or report['synthetic'] != document['synthetic']:
        raise ValueError('timeline synthetic provenance mismatch')
    sha(document['timeline_sha256'])
    issues = []
    if digest(report) != document['timeline_sha256']:
        issues.append('timeline_hash_mismatch')
    rebuilt = reconstruct_timeline(report.get('source_input'))
    if digest(report) != digest(rebuilt):
        issues.append('timeline_report_reconstruction_conflict')
    groups, sources = {}, {}
    for group in rebuilt['physical_recordings']:
        pid = group['physical_id']
        groups[pid] = group
    for source in rebuilt['segments']:
        sid = source['segment_id']
        sources[sid] = source
    group = groups.get(document['physical_id'])
    if group is None:
        issues.append('physical_recording_missing')
    elif group.get('status') == 'conflict':
        issues.append('physical_recording_conflict')
    if type(document['spans']) is not list:
        raise ValueError('selection spans array required')
    rows, seen = [], set()
    for span in document['spans']:
        fields(span, {'span_id', 'interval_ns', 'segment_ids', 'role', 'outcome', 'evidence_ids', 'uncertainty_reasons'})
        sid = text(span['span_id'])
        if sid in seen:
            raise ValueError('duplicate selection span ID')
        seen.add(sid)
        bounds = interval(span['interval_ns'])
        source_ids = ids(span['segment_ids'])
        evidence = ids(span['evidence_ids'])
        uncertainties = ids(span['uncertainty_reasons'])
        if text(span['role']) not in ROLES or text(span['outcome']) not in OUTCOMES:
            raise ValueError('unsupported role/outcome')
        reasons = list(issues)
        available = []
        if not source_ids:
            reasons.append('source_segments_missing')
        for source_id in source_ids:
            source = sources.get(source_id)
            if source is None:
                reasons.append('source_segment_missing')
            elif source.get('status') != 'reconstructed_from_supplied_evidence':
                reasons.append('source_segment_unresolved')
            elif source.get('physical_id') != document['physical_id'] or source.get('target_clock_id') != document['target_clock_id']:
                reasons.append('source_clock_or_physical_conflict')
            else:
                available.extend(source['spans_ns'])
        if not covered(bounds, available):
            unresolved = any(r in reasons for r in ('source_segments_missing', 'source_segment_missing', 'source_segment_unresolved'))
            reasons.append('source_coverage_unresolved' if unresolved else 'span_outside_evidenced_coverage')
        if not evidence:
            reasons.append('activity_evidence_missing')
        if uncertainties:
            reasons.append('activity_uncertainty_unresolved')
        conflict = bool(issues) or any(x in reasons for x in ('timeline_hash_mismatch', 'physical_recording_conflict',
                                              'source_clock_or_physical_conflict', 'span_outside_evidenced_coverage'))
        rows.append({'span_id': sid, 'status': 'conflict' if conflict else 'unknown' if reasons else 'candidate',
                     'reasons': sorted(set(reasons)), 'interval_ns': bounds})
    accepted = [r['interval_ns'] for r in rows if r['status'] == 'candidate']
    spans = union(accepted)
    known = duration(spans)
    state = 'conflict' if any(r['status'] == 'conflict' for r in rows) or issues else 'candidate' if rows and all(r['status'] == 'candidate' for r in rows) else 'unknown'
    return {'schema': 'intake-activity-selection-report/v1', 'selection_id': document['selection_id'],
            'revision': revision, 'selection_sha256': digest(document), 'status': state,
            'spans': rows, 'candidate_spans_ns': spans, 'known_candidate_duration_ns': known,
            'candidate_duration_ns': known if state == 'candidate' else None,
            'gaps_ns': [[a[1], b[0]] for a, b in zip(spans, spans[1:])],
            'usable_duration_ns': None, 'collector_credit': 'not_evaluated',
            'annotation_acceptance': 'not_evaluated', 'dataset_acceptance': 'not_evaluated',
            'source_manifest': copy.deepcopy(document),
            'limitations': ['Supplied source/evidence assertions are not authenticated.',
                            'Candidate coverage does not establish task usefulness.',
                            'No media, model, payment or raw mutation performed.']}


def _unique(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError('duplicate JSON member: ' + key)
        out[key] = value
    return out


def run_cli(function, description, argv=None):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('input', help='local JSON file or - for stdin')
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.read() if args.input == '-' else Path(args.input).read_text(encoding='utf-8')
        value = json.loads(raw, object_pairs_hook=_unique)
        result = function(value)
        validate_json(result)
        print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
        return 0
    except (ValueError, TypeError, KeyError, OSError, RecursionError) as exc:
        print('invalid activity input: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(run_cli(evaluate_selection, __doc__))
