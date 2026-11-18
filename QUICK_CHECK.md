# Quant of Rehan: Daily Check and Restart

Keep this beside the HUD. All times are Karachi. Your PC can stay off.

## A. Check the day (2 minutes, after 09:20)

1. **Relay.** Open the [health page](https://quant-of-rehan-relay.mrmrehanqureshi.workers.dev/health).
   Healthy means `"ok": true` and, on a trading day, `"trading_day": true`.
   No page, or `false`, means the relay is down.
2. **Quotes.** Open the [quotes page](https://quant-of-rehan-relay.mrmrehanqureshi.workers.dev/quotes).
   Healthy means `"stale": false`, `"updated_at"` is less than one minute old,
   and `quotes` holds about 200 rows or more. Empty or stale means the capture
   is not running.
3. **Flow.** Open the [flow page](https://quant-of-rehan-relay.mrmrehanqureshi.workers.dev/flow).
   Healthy means `counts.included` is above 0 and climbing towards 319.
   Zero while the market is open means no feed is arriving.
4. **Session.** Open [Actions](https://github.com/muhammadrehanqureshi/quant-of-rehan/actions)
   and click **KMIALL session scan loop**. After 09:15 the newest run should be
   **In progress**, not red.

If all four are healthy, you are done. Nothing needs starting.

## B. If something is off, start it

Do one step, then check the quotes page again.

1. **Relay does not answer.** Actions, **Deploy relay**, **Run workflow**.
   Wait for a green run. Open health again.
2. **Quotes are empty or stale.** Actions, **KMIALL intraday momentum scan**,
   **Run workflow**. Choose the slot that contains the current time:
   `10:00`, `11:30`, `13:00`, `14:30`, `15:40`, or `finalize` after the close.
   Run it. Wait for green, then check quotes again.
3. **Quotes still empty or stale.** Actions, **KMIALL session scan loop**,
   **Run workflow**, leave seconds at `3600`, and run it. This restarts the
   feed for the current band.
4. **Still not moving after 2 minutes.** Open the newest **KMIALL intraday
   momentum scan** run. Read the red step, then send me the run link.

## C. Healthy after a restart

- Quotes `"updated_at"` keeps moving.
- Flow `counts.included` climbs.
- The scan run is green or still in progress.
- The HUD shows LINK and a fresh FEED.

## D. Do not do this

- Do not rerun a job that failed with `push refused` or `400`. Send me the run
  link instead.
- Do not start the old local scheduler or leave anything running on the PC.
- A second capture is safe. It cannot double the volume.

**Green means:** health is ok, quotes are fresh, included is above zero, and
the newest session run is in progress. That is the whole check.
