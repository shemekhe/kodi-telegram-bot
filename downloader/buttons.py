from __future__ import annotations

from telethon import Button
from .state import DownloadState


def build_buttons(state: DownloadState):
    if state.cancelled:
        return None
    if state.paused:
        return [[
            Button.inline("▶ Resume", data=f"resume:{state.filename}"),
            Button.inline("🛑 Cancel", data=f"cancel:{state.filename}"),
        ]]
    return [[
        Button.inline("⏸ Pause", data=f"pause:{state.filename}"),
        Button.inline("🛑 Cancel", data=f"cancel:{state.filename}"),
    ]]

__all__ = ["build_buttons"]
