# DATA_SOURCING — Market Data Research Memo (PSX KMIALL)

**Date:** 2026-10-04 · **Prepared by:** the QUANT · **Status:** verdict final
for free/public sources; forward-capture plan pending owner go-ahead.
**Update (same day):** PSX Data Portal redesigned — the 5-year-per-GET EOD
endpoint is dead; see §7.

## 1. The mandate

Find **genuine historical PSX bid/ask/order-flow data**. The bot must never
pretend it has footprint analysis. Order flow is treated as necessary for the
full vision — so if it cannot be sourced, that fact must be loud, not hidden.

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
> five years of PSX footprint history would be fabricating it — which
> GOVERNANCE.md SO-3 forbids.

Consequence for the 5-year backtest: it runs on **daily + (eventually)
forward-captured intraday OHLCV**, with the footprint/order-flow layer
**explicitly disabled and labeled**:

```
FOOTPRINT DATA UNAVAILABLE / DEGRADED — footprint engine disabled
```

OHLCV-derived proxies (e.g. candle-body imbalance) may inform research only
when labeled degraded. They are never presented as true order flow.

## 4. The real paths to genuine order flow

### Path A — Forward capture from the read-only broker feed (recommended)
- Feed socket: `oms1.eclear.com.pk:8484` (per owner's credential sheet).
- Owner's own rules sanction **READ-ONLY** use: no order-side messages, ever.
- A local recorder would bank genuine tick/depth data **from today onward**,
  building a private historical archive week by week.
- **Needs owner go-ahead** before any socket is connected (it touches broker
  infrastructure, so this is the one thing the QUANT asks for).

### Path B — Forward intraday bar capture from the local runner
- No new source: the existing local runner records 1m/5m/15m/1h bars daily.
- Builds the intraday dataset the backtester eventually needs.

### Path C — Daily OHLCV backfill (DEGRADED — see §7)
- ~~PSX Data Portal / CSOR daily files cover years of history~~ The portal
  redesign removed the 5-year-per-GET EOD endpoint. The current backbone is
  the sentinel's local 177-session corpus (2026-01-05 .. 2026-09-23, 305
  KMIALL symbols); the remaining free lead for 5-year history is the
  portal's per-date "Daily Downloads" files (§7.3).

### Path D — Paid vendor (not pursued)
- If genuine historical tick data ever becomes a hard requirement, the only
  realistic route is a paid data vendor or an exchange data agreement. That
  is a cost decision reserved for the owner, only if the bot proves
  profitable first (per his own rule: VPS/infrastructure follows profit).

## 5. Secrets — canonical names (values never in this repo)

| Name | Used by | Lives in |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Signal notifications | GitHub Secrets, Cloudflare worker secret |
| `TELEGRAM_CHAT_ID` | Signal notifications | GitHub Secrets, Cloudflare worker secret |
| `GITHUB_TOKEN` | Automation | GitHub-internal (Actions), not readable |
| Broker creds | **Nothing in this repo** (SO-1) | Owner's Desktop only |

## 6. Decision requested from the owner

Approve Path A (read-only feed capture from `oms1.eclear.com.pk:8484`)?
Everything else in this memo is already actionable without further input.

## 7. Addendum (2026-10-04): DPS portal redesign — 5-year EOD source lost

### 7.1 What died
The old programmatic endpoint `dps.psx.com.pk/timeseries/eod/{SYM}` — which
returned the FULL ~1,240-session close/volume/open history per symbol in one
GET (rows `[epoch, close, volume, open]`, no high/low) — is gone:
- script requests now get **403 (WAF)** or **404** (path removed);
- the redesigned portal's API surface (`/symbols`, `/calendar`, `/performers`,
  `/timeseries/int/{SYM}`) serves **intraday only** — no EOD-history endpoint;
- the `/historical` page renders a server-side OHLCV table **with high/low**
  (591 symbols) but its date form POST is ignored by the server (same table
  regardless of date), and symbol×month search reaches only 2022.

Consequence: **the 5-year-per-GET EOD source is gone.** Any backtest claiming
5 years today would need a new legitimate source, not the old endpoint.

### 7.2 What we run on meanwhile (local, honest)
The sentinel's `eod_corpus.json`: 305 KMIALL symbols with data (8 empty of
313), 177 sessions 2026-01-05..2026-09-23, ~51,452 rows, no high/low → engine
runs in close mode. Known defects, found by probing and now screened by the
engine (SO-3):
- 128 rows with `open = 0.0` (suspended scrips, e.g. AKGL);
- **6 symbols (BLUEX, CLOV, ITANZ, MTL, SRVI, STL) have an OPEN column left
  ~10x the CLOSE column** on every row — unadjusted 10:1 par-value
  reconstruction. Closes are self-consistent, so the defect is only visible
  open-vs-close. The engine's adjacent-print invalid screen flags all such
  trades (120 in the smoke run); zero valid trades remain below -50% gross;
- ITANZ prints one +109% close-to-close move (2026-02-17, resumption-like);
  also flagged.

### 7.3 Remaining free lead for the 5-year fill
The redesigned portal's `/downloads` page links per-date **Daily Downloads**
files (e.g. Market Summary ZIP, Closing Rate Summary PDF). If a stable URL
pattern exists, ~1,240 dates could be fetched — but raw script requests are
WAF-blocked, so this needs either (a) browser-context fetching from the real
page, or (b) the owner downloading manually. Coverage/format still unprobed.
This is the only known free route back to ~2021 daily OHLCV with high/low.
