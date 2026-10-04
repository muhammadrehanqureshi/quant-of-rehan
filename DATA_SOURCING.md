# DATA_SOURCING — Market Data Research Memo (PSX KMIALL)

**Date:** 2026-10-04 · **Prepared by:** the QUANT · **Status:** verdict final
for free/public sources; forward-capture plan pending owner go-ahead.

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

### Path C — Daily OHLCV backfill (already available, free, official)
- PSX Data Portal / CSOR daily files cover years of history for the whole
  market, including the KMIALL universe. This is the backbone of the 5-year
  backtest **today**.

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
