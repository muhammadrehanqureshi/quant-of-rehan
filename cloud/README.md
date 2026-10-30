# cloud/ : the quant-of-rehan relay

Owner order 2026-10-29: the owner removed his chat account and bot, so
the relay carries no chat call at all. Notifications are
carried by owner email (src/notify/owner_email.py) from the GitHub Actions
jobs. What remains here is the app's card, market state, snapshot and
status surface, on the Cloudflare edge off your PC.

## What it does

- `GET /health`: liveness, current Karachi wall clock, next band edge,
  `market_open`, and `market_state` with the phase
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
- `POST /notify` (admin token): retired, answers 410 with a reason. The
  chat channel is gone; senders use the owner email issue
  (src/notify/owner_email.py) from the Actions jobs instead.
- `GET /signals` (admin token): the app's signal feed; `POST /signals`
  stores new signal lines from the local runner
- Cron triggers do scan dispatch and card upkeep only; the market open and
  close texts travel by owner email, and no cron sends a chat message.

| Event | Mon-Thu | Friday | Trigger (UTC) |
|---|---|---|---|
| Open | 09:32 PKT | 09:17 PKT (session 1) | `32 4 * * 1-4` / `17 4 * * 5` |
| Close | 15:30 PKT | 12:00 PKT (session 1) | `30 10 * * 1-4` / shared below |
| Open | - | 14:32 PKT (session 2) | `0,32 7,9 * * 5` (shared) |
| Close | - | 16:30 PKT (session 2) | `30 11 * * 5` |

The shared expression also fires at 07:32 and 09:00 UTC. Those are not band
edges, and the worker's scheduled handler returns without sending unless the
Karachi minute is within two minutes of a real edge, so each edge is delivered
exactly once. Six separate expressions are rejected by Cloudflare with error
10072, and that rejection used to abort the deploy after the code upload,
leaving the schedules stale while the new worker was already live.

### Punctual scan dispatch (owner audit, 2026-10-19)

GitHub's cron queue delivers `schedule` events hours late in busy periods: on
2026-10-16 the 04:17 UTC band job was created at 09:01 UTC and the 09:32 job
at 14:10 UTC, so every band that day was missed. Cloudflare's crons already
wake at the exact edges, so the same wake now also calls GitHub's
`workflow_dispatch` for `intraday-session.yml`, which starts the band job in
seconds. It is opt-in and fail-open:

- no `GH_DISPATCH_TOKEN`, no dispatch, and the GitHub schedules remain the
  only path (exactly the old behaviour);
- one dispatch per band per day is recorded in the Durable Object
  (`SCAN:DISPATCH:<day>:<open>`,
  two day TTL), so a retried cron cannot start a second loop;
- only a 204 from GitHub claims the band; a failure leaves the key free and is
  recorded in `SCAN:DISPATCH:LAST` for inspection;
- the call has a ten second timeout and never blocks the open/close text.

To turn it on, mint a fine grained personal access token limited to this one
repository with **Actions: write**, then set it as a Worker secret. Never put
it in this repository (SO-5):

```bash
cd cloud && npx wrangler secret put GH_DISPATCH_TOKEN
```

`GH_REPO` is optional and defaults to `muhammadrehanqureshi/quant-of-rehan`.
The dispatched run uses the workflow's `seconds` input, computed from the
band's own close, so a job nudged at 09:32 PKT still stops at 15:30 PKT.

Weekends, the 2026 PSX holiday list and the midday break are all closed,
mirroring `src/data/sessions.py` (the worker's band table is a copy of the
Python one, and a test fails if the two drift). The Karachi offset is
hardcoded UTC+5 forever (SO-8).

## Deploying a change

Two deploy paths exist and they must agree:

- `.github/workflows/deploy-relay.yml` runs `wrangler deploy` from this folder
  on any push to `master` that touches `cloud/`, then verifies the live edge
  answers `/health`;
- `cloud/pair.py deploy` uploads the same file through the Cloudflare API and
  sets the crons in the same run, for use from this PC.

`tests/test_relay_worker_contracts.py` pins both paths to the same Durable
Object declaration, because a deploy that ships the binding without the class
leaves `/quotes` answering 500.

## Configuration checked against Cloudflare's documentation (2026-10-19)

`wrangler.toml` declares the quote hub with the `exports` table:

```toml
[[durable_objects.bindings]]
name = "QUOTE_HUB"
class_name = "QuoteHub"

[exports.QuoteHub]
type = "durable-object"
storage = "sqlite"
```

That is the current documented shape (Durable Object class exports), and it is
what makes the class SQLite backed, which `ctx.storage.sql` requires. Two
consequences worth writing down, because both are easy to get wrong:

- a Worker uses `exports` **or** the legacy `[[migrations]]` array, never both,
  so the absence of a `new_sqlite_classes` migration here is correct and
  adding one would be rejected;
- a class that appears only in the code is not provisioned. The `exports`
  entry is what creates the namespace, and `pair.py` sends the same entry in
  the `metadata` part of its upload for that reason.

### The upload's multipart metadata

`cloud/pair.py` builds the upload body itself, so it is pinned by tests rather
than by hope. The API reads two parts: `metadata` as `application/json`, and
one part per module named exactly as `main_module` (here `worker.js`), sent as
`application/javascript+module`. The parts are CRLF delimited, the module's
UTF-8 bytes are sent unchanged, and the boundary is regenerated until it does
not occur inside the module. `tests/test_relay_worker_contracts.py` parses the
built body with Python's own MIME parser and round-trips the module, so a
newline or boundary regression fails before it reaches a deploy.

Nothing in this project accepts `multipart/form-data` from a client: the
worker's own routes are JSON only, and the app reads JSON. The only multipart
in the system is this outbound script upload.

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
`RELAY_ADMIN_TOKEN` (and, when the punctual dispatch is on, the
`GH_DISPATCH_TOKEN` secret above). Every value the relay keeps
(the card, the market snapshot, the session state, the research log) lives
in the `QuoteHub` Durable Object. There is no KV namespace: owner order
2026-10-20 removed the last quota-limited product from the path, and a
binding to a namespace that had been deleted was failing every deploy.
Nothing secret is stored in this repo.

## Setup (owner's PC, already completed on 2026-10-05)

```bash
python cloud/pair.py deploy     # upload worker, set crons, save relay url
python cloud/pair.py health     # live status from the edge
```

## Local scheduler (retired, owner order 2026-10-14)

The owner email jobs deliver even with your PC off, which is why the local
runner is no longer needed. It used to be started at every login and kept a
process resident all day for two texts the market jobs already send, so
SO-12 parks it: `python -m src.notify.schedule_runner` now refuses to start
on the owner's PC unless the owner asks for it by name, the Startup entry
that launched it is gone, and `scripts/install_scheduler.py` refuses to
register a logon task again. Its delivery leg now publishes on the owner
email ledger, its helpers (`load_relay_url`, `load_relay_admin_token`) stay
in place as imports for the daily push and the research routes.
