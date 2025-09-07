"""Thin helper layer for interacting with Kodi JSON-RPC."""
from __future__ import annotations

import requests
from typing import Any

import config


def _rpc(method: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    try:
        payload = {"jsonrpc": "2.0", "method": method, "params": params or {}, "id": 1}
        r = requests.post(
            config.KODI_URL, headers=config.HEADERS, json=payload, auth=config.KODI_AUTH, timeout=5
        )
        return r.json()
    except Exception as e:  # noqa: E722  (broad except acceptable here for logging)
        print(f"Kodi RPC error ({method}): {e}")
        return None


def notify(title: str, message: str) -> None:
    _rpc(
        "GUI.ShowNotification",
        {"title": title, "message": message, "displaytime": 2000},
    )


def play(filepath: str) -> None:
    _rpc("Player.Open", {"item": {"file": filepath}})


def is_playing() -> bool:
    data = _rpc("Player.GetActivePlayers") or {}
    return bool(data.get("result"))


def progress_notify(filename: str, percent: int, speed: str) -> None:
    bar = "▓" * (percent // 10) + "░" * (10 - percent // 10)
    notify(f"Downloading: {filename}", f"{bar} {percent}% | {speed}/s")

__all__ = ["notify", "play", "is_playing", "progress_notify"]
