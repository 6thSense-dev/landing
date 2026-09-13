from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from app.api.routes import ops
from app.core.auth_deps import current_user


@pytest.mark.asyncio
@pytest.mark.parametrize('role,expected', [('admin', 200), ('founder', 200), ('ops', 200), ('guest', 403), ('customer', 403), ('investor', 403)])
async def test_gate_and_fixed_scope(monkeypatch, role, expected):
    app = FastAPI()
    app.include_router(ops.router)
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(role=role)
    calls = []
    def inventory():
        calls.append(True)
        return {'bucket': 'configured-only', 'listing_complete': False}
    monkeypatch.setattr(ops, 'inventory_coverage', inventory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        response = await client.get('/api/ops/inventory-coverage?bucket=attacker-bucket')
    assert response.status_code == expected
    assert len(calls) == (1 if expected == 200 else 0)
    if expected == 200:
        assert response.json()['bucket'] == 'configured-only'


@pytest.mark.asyncio
async def test_unauthenticated_never_lists(monkeypatch):
    from fastapi import HTTPException
    app = FastAPI()
    app.include_router(ops.router)
    def no_user():
        raise HTTPException(status_code=401)
    app.dependency_overrides[current_user] = no_user
    monkeypatch.setattr(ops, 'inventory_coverage', lambda: pytest.fail('unauthenticated list'))
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.get('/api/ops/inventory-coverage')).status_code == 401
