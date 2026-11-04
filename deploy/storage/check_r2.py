"""Private R2 synthetic put/get/delete check; no credentials printed."""
import sys
import uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app.core.config import settings
from app.services.storage_service import storage_service, tenant_prefix

if not settings.WORKFLOW_CUSTOMER_ORG_ID:
    raise SystemExit("Configured customer required")
key = f"{tenant_prefix(settings.WORKFLOW_CUSTOMER_ORG_ID)}{uuid.uuid4()}/original.pdf"
data = b"synthetic storage connectivity probe; not an application upload"
try:
    storage_service.put(key, data, "application/octet-stream")
    if storage_service.get(key) != data:
        raise RuntimeError("Storage round trip mismatch")
finally:
    storage_service.delete(key)
print("Private storage put/get/delete passed")
