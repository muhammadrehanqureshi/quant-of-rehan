# cloud/ : the quant-of-rehan Telegram relay

Telegram is blocked for direct connections inside Pakistan (SO-9), so the
worker here is the only thing in the system that talks to api.telegram.org.
It runs on the Cloudflare edge, outside that block. Your PC never touches
Telegram; you read the messages on your phone over your VPN as usual.

## What it does

- `GET /health`: liveness, current Karachi wall clock, next band edge,
  pairing state, `market_open`, and `market_state` with the phase
  (`OPEN`, `BREAK`, `CLOSED`, `PRE_OPEN`, `POST_CLOSE`), the live band and the
  day's bands per the owner's session law (the app shows ONLINE only while the
  phase is OPEN)
- `GET /market` (public): KSE100 points and percentage plus the top three
  KMIALL stocks by current session volume, each with its day's percentage
  change and, when a genuine one exists, its buy/sell split, parsed from the
  PSX Data Portal's own pages and cached for five minutes; `POST /market`
  (admin token) stores a snapshot built by
  `python -m src.data.market_snapshot --push`, which then takes precedence for
  five minutes. The edge cannot split volume (the exchange table has one
  volume column), so the split fields are null there and the local runner
  fills them from the broker tick capture (`src/data/tick_volume.py`).
- `POST /pair/start` (admin token): finds the chat that last messaged the
  bot, stores a 4-digit code in KV, and sends that code to the chat
- `POST /pair/confirm` (admin token): `{code}` binds the chat; the bot
  confirms in the chat
- `POST /notify` (admin token): `{text, kind}` forwarded to your chat; this
  is the local runner's delivery path
- `GET /signals` (admin token): the app's signal feed; `POST /signals`
  stores new signal lines from the local runner
- `GET /updates` (admin token): raw getUpdates proxy for local debugging
- Cron triggers fire the daily texts from the edge even if your PC is off.
  Friday is TWO sessions with the exchange's midday break between them, so it
  has four edges and six crons in all:

| Event | Mon-Thu | Friday | Cron (UTC) |
|---|---|---|---|
| Open | 09:32 PKT | 09:17 PKT (session 1) | `32 4 * * 1-4` and `17 4 * * 5` |
| Close | 15:30 PKT | 12:00 PKT (session 1) | `30 10 * * 1-4` and `0 7 * * 5` |
| Open | - | 14:32 PKT (session 2) | `32 9 * * 5` |
| Close | - | 16:30 PKT (session 2) | `30 11 * * 5` |

Weekends, the 2026 PSX holiday list and the midday break are all closed,
mirroring `src/data/sessions.py` (the worker's band table is a copy of the
Python one, and a test fails if the two drift). The Karachi offset is
hardcoded UTC+5 forever (SO-8).

## Deploying a change

`cloud/pair.py deploy` uploads `worker.js` and sets the six crons in the same
run. The relay currently running in production predates the band table and
`market_state`, so a deploy is needed for the app to show the phase sentence
and to stop reporting ONLINE between 12:00 and 14:32 on a Friday.

## Where a runner finds the relay URL

`data/relay_url.txt` is gitignored (the pairing above writes it on this PC),
so a fresh checkout or a GitHub runner does not have it. Resolution order is
therefore the `RELAY_URL` environment variable first, then that file, and if
neither is present the runner fails closed and names both in the error -- a
notification must never travel to a guessed address. In GitHub Actions the
public worker URL can be set once as a repository **variable** (Settings >
Secrets and variables > Actions > Variables > `RELAY_URL`), which is not a
secret; `scripts/signal_daily.py` also writes the file before its preflight,
so a runner with no configuration at all still checks a real URL.

## Secrets (SO-5)

Worker bindings, set only by cloud/pair.py from the owner's PC:
`TELEGRAM_BOT_TOKEN` and `RELAY_ADMIN_TOKEN`. The paired chat id and the
pending pairing code live in the RELAY_KV namespace. Nothing secret is
stored in this repo.

## Setup (owner's PC, already completed on 2026-10-05)

```bash
python cloud/pair.py deploy     # upload worker, set crons, save relay url
# ... message the new bot once from your phone (VPN on) ...
python cloud/pair.py discover   # bot sends a 4-digit code; type it back
python cloud/pair.py test       # full-path test message
python cloud/pair.py health     # live status from the edge
```

Pairing state lives in KV; re-running discover re-pairs safely.

## Local scheduler (optional second delivery path)

The edge crons deliver even with your PC off. To also send from the local
runner (and journal deliveries), start it after pairing:

```bash
python -m src.notify.schedule_runner
```

Auto-start at login is handled by the scheduled task the QUANT registers
(`quant-of-rehan-scheduler`, see scripts/install_scheduler.py).
