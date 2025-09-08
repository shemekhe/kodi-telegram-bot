from __future__ import annotations

import asyncio
import os
import time
from typing import Callable, Awaitable, Any
from telethon import events, Button, TelegramClient
from telethon.tl.types import Document

import config
from organizer import build_final_path, parse_filename
from utils import remove_empty_parents
import kodi
import utils
from logger import log
from .state import DownloadState, CancelledDownload
from .buttons import build_buttons
from .progress import RateLimiter, create_progress_callback, wait_if_paused
from .queue import queue, QueuedItem
from .ids import get_file_id

states: dict[str, DownloadState] = {}
# Mapping from short file_id -> filename (buttons -> state lookup)
file_id_map: dict[str, str] = {}
# _queue_started gates one‑time registration of queue worker & handlers
_queue_started = False

_NOT_FOUND = "File not found"


def _register_file_id(filename: str) -> str:
    """Register filename and return its short ID."""
    file_id = get_file_id(filename)
    file_id_map[file_id] = filename
    log.debug("Registered file id %s for %s", file_id, filename)
    return file_id


def _resolve_file_id(file_id: str) -> str | None:
    """Resolve file ID back to filename."""
    return file_id_map.get(file_id)


async def _safe_edit(msg, text: str, buttons=None):
    try:
        await msg.edit(text, buttons=buttons)
    except Exception:  # noqa: BLE001
        log.debug("safe_edit failed for message update")


def filename_for_document(document: Document) -> str:
    from telethon.tl.types import DocumentAttributeFilename
    import mimetypes

    for attr in document.attributes:
        if isinstance(attr, DocumentAttributeFilename):
            return attr.file_name
    ext = mimetypes.guess_extension(getattr(document, "mime_type", "")) or ""
    return f"media_{int(time.time())}{ext}"


def validate_size(expected_size: int, path: str) -> bool:
    return os.path.exists(path) and os.path.getsize(path) >= expected_size * 0.98


async def pre_checks(event: events.NewMessage.Event):
    document = event.document
    if not utils.is_media_file(document):
        await event.respond("⚠️ Only video and audio files are supported")
        return None
    original_filename = filename_for_document(document)
    filename = original_filename
    file_size = document.size or 0
    # Determine organized final path (may create subdirs). We only reserve space based on
    # final path so duplicates are detected on normalized name.
    path, final_name = build_final_path(filename)
    filename = final_name  # downstream uses normalized form
    if not await _ensure_disk_space(event, filename, file_size):
        return None
    # Soft warning if approaching low space threshold
    try:
        if utils.free_disk_mb(config.DOWNLOAD_DIR) < config.DISK_WARNING_MB:
            await event.respond(
                f"⚠️ Low disk space (< {config.DISK_WARNING_MB}MB free). Consider cleaning up soon."
            )
    except Exception:  # noqa: BLE001
        pass
    if os.path.exists(path):
        try:
            actual = os.path.getsize(path)
        except OSError:
            actual = 0
        if file_size == 0 or actual >= file_size * 0.98:
            await event.respond(
                f"ℹ️ File already exists: {filename} (size: {utils.humanize_size(actual)})",
                reply_to=getattr(event, 'id', None),
            )
            log.info("Skip existing file %s", filename)
            return None
        await event.respond(
            f"⚠️ Found incomplete existing file ({utils.humanize_size(actual)}/{utils.humanize_size(file_size)}); re-downloading...",
            reply_to=getattr(event, 'id', None),
        )
        try:
            os.remove(path)
        except OSError:
            pass
    log.info("Re-downloading incomplete file %s", filename)
    return document, filename, file_size, path


def _projected_free_mb(after_adding_bytes: int) -> int:
    free_now = utils.free_disk_mb(config.DOWNLOAD_DIR)
    return free_now - int(after_adding_bytes / (1024 * 1024))


def _current_reserved_bytes() -> int:
    # Sum expected sizes of all active states for safety.
    return sum(st.size for st in states.values())


