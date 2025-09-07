from __future__ import annotations

import asyncio
import signal
from telethon import TelegramClient

import config
import kodi
from downloader.queue import queue
from downloader.manager import states, register_handlers


def startup_message() -> None:
    try:
        kodi.notify("Telegram Bot", "Ready for private media uploads")
    except Exception as e:  # noqa: BLE001
        print(f"Startup notification failed: {e}")


def main() -> None:
    client = _setup_client()
    loop = client.loop
    shutdown_event = asyncio.Event()

    async def shutdown():
        await _graceful_shutdown(client, shutdown_event)

    _install_signal_handlers(loop, shutdown)
    try:
        client.run_until_disconnected()
    finally:
        if not shutdown_event.is_set():
            loop.run_until_complete(shutdown())


def _setup_client():
    config.validate()
    client = TelegramClient("bot", config.API_ID, config.API_HASH)
    client.start(bot_token=config.BOT_TOKEN)
    register_handlers(client)
    # Schedule catch_up so it runs after loop is running
    async def _do_catch_up():
        try:
            await client.catch_up()
        except Exception as e:  # noqa: BLE001
            print(f"[catch_up] failed: {e}")
    client.loop.create_task(_do_catch_up())
    startup_message()
    print("[main] Bridge running – send a video or audio file to this bot in a private chat.")
    return client


async def _graceful_shutdown(client, shutdown_event: asyncio.Event):
    if shutdown_event.is_set():
        return
    print("\nShutting down gracefully...")
    shutdown_event.set()
    for st in states.values():
        st.mark_cancelled()
        try:
            if st.message:
                await st.message.edit(f"🛑 Cancelling (shutdown): {st.filename}")
        except Exception:  # noqa: BLE001
            pass
    try:
        await asyncio.wait_for(queue.stop(), timeout=6)
    except Exception:  # noqa: BLE001
        pass
    client.disconnect()


def _install_signal_handlers(loop, shutdown_coro):
    def trigger():  # noqa: D401
        loop.create_task(shutdown_coro())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, trigger)
        except NotImplementedError:  # pragma: no cover
            signal.signal(sig, lambda *_: loop.create_task(shutdown_coro()))


if __name__ == "__main__":  # pragma: no cover
    main()

