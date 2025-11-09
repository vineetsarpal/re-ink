"""
Service layer for document processing operations.
Handles file upload, validation, and coordination with extraction service.
"""
import os
import uuid
import shutil
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from fastapi import UploadFile, HTTPException
from app.core.config import settings

logger = logging.getLogger(__name__)


class DocumentService:
    """
    Service for handling document operations including upload and validation.
    """

    def __init__(self):
        self.upload_dir = Path(settings.UPLOAD_DIR)
        self.max_size = settings.MAX_UPLOAD_SIZE
        self.allowed_extensions = settings.ALLOWED_EXTENSIONS

        # Create upload directory if it doesn't exist
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    async def save_uploaded_file(
        self,
        file: UploadFile,
        job_id: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Save an uploaded file to disk after validation.

        Args:
            file: The uploaded file from FastAPI
            job_id: Optional job ID for file naming

        Returns:
            Dictionary with file_path, filename, and job_id

        Raises:
            HTTPException: If file validation fails
        """
        try:
            # Validate file extension
            file_ext = Path(file.filename).suffix.lower()
            if file_ext not in self.allowed_extensions:
                raise HTTPException(
                    status_code=400,
                    detail=f"File type not allowed. Allowed types: {', '.join(self.allowed_extensions)}"
                )

            # Generate job ID if not provided
            if not job_id:
                job_id = str(uuid.uuid4())

            # Create safe filename
            safe_filename = f"{job_id}_{self._sanitize_filename(file.filename)}"
            file_path = self.upload_dir / safe_filename

            # Check file size by reading in chunks
            total_size = 0
            with open(file_path, "wb") as buffer:
                while chunk := await file.read(8192):  # Read 8KB at a time
                    total_size += len(chunk)

                    if total_size > self.max_size:
                        # Clean up the partial file
                        buffer.close()
                        os.unlink(file_path)
                        raise HTTPException(
                            status_code=413,
                            detail=f"File too large. Maximum size: {self.max_size / 1024 / 1024}MB"
                        )

                    buffer.write(chunk)

            logger.info(f"File saved successfully: {safe_filename}")

            return {
                "file_path": str(file_path),
                "filename": safe_filename,
                "job_id": job_id,
                "original_filename": file.filename
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error saving uploaded file: {str(e)}")
            raise HTTPException(status_code=500, detail="Error saving file")

    def delete_file(self, file_path: str) -> bool:
        """
        Delete a file from the upload directory.

        Args:
            file_path: Path to the file to delete

        Returns:
            True if file was deleted, False otherwise
        """
        try:
            path = Path(file_path)
            if path.exists() and path.parent == self.upload_dir:
                path.unlink()
                logger.info(f"File deleted: {file_path}")
                return True
            return False
        except Exception as e:
            logger.error(f"Error deleting file: {str(e)}")
            return False

    def get_file_info(self, file_path: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a file.

        Args:
            file_path: Path to the file

        Returns:
            Dictionary with file information or None if file doesn't exist
        """
        try:
            path = Path(file_path)
            if not path.exists():
                return None

            return {
                "filename": path.name,
                "size": path.stat().st_size,
                "extension": path.suffix,
                "created_at": path.stat().st_ctime,
                "modified_at": path.stat().st_mtime
            }
        except Exception as e:
            logger.error(f"Error getting file info: {str(e)}")
            return None

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        """
        Sanitize filename to prevent directory traversal and other issues.

        Args:
            filename: Original filename

        Returns:
            Sanitized filename
        """
        # Remove any path components
        filename = os.path.basename(filename)

        # Replace any dangerous characters
        unsafe_chars = ['..', '/', '\\', '\0']
        for char in unsafe_chars:
            filename = filename.replace(char, '_')

        return filename


# Singleton instance
document_service = DocumentService()
