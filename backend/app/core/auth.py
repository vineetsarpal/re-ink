"""
WorkOS access-token validation.

`decode_and_validate` is a pure function (the testable seam): it verifies a
WorkOS-issued JWT against the environment's JWKS — RS256 signature, issuer, and
expiry — and maps the claims onto a `CurrentUser`. `get_current_user` is the
thin FastAPI dependency wrapping it, raising 401 on any failure.

The issuer and JWKS URL are derived from `WORKOS_CLIENT_ID`; no API key is
required for validation (the JWKS endpoint is public).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt
from jose.exceptions import JWTError

from app.core.config import settings

logger = logging.getLogger(__name__)

_ALGORITHMS = ["RS256"]


@dataclass
class CurrentUser:
    """Identity resolved from a validated WorkOS access token.

    ``org_id``/``role``/``permissions`` are carried but not enforced in this
    slice; they keep the later multi-tenancy work additive.
    """

    user_id: str
    session_id: Optional[str] = None
    org_id: Optional[str] = None
    role: Optional[str] = None
    permissions: list[str] = field(default_factory=list)


class AuthError(Exception):
    """Raised when an access token fails validation."""


def _issuer() -> str:
    return f"https://api.workos.com/user_management/{settings.WORKOS_CLIENT_ID}"


def _jwks_url() -> str:
    return f"https://api.workos.com/sso/jwks/{settings.WORKOS_CLIENT_ID}"


# JWKS keys cached in-memory, keyed by `kid`.
_jwks_cache: dict[str, dict] = {}


def _fetch_jwks() -> dict[str, dict]:
    resp = httpx.get(_jwks_url(), timeout=10)
    resp.raise_for_status()
    return {k["kid"]: k for k in resp.json().get("keys", [])}


def _signing_key_for(kid: str):
    """Return the signing key for ``kid``, refreshing on a miss (key rotation)."""
    global _jwks_cache
    if kid not in _jwks_cache:
        _jwks_cache = _fetch_jwks()
    if kid not in _jwks_cache:
        raise AuthError(f"unknown signing key: {kid}")
    return _jwks_cache[kid]


def decode_and_validate(token: str) -> CurrentUser:
    """Validate a WorkOS access token and return the identity it carries.

    Raises ``AuthError`` if the signature, issuer, expiry, or algorithm is invalid.
    """
    try:
        header = jwt.get_unverified_header(token)
        key = _signing_key_for(header.get("kid"))
        claims = jwt.decode(
            token,
            key,
            algorithms=_ALGORITHMS,
            issuer=_issuer(),
        )
    except (JWTError, AuthError, KeyError) as exc:
        # Log *why* a token was rejected. The common prod cause is a
        # WORKOS_CLIENT_ID mismatch — the issuer check then fails for every
        # token — so surface expected vs. actual issuer.
        try:
            token_iss = jwt.get_unverified_claims(token).get("iss")
        except Exception:
            token_iss = "<unparseable>"
        logger.warning(
            "Access token rejected (%s): %s | expected issuer=%s token issuer=%s",
            type(exc).__name__, exc, _issuer(), token_iss,
        )
        raise AuthError(str(exc)) from exc

    return CurrentUser(
        user_id=claims["sub"],
        session_id=claims.get("sid"),
        org_id=claims.get("org_id"),
        role=claims.get("role"),
        permissions=claims.get("permissions", []),
    )


# auto_error=False so a missing header yields our 401 (not HTTPBearer's default 403).
_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> CurrentUser:
    """FastAPI dependency: validate the Bearer token or raise 401."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return decode_and_validate(credentials.credentials)
    except AuthError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