async def _ensure_disk_space(event, filename: str, file_size: int) -> bool:
    """Ensure that after accounting for active + this download we stay above threshold.

    Strategy: reserve full size up-front for each running download. This is
    conservative and simple (no partial progress accounting). Before starting
    a queued item we re-run this check (see queue runner path below).
    """
    # bytes that would be reserved if this starts now
    cumulative = _current_reserved_bytes() + file_size
    projected = _projected_free_mb(cumulative)
    if projected >= config.MIN_FREE_DISK_MB:
        return True
    # Attempt auto-clean to reach: min threshold + this file + current reserved
    before = utils.free_disk_mb(config.DOWNLOAD_DIR)
    target = config.MIN_FREE_DISK_MB + int(cumulative / (1024 * 1024))
    deleted = utils.cleanup_old_files(config.DOWNLOAD_DIR, target)
    after = utils.free_disk_mb(config.DOWNLOAD_DIR)
    projected = _projected_free_mb(cumulative)
    if projected >= config.MIN_FREE_DISK_MB:
        await event.respond(
            f"♻️ Auto-clean removed {deleted} file(s) (free {before}MB -> {after}MB). Proceeding."
        )
        log.warning(
            "Auto-clean removed %d files (free %dMB -> %dMB)", deleted, before, after
        )
        return True
    await event.respond(
        (
            f"🛑 Not enough disk space for {filename} (projected free {projected}MB) "
            f"after reserving {utils.humanize_size(cumulative)}. Need >= {config.MIN_FREE_DISK_MB}MB free after all active downloads."
        )
    )
    log.error("Insufficient disk space for %s (projected %dMB)", filename, projected)
    return False


async def download_with_retries(
    client: TelegramClient,
    document: Document,
    path: str,
    progress_cb: Callable[[int, int], Awaitable[None]],
    msg: Any,
    state: DownloadState,
) -> bool:
    retry = 0
    while retry <= config.MAX_RETRY_ATTEMPTS:
        try:
            if state.cancelled:
                raise CancelledDownload
            await wait_if_paused(state)
            await client.download_media(document, file=path, progress_callback=progress_cb)
            return True
        except asyncio.TimeoutError:
            retry += 1
            if retry > config.MAX_RETRY_ATTEMPTS:
                return False
            await msg.edit(f"Download stalled. Retrying ({retry}/{config.MAX_RETRY_ATTEMPTS})...")
            await asyncio.sleep(2)
        except CancelledDownload:
            return False
        except Exception as e:  # noqa: BLE001
            log.warning("Download error attempt %d for %s: %s", retry, state.filename, e)
            retry += 1
            await asyncio.sleep(1)


def _final_cleanup(filename: str):
    # Remove state after download finishes (success, error, or cancellation)
    states.pop(filename, None)
    # Clean up file ID mapping
    file_id = get_file_id(filename)
    file_id_map.pop(file_id, None)


async def run_download(
    client: TelegramClient,
    event: events.NewMessage.Event,
    document: Document,
    filename: str,
    file_size: int,
    path: str,
    watcher_events: list[Any] | None = None,
    existing_message: Any | None = None,
) -> None:
    """Run a download and mirror progress to any duplicate requester chats.

    watcher_events: events from other users who requested the same file while queued.
    """
    state = _init_state(filename, path, file_size, event)
    if existing_message is not None:
        # Reuse queued placeholder: transform it into progress message
        state.message = existing_message
        try:
            start_text = f"Starting download of {state.filename}..."
            await existing_message.edit(start_text, buttons=build_buttons(state))
            # raw_text on Telethon object may still hold old queued text; store explicitly
            state.last_text = start_text
        except Exception:  # noqa: BLE001
            pass
        msg = existing_message
    else:
        msg = await _send_start_message(event, state)

    # Send initial starting message to watcher events (reply to their file message)
    if watcher_events:
        for wev in watcher_events:
            try:
                mirror_msg = await wev.respond(
                    f"Starting download of {state.filename}...",
                    reply_to=getattr(wev, 'id', None),
                    buttons=build_buttons(state),
                )
                state.extra_messages.append(mirror_msg)
            except Exception:  # noqa: BLE001
                pass

    # Monkey patch msg.edit to fan out updates.
    async def _mirror(text: str):
        if not state.extra_messages:
            return
        for m in state.extra_messages[:]:  # copy to allow mutation on failure
            try:
                await m.edit(text)
            except Exception:  # noqa: BLE001
                try:
                    state.extra_messages.remove(m)
                except ValueError:
                    pass

    _orig_edit = msg.edit

    async def _patched_edit(text: str, **kwargs):  # pragma: no cover simple wrapper
        try:
            r = await _orig_edit(text, **kwargs)
        except Exception:  # noqa: BLE001
            r = None
        await _mirror(text)
        return r

    try:
        setattr(msg, 'edit', _patched_edit)
    except Exception:  # noqa: BLE001
        pass

    progress_cb = create_progress_callback(filename, time.time(), RateLimiter(), msg, state)

    try:
        success = await download_with_retries(client, document, path, progress_cb, msg, state)
        if not await _post_download_check(success, file_size, path, state, msg, filename):
            return
        await _handle_success(msg, filename, path)
    except Exception as e:  # noqa: BLE001
        await _handle_error(e, state, msg, filename, path)
    finally:
        _final_cleanup(filename)


