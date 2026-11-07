# Quant of Rehan for Windows (console edition), build 13

A Windows 11 console version of the Quant of Rehan Android app, matching app **4.0.16**, in the look of the first build.
One file of about 7 MB, no installer, no runtime, no dependencies. Around 2% of one CPU core and 13 MB of memory while it animates.

## What is new in build 13

* **Build 13.** The icon is redrawn closer to the owner's picture, and its tile now has transparent rounded corners. The twelve outer blocks sit on the 12 o'clock marks instead of between them, the outer arc and the tick rings are thinner, and the background is the picture's brighter teal, so the small icon no longer reads as a white target. The workflow checks that all four corners of the 1024 icon are transparent and its centre is opaque before it builds. The console is otherwise unchanged from build 12.

## What is new in build 12

* **Build 12.** The clock is green and the UTC+5 tag keeps the darker shade; the date and the time now have one space between them. The share bars are seven eighths of a cell tall, the terminal's next step above build 11's three quarters, which is sixteen and two thirds percent more. The dial is green and turning in every state while the owner checks the build outside market hours; `hudForceLive` in `orb.go` restores the dark, still dial afterwards. Opening a sector lists its scrips inside the SECTORS tile and leaves CUSTOM SCRIPS BY VOLUME on screen; BACKSPACE brings every group back, and ENTER opens the group under the pointer as well as a click. The icon is redrawn from the teal dial, and the workflow extracts the icon the exe actually carries into the `QuantOfRehan-exe-icon` artifact so it can be checked.
* **The title.** A console has one font size for the whole window, so a literal ten percent on one line is not available. The title is now the theme's brightest ink, bold, with the ordinary word spacing the owner asked for.

## What was new in build 11

* **Build 11.** The title is `◆ QUANT OF REHAN ◆` with ordinary word spacing, the date and clock are a darker shade and end in `UTC+5`, and the index line has a thin rule on either side. The green and red share bars are three quarters of a cell tall. The dial is green and turns faster while the market is live; a closed market leaves it dark and still, as the owner asked.
* **The icon is the picture.** The Windows icon is the owner's teal dial artwork, rendered at 1024 by `tools/mkicon_hud.py` in the Windows workflow and embedded in the exe at every icon size.

## What was new in build 10

* **Build 10.** The header is the owner's picture: the live feed counter on the left, `◆ Q U A N T   O F   R E H A N ◆` tracked and centred between its diamonds, the date and the 24 hour clock on the right as `WED 04 NOV 2026  09:41:41 PKT` in pale ink, and `PSX'S KMIALL INDEX` centred under it.
* **The dial is a dot matrix.** It is drawn with Braille dots, not quadrant blocks, on the panel's own background: there is no filled field at all. Seven concentric rings, an empty centre, three seams that turn, dashed rings that crawl and one bright glint sweeping around. Offline it is the same dial, dimmer and slower.
* **Taller share bars.** Every green and red share bar is five eighths of a cell tall instead of half, the closest step the terminal font has to the further fifth the owner asked for, and each one still meets the centre line of its stock's block.

## What was new in build 9

* **Build 9.** The HUD dial is now thick concentric rings cut by three rotating seams, and every ring turns in every state. Every search box says `Search for a KMIALL scrip`. The empty CUSTOM SCRIPS tile has no prompt. The BIG BUYING NOW heading is green and BIG SELLING NOW is red. Telemetry says `MARKET IS CLOSED`. The header title is tracked 10 percent wider; a console has one font size for the whole window, so a per-title point size is not available.
* **The owner's latest layout.** The letterspaced title is centred on the first line, in the theme's accent, bold. `PSX'S KMIALL INDEX` is on the next line and the rule closes the header. The live seconds counter is at the top left of every page, in bold. The greeting has its own tile, the footer carries navigation only, and the sound and alert flags live only in Settings. The old scrolling banner is gone. The green and red share bars meet the centre line of each stock's block, never its foot.
* **Five tabs, in your order:** 1 HOME, 2 ALERTS, 3 ORDER FLOW, 4 SCANNER, 5 SETTINGS. SEARCH is no longer a tab: it is the tile at the top of SCANNER, and the scanner carries on below it.
* **LATEST SIGNAL** has SYMBOL, ENTRY TIME, ENTRY PRICE, TAKE PROFIT and STOP LOSS, in those words. Entry time comes from the signal's own `Entry time` line. If the signal does not carry one it says `not reported` and nothing is made up.
* **Alerts say what you asked:** `PRL is getting big buying orders` and `PRL is getting big selling orders`, with the stock name only. Selling has its own tone, its own flag (Settings, or the S key) and its own board next to BIG BUYING NOW. The log marks each line BUY or SELL.
* **ORDER FLOW**, a new tab, reads the relay's `GET /orderflow` (and falls back to `GET /flow`, the same answer). See the section below.
* **Percent after a bar:** every share bar is followed by one space and then the percentage, so `98%` and `100%` sit the same distance from the bar.
* **HOME:** one blank line between the BUYING NOW line and the `Data from the broker's feed...` line.
* **The HUD dial (ORB).** The owner's animated ring, drawn as a dot matrix: a 2 by 4 grid of Braille dots in every cell, and only the dots that fall on a ring are lit, so the panel's own background is the only background. Seven concentric pale ice blue rings, an empty centre, three thick cut seams that turn through every ring, dashed rings crawling in opposite directions and one bright glint sweeping around. Offline the same dial is dimmer and slower. There is no sun, no wireframe, no radar sweep and no crosshair, because the GIF has none. It is on HOME only; the SCANNER gives its width to the search, the SECTORS tile and the list. The application icon is the owner's teal dial artwork, drawn by `tools/mkicon_hud.py` in the Windows workflow.

