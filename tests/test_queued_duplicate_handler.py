import asyncio

from downloader.manager import _handle_queued_duplicate  # type: ignore
from downloader.queue import QueuedItem


class Ev:
    def __init__(self, sender_id, mid):
        self.sender_id = sender_id
        self.id = mid
        self.replies = []
    async def respond(self, text, reply_to=None, **_):  # pragma: no cover trivial stub
        self.replies.append((text, reply_to))
        await asyncio.sleep(0)


def test_handle_queued_duplicate_same_user():
    original = Ev(10, 1)
    qi = QueuedItem("dup.bin", object(), 10, "/tmp/dup.bin", original)
    dup = Ev(10, 2)  # same sender
    asyncio.run(_handle_queued_duplicate(dup, qi, qi.filename))
    assert any(("Already queued" in t) or (t.startswith("🕒 Queued:")) for t, _ in dup.replies)
    # reply_to may be None in test stub since queued placeholder has no id attribute
    assert qi.watcher_events is None  # still no watcher for same user


def test_handle_queued_duplicate_different_user():
    original = Ev(10, 1)
    qi = QueuedItem("dup2.bin", object(), 10, "/tmp/dup2.bin", original)
    dup = Ev(11, 3)
    asyncio.run(_handle_queued_duplicate(dup, qi, qi.filename))
    assert any("queued" in t.lower() for t, _ in dup.replies)
    assert qi.watcher_events and len(qi.watcher_events) == 1
