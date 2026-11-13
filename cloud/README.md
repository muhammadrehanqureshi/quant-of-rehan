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
- `GET /stock`, `GET /prices`: the app's search answers; both draw from the
  relay's acknowledged-frame store (owner order 2026-10-31), which keeps
  one regular-session frame per Karachi day, band and symbol, clamped so
  the B/S pair only moves as the day's own volume grows.
- `GET /flow` (also `/orderflow`): the complete KMIALL order-flow answer.
  One row per symbol with last, bid, ask, the resting bid and ask sizes,
  change, volume, buy, sell, the unclassified remainder, the split method,
  feed freshness, last-trade age and the day's large prints. It is a pure
  read of the durable quote snapshot: no portal fetch
  and no ACK write, so a desktop poll cannot spend the Durable Objects
  write budget.
- `GET /history`: minute OHLC bars for one symbol and one Karachi day,
  built by the relay from the accepted one-second feed, with a coverage
  answer when no symbol is given. See "Minute bars" below.
- Cron triggers do scan dispatch and card upkeep only; owner order
  2026-10-31 retires the market open/close/break emails entirely, and no
  cron sends a chat message.

## The complete order flow (`GET /flow`)

Owner order 2026-11-04: the owner's own Windows build reads the cloud, so
the relay owns the full answer. `GET /flow` (and its alias
`GET /orderflow`) returns one JSON body. The route is public and read-only.
The numbers in the shape below are illustrative, not a live claim.
`counts.universe` is the 319-name KMIALL file; `missing` names every
universe symbol with no regular-session frame that day, so the answer never
shrinks the universe to only the symbols that happened to trade.

```json
{
  "ok": true,
  "day": "2026-11-04",
  "as_of": "2026-11-04T10:31:02.218+05:00",
  "counts": {"universe": 319, "included": 282, "missing": 37, "fresh": 282},
  "totals": {"volume": 68372298, "buy": 35560858, "sell": 32811440, "unclassified": 0},
  "rows": [
    {
      "symbol": "CNERGY", "price": 11.86, "bid": 11.85, "ask": 11.87,
      "bid_size": 12000, "ask_size": 9000,
      "spread": 0.02, "change_pct": 1.2, "high": 12.1, "low": 11.4,
      "volume": 37942931, "buy_volume": 21800000, "sell_volume": 16142931,
      "classified_volume": 37942931, "unclassified_volume": 0,
      "flow_complete": true, "buy_share_pct": 57.46, "sell_share_pct": 42.54,
      "split_method": "quote_rule", "split_source": "every volume increment sided by the wire's own bid/ask at the poll",
      "observed_at": "2026-11-04T10:31:02.218+05:00", "age_seconds": 1,
      "tick_age_seconds": 3,
      "fresh": true, "status": "OPEN", "source_tick_time": "10:31:02",
      "flow_rules": {"at_ask": 1200, "at_bid": 1180},
      "large_buy_count": 2, "large_buy_shares": 180000, "large_buy_value_pkr": 2134800,
      "large_sell_count": 1, "large_sell_shares": 90000, "large_sell_value_pkr": 1067400,
      "largest_buy_pkr": 1186000, "largest_sell_pkr": 1067400,
      "last_large_at": "2026-11-04T10:30:55.000+05:00"
    }
  ],
  "missing": [
    {"symbol": "SGPL", "last_observed_at": "2026-10-22T20:48:37.469+05:00", "last_day": "2026-10-22", "reason": "no observed regular-session frame for this day"}
  ],
  "large": {
    "threshold_pkr": 1000000,
    "total": 3, "shown": 3, "truncated": false,
    "prints": [
      {"symbol": "CNERGY", "side": "BUY", "shares": 90000, "price": 11.86, "value_pkr": 1067400,
       "at": "2026-11-04T10:30:55.000+05:00", "tick": "10:30:55", "rule": "at_ask"}
    ],
    "stocks": [
      {"symbol": "CNERGY", "buy_count": 2, "buy_shares": 180000, "buy_value_pkr": 2134800,
       "sell_count": 1, "sell_shares": 90000, "sell_value_pkr": 1067400,
       "largest_buy_pkr": 1186000, "largest_sell_pkr": 1067400,
       "last_at": "2026-11-04T10:30:55.000+05:00", "total_value_pkr": 3202200}
    ]
  },
  "basis": {
    "split": "quote_rule: every observed increment of the venue counter is sided once by the bid/ask of the frame that carried it; buy and sell never decrease",
    "unclassified": "shares traded before the capture or hub first observed the symbol; they are reported separately and never guessed into buy or sell",
    "large": "one relay update carrying at least PKR 1,000,000 on one side; the broker wire has no individual order id, so this is a large observed increment, not a claimed order ticket"
  }
}
```

