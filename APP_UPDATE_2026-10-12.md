# App and card update, 2026-10-12

Four requested changes, plus the one that explains the missing buy and sell
volumes. Install `QuantOfRehan-v1.6.2.apk` from the OneDrive Desktop.

## 1. What was asked, and what is now true

| # | request | state |
|---|---|---|
| 1 | remove "MARKET NOW" from the third tile | done: the label is gone from the layout, the copy, and the built APK (verified: `MARKET NOW` is not in its `resources.arsc`) |
| 2 | separate buy and sell volumes, from real-time data | done in the card: see section 3. Rows read `B=... S=... T=...`, with `=` for measured and the estimate mark for an inference |
| 3 | replace the "Index as of ... to total volume only" line with "Quant will be scanning the market every 4 minutes during market open." | done, verbatim, as the market card's own foot (one string resource, `scan_cadence`) |
| 4 | remove the footer at the very bottom | done: the pinned bottom cadence and the rule under it are gone, so the interface ends at the card |

The APK on the Desktop was rebuilt from this source and carries all four.

## 2. Why the phone showed only `T=`

Three separate faults, each measured before it was fixed.

1. **The relay card carried no split.** The split reaches the app only if the
   PC pushes a snapshot that has one. On 2026-10-12 the pushes before 13:31
   failed (the worker host did not resolve from this PC), and the edge's own
   build cannot split volume: the PSX pages publish one volume column.
2. **The tape recorded one row in ten.** The capture split each frame on `$`,
   a separator this wire does not use, so nine of the ten symbol rows in every
   frame were banked as unnamed numbers. Measured: 902 rows arrived, 64 were
   parsed. Fixed; a capture written before the fix is now re-read from its raw
   line, so those rows count too.
3. **The tape's field map was wrong on the wire this PC receives.** The map
   read field [2] as the last price, [3] as the bid and [6] as the ask. On the
   live rows [6] is the market status (`OPN`), [3] and [4] are the bid and the
   ask, and [10] is the last price. The old map made the app's quote rule read
   `OPN` as an ask price, so no row could ever be classified. Verified against
   the venue's own numbers on 5064 live rows before the map was rewritten:
   `last - close` equals the change field on 4882 of 4994 rows, and the last
   price sat exactly at the ask on 2184 rows and exactly at the bid on 1122.

## 3. How the split now uses real-time data

The exchange publishes no side, and the broker's feed carries no per-trade
tape: it carries per-symbol snapshots, each with the venue's own running
session total, the last print, the best bid and the best ask. So the split is
built from exactly that, per symbol:

* every pair of snapshots forms one window, and the window's shares are the
  increment of the venue's own running total (the print sizes add up to a
  small fraction of it, which is why a split built from them could never
  reconcile);
* the window's side comes from where the print traded: at the ask means a
  buyer lifted the offer, at the bid means a seller hit it, and where the
  book says nothing the tick rule decides from the price move. A window with
  no evidence is counted as unclassified, and so is everything traded before
  the tape first saw the symbol, so the numbers stay complete rather than
  being a floor;
* the card then shows the tape's own numbers when the tape covered the day
  (`B=`), its flow projected onto the day's total when it did not (`B≈`), and
  the labelled range estimate when the tape has no usable coverage (`B≈`).

Two guards were added after measuring real failures on the day:

* **A window longer than ten minutes is an outage, not a sample.** Measured:
  the capture was dead from 10:32 to 13:27, and CNERGY's 4,050,063 shares
  across that dead stretch would have printed the day as 97 percent buying.
  Such a window is refused and reported.
* **A slice below a tenth of the day's shares cannot stand for the day.**
  Measured: a 0.1 percent slice of SLGL would have printed as 100 percent
  buying. Below the floor the range estimate answers instead, labelled as it
  is.

## 4. What the card carries right now (live, 14:09 PKT)

Fetched back from the deployed relay, exactly what the phone renders:

```
TREET    B=15,248,197  S=7,386,902   T=22,635,099   from the tape's prints
PIBTL    B= 8,677,143  S=1,508,386   T=10,185,529   from the tape's prints
CNERGY   B= 2,334,249  S=6,743,387   T= 9,077,636   from the day's range
```

TREET and PIBTL are the tape's real-time reading. CNERGY's tape coverage is
still 6.5 percent of its day, because today's tape only ran properly from
14:02 (the failures in section 2), so it falls back and says so. The 4-minute
tick now keeps the tape running from the open, so from the next session the
leaders' splits come from the tape itself.

## 5. What was verified

* The live tape: restarted 14:02 with the fixed parser, 154 messages and 808
  rows in seven minutes, full frames (the old one banked one row per frame).
* The live card: pushed and fetched back from the deployed relay twice, with
  `tape_flow` rows carrying the tape's attributed volume in their note.
* The app: rebuilt as v1.6.2 and inspected; the card's cadence sentence is in
  its resources, and `MARKET NOW` is not.
* The suite: 705 tests pass, and the governance guard passes (footprint
  honesty, Karachi pin, secret scan, style).

## 6. Still true, and stated plainly

* The exchange publishes total volume only. Every B and S on the card is an
  inference from the venue's own prints, which is why the estimate mark
  travels on the number and never a bare `=`.
* A tape has to run from the open for the measured path; a mid-session start
  is refused above the coverage floor rather than projected.
* The feed is a snapshot cycle, not an L2 book: there is no per-trade tape to
  read, and nothing on the card claims there is.