def _init_state(filename: str, path: str, size: int, event: events.NewMessage.Event) -> DownloadState:
    st = DownloadState(filename, path, size, original_event=event)
    states[filename] = st
    _register_file_id(filename)  # Register filename for button callbacks
    return st


async def _send_start_message(event: events.NewMessage.Event, state: DownloadState):
    start_text = f"Starting download of {state.filename}..."
    msg = await event.respond(
        start_text,
        buttons=build_buttons(state),
        reply_to=getattr(event, 'id', None),
    )
    state.message = msg
    state.last_text = start_text
    kodi.notify("Download Started", state.filename)
    log.info("Start download %s (%s)", state.filename, utils.humanize_size(state.size))
    return msg


async def _post_download_check(
    success: bool,
    expected_size: int,
    path: str,
    state: DownloadState,
    msg,
    filename: str,
) -> bool:
    if success and validate_size(expected_size, path):
        return True
    if state.cancelled:
        await _safe_edit(msg, f"🛑 Download cancelled: {filename}")
        if os.path.exists(path):
            try:
                os.remove(path)
                # Attempt to remove now-empty movie/episode directory chain
                remove_empty_parents(path, [config.DOWNLOAD_DIR])
            except OSError:
                pass
        log.info("Cancelled %s", filename)
    else:
        await _safe_edit(
            msg,
            f"❌ Download incomplete. Expected {utils.humanize_size(expected_size)}",
        )
        kodi.notify("Download Failed", f"Incomplete: {filename}")
        log.error("Incomplete download %s", filename)
    return False


async def _handle_success(msg, filename: str, path: str) -> None:
    playing = kodi.is_playing()
    if playing:
        text = (
            f"✅ Download complete: {filename}\n"
            "Kodi playing something else. File ready."
        )
    else:
        text = f"✅ Download complete: {filename}\nPlaying on Kodi..."
    await _safe_edit(msg, text)
    if not playing:
        kodi.play(path)
    kodi.notify("Download Complete", filename)
    log.info("Completed %s", filename)


async def _handle_error(
    exc: Exception,
    state: DownloadState,
    msg,
    filename: str,
    path: str,
) -> None:
    if state.cancelled:
        await _safe_edit(msg, f"🛑 Download cancelled: {filename}")
        if os.path.exists(path):
            try:
                os.remove(path)
                remove_empty_parents(path, [config.DOWNLOAD_DIR])
            except OSError:
                pass
        return
    err = str(exc)
    await _safe_edit(msg, f"❌ Error: {err[:200]}")
    kodi.notify("Download Failed", err[:50])
    log.error("Download error %s: %s", filename, err)


def register_handlers(client: TelegramClient):
    """Register Telegram handlers and start queue worker."""
    global _queue_started
    if not _queue_started:
        queue.set_runner(
            lambda c, qi: run_download(
                c,
                qi.event,
                qi.document,
                qi.filename,
                qi.size,
                qi.path,
                watcher_events=qi.watcher_events or [],
                existing_message=qi.message,
            )
        )
        queue.ensure_worker(client.loop, client)
        _queue_started = True
    log.debug("Queue worker started")

    _register_download_handler(client)
    _register_status_handler(client)
    _register_start_handler(client)
    _register_control_callbacks(client)
    client.loop.create_task(_register_bot_commands(client))


def _same_user(ev1, ev2):
    return getattr(ev1, "sender_id", None) == getattr(ev2, "sender_id", None)


async def _handle_active_duplicate(event, active_state: DownloadState, filename: str):
    if active_state.paused and not active_state.cancelled:
        active_state.mark_resumed()
        await _safe_edit(
            active_state.message,
            f"▶ Resuming: {active_state.filename}",
            buttons=build_buttons(active_state),
        )
    if active_state.original_event and _same_user(event, active_state.original_event):
        reply_to_id = active_state.message.id if active_state.message else None
        await event.respond(f"⏳ Already in progress: {filename}", reply_to=reply_to_id)
    else:
        try:
            mirror_msg = await event.respond(
                f"⏳ Already being downloaded: {filename}. You'll receive progress here.",
                reply_to=getattr(event, 'id', None),
            )
            active_state.extra_messages.append(mirror_msg)
        except Exception:  # noqa: BLE001
            pass


