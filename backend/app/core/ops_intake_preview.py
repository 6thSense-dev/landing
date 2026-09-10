"""Project pinned local Catalog reports; no commercial rules or payment actions."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re

SCHEMA = '6thsense.ops-intake-preview/1'
MAX_BYTES = 8 * 1024 * 1024
JUDGMENTS = ('capture', 'annotation', 'dataset')
MONEY = ('obligation_minor', 'observed_settled_minor', 'settled_minor', 'outstanding_minor')


def _fields(value, required, optional=()):
    if type(value) is not dict or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise ValueError('unsupported fields')
    return value


def _text(value):
    if not isinstance(value, str) or not value.strip(): raise ValueError('nonempty string required')
    return value


def _sha(value):
    if not isinstance(value, str) or re.fullmatch('[0-9a-f]{64}', value) is None: raise ValueError('SHA256 required')
    return value


def _array(value):
    if type(value) is not list: raise ValueError('array required')
    return value


def _evidence(value):
    _array(value)
    for item in value: _text(item)
    if len(set(value)) != len(value): raise ValueError('duplicate evidence ID')
    return value


def _money(value, *, signed=False):
    if value is None: return None
    if type(value) is not int or (value < 0 and not signed): raise ValueError('money must be nonnegative exact integer')
    return str(value)


def _correction_count(value, episode_id):
    """Validate the native correction shape and append-only chain, without replaying accounting."""
    corrections = _array(value)
    head = episode_id
    identities = {episode_id}
    for correction in corrections:
        _fields(correction, ('id', 'episode_id', 'supersedes_id', 'legacy_amount_minor', 'legacy_paid', 'evidence_ids'))
        ident = _text(correction['id'])
        correction_episode = _text(correction['episode_id'])
        supersedes = _text(correction['supersedes_id'])
        if type(correction['legacy_amount_minor']) is not int or correction['legacy_amount_minor'] < 0:
            raise ValueError('correction amount must be a nonnegative exact integer')
        if type(correction['legacy_paid']) is not bool:
            raise ValueError('correction paid assertion must be boolean')
        evidence = _evidence(correction['evidence_ids'])
        if correction_episode != episode_id or supersedes != head or ident in identities or not evidence:
            raise ValueError('correction must append to an evidenced existing episode chain')
        identities.add(ident)
        head = ident
    return len(corrections)


def digest(value):
    def exact(item, depth=0):
        if depth > 80: raise ValueError('JSON too deep')
        if item is None or type(item) in (str, int, bool): return
        if type(item) is list:
            for child in item: exact(child, depth+1)
        elif type(item) is dict and all(type(k) is str for k in item):
            for child in item.values(): exact(child, depth+1)
        else: raise ValueError('exact JSON values required')
    exact(value)
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def _timestamp(value):
    _text(value)
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None: raise ValueError('timezone required')
    return dt


def unknown(reason):
    return dict(schema=SCHEMA, status='unknown', synthetic=None, generated_at=None,
                expires_at=None, valid_for_ms=0, report_sha256=None, rows=[], reasons=[reason],
                authenticity='not_verified', live_source_binding='not_verified')


def project_preview(document, *, now=None):
    """Validate bindings and display reported values, without recalculating them."""
    now = now or datetime.now(timezone.utc)
    _fields(document, ('schema', 'synthetic', 'generated_at', 'expires_at', 'catalog_revision',
                      'accounting_report', 'accounting_report_sha256', 'episode_bindings', 'judgments', 'document_sha256'))
    if document['schema'] != SCHEMA or type(document['synthetic']) is not bool: raise ValueError('unsupported preview')
    if not isinstance(document['catalog_revision'], str) or re.fullmatch('[0-9a-f]{40}', document['catalog_revision']) is None: raise ValueError('Catalog commit required')
    if _sha(document['document_sha256']) != digest({k:v for k,v in document.items() if k != 'document_sha256'}): raise ValueError('preview changed')
    generated = _timestamp(document['generated_at']); expiry = _timestamp(document['expires_at'])
    if expiry <= generated: raise ValueError('invalid preview expiry')
    if generated > now: return unknown('snapshot_from_future')
    if now >= expiry: return unknown('snapshot_stale')
    report = _fields(document['accounting_report'], ('schema_version', 'synthetic', 'accounting', 'bindings', 'imports', 'issues', 'reconciliation', 'full_preview_totals', 'report_sha256'))
    if report['schema_version'] != 'intake-accounting-import/v1' or report['synthetic'] is not document['synthetic']: raise ValueError('report schema/provenance mismatch')
    report_hash = _sha(report['report_sha256'])
    if report_hash != _sha(document['accounting_report_sha256']) or report_hash != digest({k:v for k,v in report.items() if k != 'report_sha256'}): raise ValueError('report digest mismatch')
    for imported in _array(report['imports']):
        if type(imported) is not dict or imported.get('schema_version') != 'intake-accounting-snapshot/v1' or imported.get('synthetic') is not document['synthetic']:
            raise ValueError('import version/provenance mismatch')
        if _sha(imported.get('snapshot_sha256')) != digest({k:v for k,v in imported.items() if k != 'snapshot_sha256'}): raise ValueError('import source changed')
    if type(report['bindings']) is not dict or type(report['accounting']) is not dict: raise ValueError('report bindings required')
    native = {}
    for ep in _array(report['accounting'].get('episodes')):
        if type(ep) is not dict: raise ValueError('accounting episode required')
        ident = _text(ep.get('id'))
        if ident in native: raise ValueError('duplicate native episode')
        native[ident] = ep
    bindings = {}
    for row in _array(document['episode_bindings']):
        _fields(row, ('episode_id', 'recording_id', 'source_sha256'))
        _text(row['episode_id']); _text(row['recording_id']); _sha(row['source_sha256'])
        if row['episode_id'] in bindings: raise ValueError('duplicate expected episode binding')
        bindings[row['episode_id']] = row
    _fields(document['judgments'], JUDGMENTS)
    judgments = {kind:{} for kind in JUDGMENTS}
    for kind in JUDGMENTS:
        for row in _array(document['judgments'][kind]):
            _fields(row, ('id', 'episode_id', 'source_sha256', 'accounting_report_sha256', 'status', 'evidence_ids', 'reason'))
            for key in ('id', 'episode_id', 'reason'): _text(row[key])
            _sha(row['source_sha256']); _sha(row['accounting_report_sha256']); _evidence(row['evidence_ids'])
            if row['episode_id'] not in native: raise ValueError('judgment episode missing')
            if row['status'] not in ('accepted', 'rejected', 'pending', 'unknown'): raise ValueError('unsupported judgment')
            judgments[kind].setdefault(row['episode_id'], []).append(row)
    reconciliation = _fields(report['reconciliation'], ('episodes', 'totals', 'issues'))
    output = []; seen = set()
    for row in _array(reconciliation['episodes']):
        _fields(row, ('id', 'collector_id', 'currency', *MONEY, 'legacy_assertions', 'corrections', 'reasons'))
        ep = _text(row['id']); _text(row['collector_id'])
        if ep in seen or ep not in native or row['currency'] != 'KRW' or (native[ep].get('collector_id'),native[ep].get('currency')) != (row['collector_id'],row['currency']): raise ValueError('reconciliation identity conflict')
        seen.add(ep)
        source = _fields(report['bindings'].get(ep), ('recording_id', 'sha256'))
        _text(source['recording_id']); _sha(source['sha256'])
        expected = bindings.get(ep)
        source_ok = expected == dict(episode_id=ep, recording_id=source['recording_id'], source_sha256=source['sha256'])
        values = {field:_money(row[field], signed=field == 'observed_settled_minor') for field in MONEY}
        decisions = {}
        for kind in JUDGMENTS:
            candidates = judgments[kind].get(ep, [])
            status = 'unknown'; reason = 'judgment_not_supplied'; evidence_ids = []
            if not source_ok: reason = 'episode_source_binding_conflict'
            elif len(candidates) > 1: reason = 'conflicting_judgment_records'
            elif candidates:
                claim = candidates[0]
                if claim['source_sha256'] != source['sha256'] or claim['accounting_report_sha256'] != report_hash: reason = 'judgment_binding_conflict'
                elif not claim['evidence_ids']: reason = 'judgment_evidence_missing'
                else: status=claim['status']; reason=claim['reason']; evidence_ids=claim['evidence_ids']
            decisions[kind] = dict(status=status, reason=reason, evidence_ids=evidence_ids)
        assertions = _fields(row['legacy_assertions'], (), ('legacy_amount_minor', 'legacy_paid'))
        legacy_amount = _money(assertions.get('legacy_amount_minor'))
        legacy_paid = assertions.get('legacy_paid')
        if legacy_paid is not None and type(legacy_paid) is not bool: raise ValueError('paid assertion must be boolean')
        _evidence(row['reasons'])
        correction_count = _correction_count(row['corrections'], ep)
        output.append(dict(episode_id=ep, recording_id=source['recording_id'], source_sha256=source['sha256'], collector_id=row['collector_id'],
            source_binding='matched_supplied_report' if source_ok else 'conflict', currency='KRW',
            credit_minor=values['obligation_minor'] if source_ok else None,
            observed_settled_minor=values['observed_settled_minor'] if source_ok else None,
            settled_minor=values['settled_minor'] if source_ok else None,
            outstanding_minor=values['outstanding_minor'] if source_ok else None,
            legacy_amount_minor=legacy_amount if source_ok else None,
            legacy_paid=legacy_paid if source_ok else None,
            correction_count=correction_count if source_ok else None,
            judgments=decisions, reasons=row['reasons'] + ([] if source_ok else ['episode_source_binding_conflict'])))
    if seen != set(native) or set(report['bindings']) != seen or set(bindings) != seen: raise ValueError('episode coverage mismatch')
    _array(report['issues'])
    return dict(schema=SCHEMA, status='supplied_preview', synthetic=document['synthetic'], generated_at=document['generated_at'], expires_at=document['expires_at'],
                valid_for_ms=max(0, int((expiry-now).total_seconds()*1000)), report_sha256=report_hash, rows=output, reasons=['export_authenticity_not_verified', 'live_recording_bytes_not_verified'] + (['accounting_import_issues_unresolved'] if report['issues'] else []),
                authenticity='not_verified', live_source_binding='not_verified')


def load_configured_preview(*, path=None, expected_sha256=None, now=None):
    path = path if path is not None else os.environ.get('OPS_INTAKE_PREVIEW_PATH')
    expected_sha256 = expected_sha256 if expected_sha256 is not None else os.environ.get('OPS_INTAKE_PREVIEW_SHA256')
    if not path: return unknown('snapshot_not_configured')
    if not expected_sha256: return unknown('snapshot_pin_not_configured')
    try:
        _sha(expected_sha256)
        file = Path(path)
        if any(part.is_symlink() for part in [file,*file.parents]) or not file.is_file(): raise ValueError('regular local snapshot required')
        with file.open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES or hashlib.sha256(raw).hexdigest() != expected_sha256: raise ValueError('snapshot pin mismatch')
        def unique(pairs):
            value = {}
            for key, item in pairs:
                if key in value: raise ValueError('duplicate JSON key')
                value[key] = item
            return value
        doc = json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
        return project_preview(doc, now=now)
    except (ValueError, OSError, TypeError, KeyError, RecursionError, OverflowError):
        return unknown('snapshot_invalid_or_unavailable')