* **SECTORS** is on the SCANNER: the relay's `/sectors` groups in a drop down list. The wheel or the scrollbar moves through the groups. A click or ENTER opens the chosen group inside the SECTORS tile and lists every scrip of it that is in KMIALLSHR, with its price; the CUSTOM SCRIPS BY VOLUME tile below stays visible. That list scrolls and a click opens a scrip in the search tile. BACKSPACE, or ESC, brings every sector back without changing screen.

## Run it

1. Put `QuantOfRehan.exe` anywhere and double click it. On Windows 11 it opens in Windows Terminal.
2. Or run it from a terminal you already have open. It needs at least 80 x 26 characters. 120 x 30 or bigger shows the full HUD with the orb and telemetry panel.
3. Windows SmartScreen will say "Windows protected your PC" because the file is not code signed. Click More info, then Run anyway. Check the SHA-256 in `SHA256SUMS.txt` first if you want to be sure it is the file you were given.
4. First run on a new PC: `QuantOfRehan.exe -selftest` calls every relay endpoint once and prints what came back.
5. Press 5, move to **TEST THE ALERT** and press ENTER (or click it). You should see the banner, hear the tone and get the Windows notification. If one is missing, that is the part to look at.

## Screens

| Screen | Keys | What it shows |
|---|---|---|
| 1 HOME | 1, F1 | Greeting, ONLINE or OFFLINE pill with its sentence, W/L tile, LATEST SIGNAL (SYMBOL, ENTRY TIME, ENTRY PRICE, TAKE PROFIT, STOP LOSS, with the stock live), KSE100 INDEX & THE TOP 3 SCRIPS OF VOLUME with live prices, B, S & T and a chart each, who is being bought hardest right now |
| 2 ALERTS | 2, F2 | BIG BUYING NOW in green and BIG SELLING NOW in red, side by side (stacked when narrow), and the ALERT LOG with times, BUY or SELL and the sentence. LEFT and RIGHT pick the list the keys scroll |
| 3 ORDER FLOW | 3, F3 | Every KMIALL stock with price, change, bid, ask, B, S, U and T. `/` focuses the search box and filters the list as you type, ESC clears it. O (or a click on the heading chips) changes the order. UP, DOWN, PAGE UP, PAGE DOWN and the wheel scroll |
| 4 SCANNER | 4, F4 | The SEARCH tile, then the numbered SECTORS, then the scanner: PRICES RISING FAST, MORE BUYERS & LESS SELLERS and BIG BUYING & SELLING NOW (LIVE FLOW). The sector tile grows to show every group it can and the wheel scrolls the rest; every group and every scrip carries its number. The search box says `Search for a KMIALL scrip`. Type to search, UP and DOWN choose a match, ENTER opens it in the tile. A clicked sector lists its scrips in place; BACKSPACE brings all sectors back. With the box empty, LEFT and RIGHT change the sort |
| 5 SETTINGS | 5, F5 | Relay status, notifications, big buying flag, big selling flag, sound, big order size, test buying alert, test selling alert, six themes, version, request counter |