The split law is the one in `src/data/quote_flow.py`, running inside the
`QuoteHub` Durable Object. The capture starts before the open and stamps its
own observed pair on every quote, so a hub that starts later adopts that pair
instead of assigning shares it never saw. The capture carries a zero-volume
pre-open frame into the flow even when the wire has no last print yet; that
frame is the zero baseline, so the first auction increment is sided instead
of becoming an unclear prefix. Symbols the feed did not publish are seeded
at zero at the 08:55 gate and stamped `preopen_zero_seed`; that seed is an
explicit gate, never a trade. A non-zero total with no usable price is
carried as flow-only, so it stays in the baseline and is never published.The capture also sends one zero-volume baseline per symbol per day: before
2026-11-09 those frames were dropped at the publisher, so the hub's first
observation of a symbol became its baseline and the prefix could only be
reported as U. A capture process that restarts mid-session
retries the relay's same-day `/flow` pair and does not start publishing if no
seed is adopted. If the capture itself started late, the missed shares stay in
`unclassified_volume`; they are never called buy or sell. `/flow` rows carry
`flow_baseline_at`, `flow_first_seen_at` and `flow_baseline_reason` so a
remaining baseline can be traced to its first frame.

**The feed watchdog.** Owner order 2026-11-09: the capture must never be lost
mid-session. Measured on the live relay on 2026-11-06 (Friday), the hub's
newest frame was 12:09 PKT while the exchange traded to 16:30, and 148,036,924
of that day's 240,850,912 shares sat in `unclassified` because nothing had
watched the tape after the midday break. The once-per-window dispatch claim
stops a band starting twice, but it cannot see a band whose capture has died.
`ensureFeedAlive` therefore reads the hub's newest frame on every cron wake and
on every `/signals` poll while a dispatch window is open: when that frame is
older than five minutes it dispatches the band scan again with `force`, under a
ten minute cooldown of its own, so a dead capture is restarted long before the
close. A live feed costs one cooldown read and nothing else.

`age_seconds` is the age of the frame the relay holds, so it answers "is the
feed pushing now". `tick_age_seconds` is the age of the exchange's last print
for that symbol, so it answers "when did this stock last trade". They are
different numbers: a quiet stock can have an old tick on a fresh frame. A
reader that paints `tick_age_seconds` as feed lag will show a stall that is
not there, while a real push stall moves both numbers. Treat `age_seconds` as
the feed freshness and `tick_age_seconds` as the stock's last-trade age.

The live quote view uses its own Durable Object instance name,
`psx-live-quotes-v4`, because a deployed class change does not restart an
object that the one-second feed never lets go idle. The new instance adopts
the capture's observed pair on its first push, under either the measured_*
names or the original `buy_volume`/`sell_volume` pair. The original state instance
keeps the market card, signals and acknowledged rows untouched.

`large` is deliberately named as a large observed increment, not an order
ticket. The MKT-FEED wire carries a per-symbol snapshot with a cumulative
volume, bid and ask, and no individual order id. One relay update of at least
PKR 1,000,000 on one side is the smallest honest unit this data can support.

## Chart bars (`GET /bars`)

Owner order 2026-11-07: the desktop draws KSE100 and every KMIALLSHR scrip on
`1s`, `5s`, `1m`, `5m`, `15m`, `30m`, `1h`, `1D`, `1W` and `1M`. One route
answers every frame, the hub does every aggregation, and a chart read is
bounded by its own limit rather than by the year.

```
GET /bars?symbol=OGDC&tf=5m&days=365&limit=400
```

`tf` is one of the ten frames. `days` defaults to 365 and is capped at 365;
`limit` defaults to 400 and is capped at 2,000, and the newest bars in the
window are returned. KSE100 is a symbol too: the broker's own index frame is
folded into the same minute store under that name.

Two frames are live-only, and the answer says so rather than inventing a bar:
`1s` and `5s` are built on the desktop from its own quote samples, because the
broker feed observes one symbol every 30 to 90 seconds. From `1m` up, every
closed minute is rolled into `5m`, `15m`, `30m`, `1h` and `1D` buckets, one row
per bucket carrying every symbol, and `1W` and `1M` are grouped from the daily
rows when they are read. A session writes about 1,875 rollup rows, inside the
free plan's 100,000 rows a day; a chart read is a few hundred rows.