async def _handle_queued_duplicate(event, queued_item: QueuedItem, filename: str):
    if queued_item.event and _same_user(event, queued_item.event):
        await event.respond(f"🕒 Already queued: {filename}", reply_to=getattr(event, 'id', None))
    else:
        try:
            await event.respond(
                f"🕒 {filename} is queued. You'll receive progress here when it starts.",
                reply_to=getattr(event, 'id', None),
            )
            queued_item.add_watcher(event)
        except Exception:  # noqa: BLE001
            pass


async def _enqueue_or_run(client: TelegramClient, document, filename, size, path, event):
    if queue.is_saturated():
        qi = QueuedItem(filename, document, size, path, event)
        file_id = _register_file_id(filename)
        position = await queue.enqueue(qi)
        try:
            msg = await event.respond(
                (
                    f"🕒 Queued #{position}: {filename}\n"
                    f"Waiting for free slot (limit {config.MAX_CONCURRENT_DOWNLOADS})"
                ),
                buttons=[[Button.inline("🛑 Cancel", data=f"qcancel:{file_id}")]],
                reply_to=getattr(event, 'id', None),
            )
            qi.message = msg
        except Exception:  # noqa: BLE001
            pass
        return
    async with queue.slot():  # pragma: no cover - thin wrapper
        if not await _ensure_disk_space(event, filename, size):
            return
        await run_download(client, event, document, filename, size, path)


def _register_download_handler(client: TelegramClient):
    @client.on(events.NewMessage(func=lambda e: e.is_private and e.document))
    async def _download(event):  # noqa: D401
        # Access control
        sender = await event.get_sender()
        uid = getattr(sender, 'id', None)
        uname = getattr(sender, 'username', None)
        if not config.is_user_allowed(uid, uname):
            try:
                await event.respond("🛑 You are not authorized to use this bot.")
            except Exception:  # noqa: BLE001
                pass
            return
        document = event.document
        if not utils.is_media_file(document):
            await event.respond("⚠️ Only video and audio files are supported")
            return
        original_filename = filename_for_document(document)
        parsed = parse_filename(original_filename)
        ambiguous = parsed.category == "other" and parsed.year is not None
        # For non‑ambiguous cases we can derive the final organized filename now, so
        # duplicate detection aligns with the active state's normalized name.
        if not ambiguous or not config.ORGANIZE_MEDIA:
            _path_tmp, normalized_name = build_final_path(original_filename)
            lookup_name = normalized_name
        else:
            lookup_name = original_filename

        active_state = states.get(lookup_name)
        if active_state:
            await _handle_active_duplicate(event, active_state, lookup_name)
            return
        queued_item = queue.items.get(lookup_name)
        if queued_item:
            await _handle_queued_duplicate(event, queued_item, lookup_name)
            return
        if ambiguous and config.ORGANIZE_MEDIA:
            file_id = _register_file_id(original_filename)
            buttons = [[
                Button.inline("🎬 Movie", data=f"catm:{file_id}"),
                Button.inline("📺 Series", data=f"cats:{file_id}"),
                Button.inline("📁 Other", data=f"cato:{file_id}"),
            ]]
            await event.respond(f"Select category for: {original_filename}", buttons=buttons)
            return
        pre = await pre_checks(event)
        if not pre:
            return
        document, filename, size, path = pre
        await _enqueue_or_run(client, document, filename, size, path, event)
        log.debug("Enqueued or started %s", filename)


def _register_status_handler(client: TelegramClient):
    @client.on(
        events.NewMessage(
            func=lambda e: e.is_private
            and not e.document
            and (e.raw_text or "").strip().lower() == "/status"
        )
    )
    async def _status(event):  # noqa: D401
        sender = await event.get_sender()
        if not config.is_user_allowed(getattr(sender, 'id', None), getattr(sender, 'username', None)):
            await event.respond("🛑 Not authorized.")
            return
        q = list(queue.items.keys())
        active = list(states.keys())
        parts = [
            f"Active: {len(active)}/{config.MAX_CONCURRENT_DOWNLOADS}",
            f"Queued: {len(q)}",
        ]
        if active:
            parts.append("\nCurrent downloads:")
            parts.extend(f" • {fn}" for fn in active[:10])
        if q:
            parts.append("\nQueue:")
            parts.extend(f" {i+1}. {fn}" for i, fn in enumerate(q[:15]))
        await event.respond("\n".join(parts))


def _register_start_handler(client: TelegramClient):
    HELP_TEXT = (
        "Send me a video or audio file — I'll download it and play it on Kodi.\n\n"
        "Commands:\n/status – show active + queued downloads\n/start - this help"
    )

    @client.on(
        events.NewMessage(
            func=lambda e: e.is_private and (e.raw_text or "").strip().lower() == "/start"
        )
    )
    async def _start(event):  # noqa: D401
        sender = await event.get_sender()
        if not config.is_user_allowed(getattr(sender, 'id', None), getattr(sender, 'username', None)):
            await event.respond("🛑 Not authorized.")
            return
        await event.respond(HELP_TEXT)


