# Runbook: start and verify every piece that can stop

One page, in the order you need it. Times are Karachi (UTC+5). Every command is
safe to run from this PC, and nothing here needs this PC to stay on.

## 0. The four pieces

| Piece | What it does | Runs on | How you see it |
|---|---|---|---|
| Relay | Stores quotes and serves the answers the HUD reads | Cloudflare Worker, no PC | `/health`, `/quotes`, `/flow`, `/market` |
| Capture | Reads the broker tape and pushes quotes to the relay | GitHub Actions | A green run, and `/quotes` moving |
| Readiness gate | Checks the relay and the quote store before the open | GitHub Actions, 08:45 and 09:20 PKT | An email, only when something is wrong |
| HUD | Draws the screen from the relay | This PC | `QuantOfRehan.exe` |

The relay address is `https://quant-of-rehan-relay.mrmrehanqureshi.workers.dev`.
If the HUD says NO FEED, the relay is the shop and the capture is the delivery:
the shop is almost never the broken one.

## 1. Before the open: four checks, two minutes

Do these at or after 08:45 PKT on a trading day.

1. Open `https://quant-of-rehan-relay.mrmrehanqureshi.workers.dev/health`.
   Healthy: `"ok": true`, a `version` hash, `market_state.trading_day: true`,
   and `market_state.phase` reading `PRE_OPEN` before 09:32 and `OPEN` after.
   No answer at all means the relay itself is down: go to section 4.
2. Open `.../quotes`.
   Healthy: `quotes` holds 200 or more rows, `stale: false`, and `updated_at` is
   seconds old. Zero rows while the phase is `OPEN` means nothing is being
   stored: go to section 2. Rows but `stale: true` means the capture stopped
   recently: also section 2.
3. Open `.../flow`.
   Healthy: `counts.universe` is 319, `counts.included` is climbing towards it,
   and `totals` carries `buy`, `sell` and `unclassified` as three separate
   numbers. `included` of 0 with `missing` of 319 is the same fault as step 2.
4. Open the newest **Pre-open readiness** run in the Actions tab.
   Healthy: the log ends in `ready` and no email arrived. Anything else in that
   log is the sentence the gate emailed you: use section 5.

## 2. Start the feed by hand (the fix for NO FEED)

The capture is what publishes. Start it, then watch `/quotes` move.

From this PC with the `gh` command:

```bash
gh workflow run intraday-capture.yml -f slot=10:00
gh run list --workflow=intraday-capture.yml --limit 1
gh run watch <the run id> --exit-status
```

Use the slot that contains the current Karachi time: `10:00`, `11:30`, `13:00`,
`14:30`, `16:00`, or `finalize` after the close. Leave `day` empty for today.

From the browser: Actions, **KMIALL intraday momentum scan**, **Run workflow**,
choose the slot, Run.

Confirm, about a minute after it starts:

* `/quotes` `updated_at` moves and its row count climbs,
* `/flow` `counts.included` climbs towards 319,
* the run's log has no `push refused` line.

A second capture is safe. Both write to the same store and the split law keeps
one pair per symbol, so starting one never doubles anything.

## 3. Start a whole band (when the session loop never started)

This is the long job that keeps the tape alive for the rest of the band. It
gates itself: outside a band it says so and exits, so a mistaken start costs a
minute and nothing else.

```bash
gh workflow run intraday-session.yml -f seconds=3600
```

Or Actions, **KMIALL session scan loop**, **Run workflow**. It stops on its own
when `seconds` runs out, and never scans outside a band or a pre-open window.

## 4. Restart the relay (only when `/health` does not answer)

The relay is deployed by a workflow, so it needs nothing on this PC:

```bash
gh workflow run deploy-relay.yml
gh run watch <the run id> --exit-status
```

The workflow deploys with wrangler and then reads `/health` back until the
`version` it reports equals the commit it deployed, so a green run is proof the
edge was replaced. From this PC the same deploy is:

```bash
python cloud/pair.py deploy
python cloud/pair.py health
```

`pair.py` reads the Cloudflare token from `Desktop/credentials.txt`. Never paste
a token into a chat, a file in this repository, or a commit.

## 5. Read the alert email, then do the one thing it names

The gate emails at most once a day and only when a check failed. Its first line
is the check, and it is enough to choose the action.

| The email says | The layer | The action |
|---|---|---|
| `the relay did not answer /health` | Cloudflare | Section 4 |
| `the quote store holds no rows` | capture | Section 2 |
| `the quote store is stale` | capture | Section 2 |
| `all N stored rows carry zero volume` | capture started but no trade recorded | Wait for the first print, then section 2 if it stays at zero |
| `the session clock reads X on a trading day` | relay clock or session law | Section 4, then read `/health` again |
| `quotes[9] requires a valid symbol, positive price and timestamp` | relay law against the publisher | Do not re-run it: this is a code disagreement, and re-running pushes the same rejected rows. Send the run id |

