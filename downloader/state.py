from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Any
from telethon.tl.custom.message import Message


@dataclass(slots=True)
class DownloadState:
    """Holds mutable per-download state.

    Added 'size' to enable cumulative disk space prediction across concurrent
    downloads. We keep the *expected* size (bytes) rather than bytes written so
    far to stay conservative and guarantee post-download free space >= threshold.
    """

    filename: str
    path: str
    size: int  # expected total size in bytes
    message: Optional[Message] = None
    original_event: Optional[Any] = None  # Store the original event for duplicate detection
    paused: bool = False
    cancelled: bool = False
    last_text: str = ""

    def mark_paused(self):
        if not self.cancelled:
            self.paused = True

    def mark_resumed(self):
        if not self.cancelled:
            self.paused = False

    def mark_cancelled(self):
        self.cancelled = True


class CancelledDownload(Exception):  # pragma: no cover - simple marker
    pass

__all__ = ["DownloadState", "CancelledDownload"]
