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
    event: any  # original enqueue event
    message: any | None = None
    cancelled: bool = False
    # Events from other users requesting same file while queued; will receive progress when started
    watcher_events: list[Any] = None

    def add_watcher(self, ev):  # lightweight helper
        if self.watcher_events is None:
            self.watcher_events = []
        self.watcher_events.append(ev)


class DownloadQueue:
    """In‑memory async FIFO queue for pending downloads with cancellation support."""

    def __init__(self, limit: int):
        # Basic capacity + synchronization primitives
        self.limit = limit
        self._semaphore = asyncio.Semaphore(limit)
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        # Visible queued items (filename -> QueuedItem)
        self.items: Dict[str, QueuedItem] = {}
        # Monotonic counter for assigning stable queue numbers
        self._counter = 0
        # Lock protects enqueue section assigning positions
        self._lock = asyncio.Lock()
        # Worker bookkeeping
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

    async def enqueue(self, qi: QueuedItem) -> int:
        """Enqueue an item and return its 1‑based position at insertion.

        Uses an internal lock so that when multiple files are queued nearly
        simultaneously (e.g. user sends many files) each gets a distinct
        position instead of all observing the same pre‑enqueue size.
        """
        async with self._lock:
            self._counter += 1
            position = self._counter
            self.items[qi.filename] = qi
            await self._queue.put(qi.filename)
            return position

    def cancel(self, filename: str) -> bool:
        """Cancel a queued (not yet started) item.

        Implementation detail: we remove the item from the ``items`` mapping
        immediately so status queries stop reporting it. The filename token
        already sits inside the internal asyncio.Queue; when the worker later
        dequeues it, ``_process_item`` will find no entry (``None``) and skip.
        This keeps the implementation simple without needing a costly queue
        compaction / rebuild.
        """
        qi = self.items.get(filename)
        if not qi or qi.cancelled:
            return False
        qi.cancelled = True
        # Remove from visible queue immediately; worker will ignore leftover token
        self.items.pop(filename, None)
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
