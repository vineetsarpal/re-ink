"""Issue and verify narrowly scoped dispatch capabilities (not yet wired to API)."""
import base64
import binascii
import hashlib
import hmac
import json
import re
import time

MAX_TTL_SECONDS = 3600
_ENCODED = re.compile(r"^[A-Za-z0-9_-]+$")


class InvalidCapability(ValueError):
    """A capability is invalid, expired, or does not match the requested job."""


def _id(value, limit):
    return (isinstance(value, str) and bool(value.strip()) and len(value) <= limit
            and not any(ord(c) < 32 or ord(c) == 127 for c in value))


def _key(key):
    if not isinstance(key, bytes) or len(key) < 32:
        raise InvalidCapability("Invalid capability configuration")
    return key


def _b64(value):
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value):
    if not _ENCODED.fullmatch(value):
        raise InvalidCapability("Invalid capability")
    try:
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, binascii.Error) as exc:
        raise InvalidCapability("Invalid capability") from exc
    if _b64(raw) != value:
        raise InvalidCapability("Invalid capability")
    return raw


def _clock(now):
    if now is None:
        return int(time.time())
    if type(now) is not int:
        raise InvalidCapability("Invalid time")
    return now


def issue_capability(key: bytes, org_id: str, job_id: str, attempt_id: str, *, ttl_seconds: int, now: int | None = None) -> str:
    key, now = _key(key), _clock(now)
    if (not _id(org_id, 255) or not _id(job_id, 100) or not _id(attempt_id, 128)
            or type(ttl_seconds) is not int or not 1 <= ttl_seconds <= MAX_TTL_SECONDS):
        raise InvalidCapability("Invalid capability scope")
    payload = {"v": 1, "op": "extract_reinsurance_contract", "org": org_id,
               "job": job_id, "attempt": attempt_id, "iat": now, "exp": now + ttl_seconds}
    encoded = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signature = hmac.new(key, encoded.encode(), hashlib.sha256).digest()
    return encoded + "." + _b64(signature)


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidCapability("Invalid capability")
        result[key] = value
    return result


def verify_capability(token: str, keys: list[bytes], job_id: str, attempt_id: str, *, now: int | None = None) -> str:
    """Return the authenticated org; callers must still scope DB and check job state."""
    now = _clock(now)
    if not isinstance(token, str) or len(token) > 4096 or token.count(".") != 1 or not keys or len(keys) > 3:
        raise InvalidCapability("Invalid capability")
    encoded, signature = token.split(".")
    raw = _unb64(encoded)
    supplied = _unb64(signature)
    if len(supplied) != 32:
        raise InvalidCapability("Invalid capability")
    matches = [hmac.compare_digest(hmac.new(_key(key), encoded.encode(), hashlib.sha256).digest(), supplied) for key in keys]
    if not any(matches):
        raise InvalidCapability("Invalid capability")
    try:
        payload = json.loads(raw, object_pairs_hook=_unique_pairs)
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidCapability("Invalid capability") from exc
    if (not isinstance(payload, dict) or set(payload) != {"v", "op", "org", "job", "attempt", "iat", "exp"}
            or type(payload["v"]) is not int or payload["v"] != 1
            or payload["op"] != "extract_reinsurance_contract"
            or not _id(payload["org"], 255) or not _id(payload["job"], 100) or not _id(payload["attempt"], 128)
            or payload["job"] != job_id or payload["attempt"] != attempt_id
            or type(payload["iat"]) is not int or type(payload["exp"]) is not int
            or payload["iat"] > now or payload["exp"] <= now
            or not 1 <= payload["exp"] - payload["iat"] <= MAX_TTL_SECONDS):
        raise InvalidCapability("Invalid capability")
    return payload["org"]
