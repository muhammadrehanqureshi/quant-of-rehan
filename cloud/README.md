# cloud/ : the quant-of-rehan Telegram relay

Telegram is blocked for direct connections inside Pakistan (SO-9), so the
worker here is the only thing in the system that talks to api.telegram.org.
It runs on the Cloudflare edge, outside that block. Your PC never touches
Telegram; you read the messages on your phone over your VPN as usual.

## What it does

- `GET /health`: liveness, current Karachi wall clock, next open/close event
- `POST /pair` (admin token): asks Telegram which chat last messaged the bot,
  returns that chat id so `pair.py` can store it
- `POST /notify` (admin token): `{text, kind}` forwarded to your chat; this
  is the local runner's delivery path
- `GET /updates` (admin token): raw getUpdates proxy for local debugging
- Cron triggers fire the two daily texts from the edge even if your PC is off:

| Event | Mon-Thu | Friday | Cron (UTC) |
|---|---|---|---|
| Open | 09:32 PKT | 09:17 PKT | `32 4 * * 1-4` and `17 4 * * 5` |
| Close | 15:30 PKT | 16:30 PKT | `30 10 * * 1-4` and `30 11 * * 5` |

Weekends and the 2026 PSX holiday list are skipped, mirroring
src/data/sessions.py. The Karachi offset is hardcoded UTC+5 forever (SO-8).

## Secrets (SO-5)

Worker bindings, set only by cloud/pair.py from the owner's PC:
`TELEGRAM_BOT_TOKEN`, `RELAY_ADMIN_TOKEN`, `PAIRED_CHAT_ID`. Nothing secret
is stored in this repo.

## Setup (owner's PC)

```bash
python cloud/pair.py deploy     # upload worker, set crons, save relay url
# ... message the new bot once from your phone (VPN on) ...
python cloud/pair.py discover   # find your chat, redeploy paired
python cloud/pair.py test       # full-path test message
python cloud/pair.py health     # live status from the edge
```

## Local scheduler (optional second delivery path)

The edge crons deliver even with your PC off. To also send from the local
runner (and journal deliveries), start it after pairing:

```bash
python -m src.notify.schedule_runner
```

Auto-start at login is handled by the scheduled task the QUANT registers
(`quant-of-rehan-scheduler`, see scripts/install_scheduler.py).
