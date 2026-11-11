"""Synthetic originals and deterministic private storage failures; no live fallback."""
import importlib
import hashlib
import io
from types import SimpleNamespace
import zipfile

import pytest
from docx import Document
from fastapi import HTTPException, UploadFile
from pypdf import PdfWriter
from app.services.private_document_service import PrivateDocumentService
document_module = importlib.import_module("app.services.private_document_service")
from app.services.storage_service import StorageError, StorageService, tenant_prefix


def pdf_bytes():
    out = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(out)
    return out.getvalue()


@pytest.fixture
def fake_storage(monkeypatch):
    class Fake:
        objects = {}
        def put(self, key, data, content_type):
            assert key not in self.objects
            self.objects[key] = data
        def get(self, key):
            return self.objects[key]
        def delete(self, key):
            self.objects.pop(key, None)
    fake = Fake()
    monkeypatch.setattr(document_module, "storage_service", fake)
    return fake


@pytest.mark.asyncio
async def test_roundtrip_integrity_and_tenant_namespace(fake_storage):
    service = PrivateDocumentService()
    info = await service.save_uploaded_file(UploadFile(filename="../../safe.pdf", file=io.BytesIO(pdf_bytes())), "org_test")
    assert info["filename"] == "safe.pdf"
    assert info["storage_key"].startswith(tenant_prefix("org_test"))
    job = SimpleNamespace(**info, org_id="org_test")
    assert service.read_original(job) == pdf_bytes()
    fake_storage.objects[info["storage_key"]] = b"corrupt"
    with pytest.raises(HTTPException) as error:
        service.read_original(job)
    assert error.value.status_code == 503
    job.org_id = "org_other"
    with pytest.raises(HTTPException):
        service.read_original(job)
    service.delete_original(info["storage_key"])
    assert not fake_storage.objects


@pytest.mark.asyncio
async def test_docx_structure_and_content_type(fake_storage):
    data = io.BytesIO()
    doc = Document()
    doc.add_paragraph("Synthetic contract")
    doc.save(data)
    info = await PrivateDocumentService().save_uploaded_file(UploadFile(filename="contract.docx", file=io.BytesIO(data.getvalue())), "org_test")
    assert info["content_type"].endswith("wordprocessingml.document")
    assert info["sha256"] == hashlib.sha256(data.getvalue()).hexdigest()


@pytest.mark.asyncio
@pytest.mark.parametrize("name,data", [("x.pdf", b"%PDF-fake"), ("x.docx", b"not zip"), ("x.exe", b"MZ")])
async def test_invalid_upload_never_stored(fake_storage, name, data):
    with pytest.raises(HTTPException) as error:
        await PrivateDocumentService().save_uploaded_file(UploadFile(filename=name, file=io.BytesIO(data)), "org_test")
    assert error.value.status_code == 400
    assert not fake_storage.objects


@pytest.mark.asyncio
async def test_bounded_read_and_failed_put(fake_storage, monkeypatch):
    monkeypatch.setattr(document_module.settings, "MAX_UPLOAD_SIZE", 10)
    with pytest.raises(HTTPException) as error:
        await PrivateDocumentService().save_uploaded_file(UploadFile(filename="x.pdf", file=io.BytesIO(b"x" * 11)), "org_test")
    assert error.value.status_code == 413
    monkeypatch.setattr(document_module.settings, "MAX_UPLOAD_SIZE", 50 * 1024 * 1024)
    def unavailable(*args):
        raise StorageError("Unavailable")
    monkeypatch.setattr(fake_storage, "put", unavailable)
    with pytest.raises(HTTPException) as error:
        await PrivateDocumentService().save_uploaded_file(UploadFile(filename="x.pdf", file=io.BytesIO(pdf_bytes())), "org_test")
    assert error.value.status_code == 503


def test_zip_bomb_and_external_entities_rejected():
    for name, payload in [("word/document.xml", b"x" * 1000000), ("word/document.xml", b'<!DOCTYPE x [<!ENTITY y "z">]><x/>')]:
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(name, payload)
            archive.writestr("[Content_Types].xml", "<x/>")
            archive.writestr("_rels/.rels", "<x/>")
        with pytest.raises(HTTPException):
            PrivateDocumentService._validate(data.getvalue(), ".docx")


def test_storage_missing_configuration_fails_closed(monkeypatch):
    monkeypatch.setattr("app.services.storage_service.settings.R2_ACCESS_KEY_ID", "")
    with pytest.raises(StorageError, match="unavailable"):
        StorageService().get(tenant_prefix("org_test") + "00000000-0000-0000-0000-000000000000/original.pdf")
