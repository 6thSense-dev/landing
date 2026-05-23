from app.core.config import get_settings


def test_settings_reads_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h:5432/db")
    monkeypatch.setenv("SENSEPROBE_CORS_ORIGINS", "https://example.com")
    s = get_settings()
    assert s.database_url == "postgresql://u:p@h:5432/db"
    assert s.cors_origins == ["https://example.com"]
    assert s.rate_limit == "5/minute"


def test_settings_rate_limit_override(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/d")
    monkeypatch.setenv("SENSEPROBE_RATE_LIMIT", "20/minute")
    s = get_settings()
    assert s.rate_limit == "20/minute"


def test_settings_missing_database_url_raises(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    import pytest
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        get_settings()


def test_cookie_secure_defaults_true(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://stub:stub@h/d")
    monkeypatch.delenv("SENSEPROBE_COOKIE_SECURE", raising=False)
    from app.core.config import get_settings
    assert get_settings().cookie_secure is True


def test_cookie_secure_can_be_disabled(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://stub:stub@h/d")
    monkeypatch.setenv("SENSEPROBE_COOKIE_SECURE", "false")
    from app.core.config import get_settings
    assert get_settings().cookie_secure is False


def test_login_rate_limit_defaults(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://stub:stub@h/d")
    monkeypatch.delenv("SENSEPROBE_LOGIN_RATE_LIMIT", raising=False)
    from app.core.config import get_settings
    assert get_settings().login_rate_limit == "10/minute"
