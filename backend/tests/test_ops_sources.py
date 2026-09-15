"""Business provenance must never become individual contributor earnings."""
import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.ops_clean import validate_manifest
from app.core.ops_ledger import contributor_summary, footage_ledger
from app.core.ops_processing import reconcile
from app.core.ops_regions import clean_region
from app.core.ops_sources import ATTRIBUTIONS_KEY, business_source, counterparty
from app.models import CleanRun, OpsCamera, OpsSetting, Payout, PayoutItem, PayoutRecipient, ProcessingJob, Wearer
from tests.test_ops_artifacts import multimodal_manifest
from tests.test_ops_routes import app, _client, _episode, _sid, ORIGIN


BUSINESS = dict(kind='business', id='factory-example', name='Example factory', country='china', payment_model='b2b_contract')
RECORDING = 'ego_20260901_120000_ABC123'
SESSION = '2026-09-01_Trial'


def business_manifest():
    doc = multimodal_manifest()
    doc.update(country='china', counterparty=copy.deepcopy(BUSINESS))
    doc['recordings'][0]['sources'][0]['key'] = f'sessions/{SESSION}/ABC123/{RECORDING}/video.mp4'
    return doc


def registry_entry(recording=RECORDING, **overrides):
    return dict(recording=recording, device_id='ABC123', session=SESSION,
                counterparty=copy.deepcopy(BUSINESS), **overrides)


async def save_registry(db, entries):
    db.add(OpsSetting(key=ATTRIBUTIONS_KEY, value=json.dumps(entries)))
    await db.commit()


def mock_result(monkeypatch, doc):
    from app.api.routes import ops_clean
    digest = hashlib.sha256(json.dumps(doc).encode()).hexdigest()
    monkeypatch.setattr(ops_clean, 'committed_results', lambda: [(doc, f"qc-results/{doc['run_id']}/result.json", 'v1', digest)])
    return digest


@pytest.mark.parametrize('fault', ['kind', 'payment_model', 'country', 'id', 'name', 'extra', 'missing'])
def test_counterparty_rejects_incomplete_or_person_payment_identity(fault):
    party = copy.deepcopy(BUSINESS)
    if fault == 'extra': party['wearer_id'] = 1
    elif fault == 'missing': party.pop('payment_model')
    else: party[fault] = {'kind': 'person', 'payment_model': 'hourly', 'country': 'US', 'id': '../other', 'name': ' '}[fault]
    with pytest.raises(ValueError): counterparty(party)


@pytest.mark.parametrize('fault', ['recording', 'device_id', 'session', 'owner'])
def test_registry_is_bound_to_exact_source_camera_session_and_no_person(fault):
    episode = SimpleNamespace(recording=RECORDING, device_id='ABC123', session=SESSION, wearer_id=None)
    entry = registry_entry()
    if fault == 'owner': episode.wearer_id = 1
    else: entry[fault] = 'different'
    with pytest.raises(ValueError): business_source(episode, {RECORDING: entry})


def test_explicit_business_country_overrides_trial_without_masking_country_conflicts():
    doc = business_manifest()
    assert clean_region(doc) == dict(key='china', label='China', status='classified')
    doc['recordings'][0]['sources'][0]['key'] = doc['recordings'][0]['sources'][0]['key'].replace(SESSION, 'korea-work')
    assert clean_region(doc)['key'] == 'unassigned'
    doc['country'] = 'korea'
    with pytest.raises(ValueError, match='country'): validate_manifest(doc)


@pytest.mark.asyncio
@pytest.mark.parametrize('fault', ['unregistered', 'forged_business', 'missing_declaration', 'wrong_country', 'mixed_business', 'mixed_person', 'wrong_source_session', 'malformed_uploader'])
async def test_import_refuses_forged_or_mixed_business_provenance(app, db_session, monkeypatch, fault):
    sid = await _sid(db_session, 'ops')
    episode = await _episode(db_session, RECORDING)
    episode.session = SESSION
    doc = business_manifest()
    registry = {RECORDING: registry_entry()}
    if fault == 'unregistered': registry = {}
    if fault == 'forged_business': doc['counterparty']['id'] = 'another-factory'
    if fault == 'missing_declaration': doc.pop('counterparty')
    if fault == 'wrong_country': doc['country'] = 'korea'
    if fault == 'wrong_source_session':
        doc['recordings'][0]['sources'][0]['key'] = doc['recordings'][0]['sources'][0]['key'].replace(SESSION, 'another-delivery')
    if fault == 'malformed_uploader':
        doc['recordings'][0]['sources'][0]['key'] = doc['recordings'][0]['sources'][0]['key'].replace('/ABC123/', '/not-a-camera/')
    if fault in ('mixed_business', 'mixed_person'):
        other = 'ego_20260901_130000_ABC123'
        rec = copy.deepcopy(doc['recordings'][0])
        rec['recording'] = other
        rec['sources'][0]['key'] = rec['sources'][0]['key'].replace(RECORDING, other)
        rec['sources'][0]['sha256'] = 'd' * 64
        doc['recordings'].append(rec)
        outputs = copy.deepcopy(doc['outputs'])
        for item in outputs:
            item['recording'] = other
            item['key'] = item['key'].replace('factory-test/', 'factory-test/second/')
        doc['outputs'].extend(outputs)
        for field in ('source_seconds', 'retained_seconds', 'rejected_seconds'): doc[field] *= 2
        other_episode = await _episode(db_session, other)
        other_episode.session = SESSION
        if fault == 'mixed_business':
            registry[other] = registry_entry(other)
            registry[other]['counterparty']['id'] = 'another-factory'
        else:
            person = Wearer(name='Other contributor', rate_krw_hour=11000)
            db_session.add(person)
            await db_session.flush()
            other_episode.wearer_id = person.id
    await save_registry(db_session, registry)
    if fault != 'wrong_country': validate_manifest(doc)
    mock_result(monkeypatch, doc)
    async with _client(app) as client:
        response = await client.post('/api/ops/clean/scan', cookies={'sid': sid}, headers={'Origin': ORIGIN})
    assert response.status_code == 409, response.text
    assert not (await db_session.execute(select(CleanRun))).scalars().all()
    assert not (await db_session.execute(select(PayoutItem))).scalars().all()


