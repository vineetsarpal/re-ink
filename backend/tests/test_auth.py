"""
Tests for WorkOS access-token validation (app.core.auth).

These exercise the pure `decode_and_validate` seam directly — no HTTP, no live
WorkOS. A throwaway RSA keypair is generated per test run; tokens are signed
locally with `jose`, and the JWKS key resolver is monkeypatched to return the
matching public key. This verifies the security-critical validation path
(signature, issuer, expiry, algorithm pinning) without any network access.
"""
import base64
import json
import os
import sys
import time
from pathlib import Path

# Configure environment before importing application modules
os.environ.setdefault("LANDINGAI_API_KEY", "dummy-key")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt

CLIENT_ID = "client_test123"
ISSUER = f"https://api.workos.com/user_management/{CLIENT_ID}"
KID = "test-kid"


@pytest.fixture(scope="module")
def rsa_keys():
    """Generate a throwaway RSA keypair; return (private_pem, public_pem)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem


@pytest.fixture(autouse=True)
def _wire_auth(monkeypatch, rsa_keys):
    """Point auth at the test issuer and a deterministic in-memory JWKS."""
    from app.core import auth

    monkeypatch.setattr(auth.settings, "WORKOS_CLIENT_ID", CLIENT_ID, raising=False)
    _, public_pem = rsa_keys
    monkeypatch.setattr(auth, "_jwks_cache", {})
    monkeypatch.setattr(auth, "_fetch_jwks", lambda: {KID: public_pem})


def _mint(private_pem, **overrides):
    """Mint an RS256 access token resembling a WorkOS one."""
    now = int(time.time())
    claims = {
        "sub": "user_01H",
        "sid": "session_01H",
        "org_id": "org_01H",
        "role": "admin",
        "permissions": ["contracts:read", "contracts:write"],
        "iss": ISSUER,
        "iat": now,
        "nbf": now - 5,
        "exp": now + 3600,
    }
    claims.update(overrides)
    return jwt.encode(claims, private_pem, algorithm="RS256", headers={"kid": KID})


def test_valid_token_returns_current_user(rsa_keys):
    from app.core.auth import decode_and_validate

    private_pem, _ = rsa_keys
    user = decode_and_validate(_mint(private_pem))

    assert user.user_id == "user_01H"
    assert user.session_id == "session_01H"
    assert user.org_id == "org_01H"
    assert user.role == "admin"
    assert user.permissions == ["contracts:read", "contracts:write"]


def test_expired_token_is_rejected(rsa_keys):
    from app.core.auth import AuthError, decode_and_validate

    private_pem, _ = rsa_keys
    now = int(time.time())
    token = _mint(private_pem, iat=now - 7200, nbf=now - 7200, exp=now - 3600)

    with pytest.raises(AuthError):
        decode_and_validate(token)


def test_small_expiry_clock_skew_is_allowed(rsa_keys):
    """A token just beyond exp remains valid within the configured leeway."""
    from app.core.auth import decode_and_validate

    private_pem, _ = rsa_keys
    now = int(time.time())
    token = _mint(private_pem, iat=now - 3600, nbf=now - 3600, exp=now - 15)

    assert decode_and_validate(token).user_id == "user_01H"


def test_small_not_before_clock_skew_is_allowed(rsa_keys):
    """A token just before nbf remains valid within the configured leeway."""
    from app.core.auth import decode_and_validate

    private_pem, _ = rsa_keys
    now = int(time.time())
    token = _mint(private_pem, nbf=now + 15, exp=now + 3600)

    assert decode_and_validate(token).user_id == "user_01H"


def test_wrong_issuer_is_rejected(rsa_keys):
    from app.core.auth import AuthError, decode_and_validate

    private_pem, _ = rsa_keys
    token = _mint(private_pem, iss="https://api.workos.com/user_management/client_other")

    with pytest.raises(AuthError):
        decode_and_validate(token)


def test_token_signed_by_foreign_key_is_rejected(rsa_keys):
    """A token signed by a different key must fail signature verification."""
    from app.core.auth import AuthError, decode_and_validate

    foreign = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    foreign_pem = foreign.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    # _signing_key_for still resolves to the *trusted* public key (autouse fixture),
    # but the token was signed by the foreign key → signature mismatch.
    token = _mint(foreign_pem)

    with pytest.raises(AuthError):
        decode_and_validate(token)


def test_unsigned_alg_none_token_is_rejected(rsa_keys):
    """An alg:none token must be rejected (algorithm pinning)."""
    from app.core.auth import AuthError, decode_and_validate

    now = int(time.time())

    def _b64(obj):
        raw = json.dumps(obj).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    header = _b64({"alg": "none", "kid": KID, "typ": "JWT"})
    payload = _b64({"sub": "user_01H", "iss": ISSUER, "exp": now + 3600, "nbf": now - 5})
    unsigned = f"{header}.{payload}."  # empty signature

    with pytest.raises(AuthError):
        decode_and_validate(unsigned)


def test_hs256_downgrade_is_rejected(rsa_keys):
    """An HS256-signed token must be rejected because we pin RS256."""
    from app.core.auth import AuthError, decode_and_validate

    now = int(time.time())
    claims = {"sub": "user_01H", "iss": ISSUER, "exp": now + 3600, "nbf": now - 5}
    forged = jwt.encode(claims, "shared-secret", algorithm="HS256", headers={"kid": KID})

    with pytest.raises(AuthError):
        decode_and_validate(forged)


def test_token_without_org_yields_none_org(rsa_keys):
    """A single-org token without org/role/permissions claims is accepted."""
    from app.core.auth import decode_and_validate

    private_pem, _ = rsa_keys
    now = int(time.time())
    claims = {
        "sub": "user_01H",
        "sid": "session_01H",
        "iss": ISSUER,
        "iat": now,
        "nbf": now - 5,
        "exp": now + 3600,
    }
    token = jwt.encode(claims, private_pem, algorithm="RS256", headers={"kid": KID})

    user = decode_and_validate(token)
    assert user.user_id == "user_01H"
    assert user.org_id is None
    assert user.role is None
    assert user.permissions == []


def test_get_current_user_rejects_orgless_token():
    """Every resource request must resolve to an org; an orgless identity is 401."""
    from fastapi import HTTPException

    from app.core.auth import CurrentUser, get_current_user

    with pytest.raises(HTTPException) as exc:
        get_current_user(CurrentUser(user_id="user_01H", org_id=None))
    assert exc.value.status_code == 401


def test_get_authenticated_user_accepts_orgless_token(rsa_keys):
    """The orgless-allowed dependency returns the user (for the provisioning path)."""
    from fastapi.security import HTTPAuthorizationCredentials

    from app.core.auth import get_authenticated_user

    private_pem, _ = rsa_keys
    now = int(time.time())
    claims = {
        "sub": "user_01H",
        "sid": "session_01H",
        "iss": ISSUER,
        "iat": now,
        "nbf": now - 5,
        "exp": now + 3600,
    }
    token = jwt.encode(claims, private_pem, algorithm="RS256", headers={"kid": KID})
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    user = get_authenticated_user(creds)
    assert user.user_id == "user_01H"
    assert user.org_id is None


def test_jwks_cache_avoids_repeated_fetches(monkeypatch):
    from app.core import auth

    calls = 0

    def fetch():
        nonlocal calls
        calls += 1
        return {"kid-1": {"kid": "kid-1"}}

    monkeypatch.setattr(auth, "_fetch_jwks", fetch)

    assert auth._signing_key_for("kid-1") == {"kid": "kid-1"}
    assert auth._signing_key_for("kid-1") == {"kid": "kid-1"}
    assert calls == 1


def test_jwks_cache_refreshes_when_kid_rotates(monkeypatch):
    from app.core import auth

    responses = iter(
        [
            {"kid-old": {"kid": "kid-old"}},
            {
                "kid-old": {"kid": "kid-old"},
                "kid-new": {"kid": "kid-new"},
            },
        ]
    )
    monkeypatch.setattr(auth, "_fetch_jwks", lambda: next(responses))

    assert auth._signing_key_for("kid-old") == {"kid": "kid-old"}
    assert auth._signing_key_for("kid-new") == {"kid": "kid-new"}


def test_unknown_kid_is_rejected_after_refresh(monkeypatch):
    from app.core import auth

    monkeypatch.setattr(auth, "_fetch_jwks", lambda: {})

    with pytest.raises(auth.AuthError, match="unknown signing key"):
        auth._signing_key_for("missing")


def test_protected_endpoint_requires_token():
    """A resource endpoint returns 401 when no Bearer token is supplied."""
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    resp = client.get("/api/contracts/")
    assert resp.status_code == 401

    # The PDF preview uses this file endpoint directly; it is protected by the
    # same router dependency and therefore must receive the SPA Bearer token.
    file_resp = client.get("/api/documents/file/missing-job")
    assert file_resp.status_code == 401


def test_public_endpoints_need_no_token():
    """`/` and `/health` stay reachable without authentication."""
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    assert client.get("/health").status_code == 200
    assert client.get("/").status_code == 200
