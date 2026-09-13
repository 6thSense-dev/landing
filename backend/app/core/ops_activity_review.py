"""Exact decoded-source timeline accounting, independent of physical-clock hours."""
import json
import re
from decimal import Decimal
from app.vendor.intake.selections import union, duration


def source_recordings(run):
    doc = json.loads(run.manifest_json, parse_float=Decimal)
    if not isinstance(doc, dict) or not isinstance(doc.get('recordings'), list):
        raise ValueError('Invalid source document')
    out = []
    seen = set()
    for rec in doc['recordings']:
        if not isinstance(rec, dict):
            raise ValueError('Invalid source recording')
        name = rec['recording']
        if not isinstance(name, str) or not name or name in seen:
            raise ValueError('Invalid source identity')
        seen.add(name)
        seconds = rec['source_seconds']
        if isinstance(seconds, bool) or not isinstance(seconds, (int, Decimal)):
            raise ValueError('Invalid duration')
        value = Decimal(seconds)
        if not value.is_finite() or value < 0 or value >= 10**15:
            raise ValueError('Exact nanosecond duration unavailable')
        numerator, denominator = value.as_integer_ratio()
        ns, remainder = divmod(numerator * 1000000000, denominator)
        if remainder:
            raise ValueError('Exact nanosecond duration unavailable')
        pins = rec.get('sources', [])
        if not isinstance(pins, list) or (ns > 0 and not pins):
            raise ValueError('Missing source pins')
        sources = []
        for pin in pins:
            if not isinstance(pin, dict) or any(not isinstance(pin.get(k), str) or not pin[k].strip() for k in ('bucket', 'key', 'version_id', 'sha256')):
                raise ValueError('Invalid source pin')
            if pin['version_id'] == 'null' or not re.fullmatch(r'[a-f0-9]{64}', pin['sha256']):
                raise ValueError('Unpinned source')
            sources.append({k: pin[k] for k in ('bucket', 'key', 'version_id', 'sha256')})
        out.append(dict(recording=name, source_duration_ns=str(ns), sources=sources))
    if not out:
        raise ValueError('Missing source recordings')
    return out


def summarize(recordings, intervals):
    grouped = {r['recording']: {j: [] for j in ('accepted', 'excluded', 'unknown')} for r in recordings}
    bounds = {r['recording']: int(r['source_duration_ns']) for r in recordings}
    for row in intervals:
        name = row['recording']
        start, end = int(row['start_ns']), int(row['end_ns'])
        if name not in bounds or not (0 <= start < end <= bounds[name]):
            raise ValueError('Interval must lie within its declared decoded source recording')
        grouped[name][row['judgment']].append([start, end])
    out = []
    for rec in recordings:
        groups = {j: union(spans) for j, spans in grouped[rec['recording']].items()}
        labels = list(groups)
        for i, first in enumerate(labels):
            for second in labels[i+1:]:
                a, b = groups[first], groups[second]
                x = y = 0
                while x < len(a) and y < len(b):
                    if max(a[x][0], b[y][0]) < min(a[x][1], b[y][1]):
                        raise ValueError('Contradictory judgments overlap')
                    if a[x][1] <= b[y][1]: x += 1
                    else: y += 1
        accepted, excluded = duration(groups['accepted']), duration(groups['excluded'])
        out.append({**rec, 'accepted_ns': str(accepted), 'excluded_ns': str(excluded),
                    'unknown_ns': str(int(rec['source_duration_ns']) - accepted - excluded)})
    return out


def projection(run, task_id, recordings, review):
    intervals = json.loads(review.intervals_json) if review else []
    if review:
        recordings = json.loads(review.sources_json)
    rows = summarize(recordings, intervals) if review else [
        {**r, 'accepted_ns': None, 'excluded_ns': None, 'unknown_ns': r['source_duration_ns']} for r in recordings]
    details = None if review is None else dict(revision=review.revision, manifest_sha256=review.manifest_sha256,
        criteria_version=review.criteria_version, criteria_text=review.criteria_text, criteria_sha256=review.criteria_sha256,
        reviewer_id=review.reviewer_id, reviewer_email=review.reviewer_email,
        reviewed_at=review.reviewed_at.isoformat(), intervals=intervals)
    limitations = ['Human declarations apply only to this task and decoded-source timeline; QC retention and edited-video time are separate.',
        'Physical-clock synchronization evidence is missing; unique usable hours across recordings or camera views are unknown.',
        'No collector credit, settlement, annotation quality or dataset acceptance is established.']
    return dict(run_id=run.run_id, task_id=task_id, manifest_sha256=review.manifest_sha256 if review else run.manifest_sha256, current_manifest_sha256=run.manifest_sha256,
                revision=review.revision if review else 0, review=details, recordings=rows,
                unique_usable_ns=None, timeline_basis='manifest_declared_decoded_source',
                evidence_status={'source_validation': 'unknown', 'physical_clock': 'unknown', 'playback_mapping': 'unknown'}, limitations=limitations)
