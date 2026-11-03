# Eclear broker feed forensic and order-flow capability report

Date: 2026-11-03. Author: the agent, on the owner's instruction.
Feed: Syed Faraz / Eclear, `nxg1|nxg2|nxg.eclear.com.pk:8484`.
Status: read-only throughout. No order, cancel, modify or account message is
sent by any code path named here, and none was sent during this audit.

Evidence base, all measured on this machine or banked by the Actions runners:

- `src/data/feed_capture.py`: the recorder and the verified 20 field tick map.
- `data/feed_capture/capture_20261023.ndjson`: one whole session, 93.8 MB.
- `data/feed_capture/capture_20261016|18|21.ndjson`: three more sessions.
- `data/audit_20261023.json`: the forensic audit of the 93.8 MB session,
  produced by `scripts/feed_forensic_audit.py`.
- `data/order_flow_20261023.json`: the normalized order-flow aggregate,
  produced by `src/data/order_flow.py`.
- `tests/test_order_flow.py`, `tests/test_feed_forensic_audit.py`: 19 tests,
  all passing locally on 2026-11-03.

The footprint truth source `src/data/registry.py` records Level-2
footprint data as UNAVAILABLE. This audit respects that law: every number
below is top-of-book or inferred trade flow on the snapshot wire, never a
footprint, and no engine may present it as order-book data.

## 1. What the feed actually is

The socket speaks a `%`-terminated text protocol. The server greets with
`Welcome*%`. The client sends exactly three frame types, all enforced by a
guard in `feed_capture.guard()`: the `MKT-FEED|SYM1:REG;SYM2:REG;...;%`
subscription, the `EXS-FEED` index subscription, and `HELLO|%` every five
seconds. There is no login, no credentials and no session.

The critical protocol finding, measured live on 2026-10-12: the per-symbol
market suffix is mandatory. `MKT-FEED|TREET;PRL;...;%` yields zero tick
frames; `MKT-FEED|TREET:REG;PRL:REG;...;%` yields a steady stream. Bare
symbols receive only index, movers and market-stat frames, which is why an
earlier capture looked alive while banking no ticks.

The payload is a per-symbol SNAPSHOT cycle, not a trade-by-trade tape. One
frame carries several symbols separated by `||`, and each symbol is 20
semicolon fields. The measured sweep interval is 23.98 s per symbol
(2026-10-23 session, 311 symbols). The same snapshot is re-sent while a
symbol is unchanged: 89.8 percent of the session's 127,510 REG rows repeat
their predecessor exactly.

The field map, verified against 5,064 live rows on 2026-10-12 (not assumed
from the recon document):

| Index | Field | Meaning | Timestamp | Reliability | Example |
|---|---|---|---|---|---|
| 0 | scrip | symbol | - | verified | SAZEW |
| 1 | market | REG | - | verified | REG |
| 2 | bid_size | shares resting at the bid | - | verified | 115 |
| 3 | bid | best bid | - | verified | 1421.15 |
| 4 | ask | best ask | - | verified | 1422.99 |
| 5 | ask_size | shares resting at the ask | - | verified | 30 |
| 6 | status | OPN or SUS | - | verified | OPN |
| 7 | change_sign | sign of the day change, NOT trade side | - | verified | - |
| 8 | change | change in points | - | verified | -27.65 |
| 9 | tick_time | venue time of the last print | venue, seconds | verified | 10:31:16 |
| 10 | last | last traded price | - | verified | 1422.99 |
| 11 | flag | a space on every live row | - | verified | |
| 12 | avg | venue session average price (VWAP) | - | verified | 1425.90 |
| 13 | high | day high | - | verified | 1455.00 |
| 14 | low | day low | - | verified | 1412.12 |
| 15 | trades | cumulative trade count | - | verified | 1684 |
| 16 | volume | cumulative shares | - | verified | 72149 |
| 17 | last_volume | size of the print in field 10 | - | verified | 1 |
| 18 | close | previous close | - | verified | 1450.64 |
| 19 | open | day open | - | verified | 1455.00 |

Evidence for the quote and print fields: on 5,064 live rows the last price
sat exactly at field 4 on 2,184 rows and exactly at field 3 on 1,122, and
field 10 minus field 18 equalled field 8 within one paisa on 4,882 of
4,994 rows where all three arrived. Field 7 matched the sign of field 8
with zero exceptions across 902 rows, so it carries no trade-side
information; the side of a print is inferred from where it traded.

## 2. Message catalogue

Counts are from the 2026-10-23 session (13,120 tick frames alone).

