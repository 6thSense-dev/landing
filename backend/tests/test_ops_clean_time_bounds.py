"""Synthetic QC boundary cases; never repairs or reads production footage."""
import copy
import hashlib
import io
import json

import pytest
from app.core import ops_clean
from tests.test_ops_clean import manifest


def one_second():
    doc = manifest()
    doc.update(source_seconds=1, retained_seconds=1, rejected_seconds=0)
    doc['recordings'][0].update(source_seconds=1, intervals=[
        {'start_s': 0, 'end_s': 1, 'disposition': 'keep'}])
    return doc


@pytest.mark.parametrize('start,end', [(-.01, 1), (0, 1.01), (1.001, 1.01), (-.01, -.005)])
def test_outside_source_rejected_even_inside_rounding_tolerances(start, end):
    doc = one_second()
    doc['retained_seconds'] = end - start
    doc['recordings'][0]['intervals'][0].update(start_s=start, end_s=end)
    with pytest.raises(ValueError):
        ops_clean.validate_manifest(doc)


def test_exact_boundary_and_empty_zero_duration_are_preserved():
    doc = one_second()
    before = copy.deepcopy(doc)
    assert ops_clean.validate_manifest(doc) == before
    doc.update(source_seconds=0, retained_seconds=0, outputs=[])
    doc['recordings'][0].update(source_seconds=0, intervals=[], sources=[])
    assert ops_clean.validate_manifest(doc) is doc


@pytest.mark.parametrize('value', [True, False, None, [], '1', float('inf'), float('nan'), 10**400])
def test_invalid_recording_duration_is_validation_error(value):
    doc = one_second()
    doc['recordings'][0]['source_seconds'] = value
    with pytest.raises(ValueError):
        ops_clean.validate_manifest(doc)


@pytest.mark.parametrize('path,value', [
    (('run_id',), []), (('device_id',), {}),
    (('recordings',), {}), (('recordings',), [None]),
    (('recordings', 0, 'intervals'), {}), (('recordings', 0, 'intervals'), [None]),
    (('recordings', 0, 'sources'), None), (('recordings', 0, 'sources'), [False]),
    (('recordings', 0, 'sources', 0, 'key'), []),
    (('recordings', 0, 'sources', 0, 'version_id'), []),
    (('recordings', 0, 'sources', 0, 'sha256'), []),
    (('outputs',), {}), (('outputs',), [None]),
    (('outputs', 0, 'key'), None), (('outputs', 0, 'version_id'), {}),
    (('outputs', 0, 'sha256'), []), (('outputs', 0, 'bytes'), True),
    (('outputs', 0, 'bytes'), float('nan')),
])
def test_malformed_structures_fail_with_value_error(path, value):
    doc = one_second()
    target = doc
    for field in path[:-1]:
        target = target[field]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        ops_clean.validate_manifest(doc)


def test_existing_partition_tolerance_is_not_reinterpreted():
    doc = manifest()
    doc['recordings'][0]['intervals'][1]['start_s'] = 60.01
    doc['rejected_seconds'] = 39.99
    assert ops_clean.validate_manifest(doc) is doc


def test_invalid_run_does_not_hide_unrelated_committed_result(monkeypatch):
    bad = one_second()
    bad['recordings'][0]['intervals'] = [None]
    good = manifest('good')
    bodies = {d['run_id']: json.dumps(d).encode() for d in (bad, good)}

    class S3:
        def get_paginator(self, name):
            return self
        def paginate(self, **kwargs):
            return [{'Contents': [{'Key': f'qc-results/{run}/_SUCCESS.json'} for run in bodies]}]
        def get_object(self, **kwargs):
            run = kwargs['Key'].split('/')[1]
            body = bodies[run]
            if kwargs['Key'].endswith('_SUCCESS.json'):
                body = json.dumps({'manifest': {'key': f'qc-results/{run}/result.json',
                    'version_id': 'v1', 'sha256': hashlib.sha256(body).hexdigest()}}).encode()
            return {'ContentLength': len(body), 'Body': io.BytesIO(body), 'VersionId': 'v1'}
        def head_object(self, **kwargs):
            return {'ContentLength': 100, 'Metadata': {'sha256': 'b' * 64}}

    monkeypatch.setattr(ops_clean, '_client', lambda _: S3())
    results = ops_clean.committed_results()
    assert [entry[0]['run_id'] for entry in results] == ['good']
    assert results.errors == [{'marker': 'qc-results/factory-test/_SUCCESS.json', 'error': 'ValueError'}]
