import pytest

from app.services.dispatch_capability import issue_capability, verify_capability, InvalidCapability

KEY = b"a" * 32


def test_signed_dispatch_binds_job_attempt_and_organization():
    token = issue_capability(KEY, "org-a", "job-a", "attempt-a", now=1000, ttl_seconds=300)
    assert verify_capability(token, [KEY], "job-a", "attempt-a", now=1100) == "org-a"
    with pytest.raises(InvalidCapability):
        verify_capability(token, [KEY], "other-job", "attempt-a", now=1100)


def test_expired_tampered_and_wrong_attempt_capabilities_fail_closed():
    token = issue_capability(KEY, "org-a", "job-a", "attempt-a", now=1000, ttl_seconds=300)
    with pytest.raises(InvalidCapability):
        verify_capability(token, [KEY], "job-a", "attempt-a", now=1300)
    with pytest.raises(InvalidCapability):
        verify_capability(token, [KEY], "job-a", "attempt-b", now=1100)
    header, signature = token.split(".")
    tampered = header + "." + ("A" if signature[0] != "A" else "B") + signature[1:]
    with pytest.raises(InvalidCapability):
        verify_capability(tampered, [KEY], "job-a", "attempt-a", now=1100)


def test_key_rotation_preserves_only_explicitly_trusted_old_tokens():
    token = issue_capability(KEY, "org-a", "job-a", "attempt-a", now=1000, ttl_seconds=300)
    next_key = b"b" * 32
    assert verify_capability(token, [next_key, KEY], "job-a", "attempt-a", now=1100) == "org-a"
    with pytest.raises(InvalidCapability):
        verify_capability(token, [next_key], "job-a", "attempt-a", now=1100)