| Kind | Fields | Meaning | Timestamp | Reliability | Example |
|---|---|---|---|---|---|
| Welcome | none | server banner | - | verified | `Welcome*%` |
| MKT-FEED | 20 fields per row, rows separated by `\|\|` | per-symbol quote and last print snapshot | tick_time is the venue print clock, seconds | verified | `MKT-FEED*SAZEW;REG;115;1421.15;1422.99;30;OPN;-;-27.65;10:31:16;1422.99; ;1425.90;1455.00;1412.12;1684;72149;1;1450.64;1455.00` |
| EXS-FEED | `STAMP^INDEX;value;change;...;adv;dec;unch;volume;turnover` groups separated by `$` | index levels and market breadth | venue stamp with AM/PM | value, change, breadth counts and totals verified by magnitude; two middle fields unknown | `10/23/2026 10:31:08 AM^KSE100;163303.31;-621.00;163966.86;42.54688;163238.14;-686.1719;192;237;24;14255840;1154064466.05;` |
| MKT-STATS | `SEGMENT;STATE;VOLUME;TRADES;TURNOVER` separated by `\|\|` | per-segment market state and totals | none in frame | state word verified (already consumed by the card); totals read positionally | `MKT-STATS*REG;OPEN;83339305.00;67223.00;3668393693.07` |
| MKT-Movers | `SYM:REG;` lists | mover lists per category | none in frame | names and market suffix verified; category grouping not consumed | `MKT-Movers*MACFL:REG;WTL:REG;...` |
| RUCAP | `SYMBOL*PRICE` | revised upper circuit cap | none | semantics inferred from the frame name | `RUCAP*SZTM*132.52` |
| RLCAP | `SYMBOL*PRICE` | revised lower circuit cap | none | semantics inferred | `RLCAP*BAPL*18.62` |
| ADDUCAP | `SYMBOL*PRICE` | added upper cap | none | semantics inferred | `ADDUCAP*FPRM*12.23` |
| HELLO | none | keepalive, both ways | - | verified | `HELLO*%` |

Breadth from the last EXS-FEED of the session: 155 advancing, 304
declining, 22 unchanged, 39,753,212 shares, turnover PKR 3,371,371,896.76.
Last REG segment totals: state OPEN, 159,107,807 shares, 144,593 trades,
turnover PKR 7,660,239,128.30. Circuit-cap frames seen that session:
ADDUCAP FPRM 12.23, RLCAP BAPL 18.62, RLCAP BAPLR1 9.62, RUCAP SZTM 132.52.

## 3. Capability classification

| Capability | Status | Evidence |
|---|---|---|
| Level 1 (last, best bid, best ask, sizes, day volume, turnover proxy, OHLC, previous close) | VERIFIED AVAILABLE | 20-field map above; 311 of 319 KMIALL symbols seen in one session |
| Level 2 MBP (multi-level depth) | NOT AVAILABLE | one best bid and one best ask with sizes only; no ladder exists on the wire |
| Level 2 MBO (individual orders, add/modify/cancel) | NOT AVAILABLE | no order ids and no order event message types exist on the wire |
| Time and sales (trade-by-trade) | PARTIALLY AVAILABLE | only the last print of each ~24 s window is named; median print fidelity 0.42 (p25 0.23, p75 0.83) measured 2026-10-13 |
| Aggressor side | NOT AVAILABLE | no side flag exists; side is inferred from print location at the ask or bid, then the tick rule |
| Order events | NOT AVAILABLE | no additions, modifications or cancellations |
| Circuit limits | PARTIALLY AVAILABLE | RUCAP/RLCAP/ADDUCAP frames; semantics inferred |
| Market breadth | VERIFIED AVAILABLE | EXS-FEED advancing/declining/unchanged counts |
| Sequence numbers | NOT AVAILABLE | no sequence field; gaps are measured by time and by cumulative counters |
| Exchange timestamps | PARTIALLY AVAILABLE | last print time in seconds only; no quote timestamp |

## 4. Feed quality, measured

Session 2026-10-23, one capture file, 93.8 MB:

| Measure | Value |
|---|---|
| MKT-FEED frames | 13,120 |
| REG tick rows | 127,510 |
| Symbols seen | 311 of 319 (97.5%) |
| Duplicate consecutive rows | 114,555 (89.8%) |
| Out-of-order records | 0 |
| Median per-symbol cadence | 23.98 s |
| New print to local receipt | p50 8.6 s, p75 15.4 s, p90 20.6 s, p95 22.5 s, max 24.9 s, 12,628 prints |
| Index and market-state cadence | 24.0 s median |
| Print fidelity (2026-10-13 measurement) | median 0.42, p25 0.23, p75 0.83 |
| Unclassified volume share, whole session | 7.6% (inferred sides cover 92.4% of increments) |

What this means for algorithmic use: the feed is a 24-second snapshot
sampler with an 8.6-second median print lag. It is adequate for entry
quality, spread, top-of-book imbalance, intensity and session VWAP. It is
not adequate for anything requiring the book ladder or individual orders,
and it cannot resolve a 1 percent stop inside a 24-second window. Any
intraday stop/target research on this feed inevitably relies on daily bars
or on coarser intervals; that limitation is a property of the wire, not of
the parser.

## 5. Implemented extraction

`src/data/order_flow.py` (new, research only, imported by nothing in the
scanner) normalizes snapshots and windows with these laws:

- consecutive identical snapshots count once;
- windows longer than the capture bound are refused, not attributed;
- traded value and window VWAP come from the venue's own average price
  identity: total times average differences, so no price is estimated;