@pytest.mark.asyncio
@pytest.mark.parametrize('camera_folder', ['ABC123', None, 'FFFFFF', 'EGO-FFFFFF'])
async def test_business_import_review_never_enters_person_balance_or_payout(app, db_session, monkeypatch, camera_folder):
    monkeypatch.setenv('WISE_PROFILE_ID', '123')
    monkeypatch.setenv('WISE_SOURCE_CURRENCY', 'USD')
    monkeypatch.setenv('WISE_ENVIRONMENT', 'sandbox')
    sid = await _sid(db_session, 'ops')
    person = Wearer(name='Unrelated camera holder', rate_krw_hour=11000)
    db_session.add(person)
    await db_session.flush()
    db_session.add_all([OpsCamera(device_id='ABC123', wearer_id=person.id),
        PayoutRecipient(wearer_id=person.id, wise_recipient_id='321', verified_name=person.name,
            updated_by='test', wise_profile_id='123', wise_environment='sandbox', recipient_hash='verified-test')])
    episode = await _episode(db_session, RECORDING)
    episode.session = SESSION
    episode.started_at = datetime(2026, 9, 1, 15, 30, tzinfo=timezone.utc)
    episode.clock_source = 'ntp'
    await save_registry(db_session, {RECORDING: registry_entry()})
    doc = business_manifest()
    doc['recordings'][0]['sources'][0]['key'] = doc['recordings'][0]['sources'][0]['key'].replace(
        '/ABC123/', f'/{camera_folder}/' if camera_folder else '/')
    digest = mock_result(monkeypatch, doc)
    async with _client(app) as client:
        response = await client.post('/api/ops/clean/scan', cookies={'sid': sid}, headers={'Origin': ORIGIN})
        assert response.status_code == 200, response.text
        row = response.json()['runs'][0]
        assert row['counterparty'] == BUSINESS and row['region']['key'] == 'china'
        assert row['wearer_id'] is None and row['rate_krw_hour'] is None and row['estimated_krw'] is None
        # 23:30 in China is already the next calendar day in Korea.
        assert response.json()['ledger'][0]['collection_date'] == '2026-09-01'
        review = dict(run_id=doc['run_id'], recording=RECORDING, manifest_sha256=digest,
            decision='reviewed', collection_date='2026-09-01', watched_all=True)
        from app.api.routes import ops_payments
        class NearChinaMidnight(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 9, 1, 15, 30, tzinfo=timezone.utc).astimezone(tz)
        with monkeypatch.context() as clock:
            clock.setattr(ops_payments, 'datetime', NearChinaMidnight)
            future = await client.post('/api/ops/payments/review', json={**review, 'collection_date': '2026-09-02'},
                cookies={'sid': sid}, headers={'Origin': ORIGIN})
            assert future.status_code == 422 and 'future' in future.json()['detail']
        response = await client.post('/api/ops/payments/review', json=review, cookies={'sid': sid}, headers={'Origin': ORIGIN})
        assert response.status_code == 200, response.text
        state = (await client.get('/api/ops/payments/state', cookies={'sid': sid})).json()
        payer = state['contributors'][0]
        assert payer['entries'] == [] and payer['due_krw'] == 0 and payer['eligible_entries'] == []
        response = await client.post('/api/ops/payments/approve', cookies={'sid': sid}, headers={'Origin': ORIGIN}, json={
            'wearer_id': person.id, 'entries': [{k: review[k] for k in ('run_id', 'recording', 'manifest_sha256')}],
            'expected_amount_krw': 183, 'expected_recipient_revision': payer['recipient']['revision'], 'approve_payment': True})
        assert response.status_code == 409, response.text
        again = await client.post('/api/ops/clean/scan', cookies={'sid': sid}, headers={'Origin': ORIGIN})
        assert again.status_code == 200 and again.json()['imported'] == 0
    ledger = await footage_ledger(db_session)
    assert ledger[0]['payment_status'] == 'b2b_contract' and ledger[0]['allocated_krw'] is None
    summaries = await contributor_summary(db_session, ledger)
    assert summaries[0]['retained_seconds'] == 0 and summaries[0]['clean_recordings'] == 0
    assert not (await db_session.execute(select(Payout))).scalars().all()
    assert not (await db_session.execute(select(PayoutItem))).scalars().all()