The same refusal also reaches you as one email from the capture, with the
relay's own status and words. The marker it leaves is
`data/feed_capture/relay_refused.flag` in the run's own workspace; the email is
the part that survives the runner.

## 6. What now runs without you

| Guard | When | What it does |
|---|---|---|
| Pre-open readiness | 08:45 and 09:20 PKT, trading days | Checks the relay, the clock and the store, and emails only a failure |
| Feed watchdog in the relay | every cron wake and every `/signals` poll | If the newest stored frame is older than five minutes inside an open window, it starts the band scan again, with a ten minute cooldown |
| Band loops | 08:55, 12:30, 15:35 PKT, and the Friday pair | Keep the tape alive for the whole session with this PC off |
| Capture backstops | 09:20, 10:07, 11:37, 13:07, 14:37, 15:40, 15:47 PKT | A scheduled pass even if a band loop never started |
| Refusal flag | within a minute of a refused push | One email a day with the relay's own words, cleared by the first accepted push |

So the only thing left for you is the two minute check in section 1, and only if
no email arrived.

## 7. What not to do

* Do not re-run a refused push. A `400` means the relay's law and the publisher
  disagree; the same rows will be refused again, and before 2026-11-10 that
  loop is what kept the feed dead for an hour.
* Do not start the retired local scheduler, and do not leave anything running on
  this PC. The cloud carries the session.
* Do not run a backtest here. `.github/workflows/backtest.yml` is the only entry
  point, and it runs the work on Actions.
* Do not hand-edit a quote payload or a `/flow` number to make a screen look
  right. If the numbers disagree, the disagreement is the finding.

## 8. The 2026-11-10 signature, so it is recognised in seconds

* **Looked like:** the KSE100 index and the top three were live, volumes and
  all, and the card still read NO FEED.
* **Actually was:** `/quotes` held the index and the OPEN status but zero symbol
  rows, because the day's zero-volume baselines carried no price. The relay
  demanded a positive price on every row, answered 400 for the whole batch, and
  the publisher retried the same rows forever behind them.
* **Now:** the quote law accepts a zero-volume baseline while still demanding a
  symbol, a source and a timestamp, and still demanding a positive price on
  every priced row. A 400 drops the rows that carry no price instead of
  retrying them, and a refusal leaves a flag that becomes one email.
* **The tell:** index and phase moving while `counts.included` sits at 0. That
  is a store refusing pushes, not a quiet market.

## 9. The scan, the card, and the build you are running

The scan starts at 08:55 PKT and scans from the 09:15 pre-market. Two words on
the LATEST SIGNAL tile mean two different things, and they are not
interchangeable.

* **WARMING UP** is normal. The tape is alive and still filling. The strategy
  will not rank a symbol until it holds 20 completed one-minute bars inside the
  current band, so no entry can exist before about 09:52. A full entry also
  needs the 60-minute VWAP frame, which cannot exist before about 10:32. The
  card prints the minutes it still needs. Nothing is broken and nothing needs
  starting.
* **SCAN BLOCKED** is a data fault. The card names the coverage and how many
  symbols hold the 20 bars. Check `/quotes` and `/flow` as in section 1, then
  look at the band run below. It never means the market was quiet.

Confirm the day's band is running, at or after 09:15:

```bash
gh run list --workflow=intraday-session.yml --limit 3
gh run view <the newest run id> --json jobs \
  -q '.jobs[].steps[] | [.number,.name,.conclusion] | @tsv'
```

Healthy at 09:20: the 08:55 run is still in progress and its scan step has no
conclusion yet. A run that finished before 09:15 with a failure is the fault
fixed on 2026-11-10 (the pre-open empty tape was counted as five faults); if it
happens again, section 3 starts a band by hand for the rest of the session.

At 10:00 the card should read NO TRADE with a coverage line, or a signal. A
card still reading WARMING UP after 10:30 means the tape restarted; a card
reading SCAN BLOCKED after 10:00 is a data fault, not a slow morning.

The HUD is `QuantOfRehan-build35.exe` in
`Desktop/QuantOfRehan-Windows/`. The older `.exe` files beside it are kept, so
the file name is how the running build is known: build 35 carries the bigger
orb, the ten-box bars and the leader price after `T`.

## 10. This runbook as a PDF

`.github/workflows/runbook-pdf.yml` renders this file to `RUNBOOK.pdf` on
GitHub Actions, so no document is built on this PC. It runs on every change to
this file and can be started by hand:

```bash
gh workflow run runbook-pdf.yml
gh run list --workflow=runbook-pdf.yml --limit 1
gh run download <the run id> -n runbook-pdf -D .
```

The downloaded `RUNBOOK.pdf` is the same text as this page, with page numbers
and the tables intact, and it needs no terminal and no network to read.
