import asyncio

from downloader.manager import _handle_active_duplicate, DownloadState  # type: ignore

class Msg:
    def __init__(self):
        self.id = 111

class Ev:
    def __init__(self, mid):
        self.id = mid
        self.replies = []
    async def respond(self, text, reply_to=None, **_):  # pragma: no cover - test stub
        self.replies.append((text, reply_to))
        await asyncio.sleep(0)

class ActiveEvent(Ev):
    pass

async def _run():
    active_orig = ActiveEvent(10)
    st = DownloadState("abc.bin", "/tmp/abc.bin", 100)
    st.message = Msg()
    st.original_event = active_orig
    dup_event = Ev(99)
    await _handle_active_duplicate(dup_event, st, st.filename)
    return dup_event.replies


def test_active_duplicate_replies_to_new_message():
    replies = asyncio.run(_run())
    assert replies, "No reply captured"
    text, reply_to = replies[0]
    assert "Already in progress" in text
    assert reply_to == 99  # should reply to duplicate event's own id
