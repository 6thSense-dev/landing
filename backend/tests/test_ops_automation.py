from types import SimpleNamespace
import pytest
from app.core.ops_automation import advance_payout
from app.core.wise import WiseClient, WiseError


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [None, 'raw', 'clean'])
async def test_raw_refresh_precedes_clean_and_scan_failures_are_isolated(monkeypatch, failure):
    from app.core import ops_automation
    from app.api.routes import ops, ops_clean

    calls = []

    class Connection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def execute(self, query):
            if 'unlock' in str(query):
                calls.append('unlock')
            return SimpleNamespace(scalar=lambda: True)

        async def commit(self):
            calls.append('commit')

        async def rollback(self):
            calls.append('rollback')

    async def raw(_, db):
        calls.append('raw')
        if failure == 'raw':
            raise RuntimeError('Raw unavailable')

    async def clean(_, db, *, skip_invalid):
        assert skip_invalid
        calls.append('clean')
        if failure == 'clean':
            raise RuntimeError('Clean unavailable')

    async def setting(db, key, value):
        assert key == 'automation_last_success'
        calls.append('raw_success')

    async def payouts():
        calls.append('payouts')

    monkeypatch.setattr(ops_automation, 'get_engine', lambda: SimpleNamespace(connect=Connection))
    monkeypatch.setattr(ops_automation, 'get_sessionmaker', lambda: Connection)
    monkeypatch.setattr(ops_automation, 'payout_tick', payouts)
    monkeypatch.setattr(ops, 'scan_bucket', raw)
    monkeypatch.setattr(ops, '_put_setting', setting)
    monkeypatch.setattr(ops_clean, 'scan', clean)

    await ops_automation.tick()

    expected = ['raw', 'rollback'] if failure == 'raw' else ['raw', 'raw_success', 'commit']
    expected += ['clean'] + (['rollback'] if failure == 'clean' else [])
    assert calls == expected + ['payouts', 'unlock']


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [None, "false", "true"])
async def test_payout_loop_requires_separate_opt_in_even_with_wise_credentials(monkeypatch, enabled):
    from app.core import ops_automation
    monkeypatch.setenv("OPS_AUTOMATION_ENABLED", "true")
    monkeypatch.setenv("WISE_API_TOKEN", "test-only")
    monkeypatch.setenv("WISE_PROFILE_ID", "123")
    if enabled is None:
        monkeypatch.delenv("OPS_PAYOUT_AUTOMATION_ENABLED", raising=False)
    else:
        monkeypatch.setenv("OPS_PAYOUT_AUTOMATION_ENABLED", enabled)
    calls = []

    class EmptyDB:
        async def __aenter__(self):
            calls.append("database")
            return self

        async def __aexit__(self, *args):
            pass

        async def execute(self, statement):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))

    monkeypatch.setattr(ops_automation, "WiseClient", lambda: calls.append("wise"))
    monkeypatch.setattr(ops_automation, "get_sessionmaker", lambda: EmptyDB)
    await ops_automation.payout_tick()
    assert calls == (["wise", "database"] if enabled == "true" else [])


class DB:
    async def commit(self):
        pass


class Wise:
    profile = "123"
    environment = "sandbox"

    def __init__(self):
        self.identities = []
        self.funded = 0
        self.fail_once = False
        self.provider = "incoming_payment_waiting"
        self.recipient_hash = "verified"

    def recipient(self, _):
        return dict(
            active=True, hash=self.recipient_hash, profileId=123, currency="KRW"
        )

    def quote(self, p):
        return dict(id="quote", targetCurrency="KRW", targetAmount=p.amount_krw)

    def transfer(self, p):
        self.identities.append(p.id)
        if self.fail_once:
            self.fail_once = False
            raise WiseError("Response lost after transfer creation")
        return dict(id=42)

    def status(self, p):
        return dict(
            status=self.provider,
            targetAccount=321,
            targetCurrency="KRW",
            targetValue=p.amount_krw,
        )

    def fund(self, p):
        self.funded += 1
        return dict(status="COMPLETED")


def payout():
    return SimpleNamespace(
        id="unchanging-payout-id",
        wise_profile_id="123",
        wise_environment="sandbox",
        recipient_id="321",
        recipient_hash="verified",
        amount_krw=55000,
        quote_id=None,
        transfer_id=None,
        status="approved",
        error="",
    )


@pytest.mark.asyncio
async def test_lost_transfer_response_retries_same_identity_and_funding_is_not_receipt(
    monkeypatch,
):
    monkeypatch.setenv("OPS_WISE_AUTO_FUND", "true")
    p = payout()
    wise = Wise()
    wise.fail_once = True
    with pytest.raises(WiseError):
        await advance_payout(DB(), p, wise)
    assert p.quote_id == "quote" and p.transfer_id is None
    await advance_payout(DB(), p, wise)
    assert wise.identities == [p.id, p.id]
    assert wise.funded == 1 and p.status == "processing"
    wise.provider = "outgoing_payment_sent"
    await advance_payout(DB(), p, wise)
    assert p.status == "sent" and wise.funded == 1
    wise.provider = "bounced_back"
    await advance_payout(DB(), p, wise)
    assert p.status == "needs_attention" and p.transfer_id == "42"


@pytest.mark.asyncio
async def test_recipient_change_blocks_transfer_and_disabled_auto_funding_preserves_approval(
    monkeypatch,
):
    monkeypatch.delenv("OPS_WISE_AUTO_FUND", raising=False)
    p = payout()
    wise = Wise()
    wise.recipient_hash = "changed"
    with pytest.raises(WiseError):
        await advance_payout(DB(), p, wise)
    assert not wise.identities and not wise.funded
    wise.recipient_hash = "verified"
    await advance_payout(DB(), p, wise)
    assert p.status == "awaiting_funding" and not wise.funded


def test_adapter_uses_fixed_receive_amount_and_stable_transfer_id(monkeypatch):
    monkeypatch.setenv("WISE_API_TOKEN", "test-only")
    monkeypatch.setenv("WISE_PROFILE_ID", "123")
    monkeypatch.setenv("WISE_ENVIRONMENT", "sandbox")
    client = WiseClient()
    calls = []
    client.request = lambda *args, **kwargs: calls.append((args, kwargs))
    p = payout()
    p.source_currency = "USD"
    p.quote_id = "q"
    client.quote(p)
    client.transfer(p)
    client.transfer(p)
    assert client.base.startswith("https://api.wise-sandbox.com/")
    assert calls[0][0][2]["targetAmount"] == 55000
    assert calls[0][0][2]["targetCurrency"] == "KRW"
    assert (
        calls[1][0][2]["customerTransactionId"]
        == calls[2][0][2]["customerTransactionId"]
        == p.id
    )
