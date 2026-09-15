"""Synthetic list observations; these tests never use AWS or a database."""
import json
import pytest
from app.core import ops_inventory as inv

REC = 'ego_20260903_120000_ABCD'
P = f'sessions/korea/{REC}'


def obj(key, size=3):
    return {'Key': key, 'Size': size}


def test_classifies_without_merging_collision_or_validating_metadata():
    other = f'sessions/china/device/{REC}'
    result = inv.build_coverage([
        obj(P + '/clip.mp4'), obj(P + '/metadata.json'),
        obj(other + '/clip.mp4'), obj(other + '/nested/metadata.json'),
        obj('archive/take.mp4'), obj('sessions/s/_machine/status.json'),
        obj('sessions/s/.ego-s3-test/test'), obj('sessions/'),
    ], bucket='fixture', listing_complete=True)
    assert result['recognized_recording_prefixes'] == 2
    assert result['recordings_missing_metadata'] == 1
    assert result['examples']['missing_metadata_prefixes'] == [other]
    assert result['collision_recording_names'] == 1
    assert result['unrecognized_objects'] == 1
    assert result['bookkeeping_objects'] == 2
    assert result['folder_markers'] == 1
    assert result['objects_observed'] == 8
    assert result['bytes_observed'] == 24


def test_examples_bounded():
    result = inv.build_coverage([obj(f'unknown/{i}.mp4') for i in range(50)], bucket='fixture', listing_complete=True)
    assert result['unrecognized_objects'] == 50
    assert len(result['examples']['unrecognized_keys']) == 20


class Listing:
    def __init__(self, pages):
        self.pages = iter(pages)
        self.calls = []
        self.closed = False
    def list_objects_v2(self, **kwargs):
        self.calls.append(kwargs)
        value = next(self.pages)
        if isinstance(value, Exception):
            raise value
        return value
    def close(self):
        self.closed = True


def run(monkeypatch, pages):
    client = Listing(pages)
    monkeypatch.setattr(inv, '_inventory_client', lambda cfg: client)
    monkeypatch.setenv('OPS_S3_BUCKET', 'configured-only')
    return inv.inventory_coverage(), client


def test_empty_success_differs_from_denied_unknown(monkeypatch):
    empty, _ = run(monkeypatch, [{'IsTruncated': False}])
    denied, _ = run(monkeypatch, [RuntimeError('SECRET_PROVIDER_URL')])
    assert empty['listing_complete'] is True
    assert empty['objects_observed'] == denied['objects_observed'] == 0
    assert denied['listing_complete'] is False
    assert denied['stop_reason'] == 'read_error'
    assert 'unknown' in denied['limitations'][0]
    assert 'SECRET_PROVIDER_URL' not in json.dumps(denied)


def test_multiple_pages_and_partial_failure(monkeypatch):
    first = {'Contents': [obj(P + '/clip.mp4')], 'IsTruncated': True, 'NextContinuationToken': 'next'}
    report, client = run(monkeypatch, [first, {'Contents': [obj(P + '/metadata.json')], 'IsTruncated': False}])
    assert report['listing_complete'] and report['recordings_missing_metadata'] == 0
    assert client.calls[1]['ContinuationToken'] == 'next'
    assert all(c['Bucket'] == 'configured-only' and c['Prefix'] == '' for c in client.calls)
    assert client.closed
    partial, _ = run(monkeypatch, [first, RuntimeError('denied')])
    assert partial['objects_observed'] == 1
    assert partial['recordings_missing_metadata'] == 1
    assert not partial['listing_complete']
    assert 'not yet observed' in ' '.join(partial['limitations'])


@pytest.mark.parametrize('truncated,complete,reason', [(False, True, None), (True, False, 'object_limit')])
def test_exact_object_cap_uses_provider_truncation(monkeypatch, truncated, complete, reason):
    monkeypatch.setattr(inv, 'MAX_OBJECTS', 2)
    result, client = run(monkeypatch, [{'Contents': [obj('a'), obj('b')], 'IsTruncated': truncated}])
    assert result['objects_observed'] == 2
    assert result['listing_complete'] is complete
    assert result['stop_reason'] == reason
    assert len(client.calls) == 1 and client.calls[0]['MaxKeys'] == 2


