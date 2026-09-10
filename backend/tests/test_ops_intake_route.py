import hashlib
from pathlib import Path
import pytest
from tests.test_ops_routes import app,_sid,_client
@pytest.mark.parametrize('role',['ops','founder','admin'])
@pytest.mark.asyncio
async def test_existing_role_gate_and_readonly_route(app,db_session,monkeypatch,role):
    fixture=Path(__file__).parent/'fixtures/intake/synthetic.json'
    monkeypatch.setenv('OPS_INTAKE_PREVIEW_PATH',str(fixture.resolve()))
    monkeypatch.setenv('OPS_INTAKE_PREVIEW_SHA256',hashlib.sha256(fixture.read_bytes()).hexdigest())
    sid=await _sid(db_session,role)
    async with _client(app) as client:
        response=await client.get('/api/ops/intake-preview',cookies={'sid':sid})
        assert response.status_code==200 and response.json()['schema']=='6thsense.ops-intake-preview/1'
        another=await client.get('/api/ops/intake-preview?path=/etc/passwd',cookies={'sid':sid})
        assert another.json()['report_sha256']==response.json()['report_sha256']
        write=await client.post('/api/ops/intake-preview',json={},cookies={'sid':sid},headers={'Origin':'https://app.example'})
        assert write.status_code==405
@pytest.mark.parametrize('role',['guest','customer','investor'])
@pytest.mark.asyncio
async def test_other_roles_cannot_read(app,db_session,role):
    sid=await _sid(db_session,role)
    async with _client(app) as client:
        assert (await client.get('/api/ops/intake-preview',cookies={'sid':sid})).status_code==403
@pytest.mark.asyncio
async def test_anonymous_cannot_read(app):
    async with _client(app) as client:
        assert (await client.get('/api/ops/intake-preview')).status_code==401
