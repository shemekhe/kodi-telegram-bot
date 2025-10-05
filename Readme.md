<div align="center">
 
# Kodi Telegram Bot

Lightweight Telegram bot that downloads video / audio you send it and plays the file on a Kodi instance. Built to be tiny, readable and Raspberry‑Pi friendly.

<p>
<em>No databases. No tracking. One process.</em>
</p>

</div>

## Table of Contents

1. What It Does
2. Features
3. Architecture at a Glance
4. Quick Start
5. Environment Variables
6. Usage & Controls
7. Disk Space & Auto‑Clean
8. Raspberry Pi Deployment (systemd)
9. Contributing
10. Troubleshooting
11. License

## 1. What It Does

Send the bot a media file (video or audio). It:
1. Validates it looks like playable media.
2. Ensures post‑download free disk space stays above a safety threshold (auto‑clean oldest files if needed).
3. Queues or starts download (with concurrency limit).
4. Shows progress (Telegram + optional Kodi notifications).
5. On completion, plays it on Kodi unless Kodi is already playing something (then just stores it).

## 2. Features

- ✅ Video & audio detection via MIME, Telethon attributes & extension fallbacks
- 🚦 Concurrency limit + FIFO queue with per‑item cancellation
- ⏯ Inline buttons: Pause / Resume / Cancel
- 🔁 Retry on transient timeouts (configurable attempts)
- ♻️ Auto clean oldest files when space low (now recursive through organized subfolders)
- 🗂 Automatic media organization (Movies / Series / Other) with smart filename normalization
- 🎛 Category selection buttons for ambiguous uploads (choose Movie / Series / Other)
- 🛡 Disk + memory safety checks with gentle warnings
- 📊 Kodi progress notifications (rate‑limited) when idle
- 🔔 Minimal startup & error notifications (no log spam)
- 🧱 Small, modular codebase: easy to read & fork

Non‑goals: partial resume of interrupted downloads; database persistence; public group handling.

## 3. Architecture at a Glance

```
main.py            -> startup, graceful shutdown
config.py          -> env loading & validation
utils.py           -> media detection, disk/memory helpers
kodi.py            -> tiny JSON‑RPC wrapper (notify / play / status)
downloader/
   queue.py         -> concurrency + FIFO queue worker
   state.py         -> DownloadState (pause/resume/cancel flags)
   buttons.py       -> inline keyboard builder
   progress.py      -> rate‑limited progress callback factory
   manager.py       -> orchestration: handlers, retries, success/error flows
organizer.py       -> filename parsing, categorization & final path builder
```

Everything is in‑memory; restart is safe (partially downloaded files <98% are re‑fetched).

## 4. Quick Start

```bash
git clone https://github.com/shemekhe/kodi-telegram-bot.git
cd kodi-telegram-bot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in Telegram + Kodi values
python main.py
```

Send the bot a video or audio file in a private chat. Use `/status` anytime.

## 5. Environment Variables

Create a Telegram app (API ID / HASH) at https://my.telegram.org and a bot token via @BotFather.

### 5.1 Required
Set all three or the process exits on start:
```
TELEGRAM_API_ID=123456
TELEGRAM_API_HASH=your_hash
TELEGRAM_BOT_TOKEN=12345:bot_token
```

### 5.2 Core (Kodi & Paths)
```
KODI_URL=http://localhost:8080/jsonrpc   # Adjust if Kodi uses different host/port
KODI_USERNAME=kodi                       # Must match Kodi settings
KODI_PASSWORD=your_pass                  # Blank allowed if Kodi has no auth
DOWNLOAD_DIR=~/Downloads                 # Created if missing
ORGANIZE_MEDIA=1                         # 1(default)=Movies/Series/Other tree; 0=flat
```
`ORGANIZE_MEDIA=0` stores files directly under `DOWNLOAD_DIR` using (sanitized) original filename.

### 5.3 Behavior & Performance
```
MAX_RETRY_ATTEMPTS=3        # Network-ish transient failures per item
MAX_CONCURRENT_DOWNLOADS=5  # Active simultaneous downloads
```

### 5.4 Safety Thresholds
```
MIN_FREE_DISK_MB=200        # Hard gate: refuse (or auto-clean; then refuse if still low)
DISK_WARNING_MB=500         # Soft warning only
MEMORY_WARNING_PERCENT=90   # Show Kodi popup if exceeded; 0 disables
```
Disk auto-clean deletes oldest files recursively inside the media root until the projected free space after the pending download is >= `MIN_FREE_DISK_MB` or nothing left to delete.

