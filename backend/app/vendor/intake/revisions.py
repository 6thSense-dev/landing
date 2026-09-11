"""Append source-bound activity corrections and explain downstream invalidation."""
import copy
from app.vendor.intake.selections import digest, evaluate_selection, fields, ids, integer, run_cli, sha, text, validate_json


def revise_selection(document):
    validate_json(document)
    fields(document, {'schema', 'history', 'proposed', 'correction', 'artifacts'})
    if document['schema'] != 'intake-activity-revision/v1':
        raise ValueError('expected intake-activity-revision/v1')
    history, proposed = document['history'], document['proposed']
    if type(history) is not list or not history:
        raise ValueError('complete nonempty revision history required')
    reports = [evaluate_selection(s) for s in history]
    proposal_report = evaluate_selection(proposed)
    sid = history[0]['selection_id']
    hashes = {}
    previous = None
    for index, selection in enumerate(history, 1):
        if selection['selection_id'] != sid or selection['revision'] != index:
            raise ValueError('revision history must be one contiguous selection lineage from 1')
        if index > 1 and selection['parent']['sha256'] != digest(previous):
            raise ValueError('revision history parent hash conflict')
        hashes[index] = digest(selection); previous = selection
    if proposed['selection_id'] != sid or proposed['revision'] != len(history) + 1 or proposed['parent']['sha256'] != hashes[len(history)]:
        raise ValueError('proposed revision must bind exact preceding selection')
    if proposed['synthetic'] != history[-1]['synthetic']:
        raise ValueError('synthetic evidence cannot be promoted through a correction')
    content = lambda s: {k: v for k, v in s.items() if k not in ('revision', 'parent')}
    if content(proposed) == content(history[-1]):
        raise ValueError('revision has no substantive correction')
    correction = fields(document['correction'], {'reviewer_id', 'evidence_ids', 'reason', 'previous_sha256', 'proposed_sha256'})
    text(correction['reviewer_id']); text(correction['reason'])
    if not ids(correction['evidence_ids']):
        raise ValueError('correction evidence required')
    sha(correction['previous_sha256']); sha(correction['proposed_sha256'])
    if correction['previous_sha256'] != hashes[len(history)] or correction['proposed_sha256'] != digest(proposed):
        raise ValueError('correction receipt does not bind exact revisions')
    hashes[proposed['revision']] = digest(proposed)
    if type(document['artifacts']) is not list:
        raise ValueError('artifacts array required')
    artifacts, reasons = {}, {}
    for row in document['artifacts']:
        fields(row, {'artifact_id', 'kind', 'selection_ref', 'depends_on'})
        aid = text(row['artifact_id']); text(row['kind']); ids(row['depends_on'])
        if aid in artifacts:
            raise ValueError('duplicate artifact ID')
        artifacts[aid] = row; reasons[aid] = []
        ref = row['selection_ref']
        if ref is not None:
            fields(ref, {'selection_id', 'revision', 'sha256'})
            text(ref['selection_id']); integer(ref['revision'], 1); sha(ref['sha256'])
            if ref['selection_id'] == sid:
                if hashes.get(ref['revision']) != ref['sha256']:
                    reasons[aid].append('artifact_selection_binding_conflict')
                elif ref['revision'] != proposed['revision']:
                    reasons[aid].append('selection_revision_superseded')
        elif not row['depends_on']:
            reasons[aid].append('artifact_dependency_unknown')
    for aid, row in artifacts.items():
        if any(dep not in artifacts for dep in row['depends_on']):
            reasons[aid].append('artifact_dependency_missing')
    # Kahn elimination identifies cyclic components and their downstream dependents.
    remaining = set(artifacts)
    while remaining:
        ready = {aid for aid in remaining if not (set(artifacts[aid]['depends_on']) & remaining)}
        if not ready:
            for aid in remaining:
                reasons[aid].append('artifact_dependency_cycle')
            break
        remaining -= ready
    changed = True
    while changed:
        changed = False
        for aid, row in artifacts.items():
            if any(reasons.get(dep) for dep in row['depends_on']) and 'upstream_artifact_invalidated' not in reasons[aid]:
                reasons[aid].append('upstream_artifact_invalidated'); changed = True
    invalidations = [{'artifact_id': aid, 'status': 'invalidated' if reasons[aid] else 'not_implicated',
                      'reasons': sorted(set(reasons[aid]))} for aid in artifacts]
    conflicts = any(any('conflict' in reason or 'cycle' in reason or 'missing' in reason or 'unknown' in reason for reason in rs) for rs in reasons.values())
    return {'schema': 'intake-activity-revision-report/v1', 'status': 'dependency_conflict' if conflicts else 'revision_recorded',
            'selection_id': sid, 'revision': proposed['revision'], 'selection_sha256': digest(proposed),
            'proposed_selection_status': proposal_report['status'],
            'revision_history': copy.deepcopy([*history, proposed]), 'correction_receipt': copy.deepcopy(correction),
            'invalidations': invalidations, 'source_input': copy.deepcopy(document),
            'collector_credit': 'unchanged', 'settlement': 'unchanged', 'media_actions': [],
            'limitations': ['Invalidations are a read-only plan; no artifact is deleted or overwritten.',
                            'Not implicated does not prove cache compatibility or artifact quality.',
                            'A correction records reviewed assertions; downstream stages need new exact receipts.']}


if __name__ == '__main__':
    raise SystemExit(run_cli(revise_selection, __doc__))
