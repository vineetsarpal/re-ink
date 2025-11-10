"""
In-memory storage for document extraction jobs.
Provides a simple abstraction so multiple modules (documents API, agents)
can read/write job metadata without sharing global dictionaries directly.
"""
from __future__ import annotations

from datetime import datetime
from threading import Lock
from typing import Any, Dict, Optional


class ExtractionJobStore:
    """Thread-safe in-memory store for extraction job metadata."""

    def __init__(self) -> None:
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = Lock()

    def create_job(self, job_id: str, payload: Dict[str, Any]) -> None:
        """Create or overwrite a job entry."""
        with self._lock:
            payload.setdefault("created_at", datetime.utcnow())
            self._jobs[job_id] = payload

    def update_job(self, job_id: str, updates: Dict[str, Any]) -> None:
        """Merge updates into an existing job if it exists."""
        with self._lock:
            if job_id not in self._jobs:
                # Initialise missing job to allow delayed writes
                self._jobs[job_id] = {"created_at": datetime.utcnow()}
            self._jobs[job_id].update(updates)

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Return a shallow copy of a job payload."""
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def delete_job(self, job_id: str) -> None:
        """Remove a job entry if present."""
        with self._lock:
            self._jobs.pop(job_id, None)


# Singleton store used across the app
extraction_store = ExtractionJobStore()
