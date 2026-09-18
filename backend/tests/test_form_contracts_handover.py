"""Staff-verified camera handover can precede signup without granting past ownership."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import ContributorAccount, ContributorCameraClaim, Episode, OpsCamera, OpsSetting, Wearer
from app.core.contributor_attribution import owner_at_capture
from tests.test_ops_routes import app, _client, _sid, ORIGIN
from tests.test_contributor_mobile import identity, setup, SUBJECT, OTHER
from tests.test_form_contracts import configuration, evidence, send, activate, PHONE

PATH = '/api/ops/contributors/camera-preapprovals'
DEVICE = 'ABC123'


async def reserved(db):
    wearer = Wearer(name='Confirmed handover', rate_krw_hour=15000)
    db.add(wearer)
    await db.flush()
    camera = OpsCamera(device_id=DEVICE, wearer_id=wearer.id)
    db.add(camera)
    await db.commit()
    return wearer, camera


def handover(wearer, **changes):
    return {'preapproval_id': str(uuid4()), 'phone': PHONE, 'wearer_id': wearer.id,
        'device_id': DEVICE, 'physically_verified': True, 'camera_owner_verified': True,
        'permissions_verified': True, 'note': 'In-person demonstration and physical camera handover confirmed.', **changes}


async def approve(c, sid, body):
    return await c.post(PATH, json=body, cookies={'sid': sid}, headers={'Origin': ORIGIN})


async def test_preapproval_requires_staff_csrf_and_explicit_handover_checks(app, db_session):
    wearer, _ = await reserved(db_session)
    body = handover(wearer)
    customer = await _sid(db_session, 'customer')
    staff = await _sid(db_session, 'ops')
    async with _client(app) as c:
        assert (await c.post(PATH, json=body)).status_code in (401, 403)
        assert (await approve(c, customer, body)).status_code == 403
        assert (await c.post(PATH, json=body, cookies={'sid': staff}, headers={'Origin': 'https://evil.invalid'})).status_code == 403
        for flag in ('physically_verified', 'camera_owner_verified', 'permissions_verified'):
            assert (await approve(c, staff, {**body, flag: False})).status_code == 422
    assert not list((await db_session.execute(select(OpsSetting))).scalars())
    assert not list((await db_session.execute(select(ContributorCameraClaim))).scalars())


@pytest.mark.parametrize('signature_after_approval', [False, True])
async def test_pre_signup_handover_activates_existing_wearer_without_past_ownership(app, db_session, monkeypatch, signature_after_approval):
    monkeypatch.setenv('OPS_BROWSER_UPLOAD_ENABLED', 'true')
    wearer, camera = await reserved(db_session)
    history = Episode(recording='old-unassigned-recording', session='old', device_id=DEVICE)
    db_session.add(history)
    await db_session.commit()
    sid = await _sid(db_session, 'ops')
    body = handover(wearer)
    async with _client(app) as c:
        approved = await approve(c, sid, body)
        assert approved.status_code == 200, approved.text
        assert PHONE not in approved.text
        assert (await approve(c, sid, body)).json() == approved.json()
        at = datetime.fromisoformat(approved.json()['approved_at'])
        assert datetime.fromisoformat(approved.json()['expires_at']) == at + timedelta(days=7)
        assert not list((await db_session.execute(select(ContributorAccount))).scalars())
        assert not list((await db_session.execute(select(ContributorCameraClaim))).scalars())
        signed = at + timedelta(seconds=1) if signature_after_approval else at - timedelta(days=1)
        assert (await send(c, evidence(name=wearer.name, signature=wearer.name, signed_at=signed.isoformat()))).status_code == 200
        identity(app)
        for _ in range(2):
            response = await activate(c)
            assert response.status_code == 200, response.text
        account = await db_session.get(ContributorAccount, SUBJECT)
        assert account.wearer_id == wearer.id
        claims = list((await db_session.execute(select(ContributorCameraClaim))).scalars())
        assert len(claims) == 1
        claim = claims[0]
        assert claim.subject == SUBJECT and claim.device_id == DEVICE and claim.status == 'approved'
        assert claim.effective_at == max(at, signed)
        assert claim.ended_at is None
        await db_session.refresh(wearer)
        await db_session.refresh(camera)
        await db_session.refresh(history)
        assert wearer.rate_krw_hour == 15000 and camera.wearer_id == wearer.id
        assert history.wearer_id is None
        facts = {'device_id': DEVICE, 'duration_s': 10, 'clock_source': 'ntp', 'complete': True}
        assert await owner_at_capture(db_session, {**facts, 'started_at': claim.effective_at - timedelta(seconds=20)}) is None
        assert await owner_at_capture(db_session, {**facts, 'started_at': claim.effective_at + timedelta(seconds=1)}) == wearer.id
        if not signature_after_approval:
            assert (await c.get('/api/uploads/info')).status_code == 200
    assert all(PHONE not in row.value for row in (await db_session.execute(select(OpsSetting))).scalars())


async def test_preapproval_id_cannot_be_reused_with_different_evidence(app, db_session):
    wearer, _ = await reserved(db_session)
    sid = await _sid(db_session, 'ops')
    body = handover(wearer)
    async with _client(app) as c:
        assert (await approve(c, sid, body)).status_code == 200
        assert (await approve(c, sid, {**body, 'phone': '+821099998888'})).status_code == 409
        assert (await approve(c, sid, {**body, 'note': 'Different alleged handover evidence.'})).status_code == 409


@pytest.mark.parametrize('conflict', ['camera_owner', 'active_claim'])
async def test_preapproval_cannot_take_another_contributors_camera(app, db_session, conflict):
    wearer, camera = await reserved(db_session)
    other = await setup(db_session, OTHER)
    if conflict == 'camera_owner':
        camera.wearer_id = other.wearer_id
    else:
        db_session.add(ContributorCameraClaim(id=str(uuid4()), subject=OTHER, device_id=DEVICE,
            status='approved', effective_at=datetime.now(timezone.utc) - timedelta(days=1)))
    await db_session.commit()
    sid = await _sid(db_session, 'ops')
    async with _client(app) as c:
        response = await approve(c, sid, handover(wearer))
        assert response.status_code == 409, response.text
    assert not list((await db_session.execute(select(OpsSetting))).scalars())


async def test_activation_retry_does_not_recreate_a_consumed_ended_camera_claim(app, db_session):
    wearer, _ = await reserved(db_session)
    sid = await _sid(db_session, 'ops')
    async with _client(app) as c:
        assert (await approve(c, sid, handover(wearer))).status_code == 200
        assert (await send(c, evidence(name=wearer.name, signature=wearer.name))).status_code == 200
        identity(app)
        assert (await activate(c)).status_code == 200
        claim = (await db_session.execute(select(ContributorCameraClaim))).scalar_one()
        ended = datetime.now(timezone.utc)
        claim.ended_at = ended
        await db_session.commit()
        await activate(c)
        claims = list((await db_session.execute(select(ContributorCameraClaim))).scalars())
        assert len(claims) == 1
        await db_session.refresh(claims[0])
        assert claims[0].ended_at == ended


@pytest.mark.parametrize('owner_changes', [False, True])
async def test_changed_reservation_cannot_be_consumed_or_leave_partial_account(app, db_session, owner_changes):
    wearer, camera = await reserved(db_session)
    sid = await _sid(db_session, 'ops')
    async with _client(app) as c:
        assert (await approve(c, sid, handover(wearer))).status_code == 200
        if owner_changes:
            other = Wearer(name='Next wearer')
            db_session.add(other)
            await db_session.flush()
            camera.wearer_id = other.id
        # Also covers a camera assigned away and then back to the same wearer.
        camera.updated_at = camera.updated_at + timedelta(seconds=1)
        await db_session.commit()
        assert (await send(c, evidence(name=wearer.name, signature=wearer.name))).status_code == 200
        identity(app)
        response = await activate(c)
        assert response.status_code == 409, response.text
        assert response.json()['detail'] == 'camera_preapproval_changed'
    assert not list((await db_session.execute(select(ContributorAccount))).scalars())
    assert not list((await db_session.execute(select(ContributorCameraClaim))).scalars())


async def test_expired_handover_cannot_activate_or_create_camera_claim(app, db_session, monkeypatch):
    from app.core import contributor_preapproval as pre
    wearer, _ = await reserved(db_session)
    sid = await _sid(db_session, 'ops')
    async with _client(app) as c:
        approval = await approve(c, sid, handover(wearer))
        assert approval.status_code == 200
        after_expiry = datetime.fromisoformat(approval.json()['expires_at']) + timedelta(seconds=1)
        class ExpiredClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return after_expiry
        monkeypatch.setattr(pre, 'datetime', ExpiredClock)
        assert (await send(c, evidence(name=wearer.name, signature=wearer.name))).status_code == 200
        identity(app)
        response = await activate(c)
        assert response.status_code == 409, response.text
        assert response.json()['detail'] == 'camera_preapproval_expired'
    assert not list((await db_session.execute(select(ContributorAccount))).scalars())
    assert not list((await db_session.execute(select(ContributorCameraClaim))).scalars())


async def test_different_verified_phone_does_not_consume_camera_handover(app, db_session, monkeypatch):
    from app.api.routes import form_contracts as contracts
    from tests.test_form_contracts import provider
    wearer, camera = await reserved(db_session)
    sid = await _sid(db_session, 'ops')
    other_phone = '+821099998888'
    async with _client(app) as c:
        assert (await approve(c, sid, handover(wearer))).status_code == 200
        assert (await send(c, evidence(name='Unrelated signer', signature='Unrelated signer', phone=other_phone))).status_code == 200
        identity(app)
        monkeypatch.setattr(contracts, 'cognito_user', lambda _: provider(phone=other_phone))
        assert (await activate(c)).status_code == 200
    account = await db_session.get(ContributorAccount, SUBJECT)
    assert account.wearer_id != wearer.id
    assert not list((await db_session.execute(select(ContributorCameraClaim))).scalars())
    await db_session.refresh(camera)
    assert camera.wearer_id == wearer.id


async def test_two_pending_phone_approvals_cannot_reserve_the_same_camera(app, db_session):
    wearer, _ = await reserved(db_session)
    sid = await _sid(db_session, 'ops')
    async with _client(app) as c:
        assert (await approve(c, sid, handover(wearer))).status_code == 200
        response = await approve(c, sid, handover(wearer, phone='+821099998888'))
        assert response.status_code == 409, response.text


@pytest.mark.parametrize('capture', ['owned_interval', 'after_return', 'unknown_clock'])
async def test_returned_camera_accepts_only_verifiable_delayed_owned_footage(app, db_session, monkeypatch, capture):
    from app.core import upload_storage as storage
    from app.models import UploadBatch, UploadFile
    from tests.test_browser_uploads import ready, manifest, REC

    account = await ready(db_session, app, monkeypatch)
    current = datetime.now(timezone.utc)
    claim = (await db_session.execute(select(ContributorCameraClaim))).scalar_one()
    claim.effective_at = current - timedelta(hours=2)
    claim.ended_at = current - timedelta(hours=1)
    await db_session.commit()
    metadata = {'device_id': DEVICE, 'start_time': (current - timedelta(minutes=90)).isoformat(),
        'duration_s': 60, 'clock_source': 'ntp', 'complete': True}
    if capture == 'after_return':
        metadata['start_time'] = (current - timedelta(minutes=30)).isoformat()
    if capture == 'unknown_clock':
        metadata['clock_source'] = 'unknown'
    published = []
    monkeypatch.setattr(storage, 'head', lambda batch, file: {'VersionId': file.version_id, 'ETag': file.etag})
    monkeypatch.setattr(storage, 'metadata', lambda batch, file: metadata)
    monkeypatch.setattr(storage, 'publish_receipt', lambda batch, files: published.append(batch.id))
    async with _client(app) as c:
        # Returned hardware does not prevent delivery of earlier SD-card recordings.
        assert (await c.get('/api/uploads/info')).status_code == 200
        response = await c.post('/api/uploads/batches', json=manifest())
        assert response.status_code == 200, response.text
        batch_id = response.json()['id']
        files = list((await db_session.execute(select(UploadFile).where(UploadFile.batch_id == batch_id))).scalars())
        for file in files:
            file.completed_at, file.version_id, file.etag = current, 'immutable-version', 'stored-etag'
        await db_session.commit()
        response = await c.post('/api/uploads/batches/' + batch_id + '/complete')
        episode = (await db_session.execute(select(Episode).where(Episode.recording == REC))).scalar_one_or_none()
        batch = await db_session.get(UploadBatch, batch_id)
        if capture == 'owned_interval':
            assert response.status_code == 200, response.text
            assert episode is not None and episode.wearer_id == account.wearer_id
            assert batch.completed_at is not None and published == [batch_id]
            assert (await c.post('/api/uploads/batches/' + batch_id + '/complete')).status_code == 200
            assert published == [batch_id]
        else:
            assert response.status_code == 409, response.text
            assert 'assignment has ended' in response.json()['detail']
            assert episode is None and batch.completed_at is None and published == []