async def _register_bot_commands(client: TelegramClient):
    try:
        from telethon.tl.functions.bots import SetBotCommandsRequest
        from telethon.tl.types import BotCommand
    except Exception:  # noqa: BLE001
        return
    commands = [
        BotCommand("start", "Help / usage"),
        BotCommand("status", "Show downloads"),
    ]
    try:
        await client(SetBotCommandsRequest(commands=commands))
    except Exception:  # noqa: BLE001
        pass


def _register_control_callbacks(client: TelegramClient):
    _register_pause_resume_cancel(client)
    _register_qcancel(client)
    _register_category_selection(client)


def _register_pause_resume_cancel(client: TelegramClient):
    pattern = b"(pause|resume|cancel):"

    async def _do_pause(st, event):
        if st.paused:
            await event.answer("Already paused", alert=False)
            return
        st.mark_paused()
        await _safe_edit(st.message, st.last_text or st.message.raw_text, buttons=build_buttons(st))
        await event.answer("Paused")

    async def _do_resume(st, event):
        if not st.paused:
            await event.answer("Not paused", alert=False)
            return
        st.mark_resumed()
        await _safe_edit(st.message, f"▶ Resuming: {st.filename}", buttons=build_buttons(st))
        await event.answer("Resuming")

    async def _do_cancel(st, event):
        st.mark_cancelled()
        await _safe_edit(st.message, f"🛑 Cancelling: {st.filename}")
        await event.answer("Cancelling")

    @client.on(events.CallbackQuery(pattern=pattern))
    async def _prc(event):  # noqa: D401
        action, file_id = event.data.decode().split(":", 1)
        filename = _resolve_file_id(file_id)
        if not filename:
            await event.answer(_NOT_FOUND, alert=False)
            return
        st = states.get(filename)
        if not st or st.cancelled:
            await event.answer("Not available", alert=False)
            return
        if action == "pause":
            await _do_pause(st, event)
        elif action == "resume":
            await _do_resume(st, event)
        else:  # cancel
            await _do_cancel(st, event)


def _register_qcancel(client: TelegramClient):
    @client.on(events.CallbackQuery(pattern=b"qcancel:"))
    async def _qcancel(event):  # noqa: D401
        file_id = event.data.decode().split(":", 1)[1]
        filename = _resolve_file_id(file_id)
        if not filename:
            await event.answer(_NOT_FOUND, alert=False)
            return
        qi = queue.items.get(filename)
        if not (qi and not qi.cancelled):
            await event.answer("Not found", alert=False)
            return
        queue.cancel(filename)
        # Update UI: new text + remove buttons. Use safe edit to swallow Telegram race errors.
        if qi.message:
            await _safe_edit(qi.message, f"🛑 Cancelled (queued): {filename}", buttons=None)
        # Remove file id mapping so further clicks show not found
        try:
            file_id_map.pop(file_id, None)
        except Exception:  # noqa: BLE001
            pass
        await event.answer("Cancelled")


def _register_category_selection(client: TelegramClient):
    @client.on(events.CallbackQuery(pattern=b"cat[ms|o]:"))
    async def _cat(event):  # noqa: D401
        data = event.data.decode()
        prefix, file_id = data.split(":", 1)
        filename = _resolve_file_id(file_id)
        if not filename:
            await event.answer(_NOT_FOUND, alert=False)
            return
        forced = {"catm": "movie", "cats": "series", "cato": "other"}.get(prefix)
        if not forced:
            await event.answer("Unknown", alert=False)
            return
        # Reconstruct path with forced category then enqueue
        path, final_name = build_final_path(filename, forced_category=forced)
        # Provide a lightweight object mimicking original event for duplicate detection
        fake_document = event._message.document  # type: ignore[attr-defined]
        size = getattr(fake_document, 'size', 0) or 0
        # Use original event as reply target
        orig_event = event._message  # type: ignore[attr-defined]
        # Minimal structure for pre_checks bypass since we already built path
        # Validate disk and duplicates again
        if states.get(final_name) or queue.items.get(final_name):
            await event.answer("Already queued", alert=False)
            return
        # Quick disk check: reuse logic
        if not await _ensure_disk_space(event, final_name, size):
            return
        # Enqueue/run directly
        await _enqueue_or_run(client, fake_document, final_name, size, path, orig_event)
        await event.answer("Queued", alert=False)

__all__ = [
    "register_handlers",
    "run_download",
]