### 5.5 Access Control (Optional)
```
ALLOWED_USERS=12345678,@alice,bob
```
Comma OR space separated. Accepts numeric IDs and/or usernames (with or without `@`). Empty/unset = open to everyone (still private chats only). Usernames are case‑insensitive; prefer numeric IDs for permanence.

### 5.6 Logging (Optional Overrides)
```
LOG_FILE=bot.log            # Path; single file truncated in-place
LOG_LEVEL=INFO              # DEBUG / INFO / WARNING / ERROR
LOG_MAX_MB=200              # Hard cap; file truncates before exceeding
```
Set none to accept defaults. Truncation writes a header line noting previous size & UTC timestamp.

### 5.7 Quick Reference Table

| Name | Default | Notes |
|------|---------|-------|
| TELEGRAM_API_ID | (required) | Numeric app ID from my.telegram.org |
| TELEGRAM_API_HASH | (required) | App hash from my.telegram.org |
| TELEGRAM_BOT_TOKEN | (required) | Token from @BotFather |
| KODI_URL | http://localhost:8080/jsonrpc | Kodi JSON-RPC endpoint |
| KODI_USERNAME | kodi | Kodi HTTP username |
| KODI_PASSWORD | (blank) | Kodi HTTP password (blank allowed) |
| DOWNLOAD_DIR | ~/Downloads | Storage root (created if missing) |
| ORGANIZE_MEDIA | 1 | 1 enable Movies/Series/Other; 0 flat layout |
| MAX_RETRY_ATTEMPTS | 3 | Per download retry count (transient errors) |
| MAX_CONCURRENT_DOWNLOADS | 5 | Parallel download slots |
| MIN_FREE_DISK_MB | 200 | Hard free-space floor (after projected size) |
| DISK_WARNING_MB | 500 | Soft warning threshold |
| MEMORY_WARNING_PERCENT | 90 | 0 disables memory popup; otherwise warn >= value |
| ALLOWED_USERS | (blank) | Comma/space IDs & usernames; blank=open |
| LOG_FILE | bot.log | Truncating log file path |
| LOG_LEVEL | INFO | Logging verbosity |
| LOG_MAX_MB | 200 | Max size before in-place truncate |

Tip: copy `.env.example` to `.env` then edit; unused commented lines can stay.

## Creating Your Telegram Bot (Detail)

1. Open Telegram and start a chat with **@BotFather**.
2. Send `/newbot` and follow the prompts (choose a name + unique username ending in `bot`).
3. BotFather returns an HTTP API token – set this as `TELEGRAM_BOT_TOKEN` in your `.env`.
4. (Optional) Set a profile picture with `/setuserpic` and a description with `/setdescription`.
5. Keep the token secret; regenerate with `/revoke` if leaked.

Environment variables needed from this step:
```
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_BOT_TOKEN=the_token_from_botfather
```
You can obtain API ID/HASH at https://my.telegram.org (create an application). These differ from the bot token.

_Duplicate of feature bullets removed for brevity; see section 2._

## Requirements

- Python 3.10+ (tested on 3.12)  
- Telegram API ID / Hash + bot token  
- Kodi with JSON‑RPC (remote control via HTTP) enabled  
- Works well on Raspberry Pi (3 or newer)

## Kodi Configuration (Remote Control)

Before running the bot, make sure Kodi allows remote control over HTTP:

1. On your Kodi device open: Settings (gear icon) > Services > Control
2. Enable: "Allow remote control via HTTP"
3. (Optional but recommended) Set the port (default 8080), username, and password
4. Also enable: "Allow remote control from applications on other systems"

Match the chosen username/password/port with your `.env` values (`KODI_URL`, `KODI_USERNAME`, `KODI_PASSWORD`). Without this, the bot can’t send play or notification commands.

## 6. Usage & Controls

Run: `python main.py`

Bot actions:
1. Startup notification to Kodi (optional failure logged to stdout).
2. Accepts only private messages with a document (video/audio). Others ignored unless `/start` or `/status`.
3. If busy beyond concurrency limit -> place into queue with position number.

Inline controls during active download:

- ⏸ Pause – temporarily halts; can resume from same offset.
- ▶ Resume – continues download.
- 🛑 Cancel – aborts and deletes partial file.

Commands:
`/start` help text  
`/status` active + queued summary  

If the bot was offline for a long time you may need to resend older files.

### Media Organization & Naming

Enabled by default (`ORGANIZE_MEDIA=1`). Incoming filenames are parsed heuristically:

1. Detect series tokens like `S02E06`, `SO4E24` (some releases use `O` instead of `0`).
2. Detect a year token (e.g. `2024`) to classify as a Movie when no series token exists.
3. Strip common quality / codec / group tags (e.g. `1080p`, `WEB-DL`, `x265`, `YTS`, `Farsi`, release group names).
4. Normalize dots/underscores into spaces, capitalize words, and build final names.