@pytest.mark.asyncio
async def test_registered_business_cannot_be_assigned_or_autofilled_but_can_be_claimed(app, db_session, monkeypatch):
    monkeypatch.setenv('OPS_PROCESSOR_TOKEN', 'worker-test-only')
    sid = await _sid(db_session, 'ops')
    person = Wearer(name='Camera holder', rate_krw_hour=11000)
    db_session.add(person)
    await db_session.commit()
    episode = await _episode(db_session, RECORDING)
    episode.session = SESSION
    personal = await _episode(db_session, 'ego_20260901_130000_ABC123')
    await save_registry(db_session, {RECORDING: registry_entry()})
    async with _client(app) as client:
        response = await client.post('/api/ops/clean/cameras', cookies={'sid': sid}, headers={'Origin': ORIGIN},
            json=dict(device_id='ABC123', wearer_id=person.id, assign_unassigned_recordings=True))
        assert response.status_code == 200, response.text
        await db_session.refresh(episode)
        await db_session.refresh(personal)
        assert episode.wearer_id is None and personal.wearer_id == person.id
        response = await client.post(f'/api/ops/episodes/{RECORDING}/assign', cookies={'sid': sid}, headers={'Origin': ORIGIN}, json={'wearer_id': person.id})
        assert response.status_code == 409, response.text
        takes = {RECORDING: dict(prefixes=[f'sessions/{SESSION}/ABC123/{RECORDING}/'],
            media=[dict(key=f'sessions/{SESSION}/ABC123/{RECORDING}/video.mp4', bytes=100)],
            meta={'duration_s': 60}, uploaded=datetime.now(timezone.utc)-timedelta(hours=7))}
        jobs = await reconcile(db_session, takes, [], [])
        await db_session.commit()
        assert episode.wearer_id is None and jobs[RECORDING].state == 'queued'
        response = await client.post('/api/ops/processing/claim', headers={'Authorization': 'Bearer worker-test-only', 'Origin': ORIGIN})
        assert response.status_code == 200, response.text
        assert response.json()['job']['counterparty'] == BUSINESS


def test_business_entries_are_ineligible_even_if_a_caller_supplies_a_person_rate():
    from app.api.routes.ops_payments import eligible
    from tests.test_ops_workflow import entry
    row = entry(counterparty=BUSINESS)
    row['retained_seconds'] = 18000
    assert eligible([row], datetime(2026, 9, 18, 9, tzinfo=timezone.utc), 'accumulated') == ([], 0)


@pytest.mark.asyncio
@pytest.mark.parametrize('fault', [None, 'individual_owner', 'individual_rate', 'other_business'])
async def test_worker_completion_requires_matching_business_and_no_person_rate(app, db_session, monkeypatch, fault):
    monkeypatch.setenv('OPS_PROCESSOR_TOKEN', 'worker-test-only')
    episode = await _episode(db_session, RECORDING)
    episode.session = SESSION
    await save_registry(db_session, {RECORDING: registry_entry()})
    doc = business_manifest()
    person = Wearer(name='Unrelated person', rate_krw_hour=11000)
    db_session.add(person)
    await db_session.flush()
    if fault == 'other_business': doc['counterparty']['id'] = 'another-factory'
    run = CleanRun(run_id=doc['run_id'], device_id='ABC123', manifest_key='qc-results/factory-test/result.json',
        manifest_version='v1', manifest_sha256='a' * 64, manifest_json=json.dumps(doc),
        retained_seconds=60, rejected_seconds=40, wearer_id=person.id if fault == 'individual_owner' else None,
        rate_krw_hour=11000 if fault == 'individual_rate' else None)
    job = ProcessingJob(recording=RECORDING, state='running', reason='Test extraction', attempts=1, fingerprint='fp', input_json='{}',
        lease_token='lease', lease_until=datetime.now(timezone.utc)+timedelta(minutes=10))
    db_session.add_all([run, job])
    await db_session.commit()
    async with _client(app) as client:
        response = await client.post('/api/ops/processing/result', headers={'Authorization': 'Bearer worker-test-only', 'Origin': ORIGIN},
            json=dict(recording=RECORDING, fingerprint='fp', lease_token='lease', outcome='completed', run_id=run.run_id))
    assert response.status_code == (409 if fault else 200), response.text
    await db_session.refresh(job)
    assert job.state == ('running' if fault else 'awaiting_verification')
