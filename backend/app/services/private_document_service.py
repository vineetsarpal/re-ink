"""Bounded validation and immutable private storage for uploaded originals."""
from __future__ import annotations

import hashlib
import io
import re
import uuid
import zipfile
from pathlib import PurePosixPath
from xml.etree import ElementTree

from fastapi import HTTPException, UploadFile
from pypdf import PdfReader
from docx import Document
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.services.storage_service import StorageError, storage_service, tenant_prefix

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MAX_SIZE = 50 * 1024 * 1024


class PrivateDocumentService:
    @staticmethod
    def _sanitize_filename(filename):
        name = (filename or "").replace("\\", "/").split("/")[-1]
        return re.sub(r"[\x00-\x1f\x7f]", "_", name).replace("..", "_")[:255]

    @staticmethod
    def _validate(data, extension):
        try:
            if extension == ".pdf":
                if not data.startswith(b"%PDF-"):
                    raise ValueError("Not PDF")
                reader = PdfReader(io.BytesIO(data), strict=True)
                if reader.is_encrypted or not len(reader.pages):
                    raise ValueError("Encrypted or empty PDF")
                # Resolve every page so malformed page trees are rejected at upload.
                for page in reader.pages:
                    _ = page.mediabox
                return PDF
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                infos = archive.infolist()
                if len(infos) > 2000 or len({i.filename for i in infos}) != len(infos):
                    raise ValueError("Invalid archive entries")
                if sum(i.file_size for i in infos) > 100 * 1024 * 1024:
                    raise ValueError("Expanded archive exceeds limit")
                for info in infos:
                    path = PurePosixPath(info.filename)
                    if (path.is_absolute() or ".." in path.parts or "\\" in info.filename
                            or info.flag_bits & 1 or info.file_size > 20 * 1024 * 1024
                            or info.file_size > max(1, info.compress_size) * 200):
                        raise ValueError("Unsafe archive member")
                names = {i.filename for i in infos}
                if not {"[Content_Types].xml", "_rels/.rels", "word/document.xml"} <= names:
                    raise ValueError("Missing Word structure")
                if any("vbaproject" in name.lower() for name in names):
                    raise ValueError("Active document content")
                for info in infos:
                    if info.filename.endswith((".xml", ".rels")):
                        xml = archive.read(info)
                        if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
                            raise ValueError("XML entities forbidden")
                        ElementTree.fromstring(xml)
                Document(io.BytesIO(data))
                return DOCX
        except Exception as exc:
            raise HTTPException(400, "Upload must be a valid unencrypted PDF or DOCX") from exc

    async def save_uploaded_file(self, file: UploadFile, org_id: str, job_id=None, before_store=None):
        filename = self._sanitize_filename(file.filename)
        extension = PurePosixPath(filename).suffix.lower()
        if extension not in (".pdf", ".docx"):
            raise HTTPException(400, "Only PDF and DOCX uploads are supported")
        data = bytearray()
        limit = min(settings.MAX_UPLOAD_SIZE, MAX_SIZE)
        # Match the Cloudflare consumer’s conservative memory bound.
        limit = min(limit, 5 * 1024 * 1024)
        while chunk := await file.read(64 * 1024):
            data.extend(chunk)
            if len(data) > limit:
                raise HTTPException(413, "File exceeds the upload size limit")
        content = bytes(data)
        content_type = await run_in_threadpool(self._validate, content, extension)
        # Never use a caller-provided identity or path for immutable object names.
        job_id = str(uuid.uuid4())
        key = f"{tenant_prefix(org_id)}{job_id}/original{extension}"
        if before_store is not None:
            before_store(job_id, key)
        try:
            await run_in_threadpool(storage_service.put, key, content, content_type)
        except StorageError as exc:
            raise HTTPException(503, "Original document storage is unavailable") from exc
        return {"job_id": job_id, "filename": filename, "storage_key": key,
                "content_type": content_type, "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest()}

    def read_original(self, job):
        try:
            if not job.storage_key or not job.storage_key.startswith(tenant_prefix(job.org_id)):
                raise StorageError("Invalid original metadata")
            data = storage_service.get(job.storage_key)
            if len(data) != job.size_bytes or hashlib.sha256(data).hexdigest() != job.sha256:
                raise StorageError("Original integrity check failed")
            return data
        except StorageError as exc:
            raise HTTPException(503, "Original document is unavailable") from exc

    def delete_original(self, key):
        storage_service.delete(key)


private_document_service = PrivateDocumentService()
