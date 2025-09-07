from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Dict, Protocol, Any
from telethon import TelegramClient
import config


class RunnerFunc(Protocol):
    async def __call__(self, client: TelegramClient, qi: "QueuedItem") -> Any: ...



@dataclass(slots=True)
class QueuedItem:
    filename: str
    document: any
    size: int
    path: str
    event: any
    message: any | None = None
    cancelled: bool = False


class DownloadQueue:
    """In‑memory async FIFO queue for pending downloads with cancellation support."""

    def __init__(self, limit: int):
        self.limit = limit
        self._semaphore = asyncio.Semaphore(limit)
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self.items: Dict[str, QueuedItem] = {}
        self._worker_task: asyncio.Task | None = None
        self._runner: RunnerFunc | None = None
        self._stopping = False

    def set_runner(self, runner: RunnerFunc):  # runner(client, qitem)
        self._runner = runner

    def stats(self):
        return {
            "limit": self.limit,
            "pending": len(self.items),  # items waiting to be processed
        }

    def is_saturated(self) -> bool:
        return self._semaphore.locked()

    async def enqueue(self, qi: QueuedItem):
        self.items[qi.filename] = qi
        await self._queue.put(qi.filename)

    def cancel(self, filename: str) -> bool:
        qi = self.items.get(filename)
        if not qi or qi.cancelled:
            return False
        qi.cancelled = True
        return True

    def ensure_worker(self, loop: asyncio.AbstractEventLoop, client: TelegramClient):
        if self._worker_task is None:
            self._worker_task = loop.create_task(self._worker(client))

    async def stop(self):  # graceful shutdown
        self._stopping = True
        if self._worker_task:
            # put a sentinel to unblock queue get
            await self._queue.put("__STOP__")
            try:
                await asyncio.wait_for(self._worker_task, timeout=5)
            except asyncio.TimeoutError:
                self._worker_task.cancel()

    def slot(self):  # pragma: no cover
        return self._semaphore

    async def _worker(self, client: TelegramClient):  # pragma: no cover
        while True:
            fname = await self._queue.get()
            try:
                if fname == "__STOP__":
                    break
                await self._process_item(client, fname)
            finally:
                self._queue.task_done()
        if self._stopping:
            await self._cleanup_remaining()

    async def _process_item(self, client: TelegramClient, fname: str):
        qi = self.items.pop(fname, None)
        if not qi or qi.cancelled:
            return
        async with self._semaphore:
            try:
                if self._runner:
                    # Late disk-space revalidation for queued downloads.
                    from . import manager  # local import to avoid cycle at module import
                    if not await manager._ensure_disk_space(qi.event, qi.filename, qi.size):  # type: ignore[attr-defined]
                        return
                    await self._runner(client, qi)
            except Exception:  # noqa: BLE001
                try:
                    await qi.event.respond(f"❌ Failed: {qi.filename}")
                except Exception:  # noqa: BLE001
                    pass

    async def _cleanup_remaining(self):
        for qi in self.items.values():
            qi.cancelled = True
            try:
                if qi.message:
                    await qi.message.edit(f"🛑 Cancelled (shutdown): {qi.filename}")
            except Exception:  # noqa: BLE001
                pass
        self.items.clear()


queue = DownloadQueue(config.MAX_CONCURRENT_DOWNLOADS)

__all__ = ["queue", "QueuedItem", "DownloadQueue"]
