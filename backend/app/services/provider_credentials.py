"""Authenticated encryption for organization-owned provider credentials.

The encryption key is supplied by the deployment's secret manager. Ciphertexts
are bound to their organization and provider to prevent substitution between
tenants or credential types.
"""
import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CredentialEncryptionError(ValueError):
    """A credential cannot be encrypted or authenticated."""


def _cipher(encoded_key: str) -> AESGCM:
    try:
        key = base64.b64decode(encoded_key, altchars=b"-_", validate=True)
    except (ValueError, binascii.Error) as exc:
        raise CredentialEncryptionError("Invalid credential encryption key") from exc
    if len(key) != 32:
        raise CredentialEncryptionError("Credential encryption key must be 32 bytes")
    return AESGCM(key)


def _associated_data(org_id: str, provider: str) -> bytes:
    if not org_id or not provider or "\0" in org_id or "\0" in provider:
        raise CredentialEncryptionError("Invalid credential scope")
    return b"re-ink-provider-key-v1\0" + org_id.encode() + b"\0" + provider.encode()


def encrypt_credential(value: str, org_id: str, provider: str, encoded_key: str) -> bytes:
    if not value:
        raise CredentialEncryptionError("Credential is empty")
    nonce = os.urandom(12)
    return nonce + _cipher(encoded_key).encrypt(nonce, value.encode(), _associated_data(org_id, provider))


def decrypt_credential(ciphertext: bytes, org_id: str, provider: str, encoded_key: str) -> str:
    if len(ciphertext) < 29:
        raise CredentialEncryptionError("Invalid encrypted credential")
    try:
        return _cipher(encoded_key).decrypt(ciphertext[:12], ciphertext[12:], _associated_data(org_id, provider)).decode()
    except (InvalidTag, UnicodeDecodeError) as exc:
        raise CredentialEncryptionError("Credential authentication failed") from exc


def credentials_available(user) -> bool:
    from app.core.config import settings
    return bool(settings.CLOUDFLARE_TRIAL_ENABLED and user.org_id
                and user.org_id in settings.TRIAL_ALLOWED_ORGANIZATION_IDS)
