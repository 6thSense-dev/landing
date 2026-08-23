"""Login by username OR email: LoginRequest validation + route resolution.

The schema half is a table of every identifier shape we care about. The route
half asserts that adding usernames changed nothing for real users, and that
the anti-enumeration behaviour (identical 401s, constant-time decoy) survived.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.api.routes.auth import RESERVED_USERNAMES, _email_domain, resolve_identifier
from app.core.passwords import hash_password
from app.main import create_app
from app.models import User
from app.models.user import GUEST_EMAIL
from app.schemas import LoginRequest
from app.schemas.auth import normalise_identifier


HDRS = {"Origin": "https://app.example"}


@pytest_asyncio.fixture
async def client(db_session, monkeypatch):
    monkeypatch.setenv("SENSEPROBE_CORS_ORIGINS", "https://app.example")
    monkeypatch.setenv("SENSEPROBE_COOKIE_SECURE", "false")
    from app.core.limiter import limiter
    limiter.reset()
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


@pytest_asyncio.fixture
async def alex(db_session):
    user = User(
        email="alex@example.com",
        name="Alex",
        role="founder",
        password_hash=hash_password("twelve-chars!!"),
    )
    db_session.add(user)
    await db_session.commit()
    return user


# --------------------------------------------------------------------------- #
# Schema: the identifier validation table                                      #
# --------------------------------------------------------------------------- #

VALID_IDENTIFIERS = [
    ("alex@example.com", "alex@example.com"),      # plain email
    ("  Alex@Example.COM  ", "alex@example.com"),  # trimmed + lowercased
    ("a.b+c@sub.example.co.uk", "a.b+c@sub.example.co.uk"),
    ("guest", "guest"),                            # the reserved username
    ("GUEST", "guest"),                            # case folded
    ("  guest  ", "guest"),                        # trimmed
    ("ab", "ab"),                                  # shortest allowed username
    ("user.name-1_x", "user.name-1_x"),            # every allowed punctuation
    ("0lead", "0lead"),                            # may start with a digit
    ("a" * 64, "a" * 64),                          # longest allowed username
]

INVALID_IDENTIFIERS = [
    "guest@",          # has an @, so it must be a real address
    "@example.com",    # ditto
    "a@b@c.com",       # ditto
    "not an email",    # space is not in the username alphabet
    "../etc",          # path traversal shape
    "../../etc/passwd",
    "guest;DROP",
    "guest\n",         # normalises to "guest"? no: \n is stripped -> "guest"
    "_leading",        # must start alphanumeric
    "-leading",
    ".leading",
    "a",               # too short
    "a" * 65,          # too long for a username
    "a" * 400,         # over MAX_IDENTIFIER_LEN
    "",                # empty
    "   ",             # empty after trim
]


@pytest.mark.parametrize("raw,expected", VALID_IDENTIFIERS)
def test_valid_identifiers_normalise(raw, expected):
    req = LoginRequest(identifier=raw, password="pw")
    assert req.identifier == expected


@pytest.mark.parametrize("raw", [x for x in INVALID_IDENTIFIERS if x != "guest\n"])
def test_invalid_identifiers_rejected(raw):
    with pytest.raises(ValidationError):
        LoginRequest(identifier=raw, password="pw")


def test_trailing_newline_is_stripped_not_smuggled():
    """`guest\\n` is whitespace-stripped, which is the same normalisation a
    pasted credential gets. It must not be able to carry the newline into a
    log line or a lookup."""
    assert LoginRequest(identifier="guest\n", password="pw").identifier == "guest"


def test_missing_both_fields_rejected():
    with pytest.raises(ValidationError):
        LoginRequest(password="pw")


def test_both_fields_agreeing_is_accepted():
    req = LoginRequest(identifier="Alex@Example.com", email="alex@example.com", password="pw")
    assert req.identifier == "alex@example.com"
    assert req.email == "alex@example.com"


def test_both_fields_disagreeing_rejected():
    with pytest.raises(ValidationError):
        LoginRequest(identifier="guest", email="alex@example.com", password="pw")


def test_email_only_body_still_populates_identifier():
    """The historical wire shape keeps working and needs no client change."""
    req = LoginRequest(email="  Alex@Example.COM  ", password="pw")
    assert req.identifier == "alex@example.com"
    assert req.email == "alex@example.com"


def test_email_field_validation_is_not_weakened():
    """A username-shaped value in the `email` key is still a 422. Usernames go
    in `identifier`; `email` stays a strict EmailStr for every real user."""
    with pytest.raises(ValidationError):
        LoginRequest(email="not-an-email", password="pw")
    with pytest.raises(ValidationError):
        LoginRequest(email="guest", password="pw")


def test_normalise_identifier_survives_non_strings():
    assert normalise_identifier(None) == ""
    assert normalise_identifier(5) == ""
    assert normalise_identifier({"a": 1}) == ""
    assert normalise_identifier(" X ") == "x"


# --------------------------------------------------------------------------- #
# Resolution + logging helpers                                                 #
# --------------------------------------------------------------------------- #

def test_reserved_usernames_is_exactly_one_auditable_entry():
    assert RESERVED_USERNAMES == {"guest": "guest@6thsense.dev"}
    assert RESERVED_USERNAMES["guest"] == GUEST_EMAIL


def test_resolve_identifier():
    assert resolve_identifier("alex@example.com") == "alex@example.com"
    assert resolve_identifier("guest") == GUEST_EMAIL
    # A bare word that is not reserved addresses no account at all — it is NOT
    # looked up as though it were an email.
    assert resolve_identifier("admin") is None
    assert resolve_identifier("alex") is None


def test_email_domain_copes_with_usernames_and_junk():
    assert _email_domain("alex@example.com") == "example.com"
    assert _email_domain("guest") == "username"
    assert _email_domain("") == "unknown"
    assert _email_domain(None) == "unknown"
    assert _email_domain(12) == "unknown"
    assert _email_domain("trailing@") == "unknown"


# --------------------------------------------------------------------------- #
# Route: real users are unaffected                                             #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_email_login_for_existing_role_unchanged(client, alex):
    res = await client.post(
        "/api/auth/login",
        json={"email": "alex@example.com", "password": "twelve-chars!!"},
        headers=HDRS,
    )
    assert res.status_code == 200, res.text
    assert res.json()["user"]["role"] == "founder"


@pytest.mark.asyncio
async def test_identifier_key_works_for_a_real_email(client, alex):
    res = await client.post(
        "/api/auth/login",
        json={"identifier": "ALEX@example.com", "password": "twelve-chars!!"},
        headers=HDRS,
    )
    assert res.status_code == 200, res.text
    assert res.json()["user"]["email"] == "alex@example.com"


@pytest.mark.asyncio
async def test_unknown_identifier_and_wrong_password_are_indistinguishable(client, alex):
    """Anti-enumeration: the two failure modes must return the same status and
    the same body, whichever spelling of the identifier is used."""
    wrong_password = await client.post(
        "/api/auth/login",
        json={"identifier": "alex@example.com", "password": "not-the-password"},
        headers=HDRS,
    )
    unknown_email = await client.post(
        "/api/auth/login",
        json={"identifier": "nobody@example.com", "password": "not-the-password"},
        headers=HDRS,
    )
    unknown_username = await client.post(
        "/api/auth/login",
        json={"identifier": "nobodyatall", "password": "not-the-password"},
        headers=HDRS,
    )
    assert wrong_password.status_code == 401
    assert unknown_email.status_code == 401
    assert unknown_username.status_code == 401
    assert wrong_password.json() == unknown_email.json() == unknown_username.json()
    assert wrong_password.json() == {"detail": "Invalid email or password."}


@pytest.mark.asyncio
async def test_unresolvable_username_still_runs_the_decoy_verify(client, alex, monkeypatch):
    """A bare username that addresses no account must still burn a password
    verification, or the 401 timing tells an attacker which usernames exist."""
    calls: list[str] = []
    import app.api.routes.auth as auth_module

    real_verify = auth_module.verify_password

    def _spy(plain, encoded):
        calls.append(encoded)
        return real_verify(plain, encoded)

    monkeypatch.setattr(auth_module, "verify_password", _spy)
    res = await client.post(
        "/api/auth/login",
        json={"identifier": "nobodyatall", "password": "whatever"},
        headers=HDRS,
    )
    assert res.status_code == 401
    assert calls == [auth_module.DUMMY_HASH]


@pytest.mark.asyncio
async def test_oversize_identifier_is_422_not_401(client):
    res = await client.post(
        "/api/auth/login",
        json={"identifier": "a" * 400, "password": "pw"},
        headers=HDRS,
    )
    assert res.status_code == 422
    assert res.json()["ok"] is False


@pytest.mark.asyncio
async def test_body_with_neither_field_is_422(client):
    res = await client.post("/api/auth/login", json={"password": "pw"}, headers=HDRS)
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_disagreeing_fields_are_422(client, alex):
    res = await client.post(
        "/api/auth/login",
        json={"identifier": "guest", "email": "alex@example.com", "password": "pw"},
        headers=HDRS,
    )
    assert res.status_code == 422
