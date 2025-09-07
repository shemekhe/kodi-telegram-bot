"""Backwards-compatible import shim.

Public API kept stable: `register(client)` now delegates to modular downloader package.
"""
from downloader.manager import register_handlers as register  # noqa: F401

__all__ = ["register"]