Retention is a budget decision, stated in the answer's `retention_days`: `1m`
for 45 days, `5m` for 180, and `15m` through `1M` for a full year. A 365 day
window therefore fills over the first year of storage; the relay began storing
on 2026-11-07 and nothing before that date is invented. KMIALLSHR has no
published index level in the broker feed or on the exchange's constituent page
(only its members and weights), so no KMIALLSHR line is drawn (SO-3).

## Minute bars (`GET /history`)

Owner order 2026-11-07: the owner's desktop build draws a full-day
candlestick chart per KMIALL scrip. Its own buffer holds only about five
minutes of one-second samples, so the relay aggregates the accepted quote
feed into minute bars and serves them here. The route is public and read-only.

```
GET /history?symbol=OGDC&day=2026-11-05&limit=500
```

`resolution` is `1m`, the only resolution this route serves. `day` defaults
to the current Karachi day and must be `YYYY-MM-DD`. `limit` defaults to 500
and is capped at 1,000 bars, which covers a whole session (about 360 bars on
Monday to Thursday, about 280 on Friday). Calling the route without `symbol`
returns coverage instead: the days the relay holds, each with its minute
count and first and last minute.

The numbers below are illustrative, not a live claim.

```json
{
  "ok": true,
  "symbol": "OGDC",
  "day": "2026-11-05",
  "resolution": "1m",
  "source": "eClear broker feed, aggregated to minute bars inside the relay",
  "bars": [
    {"t": "2026-11-05T09:32:00+05:00", "minute": "09:32", "o": 241.5, "h": 241.9, "l": 241.2, "c": 241.7, "v": 18200}
  ],
  "bar_count": 1,
  "first_minute": "09:32",
  "last_minute": "09:32",
  "forming": false,
  "as_of": "2026-11-05T10:05:11+05:00",
  "retention_days": 10,
  "notes": [
    "built by the relay from accepted one-second quote frames, not from an exchange OHLC feed",
    "a minute's volume is the observed increase of the venue's cumulative day total between the first and last frame accepted in that minute",
    "times are ISO 8601 with the Karachi offset (+05:00)"
  ]
}
```

`t` is the minute's start as an ISO 8601 stamp with the Karachi offset
(`+05:00`); `minute` is the same moment as `HH:MM` for a chart axis. The store
is one row per Karachi minute carrying every symbol, not one row per symbol
per minute: a session costs about 360 written rows, and the route's day
reader keeps one day in memory, so paging a chart costs one SQL read.

Two limitations are stated plainly because a chart must not imply more than
the relay measured:

- a bar exists only where the relay accepted a print in that minute; a minute
  with no accepted frame has no bar, and a day with no stored rows is
  answered as an empty list with a note, never filled with a flat line;
- the volume is the observed increase of the venue's cumulative total, so it
  is a measured increment, not an exchange-reported minute volume.

Bars are kept for 45 days and pruned once a day. Storing began on
2026-11-07, so earlier sessions have no history at this resolution.

| Event | Mon-Thu | Friday | Trigger (UTC) |
|---|---|---|---|
| Open | 09:32 PKT | 08:55 PKT (pre-open capture, before the 09:00 pre-open; band 09:17) | `15,20,25,32 4 * * 1-4` / `55,5,10,17 3,4 * * 5` |
| Close | 15:30 PKT | 12:00 PKT (session 1) | shared below |
| Open | - | 14:10 PKT (pre-open warm-up; band 14:32) | `10,20,25,32 9 * * 5` |
| Close | - | 16:30 PKT (session 2) | shared below |

The shared expression (`0,30,33,40,45 7,10,11 * * 1-5`) also carries the
pre-open and post-market wake and retries: 09:20/09:25 Mon-Thu, 09:05/09:10
and 14:20/14:25 Friday, 15:33/15:40/15:45 Mon-Thu, and 16:33/16:40/16:45
Friday. A retry that
is not a band edge sends no notification, so each edge is still delivered
exactly once. What the retries do is let the feed watchdog start the capture
inside the exchange's pre-open or post-market window when the punctual wake was
lost; the 09:20 retry is the last one that can still seed the day at zero before
the 09:30 pre-open ends. Six separate expressions are rejected by Cloudflare
with error 10072, and that rejection used to abort the deploy after the code
upload, leaving the schedules stale while the new worker was already live.

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
- the feed watchdog never forces a start at a band's own open edge, gives a
  dispatch ten minutes to publish its first frame, and reads GitHub's run list
  before forcing, so a queued band is not replaced by a later retry (GitHub
  keeps one pending run per concurrency group and cancels the older one);
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
