from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Dict, Protocol, Any, List
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
    watcher_events: list[Any] | None = None
    # Short file id used for callback data (cancel button). Stored so we can rebuild buttons when renumbering.
    file_id: str | None = None

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
        # Lock protects enqueue + renumber
        self._lock = asyncio.Lock()
        # Worker bookkeeping
        self._worker_task: asyncio.Task | None = None
        self._active_tasks: List[asyncio.Task] = []
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

        Positions are dynamic: when earlier items start or are cancelled the
        remaining queued messages are renumbered. We still need a lock to avoid
        race conditions when several enqueues happen at once.
        """
        async with self._lock:
            position = len(self.items) + 1
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
        # Schedule renumber of remaining items (fire-and-forget)
        try:  # pragma: no cover - best effort
            loop = asyncio.get_running_loop()
            loop.create_task(self._renumber())
        except Exception:
            pass
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
        # Spawn a task per queued item so multiple queued downloads can run
        # concurrently up to the semaphore limit. Previously we awaited each
        # item sequentially which effectively forced single concurrency for
        # queued items.
        while True:
            fname = await self._queue.get()
            if fname == "__STOP__":
                self._queue.task_done()
                break
            # Start processing task (will itself acquire semaphore)
            t = asyncio.create_task(self._process_item(client, fname))
            self._active_tasks.append(t)
            # Remove finished tasks
            t.add_done_callback(lambda _t: self._active_tasks.remove(_t) if _t in self._active_tasks else None)
            self._queue.task_done()
        # Wait for active tasks to finish (graceful shutdown)
        if self._active_tasks:
            await asyncio.gather(*self._active_tasks, return_exceptions=True)
        if self._stopping:
            await self._cleanup_remaining()

    async def _process_item(self, client: TelegramClient, fname: str):
        # Keep item in self.items while waiting for semaphore so it appears in /status and can be cancelled.
        qi = self.items.get(fname)
        if not qi or qi.cancelled:
            return
        async with self._semaphore:
            # Pop only after acquiring slot (start time) so other queued positions remain stable.
            qi = self.items.pop(fname, None)
            if not qi or qi.cancelled:
                # If cancelled while waiting, just renumber remaining.
                await self._renumber()
                return
            # Renumber remaining queued messages since this one is starting now.
            await self._renumber()
            try:
                if self._runner:
                    from . import manager  # local import to avoid cycle
                    if not await manager._ensure_disk_space(qi.event, qi.filename, qi.size, qi.path, from_queue=True):  # type: ignore[attr-defined]
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

    async def _renumber(self):  # pragma: no cover - UI side-effects
        """Renumber queued items' messages after a dequeue/cancel.

        Best effort: failures are swallowed to avoid breaking core flow.
        """
        async with self._lock:
            if not self.items:
                return
            try:
                from telethon import Button as button_cls  # imported lazily
            except Exception:  # noqa: BLE001
                button_cls = None  # type: ignore
            # Copy values snapshot to avoid RuntimeError if items mutates while iterating
            snapshot = list(self.items.values())
            for idx, qi in enumerate(snapshot, start=1):
                if not qi.message or qi.cancelled:
                    continue
                try:
                    buttons = None
                    if button_cls and qi.file_id:
                        buttons = [[button_cls.inline("🛑 Cancel", data=f"qcancel:{qi.file_id}")]]
                    await qi.message.edit(
                        f"🕒 Queued #{idx}: {qi.filename}\nWaiting for free slot (limit {self.limit})",
                        buttons=buttons,
                    )
                except Exception:  # noqa: BLE001
                    pass


queue = DownloadQueue(config.MAX_CONCURRENT_DOWNLOADS)

__all__ = ["queue", "QueuedItem", "DownloadQueue"]