Other keys: TAB and SHIFT+TAB switch screens, R refresh now, D flip the signal card to raw text (Home), `[` and `]` mark roundness (Home), ESC clears the search or goes Home, Q quits, CTRL+C quits anywhere. The sound and alert flags are changed only on SETTINGS. On the Scanner letters and digits go into the search box; with the box empty a digit still jumps to that tab, and CTRL+C always quits. On ALERTS, ENTER plays a test and DEL clears the log.

## ORDER FLOW, and why every number can be trusted

The tab shows the relay's own numbers, written down as they arrived. Nothing is rounded, merged or filled in.

* **B and S are shown only when the relay measured them.** That is `split_method: quote_rule`: every increment of volume was sided by the wire's own bid and ask.
* **U is the relay's `unclassified_volume`**: volume the capture saw but could not side. It is written on its own as `U=` and is never added to B or S. For a measured stock B + S + U = T. If that ever fails for a stock, the row says CHECK and the summary counts it. It is never smoothed over.
* **An estimate is marked.** A stock whose split is only guessed from the day's range (`range_position`) shows `B~` and `S~` with a tilde, dimmed, and is left out of the totals at the top. A stock with no split shows only its total, and says `no split`.
* **The totals** at the top add up the measured stocks only: `MEASURED 6 stocks  B=..., S=..., U=... & T=...`. The line under it says how many stocks are estimated or unsplit and why they are not in it.
* **BID and ASK** are the relay's. A missing one shows `n/a`, never a zero. A stock whose frame is stale is dimmed and marked STALE.
* Wide windows (about 110 columns and up) show one table with a column each for B, S, U and T and a buy share bar. Narrower windows show two lines per stock: price, change, bid and ask, then `B=..., S=..., U=... & T=...`.
* **The ALERTS and ORDER FLOW can differ on purpose.** The flag engine counts executed volume once a second from `/quotes` (a tick rule). ORDER FLOW shows the relay's quote rule split. They are two measures of the same thing, so a stock can be flagged while its ORDER FLOW B and S look different. Trust ORDER FLOW for the day's split, and the flags for what is happening this minute.

## The big buying and big selling flags, and what they can and cannot see

Your relay's `/quotes` gives each stock's last price, the day's high and low and the day's running volume. A buy order that is resting and has not traded cannot be seen by this app or by any app reading only that feed. ORDER FLOW does use the relay's bid and ask for the split of what has traded.

What the flags measure is **executed trading**, once a second: the volume added since the last look is counted as buying if the price ticked up (or held after an uptick) and as selling if it ticked down. A stock is flagged for buying (selling is the mirror image) when, inside the last 60 seconds:

1. at least PKR 10 million was bought (choose 5M, 10M, 25M, 50M or 100M in Settings), and at least 4 times the stock's own average minute of the day, so a heavy stock does not flag all day;
2. buyers are at least 70% of the classified volume, over at least 2 separate seconds;
3. the price has not fallen through the window (for selling: has not risen).

Or a **block**: one second of trading worth at least twice the threshold.

A stock cannot flag again on the same side for 5 minutes unless it triples and a minute has passed. At most 6 alerts ring in one minute; more are written to the log quietly. Volume counted across a gap of more than 20 seconds, or after the day's volume went backwards, is thrown away, because nobody knows how it was split. Nothing is counted outside the session. Once the relay sends the KMIALL table (`/prices`), only those names can flag.

These are alerts that something big is trading, not trade signals and not predictions. Test them on a live day before you trust them, and tune the size to your market.

## Is it really live?

Short answer: the app asks the relay once a second and shows every answer the instant it arrives, so the app adds no delay. What it cannot do is make the broker's data newer than the broker sends it. Here is exactly what the light measures and what can make it say LAGGING.

