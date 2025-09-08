from __future__ import annotations

from telethon import Button
from .state import DownloadState
from .ids import get_file_id


def build_buttons(state: DownloadState):
    if state.cancelled:
        return None
    
    file_id = get_file_id(state.filename)
    
    if state.paused:
        return [[
            Button.inline("▶ Resume", data=f"resume:{file_id}"),
            Button.inline("🛑 Cancel", data=f"cancel:{file_id}"),
        ]]
    return [[
        Button.inline("⏸ Pause", data=f"pause:{file_id}"),
        Button.inline("🛑 Cancel", data=f"cancel:{file_id}"),
    ]]

__all__ = ["build_buttons"]
