"""
Translation job tracking with checkpoints, resume, and failed-item retry support.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from translation_app import __version__


VALID_JOB_STATUSES = {
    "pending",
    "running",
    "paused",
    "completed",
    "failed",
    "cancelled",
}

RESUMABLE_JOB_STATUSES = {"pending", "running", "paused", "failed"}

CHECKPOINT_EVENTS = {
    "segment_started",
    "segment_completed",
    "segment_completed_after_retry",
    "segment_failed",
    "provider_success",
    "provider_fail",
    "job_paused",
    "job_completed",
    "job_failed",
    "job_resumed",
}

_SENSITIVE_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z\-_]{8,}"),
    re.compile(r"(?i)\b(?:gemini|google)?[_-]?api[_-]?key\b\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)\bsentinel(?:[_-]?api)?(?:[_-]?key)?[0-9A-Za-z\-_]*\b"),
]


def get_jobs_dir() -> Path:
    """Get the correct jobs directory for the current runtime."""
    if getattr(sys, "frozen", False):
        app_data = os.getenv("APPDATA", os.path.expanduser("~"))
        jobs_dir = Path(app_data) / "DichTuDong" / "jobs"
    else:
        jobs_dir = Path(__file__).resolve().parent.parent / "data" / "jobs"

    jobs_dir.mkdir(parents=True, exist_ok=True)
    return jobs_dir


def iso_timestamp() -> str:
    """Return a timezone-aware ISO 8601 timestamp."""
    return datetime.now(timezone.utc).isoformat()


def redact_sensitive(value: Any) -> Any:
    """Redact API key-like patterns recursively."""
    if isinstance(value, dict):
        return {key: redact_sensitive(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive(item) for item in value)
    if not isinstance(value, str):
        return value

    redacted = value
    for pattern in _SENSITIVE_PATTERNS:
        redacted = pattern.sub("[REDACTED_API_KEY]", redacted)
    return redacted


class TranslationJobManager:
    """Manage translation jobs, progress, checkpoints, and retry metadata."""

    def __init__(self, jobs_dir: Optional[Path] = None):
        self.jobs_dir = Path(jobs_dir) if jobs_dir else get_jobs_dir()
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def get_jobs_dir(self) -> Path:
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        return self.jobs_dir

    def create_job(
        self,
        input_files,
        output_dir,
        source_lang,
        target_lang,
        strategy,
        job_type="unknown",
        notes="",
    ) -> dict:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        short_id = uuid.uuid4().hex[:6]
        job_id = f"job_{timestamp}_{short_id}"
        now = iso_timestamp()

        job_data = {
            "job_id": job_id,
            "created_at": now,
            "updated_at": now,
            "status": "pending",
            "source_lang": redact_sensitive(source_lang or ""),
            "target_lang": redact_sensitive(target_lang or ""),
            "strategy": redact_sensitive(strategy or ""),
            "input_files": redact_sensitive(list(input_files or [])),
            "output_dir": redact_sensitive(str(output_dir or "")),
            "job_type": redact_sensitive(job_type or "unknown"),
            "app_version": __version__,
            "notes": redact_sensitive(str(notes or "")),
        }

        progress_data = {
            "job_id": job_id,
            "total_segments": 0,
            "completed_segments": 0,
            "failed_segments": 0,
            "skipped_segments": 0,
            "tm_hits": 0,
            "provider_calls": 0,
            "current_file": "",
            "current_sheet": "",
            "current_segment_id": "",
            "percent": 0.0,
            "updated_at": now,
        }

        job_dir = self._get_job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        self._write_json_atomic(job_dir / "job.json", job_data)
        self._write_json_atomic(job_dir / "progress.json", progress_data)
        self._touch_file(job_dir / "errors.jsonl")
        self._touch_file(job_dir / "checkpoints.jsonl")
        return job_data

    def load_job(self, job_id) -> dict:
        return self._read_json(self._get_job_dir(job_id) / "job.json")

    def list_jobs(self, limit=50) -> list[dict]:
        jobs: list[dict] = []
        for job_dir in self.get_jobs_dir().glob("job_*"):
            job_file = job_dir / "job.json"
            if not job_file.exists():
                continue
            try:
                jobs.append(self._read_json(job_file))
            except Exception:
                continue

        jobs.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return jobs[:limit]

    def update_job_status(self, job_id, status) -> None:
        self._validate_status(status)
        with self._lock:
            job_path = self._get_job_dir(job_id) / "job.json"
            job_data = self._read_json(job_path)
            job_data["status"] = status
            job_data["updated_at"] = iso_timestamp()
            self._write_json_atomic(job_path, job_data)

    def update_progress(
        self,
        job_id,
        total_segments=None,
        completed_delta=0,
        failed_delta=0,
        skipped_delta=0,
        tm_hit_delta=0,
        provider_call_delta=0,
        current_file=None,
        current_sheet=None,
        current_segment_id=None,
    ) -> dict:
        with self._lock:
            progress_path = self._get_job_dir(job_id) / "progress.json"
            progress_data = self._read_json(progress_path)

            if total_segments is not None:
                progress_data["total_segments"] = max(0, int(total_segments))

            progress_data["completed_segments"] = max(
                0, int(progress_data.get("completed_segments", 0)) + int(completed_delta)
            )
            progress_data["failed_segments"] = max(
                0, int(progress_data.get("failed_segments", 0)) + int(failed_delta)
            )
            progress_data["skipped_segments"] = max(
                0, int(progress_data.get("skipped_segments", 0)) + int(skipped_delta)
            )
            progress_data["tm_hits"] = max(
                0, int(progress_data.get("tm_hits", 0)) + int(tm_hit_delta)
            )
            progress_data["provider_calls"] = max(
                0, int(progress_data.get("provider_calls", 0)) + int(provider_call_delta)
            )

            if current_file is not None:
                progress_data["current_file"] = redact_sensitive(str(current_file))
            if current_sheet is not None:
                progress_data["current_sheet"] = redact_sensitive(str(current_sheet))
            if current_segment_id is not None:
                progress_data["current_segment_id"] = redact_sensitive(str(current_segment_id))

            total = int(progress_data.get("total_segments", 0))
            done = (
                int(progress_data.get("completed_segments", 0))
                + int(progress_data.get("failed_segments", 0))
                + int(progress_data.get("skipped_segments", 0))
            )
            progress_data["percent"] = round(min(100.0, (done / total) * 100.0), 2) if total > 0 else 0.0
            progress_data["updated_at"] = iso_timestamp()
            self._write_json_atomic(progress_path, progress_data)
            return progress_data

    def record_checkpoint(self, job_id, event, **metadata) -> None:
        if event not in CHECKPOINT_EVENTS:
            raise ValueError(f"Invalid checkpoint event: {event}")

        payload = {
            "timestamp": iso_timestamp(),
            "job_id": job_id,
            "event": event,
            "file": redact_sensitive(str(metadata.get("file", "") or "")),
            "sheet": redact_sensitive(str(metadata.get("sheet", "") or "")),
            "cell": redact_sensitive(str(metadata.get("cell", "") or "")),
            "segment_id": redact_sensitive(str(metadata.get("segment_id", "") or "")),
            "provider": redact_sensitive(str(metadata.get("provider", "") or "")),
            "model": redact_sensitive(str(metadata.get("model", "") or "")),
            "error_type": redact_sensitive(str(metadata.get("error_type", "") or "")),
            "error_message": self._sanitize_error_message(metadata.get("error_message", "")),
            "status": redact_sensitive(str(metadata.get("status", "") or "")),
        }
        self._append_jsonl_safe(self._get_job_dir(job_id) / "checkpoints.jsonl", payload)

    def record_failed_item(
        self,
        job_id,
        file=None,
        sheet=None,
        cell=None,
        segment_id=None,
        source_lang=None,
        target_lang=None,
        error_type=None,
        error_message=None,
        retry_count=0,
        source_hash=None,
        source_length=None,
    ) -> None:
        payload = {
            "timestamp": iso_timestamp(),
            "job_id": job_id,
            "file": redact_sensitive(str(file or "")),
            "sheet": redact_sensitive(str(sheet or "")),
            "cell": redact_sensitive(str(cell or "")),
            "segment_id": redact_sensitive(str(segment_id or "")),
            "source_lang": redact_sensitive(str(source_lang or "")),
            "target_lang": redact_sensitive(str(target_lang or "")),
            "error_type": redact_sensitive(str(error_type or "")),
            "error_message": self._sanitize_error_message(error_message),
            "retry_count": max(0, int(retry_count)),
            "source_hash": redact_sensitive(str(source_hash or "")),
            "source_length": int(source_length) if source_length is not None else 0,
        }
        self._append_jsonl_safe(self._get_job_dir(job_id) / "errors.jsonl", payload)

    def load_failed_items(self, job_id) -> list[dict]:
        return self._read_jsonl(self._get_job_dir(job_id) / "errors.jsonl")

    def mark_completed(self, job_id) -> None:
        with self._lock:
            progress_path = self._get_job_dir(job_id) / "progress.json"
            progress_data = self._read_json(progress_path)
            if int(progress_data.get("total_segments", 0)) > 0:
                done = (
                    int(progress_data.get("completed_segments", 0))
                    + int(progress_data.get("failed_segments", 0))
                    + int(progress_data.get("skipped_segments", 0))
                )
                progress_data["percent"] = round(min(100.0, (done / progress_data["total_segments"]) * 100.0), 2)
            else:
                progress_data["percent"] = 100.0
            progress_data["updated_at"] = iso_timestamp()
            self._write_json_atomic(progress_path, progress_data)

        self.update_job_status(job_id, "completed")
        self.record_checkpoint(job_id, "job_completed", status="completed")

    def mark_failed(self, job_id, reason) -> None:
        with self._lock:
            job_path = self._get_job_dir(job_id) / "job.json"
            job_data = self._read_json(job_path)
            job_data["status"] = "failed"
            job_data["updated_at"] = iso_timestamp()
            job_data["failure_reason"] = self._sanitize_error_message(reason)
            self._write_json_atomic(job_path, job_data)

        self.record_checkpoint(job_id, "job_failed", status="failed")

    def can_resume(self, job_id) -> bool:
        status = self.load_job(job_id).get("status", "")
        return status in RESUMABLE_JOB_STATUSES

    def resume_job(self, job_id) -> dict:
        if not self.can_resume(job_id):
            raise ValueError(f"Job {job_id} is not resumable")

        self.update_job_status(job_id, "running")
        self.record_checkpoint(job_id, "job_resumed", status="running")
        return self.get_job_summary(job_id)

    def prepare_retry_failed(self, job_id) -> list[dict]:
        retry_items = []
        for item in self.load_failed_items(job_id):
            retry_item = dict(item)
            retry_item["retry_count"] = max(0, int(item.get("retry_count", 0))) + 1
            retry_items.append(retry_item)
        return retry_items

    def reset_failed_items_for_retry(self, job_id) -> list[dict]:
        return self.prepare_retry_failed(job_id)

    def get_job_summary(self, job_id) -> dict:
        job_data = self.load_job(job_id)
        progress_data = self._read_json(self._get_job_dir(job_id) / "progress.json")
        failed_items = self.load_failed_items(job_id)
        return {
            "job": job_data,
            "progress": progress_data,
            "failed_items": failed_items,
            "failed_item_count": len(failed_items),
            "can_resume": job_data.get("status") in RESUMABLE_JOB_STATUSES,
        }

    def _get_job_dir(self, job_id: str) -> Path:
        return self.get_jobs_dir() / job_id

    def _validate_status(self, status: str) -> None:
        if status not in VALID_JOB_STATUSES:
            raise ValueError(f"Invalid job status: {status}")

    def _touch_file(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)

    def _read_json(self, path: Path) -> dict:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _read_jsonl(self, path: Path) -> list[dict]:
        if not path.exists():
            return []

        items: list[dict] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    items.append(json.loads(stripped))
                except Exception:
                    continue
        return items

    def _write_json_atomic(self, path: Path, payload: dict) -> None:
        safe_payload = redact_sensitive(payload)
        tmp_path = path.with_suffix(f"{path.suffix}.tmp")
        with self._lock:
            try:
                with tmp_path.open("w", encoding="utf-8", newline="\n") as handle:
                    json.dump(safe_payload, handle, ensure_ascii=False, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp_path, path)
            except Exception:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass
                raise

    def _append_jsonl_safe(self, path: Path, payload: dict) -> None:
        safe_payload = redact_sensitive(payload)
        try:
            with self._lock:
                with path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(json.dumps(safe_payload, ensure_ascii=False) + "\n")
        except Exception:
            return

    def _sanitize_error_message(self, error_message: Any) -> str:
        redacted = redact_sensitive(str(error_message or ""))
        return redacted[:500]


_translation_job_manager: Optional[TranslationJobManager] = None


def get_translation_job_manager() -> TranslationJobManager:
    global _translation_job_manager
    if _translation_job_manager is None:
        _translation_job_manager = TranslationJobManager()
    return _translation_job_manager

