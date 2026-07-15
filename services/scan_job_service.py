from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from config.settings import SCAN_JOB_MAX_WORKERS, SCAN_JOB_RETENTION_SECONDS
from services.openclaw_service import OpenClawService


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ScanJobService:
    """Serialized background execution for long, quality-preserving scans."""

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max(1, SCAN_JOB_MAX_WORKERS))
        self._jobs: dict[str, dict[str, Any]] = {}
        self._created_monotonic: dict[str, float] = {}
        self._lock = threading.RLock()

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._cleanup()
        job_id = f"whalebot-job-{uuid.uuid4().hex[:16]}"
        job = {
            "job_id": job_id,
            "status": "QUEUED",
            "submitted_at": _now(),
            "started_at": None,
            "finished_at": None,
            "request": dict(payload),
            "result": None,
            "error": None,
        }
        with self._lock:
            self._jobs[job_id] = job
            self._created_monotonic[job_id] = time.monotonic()
        self._executor.submit(self._run, job_id, dict(payload))
        return self.get(job_id) or job

    def get(self, job_id: str) -> dict[str, Any] | None:
        self._cleanup()
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job is not None else None

    def _run(self, job_id: str, payload: dict[str, Any]) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job["status"] = "RUNNING"
            job["started_at"] = _now()
        try:
            result = OpenClawService().execute(
                mode=str(payload.get("mode", "whale")),
                focus=payload.get("focus"),
                wallet=payload.get("wallet"),
                cache_policy=str(payload.get("cache_policy", "same_run_reuse")),
                verification_passes=int(payload.get("verification_passes", 1)),
                run_id=job_id,
                market_pages_per_run=int(payload.get("market_pages_per_run", 3)),
                market_max_pages=int(payload.get("market_max_pages", 25)),
            )
            with self._lock:
                job = self._jobs[job_id]
                job["status"] = "COMPLETED" if result.get("ok") else "COMPLETED_WITH_SOURCE_ERROR"
                job["result"] = result
                job["finished_at"] = _now()
        except Exception as exc:
            with self._lock:
                job = self._jobs[job_id]
                job["status"] = "FAILED"
                job["error"] = str(exc)
                job["finished_at"] = _now()

    def _cleanup(self) -> None:
        cutoff = time.monotonic() - SCAN_JOB_RETENTION_SECONDS
        with self._lock:
            expired = [
                job_id
                for job_id, created in self._created_monotonic.items()
                if created < cutoff
                and self._jobs.get(job_id, {}).get("status")
                not in {"QUEUED", "RUNNING"}
            ]
            for job_id in expired:
                self._created_monotonic.pop(job_id, None)
                self._jobs.pop(job_id, None)


_scan_job_service = ScanJobService()


def get_scan_job_service() -> ScanJobService:
    return _scan_job_service
