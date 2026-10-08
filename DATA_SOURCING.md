# DATA_SOURCING: Market Data Research Memo (PSX KMIALL)

**Date:** 2026-10-08 · **Prepared by:** the QUANT · **Status:** source audit
for free/public sources; scheduled OHLC capture is configured in GitHub Actions.
**Update (same day):** PSX Data Portal redesigned: the 5-year-per-GET EOD
endpoint is dead; see §7.

## 1. The mandate

Find **genuine historical PSX bid/ask/order-flow data**. The bot must never
pretend it has footprint analysis. Order flow is treated as necessary for the
full vision: so if it cannot be sourced, that fact must be loud, not hidden.

## 2. What was searched (this session)

| Source searched | Query families used | Result |
|---|---|---|
| GitHub repositories (code + repo search) | PSX orderbook / tick data / order flow / KMI csv / Pakistan Stock Exchange dataset / footprint | **0 genuine hits** across every formulation |
| Cloudflare account inventory | Workers, KV, R2 | Only `sentinel-seatbelt` watchdog exists. **No R2 buckets, no data archive** in the account |
| Known PSX data surfaces | PSX Data Portal / CSOR | Daily OHLCV only (official, free). No intraday, no depth-of-book, no historical bid/ask |

## 3. Verdict

> **Genuine historical PSX bid/ask/order-flow data does not exist in any
> free or public source.** PSX does not publish Level 2 / depth-of-book
> history, and no third-party free archive was found. Any system claiming
> five years of PSX footprint history would be fabricating it: which
> GOVERNANCE.md SO-3 forbids.

Consequence for the 5-year backtest: it runs on **daily + (eventually)
forward-captured intraday OHLCV**, with the footprint/order-flow layer
**explicitly disabled and labeled**:

```
FOOTPRINT DATA UNAVAILABLE / DEGRADED: footprint engine disabled
```

OHLCV-derived proxies (e.g. candle-body imbalance) may inform research only
when labeled degraded. They are never presented as true order flow.

## 4. The real paths to genuine order flow

### Path A: Forward capture from the read-only broker feed: approved for capture
- The owner approved read-only capture on 2026-10-06. GitHub Actions collects
  one-minute OHLC at 10:45, 12:45, 14:45, and 16:45 Karachi time. Capture
  artifacts are retained for 90 days and daily summaries are stored in
  Cloudflare KV. No order or broker session credentials are used.
- `src/data/ohlc_poller.py` reads the eClear `GetOHLCData` public read tier.
  TLS certificate and hostname verification are enabled. The feed provides
  OHLC only, without volume, bid/ask, or order flow.
- Capture is not proof of source latency or rights for cloud retention and
  signal redistribution. Both remain unconfirmed. The GitHub Actions
  variables `KMIALL_DATA_RIGHTS_CONFIRMED`,
  `KMIALL_DATA_LATENCY_CONFIRMED`, and `KMIALL_UNIVERSE_CONFIRMED` default to
  false. The production gate
  cannot open until both are confirmed and the full evidence window uses the
  approved source.
- The local audit contains one session only (2026-10-06), with 32,639 bars
  across 298 symbols. It cannot establish strategy performance.
- A read-only source check on 2026-10-08 at 10:09 PKT returned HTTP 200 from
  the eClear host but only the `OGDC;REG;` header and no bars for requested
  1-, 5-, or 15-minute intervals. Therefore the feed was not verified as
  operational in that check. A one-pass scheduled collector now fails closed
  below 80% symbol coverage, so a blank feed cannot silently advance research.
- The separate MKT-FEED socket did not deliver per-symbol ticks in anonymous
  mode during the 2026-10-06 probe. It is not used for OHLC strategy signals.
  Credentialed read-only L1 collection is not configured.

### Path B: Longer-term intraday archive
- The 90-day workflow artifacts must be downloaded and consolidated for
  research before they expire. No historical bars are inferred from daily
  data, and no local background capture process is required.

### Path C: Daily OHLCV backfill (DEGRADED: see §7)
- ~~PSX Data Portal / CSOR daily files cover years of history~~ The portal
  redesign removed the 5-year-per-GET EOD endpoint. The current backbone is
  the sentinel's local 177-session corpus (2026-01-05 .. 2026-09-23, 305
  KMIALL symbols); the remaining free lead for 5-year history is the
  portal's per-date "Daily Downloads" files (§7.3).

### Path D: Paid vendor (not pursued)
- If genuine historical tick data ever becomes a hard requirement, the only
  realistic route is a paid data vendor or an exchange data agreement. That
  is a cost decision reserved for the owner, only if the bot proves
  profitable first (per his own rule: VPS/infrastructure follows profit).

## 5. Market-data rights and latency