- sides are inferred and every output says so;
- an absent field yields None, never zero.

Features with their status (single source of truth `FEATURE_STATUS`):

| Feature | Status | Definition |
|---|---|---|
| spread, spread in bps | AVAILABLE | ask minus bid at the touch |
| OBI top 1 | AVAILABLE | (bid size - ask size) / (bid size + ask size) |
| trade intensity | AVAILABLE | trades and volume per window from the venues own counters |
| traded value | AVAILABLE | total times average differences |
| session VWAP | AVAILABLE | venue average price field |
| window VWAP | AVAILABLE | traded value / volume increment |
| CVD (inferred) | INFERRED LIMITED | buy side minus sell side of attributed windows |
| bid replenishment | INFERRED LIMITED | after selling hit the bid, resting bid size returned to its prior level, at snapshot cadence |
| ask absorption | INFERRED LIMITED | after buying lifted the ask, resting ask size shrank while price refused to fall |
| depth within 0.25/0.50/1.00 percent | NOT AVAILABLE | needs the ladder |
| order cancellation analysis | NOT AVAILABLE | needs order events |
| price impact by level | NOT AVAILABLE | needs the ladder |

`scripts/feed_forensic_audit.py` (new) produces the catalogue, duplicate,
cadence, latency, breadth and cap measurements above from any capture file.

Session aggregate from the real capture: 311 symbols, 12,644 windows,
39,540,163 shares moved, 36,525,994 attributed (92.4 percent), 3,014,169
unclassified (7.6 percent, dominated by shares traded before the capture
started and by gap windows).

## 6. Historical data collected

- Four whole sessions banked locally and kept: 2026-10-16, 10-18, 10-21,
  10-23 (the last is 93.8 MB, 13,120 tick frames).
- The runner captures every live session and archives the day's tape to R2
  (`data/feed_capture` push in `src/data/band_state.py`), so sessions after
  these dates exist in the archive rather than on this PC.
- Retention: the R2 archive keeps 45 days by design; local files are never
  deleted by this project.
- A study of a 2 percent target versus 1 percent stop with a split-half
  validation needs at least 20 complete sessions with the tape alive from
  the open, plus the frozen feature definitions. Four complete sessions are
  banked locally today. That is enough to test the pipeline, not enough to
  claim an edge, and no such claim is made.

## 7. The nineteen questions

1. What exact data does Eclear deliver? A 24-second per-symbol snapshot
   sampler: best bid and ask with sizes, last print with size and venue
   time, cumulative trades and volume, session average, OHLC, previous
   close, status, plus index/breadth, segment totals, movers and circuit
   caps.
2. Level 1? Yes, verified.
3. Level 2 MBP? No. Top of book only.
4. Level 2 MBO? No.
5. Genuine tick by tick? Partially: the last print of each window only,
   fidelity median 0.42.
6. Order additions, modifications, cancellations? No.
7. Aggressor side? Not supplied; inferred only, labelled as inferred.
8. How many KMIALL symbols can be monitored? 311 of 319 in one session with
   the current subscription; nothing in the protocol limits it below the
   universe.
9. Actual feed latency? New print to local bank: 8.6 s median, 22.5 s p95,
   bounded by the 24 s snapshot cycle.
10. Data quality limitations? Snapshot cadence, 89.8 percent duplicate
    rows, last-print-only tape, no sequence numbers, cap-frame semantics
    inferred, two EXS-FEED middle fields unidentified.
11. Which order-flow features were successfully implemented? Spread, OBI
    top 1, trade intensity, traded value, session and window VWAP, inferred
    CVD, replenishment and absorption proxies.
12. Which are impossible? Multi-level depth, order event analysis,
    cancellations, per-level impact, depth within a price band.
13. Does this eliminate the need for another subscription? For Level 1,
    top-of-book and coarse trade flow, yes. For genuine order-book research,
    no.
14. How much history? Four complete local sessions plus the R2 archive of
    recent runner sessions, 45-day retention.
15. Did order-flow features improve the strategy? Not tested yet; no
    evaluation has been run on this layer.
16. Did any improvement survive validation and untouched OOS? No claim is
    made; that evaluation requires the 20-session dataset above.
17. Actual net expectancy? Unchanged from the deployed record: 0 wins and
    2 losses observed, net expectancy negative on the frozen 2.0/1.0 family.
18. Is the order-flow module safe for shadow testing? Yes: it is read-only,
    test-pinned, imported by no production path, and reports unavailable
    states explicitly.
19. Is any feature justified for production? None yet. The available
    features (OBI, CVD, intensity, VWAP) are candidates for the shadow
    research only; no gate change is proposed without out-of-sample
    evidence.

## 8. Production isolation

The scanner, the card and the relay were not modified by this audit. The
new module is imported only by its tests and its CLI. The production buy
gate is untouched (one BUY maximum per day, NO TRADE valid, no broker
execution). Missing optional data cannot become zero or bullish: the module
returns None and names the missing input.

VERDICT: EXISTING ECLEAR FEED IS PARTIALLY SUFFICIENT.