Resulting structure examples:

```
Movies/
   Bullet Train (2022)/
      Bullet Train (2022).mkv

Series/
   The Mentalist (2008)/
      Season 4/
         The Mentalist S04E24.mkv
```

If classification is ambiguous (looks like a movie because it has a year but parser can’t be sure) you’ll get inline buttons:
`🎬 Movie` · `📺 Series` · `📁 Other`

Selecting one forces the directory choice without re‑uploading.

Other / unknown files (no year & no season/episode pattern) go under:
```
Other/<OriginalFileName.ext>
```

Disable the whole feature with `ORGANIZE_MEDIA=0` to revert to flat storage.

### Concurrency & Queue
Active downloads <= `MAX_CONCURRENT_DOWNLOADS`; extra items wait. The `/status` output lists active first, then queued. Queued items expose a Cancel button (labelled "Cancelled (queued)" when removed).

### Restart Behavior
On restart any partial files <98% complete are deleted & re‑downloaded when resent. Completed files can be re‑played by sending them again (Kodi will just play existing file if unchanged).

## 7. Disk Space & Auto‑Clean

Each download is allowed only if predicted free space after completion stays above `MIN_FREE_DISK_MB`.
If not, the bot automatically deletes the oldest files (recursive across Movies/Series/Other) until the requirement is met. If still not enough, the download is refused. A soft warning is shown when free space drops below `DISK_WARNING_MB`.

## 8. Raspberry Pi Setup

Optimized for Raspberry Pi (Pi 3 or later recommended). Below is a concise, production-friendly setup.

### 1. OS & Packages
```sh
sudo apt update
sudo apt install -y python3 python3-venv git
```

### 2. Clone & Install
```sh
cd /home/pi
git clone https://github.com/shemekhe/kodi-telegram-bot.git
cd kodi-telegram-bot
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env  # then edit .env with your values
```

Edit `.env` and set your Telegram + Kodi values. Ensure `DOWNLOAD_DIR` exists or let the app create it.

### 3. systemd Service
Create the service file:
```sh
sudo nano /etc/systemd/system/kodi-telegram-bot.service
```

Paste (adjust paths if you used a different location):
```ini
[Unit]
Description=Kodi Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/kodi-telegram-bot
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=/home/pi/kodi-telegram-bot/.env
ExecStart=/home/pi/kodi-telegram-bot/.venv/bin/python main.py
Restart=on-failure
RestartSec=5

# (Optional hardening — relax if it causes issues)
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=false

[Install]
WantedBy=multi-user.target
```

Enable & start:
```sh
sudo systemctl daemon-reload
sudo systemctl enable kodi-telegram-bot
sudo systemctl start kodi-telegram-bot
```

### 4. Logs & Maintenance
```sh
journalctl -u kodi-telegram-bot -f    # live logs
sudo systemctl restart kodi-telegram-bot
sudo systemctl status kodi-telegram-bot
```

Update to latest version:
```sh
cd /home/pi/kodi-telegram-bot
git pull
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart kodi-telegram-bot
```

### 5. File Storage Considerations
- Use an external drive for large media: set `DOWNLOAD_DIR` to the mounted path (e.g. `/mnt/media`).
- Ensure the `pi` user has write permissions on that path.
- Monitor space: `df -h`.

### 6. Optional Optimization
- Add swap if memory constrained (but SSD wear risk).
- Use `ionice` / `nice` wrappers if downloads compete with playback (advanced).

You now have an auto‑starting bot instance.

## 9. Contributing

PRs and small improvements welcome. Suggested first issues:
- Add tests for a missing edge case (see `tests/` for style)
- Improve docs / examples
- Add optional logging verbosity flag

Guidelines:
1. Keep functions small & side‑effect light.
2. Avoid adding heavy dependencies.
3. Run `pytest -q` before submitting.
4. Prefer clarity over cleverness.

No formal Code of Conduct yet; be respectful.

## 10. Troubleshooting

Issue | Things to Check
----- | ----------------
Kodi not playing | JSON‑RPC enabled? Correct URL / credentials? Port reachable?
Bot silent | Is it a private chat? Did you send a *file* (not a streaming link)?
Stuck queued | Concurrency limit reached; lower file count or raise limit.
Always low space | Increase `MIN_FREE_DISK_MB` cautiously or clean directory.
Memory warnings | Set `MEMORY_WARNING_PERCENT=0` to disable.

Logging is intentionally minimal; feel free to add temporary prints while debugging.

## 11. License

MIT — do what you like; attribution appreciated. No warranty.

---

Happy hacking. If this helped you, a ⭐ on the repo helps others find it.
