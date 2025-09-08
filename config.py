"""Runtime configuration.

Reads environment variables once (via python-dotenv if present) and exposes
constants for the rest of the code. Keep this lean: only parsing + validation.
Required: TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_BOT_TOKEN.
"""
from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default

API_ID: int = _env_int("TELEGRAM_API_ID", 0)
API_HASH: str = os.getenv("TELEGRAM_API_HASH", "")
BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")

KODI_URL: str = os.getenv("KODI_URL", "http://localhost:8080/jsonrpc")
KODI_USERNAME: str = os.getenv("KODI_USERNAME", "kodi")
KODI_PASSWORD: str = os.getenv("KODI_PASSWORD", "")
KODI_AUTH = (KODI_USERNAME, KODI_PASSWORD)
HEADERS = {"Content-Type": "application/json"}

_RAW_DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "~/Downloads")
DOWNLOAD_DIR = os.path.expanduser(os.path.expandvars(_RAW_DOWNLOAD_DIR))
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Media organization feature flag.
# Only toggle is ORGANIZE_MEDIA (defaults ON). Folder names are fixed constants
# to keep layout predictable and portable (not overridden by env vars).
ORGANIZE_MEDIA: bool = os.getenv("ORGANIZE_MEDIA", "1").lower() in {"1", "true", "yes", "on"}
MOVIES_DIR_NAME: str = "Movies"
SERIES_DIR_NAME: str = "Series"
OTHER_DIR_NAME: str = "Other"

MAX_RETRY_ATTEMPTS: int = _env_int("MAX_RETRY_ATTEMPTS", 3)
MAX_CONCURRENT_DOWNLOADS: int = _env_int("MAX_CONCURRENT_DOWNLOADS", 5)
MIN_FREE_DISK_MB: int = _env_int("MIN_FREE_DISK_MB", 200)
DISK_WARNING_MB: int = _env_int("DISK_WARNING_MB", 500)
MEMORY_WARNING_PERCENT: int = _env_int("MEMORY_WARNING_PERCENT", 90)


def validate() -> None:
    if API_ID == 0 or not API_HASH or not BOT_TOKEN:
        raise SystemExit(
            "Missing TELEGRAM_API_ID / TELEGRAM_API_HASH / TELEGRAM_BOT_TOKEN"
        )

__all__ = [
    "API_ID",
    "API_HASH",
    "BOT_TOKEN",
    "KODI_URL",
    "KODI_AUTH",
    "HEADERS",
    "DOWNLOAD_DIR",
    "ORGANIZE_MEDIA",
    "MOVIES_DIR_NAME",
    "SERIES_DIR_NAME",
    "OTHER_DIR_NAME",
    "MAX_RETRY_ATTEMPTS",
    "MAX_CONCURRENT_DOWNLOADS",
    "MIN_FREE_DISK_MB",
    "DISK_WARNING_MB",
    "MEMORY_WARNING_PERCENT",
    "validate",
]
