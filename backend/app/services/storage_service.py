"""Private, authenticated S3 storage. No local or public-URL fallback."""
from __future__ import annotations

import hashlib
import hmac
import re
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit
from xml.etree import ElementTree

import httpx

from app.core.config import settings


class StorageError(RuntimeError):
    """Safe failure whose message contains no endpoint, object or credentials."""


def tenant_prefix(org_id: str) -> str:
    if not org_id:
        raise StorageError("Storage tenant is required")
    return f"originals/{hashlib.sha256(org_id.encode()).hexdigest()}/"


_KEY = re.compile(r"originals/[a-f0-9]{64}/[a-f0-9-]{36}/original\.(pdf|docx)\Z")


class StorageService:
    def _request(self, method, key="", *, body=b"", content_type=None, query=None, immutable=False):
        if (settings.STORAGE_BACKEND != "r2" or not settings.R2_ENDPOINT_URL
                or not settings.R2_BUCKET or not settings.R2_ACCESS_KEY_ID
                or not settings.R2_SECRET_ACCESS_KEY):
            raise StorageError("Private storage is unavailable")
        endpoint = urlsplit(settings.R2_ENDPOINT_URL)
        if endpoint.scheme != "https" or not endpoint.hostname or endpoint.path not in ("", "/"):
            raise StorageError("Private storage configuration is invalid")
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", settings.R2_BUCKET):
            raise StorageError("Private storage configuration is invalid")
        if key and not _KEY.fullmatch(key):
            raise StorageError("Invalid storage key")
        path = "/" + quote(settings.R2_BUCKET, safe="") + ("/" + quote(key, safe="/") if key else "")
        canonical_query = "&".join(f"{quote(str(k), safe='~')}={quote(str(v), safe='~')}" for k, v in sorted((query or {}).items()))
        now = datetime.now(timezone.utc)
        stamp, day = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
        digest = hashlib.sha256(body).hexdigest()
        headers = {"host": endpoint.netloc, "x-amz-content-sha256": digest, "x-amz-date": stamp}
        if content_type:
            headers["content-type"] = content_type
        if immutable:
            headers["if-none-match"] = "*"
        signed = ";".join(sorted(headers))
        canonical_headers = "".join(f"{k}:{headers[k]}\n" for k in sorted(headers))
        canonical = "\n".join([method, path, canonical_query, canonical_headers, signed, digest])
        scope = f"{day}/{settings.R2_REGION}/s3/aws4_request"
        sign = ("AWS4" + settings.R2_SECRET_ACCESS_KEY).encode()
        for part in (day, settings.R2_REGION, "s3", "aws4_request"):
            sign = hmac.new(sign, part.encode(), hashlib.sha256).digest()
        string_to_sign = f"AWS4-HMAC-SHA256\n{stamp}\n{scope}\n{hashlib.sha256(canonical.encode()).hexdigest()}"
        signature = hmac.new(sign, string_to_sign.encode(), hashlib.sha256).hexdigest()
        headers["authorization"] = f"AWS4-HMAC-SHA256 Credential={settings.R2_ACCESS_KEY_ID}/{scope}, SignedHeaders={signed}, Signature={signature}"
        url = f"https://{endpoint.netloc}{path}" + (f"?{canonical_query}" if canonical_query else "")
        try:
            # Bound original retrieval even if a remote object is corrupt/oversized.
            with httpx.Client(timeout=30, follow_redirects=False) as client:
                with client.stream(method, url, headers=headers, content=body) as response:
                    if method == "DELETE" and response.status_code == 404:
                        return b""
                    response.raise_for_status()
                    chunks, size = [], 0
                    limit = 50 * 1024 * 1024 if key else 4 * 1024 * 1024
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > limit:
                            raise StorageError("Private storage response exceeds limit")
                        chunks.append(chunk)
                    return b"".join(chunks)
        except (httpx.HTTPError, ValueError) as exc:
            raise StorageError("Private storage operation failed") from exc

    def put(self, key: str, data: bytes, content_type: str):
        self._request("PUT", key, body=data, content_type=content_type, immutable=True)

    def get(self, key: str) -> bytes:
        return self._request("GET", key)

    def delete(self, key: str):
        self._request("DELETE", key)

    def list_objects(self, org_id: str):
        """List only the explicit trusted tenant namespace; never the whole account."""
        yield from self._list_prefix(tenant_prefix(org_id))

    def list_originals(self):
        """Inventory originals in the dedicated bucket for operator reconciliation."""
        yield from self._list_prefix("originals/")

    def _list_prefix(self, prefix: str):
        token = None
        ns = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}
        while True:
            query = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
            if token:
                query["continuation-token"] = token
            try:
                root = ElementTree.fromstring(self._request("GET", query=query))
                for item in root.findall("s:Contents", ns):
                    key = item.findtext("s:Key", namespaces=ns)
                    if not key or not key.startswith(prefix) or not _KEY.fullmatch(key):
                        raise StorageError("Storage inventory escaped tenant namespace")
                    modified = datetime.fromisoformat(item.findtext("s:LastModified", namespaces=ns).replace("Z", "+00:00"))
                    yield key, modified
                if root.findtext("s:IsTruncated", namespaces=ns) != "true":
                    return
                next_token = root.findtext("s:NextContinuationToken", namespaces=ns)
                if not next_token or next_token == token:
                    raise StorageError("Invalid storage inventory pagination")
                token = next_token
            except (ElementTree.ParseError, ValueError, AttributeError) as exc:
                raise StorageError("Invalid storage inventory") from exc


storage_service = StorageService()
