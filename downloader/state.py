from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Any, List
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
    original_event: Optional[Any] = None  # Original upload event (reply target for progress)
    paused: bool = False
    cancelled: bool = False
    last_text: str = ""
    # Additional progress mirror messages (for duplicate requests from other users)
    extra_messages: List[Message] = field(default_factory=list)

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
