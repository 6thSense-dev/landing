"""Sieve inherits only committed Clean versions; stereo never doubles time."""
import copy
import io
import json
import hashlib
from datetime import datetime, timezone

import pytest
from botocore.exceptions import ClientError
from app.core import ops_sieve as sieve
from app.models import CleanRun, Episode, Wearer, OpsSetting
from tests.test_ops_routes import app, _sid, _client
from tests.test_ops_artifacts import multimodal_manifest, calibration_fixture


class Storage:
    def __init__(self):
        self.objects, self.reads, self.copies = {}, [], []

    def add(self, key, body, bucket='6thsense-processed', metadata=None):
        ref = dict(bucket=bucket, key=key, version_id=f'v{len(self.objects)}', bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
        self.objects[bucket, key] = (body, ref, metadata or {'sha256': ref['sha256']})
        return ref

    def lookup(self, Bucket, Key, VersionId=None):
        self.reads.append((Bucket, Key, VersionId))
        assert Bucket in ('6thsense-processed', '6thsense-sieve'), 'Attempted a Raw read'
        if (Bucket, Key) not in self.objects:
            raise ClientError({'Error': {'Code': 'NoSuchKey'}}, 'GetObject')
        body, ref, meta = self.objects[Bucket, Key]
        if VersionId and VersionId != ref['version_id']:
            raise ClientError({'Error': {'Code': 'NoSuchVersion'}}, 'GetObject')
        return body, ref, meta

    def get_object(self, **kw):
        body, ref, meta = self.lookup(**kw)
        return dict(Body=io.BytesIO(body), ContentLength=len(body), VersionId=ref['version_id'])

    def head_object(self, **kw):
        if kw['Bucket'] == sieve.BUCKET and (kw['Bucket'], kw['Key']) not in self.objects:
            raise ClientError({'Error': {'Code': '403'}}, 'HeadObject')
        body, ref, meta = self.lookup(**kw)
        return dict(ContentLength=len(body), VersionId=ref['version_id'], Metadata=meta)

    def list_objects_v2(self, Bucket, Prefix, MaxKeys):
        assert Bucket == sieve.BUCKET and Prefix.startswith(sieve.PREFIX)
        return {'Contents': [{'Key': k} for b,k in sorted(self.objects) if b == Bucket and k.startswith(Prefix)][:MaxKeys]}

    def copy(self, source, bucket, key, ExtraArgs, Config):
        body, ref, meta = self.lookup(**source)
        self.copies.append((source, bucket, key, Config))
        self.add(key, body, bucket, ExtraArgs['Metadata'])

    def put_object(self, Bucket, Key, Body, Metadata, ContentType, IfNoneMatch=None):
        if IfNoneMatch and (Bucket, Key) in self.objects:
            raise ClientError({'Error': {'Code': 'PreconditionFailed'}}, 'PutObject')
        ref = self.add(Key, Body, Bucket, Metadata)
        return {'VersionId': ref['version_id']}


def fixture():
    storage, doc = Storage(), multimodal_manifest()
    rec = doc['recordings'][0]
    base = f"clean/{doc['run_id']}/{rec['recording']}/"
    for o in doc['outputs']:
        o['key'] = base + ('calibration.json' if o['role'] == 'calibration' else o['key'].split('/')[-1])
        if o['role'] == 'calibration':
            body = json.dumps(calibration_fixture()).encode()
        else:
            body = b'test content'
        ref = storage.add(o['key'], body)
        o.update({k: ref[k] for k in ('version_id', 'sha256', 'bytes')})
    meta = storage.add(base+'metadata.json', b'{"device":"ABC123"}')
    provenance = {'schema': '6thsense-clean-source-metadata/1', 'run_id': doc['run_id'], 'recording': rec['recording'],
                  'source_media': [{k: s[k] for k in ('bucket', 'key', 'version_id')} for s in rec['sources']],
                  'copy_mode': 'byte_exact_from_versioned_source', 'metadata': meta, 'source_metadata': [dict(meta, bucket='6thsense-raw')]}
    storage.add(base+'metadata-provenance.json', sieve.encoded(provenance))
    ref = storage.add(f"qc-results/{doc['run_id']}/result.json", sieve.encoded(doc))
    storage.add(f"qc-results/{doc['run_id']}/_SUCCESS.json", sieve.encoded({'manifest': ref}))
    row = dict(run_id=doc['run_id'], recording=rec['recording'], manifest_key=ref['key'], manifest_version=ref['version_id'], manifest_sha256=ref['sha256'],
               doc=doc, rec=rec, entity={'id':'wearer:1','name':'Contributor','kind':'Contributor'}, country='Korea', activity='Unclassified', camera='ABC123', format='Split stereo',
               retained_seconds=60, revision='revision', clean_date='2026-09-15')
    return storage, row


@pytest.mark.parametrize('country', ['Korea', 'India'])
def test_copy_is_clean_only_idempotent_and_committed_after_all_files(country):
    s3, row = fixture()
    row['country'] = country
    result = sieve.copy_recording(s3, row)
    assert result['status'] == 'inherited'
    assert len(s3.copies) == 5
    assert {s['Bucket'] for s, _, _, _ in s3.copies} == {'6thsense-processed'}
    assert {key.split('/')[-1] for _, _, key, _ in s3.copies} == {'left.mp4','right.mp4','metadata.json','metadata-provenance.json','calibration.json'}
    assert all(config.multipart_threshold < 5*1024**3 for _, _, _, config in s3.copies)
    again = sieve.copy_recording(s3, row)
    assert result['receipt'] == again['receipt'] and len(s3.copies) == 5
    report = sieve.summarize([row], {'recordings': {row['recording']: result}})
    assert report['totals']['clean_seconds'] == report['totals']['inherited_seconds'] == 60
    assert report['acceptance']['status'] == 'not_recorded'


@pytest.mark.parametrize('country', ['China', 'Vietnam', 'Unclassified', ''])
def test_ineligible_country_copy_is_rejected_before_storage_access(country):
    s3, row = fixture()
    row['country'] = country
    with pytest.raises(ValueError, match='requires India or Korea'):
        sieve.copy_recording(s3, row)
    assert s3.reads == [] and s3.copies == []


@pytest.mark.asyncio
@pytest.mark.parametrize('business', [False, True])
@pytest.mark.parametrize('country,eligible', [('china', False), ('vietnam', False), ('unknown', False), ('india', True), ('korea', True)])
async def test_country_eligibility_preserves_clean_run(db_session, business, country, eligible):
    _, row = fixture()
    doc = row['doc']
    if business:
        doc['counterparty'] = {'id': 'test-business', 'name': 'Test business', 'country': country}
    else:
        for source in doc['recordings'][0]['sources']:
            source['key'] = f'sessions/{country}-collection/original.mp4'
    run = CleanRun(run_id=doc['run_id'], device_id='ABC123', manifest_key='key',
                   manifest_version='v', manifest_sha256='a'*64, manifest_json=json.dumps(doc),
                   retained_seconds=60, rejected_seconds=40, rate_krw_hour=11000)
    db_session.add(run)
    await db_session.commit()
    assert len(await sieve.inventory(db_session)) == int(eligible)
    assert await db_session.get(CleanRun, run.run_id) is run


@pytest.mark.parametrize('fault', ['missing_metadata','foreign_metadata','changed_source','wrong_calibration','wrong_manifest','unassigned','destination_conflict'])
def test_no_completed_receipt_when_required_evidence_fails(fault):
    s3, row = fixture()
    base = f"clean/{row['run_id']}/{row['recording']}/"
    if fault == 'missing_metadata': del s3.objects['6thsense-processed', base+'metadata.json']
    if fault == 'foreign_metadata':
        p, _, _ = s3.lookup('6thsense-processed', base+'metadata-provenance.json')
        data = json.loads(p); data['metadata']['bucket'] = '6thsense-raw'
        s3.add(base+'metadata-provenance.json', sieve.encoded(data))
    if fault == 'changed_source': s3.add(row['doc']['outputs'][0]['key'], b'changed')
    if fault == 'wrong_calibration':
        body, ref, meta = s3.objects['6thsense-processed', base+'calibration.json']
        value = json.loads(body); value['device_id'] = 'FFFFFF'
        s3.objects['6thsense-processed', base+'calibration.json'] = (sieve.encoded(value), ref, meta)
    if fault == 'wrong_manifest': row['manifest_sha256'] = 'f'*64
    if fault == 'unassigned': row['entity']['id'] = 'unassigned'
    if fault == 'destination_conflict':
        original_copy = s3.copy
        def corrupt(*args, **kw):
            original_copy(*args, **kw)
            _, bucket, key = args
            s3.objects[bucket,key][2]['clean-source'] = 'conflict'
        s3.copy = corrupt
    with pytest.raises((ValueError, ClientError)):
        sieve.copy_recording(s3, row)
    assert not any(bucket == sieve.BUCKET and key.endswith('/manifest.json') for bucket,key in s3.objects)


def test_changed_revision_cannot_keep_old_inherited_hours():
    _, row = fixture()
    report = sieve.summarize([row], {'recordings': {row['recording']: {'revision':'old','status':'inherited','copied_bytes':100}}})
    assert report['totals']['inherited_seconds'] == 0
    assert report['totals']['copied_bytes'] == 0
    assert report['recordings'][0]['status'] == 'pending'


def test_expiry_is_end_of_september_25_los_angeles():
    assert sieve.availability(datetime(2026,9,26,6,59,59,tzinfo=timezone.utc))['visible']
    assert not sieve.availability(datetime(2026,9,26,7,tzinfo=timezone.utc))['visible']
    assert sieve.availability()['contract_ends_on'] == '2026-09-22'


@pytest.mark.asyncio
async def test_roles_and_expired_api(app, db_session, monkeypatch):
    monkeypatch.setattr(sieve, 'availability', lambda: {'visible': True})
    guest, ops = await _sid(db_session,'guest'), await _sid(db_session,'ops')
    async with _client(app) as client:
        for path in ('state','availability'):
            assert (await client.get('/api/ops/sieve/'+path)).status_code == 401
            assert (await client.get('/api/ops/sieve/'+path,cookies={'sid':guest})).status_code == 403
            assert (await client.get('/api/ops/sieve/'+path,cookies={'sid':ops})).status_code == 200
        monkeypatch.setattr(sieve,'availability',lambda: {'visible': False})
        assert (await client.get('/api/ops/sieve/state',cookies={'sid':ops})).status_code == 410


@pytest.mark.asyncio
async def test_inventory_excludes_deleted_and_deduplicates_sources(db_session):
    _, row = fixture()
    row['doc']['country'] = 'korea'
    person = Wearer(name='Contributor'); db_session.add(person); await db_session.flush()
    for index in range(3):
        doc = copy.deepcopy(row['doc'])
        doc['run_id'] = f'run-{index}'
        rec = doc['recordings'][0]
        rec['recording'] += f'_s0{index+1}'
        if index == 2: rec['sources'][0]['sha256'] = 'f'*64
        db_session.add(CleanRun(run_id=doc['run_id'],device_id='ABC123',wearer_id=person.id,manifest_key='key',manifest_version='v',manifest_sha256='a'*64,manifest_json=json.dumps(doc),retained_seconds=60,rejected_seconds=40,rate_krw_hour=11000))
        db_session.add(Episode(recording=rec['recording'],deleted_at=datetime.now(timezone.utc) if index == 2 else None,delete_kind='hard' if index == 2 else None))
    await db_session.commit()
    rows = await sieve.inventory(db_session)
    assert len(rows) == 1
    assert rows[0]['retained_seconds'] == 60 and rows[0]['activity'] == 'Unclassified'


@pytest.mark.asyncio
@pytest.mark.parametrize('owner', ['run', 'episode'])
async def test_sieve_wearer_exclusion_blocks_historical_aliases_without_removing_clean(db_session, owner):
    _, row = fixture()
    person = Wearer(name='Residential contributor'); db_session.add(person); await db_session.flush()
    db_session.add(OpsSetting(key=sieve.EXCLUSIONS_KEY, value=json.dumps({
        'schema':'6thsense-sieve-delivery-exclusions/1',
        'wearers':{str(person.id):{'reason':'Residential footage; excluded by user'}}})))
    for index in range(3):
        doc = copy.deepcopy(row['doc']); doc['run_id'] = f'exclusion-{index}'
        doc['counterparty'] = {'id':'business','name':'Business','country':'korea'}
        rec = doc['recordings'][0]; rec['recording'] += f'_s{index+1:02d}'
        if index == 2: rec['sources'][0]['sha256'] = 'e'*64
        run = CleanRun(run_id=doc['run_id'], device_id='ABC123',
            wearer_id=person.id if index == 0 and owner == 'run' else None,
            manifest_key='key', manifest_version='v', manifest_sha256='a'*64,
            manifest_json=json.dumps(doc), retained_seconds=60, rejected_seconds=0, rate_krw_hour=11000)
        db_session.add(run)
        db_session.add(Episode(recording=rec['recording'],
            wearer_id=person.id if index == 0 and owner == 'episode' else None))
    await db_session.commit()
    rows = await sieve.inventory(db_session)
    assert [row['run_id'] for row in rows] == ['exclusion-2']
    for index in range(3): assert await db_session.get(CleanRun, f'exclusion-{index}') is not None


@pytest.mark.asyncio
async def test_invalid_sieve_exclusion_policy_holds_delivery(db_session):
    db_session.add(OpsSetting(key=sieve.EXCLUSIONS_KEY, value='{"wearers": []}'))
    await db_session.commit()
    with pytest.raises(ValueError, match='exclusion policy is invalid'):
        await sieve.inventory(db_session)


@pytest.mark.asyncio
async def test_new_exclusion_prevents_copy_from_an_earlier_inventory(db_session, monkeypatch):
    storage, row = fixture()
    calls = 0
    async def changed_inventory(db):
        nonlocal calls
        calls += 1
        return [row] if calls == 1 else []
    monkeypatch.setattr(sieve, 'inventory', changed_inventory)
    monkeypatch.setattr(sieve, 'storage_client', lambda: storage)
    await sieve.sync_once()
    assert calls >= 2 and storage.copies == []
    index = json.loads(storage.objects[sieve.BUCKET, sieve.PREFIX+'latest.json'][0])
    assert index['recordings'] == []


@pytest.mark.parametrize('nested', [False, True])
def test_committed_revision_video_paths_are_inherited(nested):
    s3, row = fixture()
    for o in row['doc']['outputs']:
        if o['role'] in ('left_video','right_video'):
            original = o['key']
            o['key'] = original.replace('/factory-test/', '/factory-test/revisions/review-v2/')
            if nested: o['key'] = o['key'].rsplit('/',1)[0] + '/boundary-v2/' + o['key'].rsplit('/',1)[1]
            s3.objects['6thsense-processed',o['key']] = s3.objects.pop(('6thsense-processed',original))
    ref = s3.add(row['manifest_key'],sieve.encoded(row['doc']))
    row.update(manifest_version=ref['version_id'],manifest_sha256=ref['sha256'])
    s3.add('qc-results/factory-test/_SUCCESS.json',sieve.encoded({'manifest':ref}))
    result = sieve.copy_recording(s3,row)
    assert result['status']=='inherited'


@pytest.mark.asyncio
async def test_worker_retries_even_when_error_state_database_is_down(monkeypatch):
    import asyncio
    attempts=[]
    async def fail():
        attempts.append(1)
        raise ConnectionError('database unavailable')
    def unavailable(): raise ConnectionError('database still unavailable')
    async def next_tick(seconds):
        if len(attempts)==2: raise asyncio.CancelledError
    monkeypatch.setattr(sieve,'sync_once',fail)
    monkeypatch.setattr(sieve,'get_sessionmaker',unavailable)
    monkeypatch.setattr(sieve.asyncio,'sleep',next_tick)
    with pytest.raises(asyncio.CancelledError): await sieve.run()
    assert len(attempts)==2