@pytest.mark.parametrize('page', [{}, {'IsTruncated': True}, {'IsTruncated': True, 'NextContinuationToken': 'loop'}])
def test_bad_or_repeating_pages_never_claim_completion(monkeypatch, page):
    result, _ = run(monkeypatch, [page, page])
    assert not result['listing_complete']
    assert result['stop_reason'] == 'read_error'


def test_request_budget_even_for_empty_pages(monkeypatch):
    monkeypatch.setattr(inv, 'MAX_PAGES', 2)
    result, client = run(monkeypatch, [{'IsTruncated': True, 'NextContinuationToken': str(i)} for i in range(5)])
    assert len(client.calls) == 2
    assert not result['listing_complete']


def test_unknown_hidden_folder_is_not_assumed_bookkeeping():
    result = inv.build_coverage([obj('_unfamiliar/raw.mp4')], bucket='fixture', listing_complete=True)
    assert result['unrecognized_objects'] == 1
    assert result['bookkeeping_objects'] == 0


def test_oversized_page_is_capped(monkeypatch):
    monkeypatch.setattr(inv, 'MAX_OBJECTS', 2)
    result, _ = run(monkeypatch, [{'Contents': [obj('a'), obj('b'), obj('c')], 'IsTruncated': False}])
    assert result['objects_observed'] == 2
    assert result['stop_reason'] == 'object_limit'
    assert not result['listing_complete']


def test_client_configuration_uses_ops_credentials_and_bounded_requests(monkeypatch):
    import boto3
    from app.core.ops_s3 import OpsS3Settings
    called = {}
    class Session:
        def __init__(self, **kwargs):
            called['credentials'] = kwargs
        def client(self, name, **kwargs):
            called['config'] = kwargs['config']
            return 'fake'
    monkeypatch.setattr(boto3.session, 'Session', Session)
    cfg = OpsS3Settings('fixture', 'us-west-2', 'fixture-id', 'fixture-secret', 900)
    assert inv._inventory_client(cfg) == 'fake'
    assert called['credentials']['aws_access_key_id'] == 'fixture-id'
    assert called['config'].read_timeout == 5
    assert called['config'].connect_timeout == 3
    assert called['config'].retries['total_max_attempts'] == 1
    with pytest.raises(inv.OpsS3Unavailable):
        inv._inventory_client(OpsS3Settings('fixture', 'us-west-2', 'fixture-id', '', 900))


@pytest.mark.parametrize('bad', [None, {}, {'Key': 123, 'Size': 3},
                               {'Key': '', 'Size': 3}, {'Key': 'bad', 'Size': '3'},
                               {'Key': 'bad', 'Size': None}, {'Key': 'bad'},
                               {'Key': 'bad', 'Size': -1}, {'Key': 'bad', 'Size': True}])
def test_invalid_object_preserves_valid_prior_rows(monkeypatch, bad):
    first = {'Contents': [obj(P + '/clip.mp4')], 'IsTruncated': True, 'NextContinuationToken': 'next'}
    second = {'Contents': [obj('archive/valid.mp4'), bad, obj('after-invalid')], 'IsTruncated': False}
    result, client = run(monkeypatch, [first, second])
    assert result['objects_observed'] == 2
    assert result['bytes_observed'] == 6
    assert result['recognized_recording_prefixes'] == 1
    assert result['unrecognized_objects'] == 1
    assert result['listing_complete'] is False
    assert result['stop_reason'] == 'read_error'
    assert client.closed


@pytest.mark.parametrize('contents', [None, {}, 'SECRET', 42, (obj('tuple'),)])
def test_nonlist_contents_fails_incomplete(monkeypatch, contents):
    result, _ = run(monkeypatch, [{'Contents': contents, 'IsTruncated': False}])
    assert result['objects_observed'] == 0
    assert result['listing_complete'] is False
    assert result['stop_reason'] == 'read_error'
    assert 'unknown' in result['limitations'][0]
    assert 'SECRET' not in json.dumps(result)