* **What the number is.** The relay's `/quotes` answer carries every stock the feeder has pushed, each stamped with the time the broker frame was seen. The header light shows the age of the **freshest** stock in that answer, counting up each second. The Telemetry FEED line shows the same, and now the typical stock's age too.
* **What `LAGGING 23s` therefore means.** For 23 seconds no stock at all had a newer tick than that. A single quiet stock being old would not do it, because the light takes the freshest of all of them. So it is either a pause of the whole feed or a feed that arrives in bursts.
* **What your own audit says.** `reports/2026-11-03-eclear-order-flow.md` (section 1) measured the broker wire repeating each symbol about every 24 seconds (23.98 s), with 89.8% of rows duplicates and a median lag of 8.6 s for a new print. If the wire delivers in bursts of that period, the freshest tick ages 0, 1, 2 ... 23 and drops back to 0, and the light flips between LIVE and LAGGING on that beat. That would match what you saw. This is an inference from the audit, not something I could measure: the relay cannot be reached from my workspace.
* **Which of the three it is.** Run `QuantOfRehan.exe -feedwatch 180` while the market is trading. It asks `/quotes` once a second for 180 seconds (180 of the free 100,000 daily requests), prints one line per second and writes the same to `qor-feedwatch.txt` in the current folder. At the end it prints a verdict:
  * `WIRE`: the feed as a whole is live but each stock repeats only about every 24 s.
  * `BURSTS`: every stock arrives together on a steady beat and the light ages between bursts. This is the 24 second wire cycle showing through.
  * `STALL`: the whole feed went quiet once, for a stretch. That is upstream of this app, in the feeder or the relay.
  * `NETWORK`: answers fail or crawl between this PC and the relay.
  * `CLEAN`: stocks refresh every few seconds and nothing stalled.
  Send `qor-feedwatch.txt` to the coding agent. It tells it where to look.
* **What I changed on this side.** A `/quotes` read that has not answered in 4 seconds is dropped and the next goes out at once, each endpoint is polled on its own so a slow `/health` or `/signals` cannot hold up the prices, and the next read is timed from when the last one left. None of that can make data newer than the relay holds, and I do not claim it fixes a 23 second gap. If `-feedwatch` says BURSTS or WIRE, the data is as live as the broker's wire allows, and the only way to make it faster is a faster source than that wire. If it says STALL, the fix is in the feeder or relay, not here.

* **Build 6 finding about the 20 seconds.** Your report shows the broker wire repeating each stock about every 24 seconds, so the relay's snapshot is refreshed in bursts. Both apps then see the same age beat, 0 up to about 23 and back to 0, and the light follows it. The apps cannot change that. `scripts/feed_cadence_probe.py` (and `QoR-feed-lag-brief-2026-11-05.md`) measure it from a GitHub runner so the repo agent can find which hop adds the seconds (feeder cycle, Worker cache, KV). I tested the probe against a mock relay that bursts every 24 seconds. It has not touched the live relay. The age is always shown, never hidden.

**Pre-market, the Friday break and post-market.** The app scans from 08:55 to the post-market close, but the relay only stores a frame when its own tick falls inside a regular trading band (09:32 to 15:30 Monday to Thursday, 09:17 to 12:00 and 14:32 to 16:30 on Friday) plus five minutes of grace. That is an order you gave it on 2026-10-31 so the post-market tail cannot overwrite the day's regular numbers. The effect is that during the pre-open, the Friday break and the post-market, the numbers on screen are the last regular-session ticks and they do not move. That is how the relay is set up, not a fault of this app. The ring still turns during pre and post because the quant is online then.

**The W/L tile** shows what the relay reports in `/market` as `win_loss`, refreshed every 5 seconds. It cannot know more than the relay does.

## Requests and the free Cloudflare quota

The free tier allows 100,000 requests per UTC day (the counter resets at 05:00 Karachi). The pace: `/quotes` every second inside the scanning window, `/market` and `/signals` every 5 seconds, `/health` every 15 seconds, `/prices` every 2 seconds only while Scanner or Search is open, and every 30 seconds (never later than the next 08:55) outside the window or when the relay says it is not a trading day. A console left open for 24 hours uses about **44,700 requests** on the Home screen on a Monday to Thursday and **49,500** on a Friday. With Scanner or Search open all day that becomes about **59,200** and **65,600**. The phone app polls every second too while it is on screen, so leave the phone off the Home screen when the console is running if you are close to the cap. Telemetry shows today's count and turns amber at 80,000.

## Things that differ from the phone, on purpose

* The signal card also shows the symbol, and its stock live.
* A card from another day shows no prices, and says which date it carries.
* If the relay stops answering, the last reading stays on screen labelled `STALE 47s`.
* Telemetry, the orb, the charts, the alerts and the mouse are new.

## B and S on HOME and SCANNER

B and S there come from the relay's method: the share of the day's volume counted as buying is where the price sits inside the day's range. This app works that out on the live tick, so it moves every second, and it matched the relay's own figure for KEL on 2026-10-30. It is still an estimate and not order flow. The ORDER FLOW tab shows the measured split, and the flags use executed volume second by second.

## Command line flags (this run only, never saved)

