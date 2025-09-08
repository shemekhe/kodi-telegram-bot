"""Utility helpers (size formatting, media detection, resource checks)."""
from __future__ import annotations

import math
import os
import shutil
import time
import psutil  # lightweight import; already in requirements
from telethon.tl.types import (
    DocumentAttributeFilename,
    DocumentAttributeVideo,
    DocumentAttributeAudio,
)



def humanize_size(size_bytes: float) -> str:
    """Return human readable size (caps at TB to avoid index errors).

    For extremely large inputs > TB we still label as TB.
    """
    if size_bytes <= 0:
        return "0B"
    names = ("B", "KB", "MB", "GB", "TB")
    i = int(math.log(size_bytes, 1024))
    if i >= len(names):  # safeguard for pathological values
        i = len(names) - 1
    p = 1024 ** i
    return f"{round(size_bytes / p, 2)} {names[i]}"


_VIDEO_EXT = {".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".webm", ".m4v", ".3gp"}
_AUDIO_EXT = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".wma"}


def is_media_file(document) -> bool:  # type: ignore[override]
    mime_type = getattr(document, "mime_type", "") or ""
    if mime_type.startswith(("video/", "audio/")):
        return True
    for attr in getattr(document, "attributes", []):
        if isinstance(attr, (DocumentAttributeVideo, DocumentAttributeAudio)):
            return True
        if isinstance(attr, DocumentAttributeFilename):
            ext = os.path.splitext(attr.file_name)[1].lower()
            if ext in _VIDEO_EXT or ext in _AUDIO_EXT:
                return True
    return False


def free_disk_mb(path: str) -> int:
    """Return free disk space for the partition containing path in MB."""
    usage = shutil.disk_usage(path)
    return int(usage.free / (1024 * 1024))


def has_enough_space(path: str, file_size_bytes: int, min_free_mb: int) -> bool:
    """Check if after downloading file_size_bytes we still have >= min_free_mb free."""
    free_after = free_disk_mb(path) - int(file_size_bytes / (1024 * 1024))
    return free_after >= min_free_mb


def cleanup_old_files(directory: str, target_free_mb: int) -> int:
    """Delete oldest files (by mtime) recursively until free space >= target_free_mb.

    Designed to work with organized media directories (Movies/, Series/, Other/).
    Only regular files are removed; empty directories are left as‑is. Best effort.
    """
    deleted = 0
    try:
        entries = []
        for root, _dirs, files in os.walk(directory):
            for name in files:
                full = os.path.join(root, name)
                try:
                    entries.append((os.path.getmtime(full), full, os.path.getsize(full)))
                except OSError:
                    pass
        entries.sort()  # oldest first
        for _mtime, full, _size in entries:
            if free_disk_mb(directory) >= target_free_mb:
                break
            try:
                os.remove(full)
                deleted += 1
            except OSError:  # ignore failures
                pass
    except Exception:  # noqa: BLE001
        return deleted
    return deleted


def remove_empty_parents(path: str, stop_dirs: list[str]) -> int:
    """Remove empty parent directories up to (but excluding) any stop directory.

    Returns number of directories removed. Best effort only.
    """
    removed = 0
    try:
        stop_set = {os.path.abspath(d) for d in stop_dirs}
        cur = os.path.abspath(os.path.dirname(path))
        while cur not in stop_set:
            if not os.path.isdir(cur):  # nothing more to do
                break
            try:
                if os.listdir(cur):  # not empty
                    break
            except OSError:
                break
            try:
                os.rmdir(cur)
                removed += 1
            except OSError:
                break
            cur = os.path.abspath(os.path.dirname(cur))
    except Exception:  # noqa: BLE001
        return removed
    return removed


_last_mem_warn: float = 0.0


def maybe_memory_warning(threshold_percent: int) -> bool:
    """Return True if memory usage >= threshold and we haven't warned recently.

    Simple rate limit: at most one warning every 60 seconds.
    """
    global _last_mem_warn
    if threshold_percent <= 0:
        return False
    now = time.time()
    if now - _last_mem_warn < 60:
        return False
    try:
        percent = psutil.virtual_memory().percent
    except Exception:  # pragma: no cover - psutil edge failures
        return False
    if percent >= threshold_percent:
        _last_mem_warn = now
        return True
    return False


__all__ = [
    "humanize_size",
    "is_media_file",
    "free_disk_mb",
    "has_enough_space",
    "maybe_memory_warning",
    "cleanup_old_files",
    "remove_empty_parents",
]