The official PSX Data Portal labels its displayed data as delayed by five
minutes and includes a notice requiring rights or a license for data
transmission. The eClear public read-tier endpoint used here is a separate
source; its timing and redistribution rights have not been independently
verified. Structural bar checks do not establish either. Research snapshots
stay paper-only unless the owner confirms both source rights and data latency
in the two GitHub Actions variables described above.

## 6. Secrets: canonical names (values never in this repo)

| Name | Used by | Lives in |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | [src/notify/telegram.py](src/notify/telegram.py): env first, then gitignored `.env` | Owner's Desktop credentials.txt (canonical) + local `.env`. **NEW quant-of-rehan bot token** (2026-10-05); the sentinel's old token is retired and never reused |
| `TELEGRAM_CHAT_ID` | same | Owner sends the bot one message, then the id goes into local `.env` |
| `GITHUB_TOKEN` | Automation | GitHub-internal (Actions), not readable |
| Broker creds | **Nothing in this repo** (SO-1/SO-6) | Owner's Desktop only |

Cloudflare Worker deployment and the private GitHub Actions relay secret are
active. Secret values are never recorded in repository files or reports.

## 7. Current decision

Read-only capture is approved and scheduled. Production remains closed until
historical membership, data-source rights, and latency are adequately
verified. The code does not infer those permissions from public reachability.
Everything else in this memo is already actionable without further input.

## 8. Addendum (2026-10-04): DPS portal redesign: 5-year EOD source lost

### 8.1 What died
The old programmatic endpoint `dps.psx.com.pk/timeseries/eod/{SYM}`: which
returned the FULL ~1,240-session close/volume/open history per symbol in one
GET (rows `[epoch, close, volume, open]`, no high/low): is gone:
- script requests now get **403 (WAF)** or **404** (path removed);
- the redesigned portal's API surface (`/symbols`, `/calendar`, `/performers`,
  `/timeseries/int/{SYM}`) serves **intraday only**: no EOD-history endpoint;
- the `/historical` page renders a server-side OHLCV table **with high/low**
  (591 symbols) but its date form POST is ignored by the server (same table
  regardless of date), and symbol×month search reaches only 2022.

Consequence: **the 5-year-per-GET EOD source is gone.** Any backtest claiming
5 years today would need a new legitimate source, not the old endpoint.

### 8.2 What we run on meanwhile (local, honest)
The sentinel's `eod_corpus.json`: 305 KMIALL symbols with data (8 empty of
313), 177 sessions 2026-01-05..2026-09-23, ~51,452 rows, no high/low → engine
runs in close mode. Known defects, found by probing and now screened by the
engine (SO-3):
- 128 rows with `open = 0.0` (suspended scrips, e.g. AKGL);
- **6 symbols (BLUEX, CLOV, ITANZ, MTL, SRVI, STL) have an OPEN column left
  ~10x the CLOSE column** on every row: unadjusted 10:1 par-value
  reconstruction. Closes are self-consistent, so the defect is only visible
  open-vs-close. The engine's adjacent-print invalid screen flags all such
  trades (120 in the smoke run); zero valid trades remain below -50% gross;
- ITANZ prints one +109% close-to-close move (2026-02-17, resumption-like);
  also flagged.

### 8.3 5-year fill: SOLVED: Daily Downloads mkt_summary (confirmed 2026-10-04)
The redesigned portal's `/downloads` page exposes per-date files with a
stable URL pattern:

    https://dps.psx.com.pk/download/mkt_summary/{YYYY-MM-DD}.Z

Probed and confirmed: `.{Z}` is a misnamed container: ZIP (`PK`) from ~2021
onward, gzip (`1f8b`) in older years: holding one pipe-delimited listing
`closing11.lis` per session:

    02OCT2026|OGDC|0820|Oil & Gas Dev|313.01|315.95|311.8|314.62|1836867|313.39|||

= date|symbol|code|name|**OPEN|HIGH|LOW|CLOSE|VOLUME**|rate2|||. That is full
OHLCV **with high/low**: strictly better than the dead endpoint. Raw
`requests` fetches work (no WAF on `/download/*`); non-session dates 404.
Archive depth: 2015-01-02 returns 200, 2010-01-04 is 404 → coverage ≥ 2015,
far beyond the 5-year need. ~1,240 sessions × ~20KB ≈ 30MB total.

Builder: `python scripts/build_eod_history.py --start 2021-10-04 --end
2026-10-02` (LOCAL ONLY, resumable, 0.35s pause, 404=holiday). Fetcher/tests:
`src/data/psx_daily_downloads.py`. PSX's legal notice prohibits commercial
redistribution of market data; this crawl is private research on the owner's
machine, dataset gitignored under `/data/`.