```
-selftest        check every relay endpoint, then exit
-relay URL       use another relay (http or https only)
-poll MS         scan interval, 1000 to 60000
-cell WxH        size of one terminal cell in pixels for this run, for example 10x19 (the default is 9x20, a shape of 2.22; ] and [ keep your own choice)
-feedwatch N     record the live feed for N seconds (10 to 900), write qor-feedwatch.txt and say what the lag is
-theme N         theme 0 to 5 for this run
-no-notify       no Windows notifications this run
-no-sound        no tones this run
-halfblock       draw the ring with half blocks (only if the quadrant ring looks broken in your font)
-demo            invented demo market with a simulated feed and big buying bursts, no network
-version         print the version
```

## Files and network

* Settings: `%APPDATA%\QuantOfRehan\settings.json`. Older files are upgraded on first start (the radar roundness starts at 2.22). Nothing else is written anywhere, except `qor-feedwatch.txt` in the current folder when you run `-feedwatch`.
* Network: HTTPS GET requests to the relay only. No telemetry, no updater, no other host. No token or login of any kind, and no admin header.

## Security notes

* Everything the relay sends is untrusted text. Control characters and invisible bidi marks are replaced with a dot before they reach the terminal.
* Toast text is XML escaped and the script goes to PowerShell on standard input by full path, without `-EncodedCommand` or `-ExecutionPolicy Bypass`. It still appears in process logs as a hidden PowerShell start. If your EDR objects, turn notifications off. The banner and the tone keep working.
* The tone is the Windows `Beep` call, played on its own thread. The mouse uses the console's own mouse records, not a hook.
* The relay address must be http or https with a host.
* Built with `-trimpath` and no build id. Building twice gives the same SHA-256. The exe carries version information (Properties, Details) and the icon.

## Not verified here, please check on your PC

Built and tested on Linux, because there is no Windows machine in this workspace. Tested: thousands of screen renders across sizes, states, themes and screens; the flow detector with buying, selling, blocks, gaps and cooldowns; the scan window and the request budget; mouse decoding from the Windows record fields and from terminal reports; and the real binary run in a terminal emulator against a mock relay that bursts one stock. The Windows only parts compile and pass `go vet` but have never run on Windows: console mode, key and **mouse input**, the **Beep tone**, the toast, opening the browser, and how the **icon** looks in Explorer and the taskbar, and the ring's roundness on your screen (it assumes a 9 by 20 pixel cell, 2.22). Windows Terminal tabs show the profile's icon, not the exe's. The ring needs 24 bit colour and the quadrant block characters (U+2596 to U+259F), which Windows Terminal draws itself. If the ring ever looks broken or has gaps in your font, start the app with `-halfblock` and it draws the plainer half block ring instead, and tell me. The first build's diamond `◆` is used again on purpose; if your font cuts it off, tell me and I will swap only that glyph.

Also not checked from here: whether Cloudflare accepts this program's User-Agent from your network. `-selftest` tells you in a second.

## Build and test from source

Go 1.24 or newer, standard library only.

```
go test ./...
set GOOS=windows& set GOARCH=amd64& go build -trimpath -ldflags "-s -w -buildid=" -o QuantOfRehan.exe .
```

`rsrc_windows_amd64.syso` holds the icon and version info. `python tools/mkicon_hud.py assets/QuantOfRehan.ico assets/icon-1024.png` draws the blue HUD dial icon (needs Pillow) and `python tools/mksyso.py assets/QuantOfRehan.ico rsrc_windows_amd64.syso 4.0.16.13` writes the resource file. The Windows workflow runs both before the tests and the build.

Source map: `signaltext.go` and `rank.go` port the app's signal and ranking rules, `relay.go` is the relay client, `session.go` is the PSX session law (pre, trading, break and post times) and the scan window, `flow.go` is the big buying detector, `live.go` holds flashes, charts, feed health and the mouse, `screens*.go`, `orb.go` (the ring), `orderflow_data.go` and `screens_orderflow.go` (the ORDER FLOW tab), `feedstats.go` and `feedwatch.go` (feed ages and the diagnostic) and `spark.go` draw the HUD, `term_windows.go` is the Windows console layer.

## Brief for the repo agent: SECTORS

If you want the SECTORS tab, the relay needs one more answer: `GET /sectors`, returning for each KMIALL symbol its sector as the exchange publishes it, with the source and the date it was read. The desktop tab is then a grouped list. Rules for the agent: read the sector from an official or licensed source only, write down which one, never infer a sector from a company name, and return `unknown` for a symbol the source does not cover instead of guessing.
