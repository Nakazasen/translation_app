"""
Cooperative stop control for long-running file translations.
"""

from __future__ import annotations

import threading
from typing import Optional


VALID_FILE_TRANSLATION_STOP_STATUSES = {"paused", "cancelled"}


class FileTranslationStopRequested(Exception):
    """Internal exception raised at safe points when stop is requested."""

    def __init__(self, status: str):
        super().__init__(status)
        self.status = status


class FileTranslationInterrupted(Exception):
    """Public exception surfaced after partial output is preserved."""

    def __init__(
        self,
        status: str,
        output_file: Optional[str] = None,
        partial_saved: bool = False,
        save_error: Optional[Exception] = None,
    ):
        if status not in VALID_FILE_TRANSLATION_STOP_STATUSES:
            raise ValueError(f"Unsupported file translation stop status: {status}")

        self.status = status
        self.output_file = output_file
        self.partial_saved = bool(partial_saved)
        self.save_error = save_error

        verb = "paused" if status == "paused" else "cancelled"
        if partial_saved and output_file:
            message = f"File translation {verb}. Partial output saved to: {output_file}"
        elif output_file:
            message = f"File translation {verb}. Partial output could not be saved: {output_file}"
        else:
            message = f"File translation {verb}."
        if save_error is not None:
            message = f"{message} Save error: {save_error}"
        super().__init__(message)


class FileTranslationControl:
    """Track pause/cancel requests for a running file translation batch."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._requested_status: Optional[str] = None

    def request_pause(self) -> None:
        self._request("paused")

    def request_cancel(self) -> None:
        self._request("cancelled")

    def get_requested_status(self) -> Optional[str]:
        with self._lock:
            return self._requested_status

    def raise_if_stopped(self) -> None:
        status = self.get_requested_status()
        if status:
            raise FileTranslationStopRequested(status)

    def _request(self, status: str) -> None:
        if status not in VALID_FILE_TRANSLATION_STOP_STATUSES:
            raise ValueError(f"Unsupported file translation stop status: {status}")
        with self._lock:
            # Cancel always wins over pause.
            if self._requested_status == "cancelled":
                return
            if status == "cancelled" or self._requested_status is None:
                self._requested_status = status
