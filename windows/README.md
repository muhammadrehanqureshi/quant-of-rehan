# Quant of Rehan for Windows (console edition), build 32

A Windows 11 console version of the Quant of Rehan Android app, matching app **4.0.16**, in the look of the first build.
One file of about 7 MB, no installer, no runtime, no dependencies. Around 2% of one CPU core and 13 MB of memory while it animates.

## What is new in build 32

* **Build 32.** The quant mark is the GIF's own picture at the panel's dot resolution: `tools/mkorb.py` samples every frame of `windows/assets/orb-online-green-refined.gif` onto a 152 by 152 dot raster, zlib compresses the whole set into `windows/orbpattern.go`, and the console draws the mark with one console dot per grid point, every point taking the brightest cell of the GIF it covers and its shade from five concentric bands measured from where the ink begins, so the very inside circle is always the darker shade and the rings alternate outward from it, the lighter step lightened so the two read apart while the darker one is untouched, and the whole mark ten percent under the tile; the greens are darkened versions of the GIF's measured `#35a373` and `#6cf3b3`, and outside the market window the mark is the owner's red GIF itself, its dots, its own two reds and its own ring shading copied from that file rather than recoloured, and since that file holds one frame only, the red mark turns a full circle clockwise across the green GIF's own 160 frames, the same dots in the same two shades all the way round. Before sampling, the artwork is cropped to its own square bounding box, because the GIF ships the dial inside a frame that is not square around it and the mark therefore drew wider than it was tall. The left column widens with the window, from 40 cells to 60, so a wide console carries more dots; at 120 x 30 the panel carries 62 by 56 of them. The TELEMETRY flow row is `FLOW` and prints buying and selling as two separate figures, with the unclear remainder beside them as `U` only when there is any: the sides are never added together and U is never folded into either of them. The SCAN row follows the market's own day and clock, naming the weekend, a closed trading day (`MARKET IS CLOSED TODAY`), the 08:55 start and the finish. The KSE100 tile's idle line now reads `Quant is sleeping till the next market day.` The SETTINGS page names the version `2.8` alone, with no Windows build number and no ported app version beside it.

## What is new in build 31

* **Build 31.** The quant mark is the owner's GIF itself again, frame for frame. Build 30 sampled a single frame and drew its own turn and glint; this build embeds every frame of `windows/assets/orb-online-green-refined.gif` on the GIF's own 55 by 50 dot grid and plays each frame at its own declared delay, so the rotation on screen is the source's rotation. The palette is the GIF's two measured greens, not the four invented shades of builds 28 and 29, and a PSX holiday paints the same matrix in two reds all day: the relay's `TradingDay` and the holiday law in `windows/session.go` both close the green window, so 9 November reads red on a Monday morning. `python tools/mkorb.py` regenerates `windows/orbpattern.go` and `orb-preview.png` in the Windows workflow before the tests, so the dots, both shades and the timing are the GIF's own pixels rather than a drawing of them.

## What is new in build 30

* **Build 30.** The console now stops itself at 90,000 relay requests a day. Cloudflare's free tier allows 100,000 and then refuses to answer, so the app keeps 10,000 in reserve for the phone and the relay instead of discovering that limit as an outage: no request leaves after the cap, the last answer stays on screen, telemetry shows `paused until 05:00 PKT` in red, and the count resets at 00:00 UTC. The Settings screen states the stop beside the day's count.

## What is new in build 29

* **Build 29.** The quant mark now turns and carries a moving highlight; its four GIF brightness levels are painted in four green shades from 08:55 to 16:00 Monday to Thursday and 08:55 to 17:00 on Friday, and in four red shades outside those windows. The mark is 10 percent larger than build 28. The index line is `PSX'S KMIALL INDEX` in the build's own font again. The footer actions read `DETAILS`, `NEXT`, `REFRESH` and `QUIT`. The closed status says `Market is closed and the quant is sleeping now.` Telemetry's `NEXT` no longer carries the word `Scanner`; the alerts heading is `ALERTS LOG`; the ORDER FLOW field stands alone without the word `SEARCH` before it; and the `T` volume is blue beside the green buy, red sell and yellow unclassified values. The last stored session now includes the ORDER FLOW table, so reopening the window restores it with the card, scanner, signal and sectors.

## What is new in build 28

* **Build 28.** The quant mark is the owner's GIF itself, not a drawing of it: the console draws the 55 by 50 dot matrix sampled from `windows/assets/orb-online-green-refined.gif`, dot for dot, with its own four brightness levels and the palette switching between the refined green and the owner's red. The SECTORS tile now keeps one blank row between its search field and the list, so the first group no longer touches the box.

## What is new in build 27

* **Build 27.** The index line is back in the owner's small capitals (`ᴘꜱx'ꜱ ᴋᴍɪᴀʟʟ ɪɴᴅᴇx`), a size below the title, the order of 2026-11-08 after build 25 set it in the plain font. The SECTORS tile opens with its filled field alone: the inline `SEARCH` word is gone, and the field stands at the tile's left edge. The quant mark is the refined dial of `windows/assets/orb-online-green-refined.gif` in the market's own colour: green through the pre-market, the trading session and the post-market, red at every other hour and day, including a break, a halt and a weekend.

## What is new in builds 25 and 26

* **Build 26.** The window keeps the last market day's answers on disk, in `%AppData%\QuantOfRehan\last-session.json`, and starts from them: the card, the scanner's table, the signal and the sector groups are on screen even when the exchange is shut or the relay answers with an empty feed. A sentence under the status pill names the day (`Showing the last stored session, 06 Nov 2026`) whenever the data is not today's. A relay answer that carries no rows never erases the stored table, and prices and sectors are now read even when the scanner is not open, so the file always has the whole session.
* **Build 25.** The quant mark is the owner's refined green dial at every hour and on every day, the palette of `windows/assets/orb-online-green-refined.gif`; the red palette and its 08:55 to 17:00 rule are withdrawn. The CHARTS tab is removed at the owner's order of 2026-11-08: charts belong to the Charts of Rehan project now, so the desktop carries HOME, ALERTS, ORDER FLOW, SCANNER and SETTINGS only, and `3` to `5` (or F3 to F5) are the tabs after ALERTS. The index line under the title keeps the build's own font: build 23's small-capital letterforms are gone, and the line is set unbolded under the title because a Windows console draws one glyph size per window.

## What is new in build 24

* **Build 24.** The ORB is green from 08:55 to 17:00 Karachi on a market day and red at every other time, the owner's order of 2026-11-08. The PSX week is Monday to Friday; when the relay's trading-day flag names today, a holiday is red as well. The dial still turns in every state; only its ink changes. The rest of build 23 is unchanged.

## What is new in build 23

* **Build 23.** The index line is set in Unicode small capitals, the same eighteen cells and the same words a size below the title; a Windows console has one font size for the whole window, so this is the per-line size change the owner asked for on 2026-11-08. The CHARTS tab's selector tile is titled `SCRIPS`. The chart opens on `1D` and draws the owner's full year, 08 Nov 2025 to 08 Nov 2026, from the local `data/eod_history.csv.gz` (each session's own OHLCV) when that file is beside the program; the footer names the first and last bar it actually read, and the relay remains the fallback, with its honest note, when the file or the symbol is absent. The ORB is the owner's new green dot-matrix GIF, replacing build 22's red palette; `windows/assets/orb-online-green-refined.gif` is the reference the dial follows, and the red palette is one commit back if he prefers it.

## What is new in build 22

* **Build 22.** The line under the title is `PSX'S KMIALL INDEX` again, at the owner's order of 2026-11-07; build 18's shortened line is withdrawn. The CHARTS list now comes from the relay's `/sectors` KMIALLSHR membership, so every scrip is listed even when the market is closed and `/prices` is empty. A selected scrip says the market is closed, gives the next open time, and repeats the relay's own reason for an empty chart instead of showing a blank panel. The icon and every other screen are build 21's.

## What is new in build 21

* **Build 21.** The CHARTS tab is the owner's chart system: KSE100, KMIALLSHR and every KMIALLSHR scrip, each on ten frames (`1s`, `5s`, `1m`, `5m`, `15m`, `30m`, `1h`, `1D`, `1W`, `1M`) from the relay's new `GET /bars`. The frames are chips above the candles: click one, or press `[` and `]`. A stored frame asks for the newest bars in a rolling 365 day window and the forming minute ticks with the live price; the answer's own store size is written in the footer, so a one minute chart says 45 days and a daily chart says 365. The two second frames are built from the desk's own live samples and are labelled `live samples`, because the broker feed observes a symbol every 30 to 90 seconds and no stored second bar exists. The list starts with the two indices. KSE100 rides the broker's own index frame, so its candles are real. KMIALLSHR has no published index level in the feed or on the exchange's constituent page, so its panel says so and draws nothing rather than inventing a level. The icon, the header and every other tab are build 20's.

## What is new in build 20

* **Build 20.** The application icon is the owner's own picture again, and it is pinned. `windows/assets/icon-source.png` is byte for byte `logo2.png`, and a test fails if its SHA-256 changes, so no build can silently replace, recolour or redraw it. Build 19's red dial is withdrawn. The line at the top centre is `PSX'S KMIALL`, with no `INDEX`, and a test pins that too. Everything else is build 19's.

## What is new in build 19

* **Build 19.** The application icon is the HUD's own red dial now, instead of the older teal picture. Build 18's icon step still preferred `assets/icon-source.png` whenever that file existed, so the red palette never reached the icon Explorer draws. That override is retired and the dial is always drawn, so the icon matches the ORB. The title line, the tab order and the rest of the HUD are unchanged from build 18.

## What is new in build 18

* **Build 18.** The index line is `PSX'S KMIALL`, the owner's own spelling, at 12 cells instead of 15: a fifth narrower. A console has one fixed font size, so a shorter line is the only way to draw it smaller, and INDEX stepped out to buy the width. CHARTS moved to tab 3 and the tabs after it followed: `3` or F3 is CHARTS, `4` or F4 is ORDER FLOW, `5` or F5 is SCANNER, `6` or F6 is SETTINGS.

## What is new in build 17

* **Build 17.** The ORB is a saturated, brighter red: its lighter shade is `255,64,64` instead of the washed out `255,178,178`, and its core is `255,4,4`. The header diamonds sit one space from the words, and the index line is 16 cells instead of 18, the nearest whole cell to the ten percent smaller the owner asked for. Every buy versus sell bar is still 17 cells wide and still ten tabs, but a tab now fills its cells, so the bar has exactly ten boxes and each one is about twice as long. The SECTORS search box sits below the title, says `Search for a sector`, and the scrip count at the right of each sector is gone. The ORDER FLOW search is the same filled field as SCANNER's.
* **CHARTS, a sixth tab.** Every KMIALL stock is in a searchable list on the left; the chosen stock's live intraday chart is on the right, built from the relay's `GET /history` one minute bars. A whole session is grouped into candles that fit the width, the live price is a dotted line across them, and the last bar's O, H, L, C and volume are written above. A day the relay has no bars for says so, and no bar is invented. In demo mode the bars are invented and labelled `demo bars`. `5` or F5 opens the tab, `6` or F6 is Settings.

## What was new in build 16

* **Build 16.** The ORB is red. The header title is 20 cells wide instead of 18, 11.1 percent wider: the diamonds sit one extra space from the words, the nearest whole cell to the ten percent the owner asked for. The glyph height stays the console's fixed font. Every buy versus sell bar is back to its previous 17-cell span, still split into ten ten-percent tabs. The ORDER FLOW bar column is called `BARS`, right-aligned like the numeric columns. The application icon is the owner's exact `logo2.png`, saved as `assets/icon-source.png`; `mkicon_hud.py` crops it square, gives it transparent rounded corners and embeds it in the exe.

## What was new in build 15

* **Build 15.** D and R are green in the footer, Q is red, and every coloured footer key is bold. The five tab numbers are bold green as well. The ORB rings are a more vivid green. The title is still bold in the theme's accent, at the console's one fixed size; a 20 percent per-line font size is not a cell the console can draw.
* **The icon source.** Build 15 still used the drawn fallback because the owner's rounded picture was not yet a file in the repository.

## What was new in build 14

* **Build 14.** The header title is back in the theme's accent ink. The footer keys are coloured: the five tab numbers and TAB green, ESC yellow, CTRL+C red. Telemetry now says `Scanner Tue 10 Nov, 08:55` for the next OPEN, because 08:55 is when the scanner goes live; a CLOSE keeps its relay time. Every share bar is ten tabs, one per ten percent, so 100% is easy to read, and the percentage keeps its old place.
* **The SECTORS search box.** The SECTORS tile has its own field now. Click it, or press `/` while the top scrip search is empty, and type a sector name or a scrip. The groups filter as you type. ENTER opens the first match; in an open sector the same box filters its scrips. ESC clears the box and BACKSPACE edits it. The CUSTOM SCRIPS tile stays on screen.
* **The title size.** A Windows console uses one font size for the whole window, so a literal ten percent on only the title is not a cell that can be drawn. The title is bold and in the accent again, at the console's fixed size, with the owner's ordinary word spacing.
* **The icon source.** `tools/mkicon_hud.py` now uses `assets/icon-source.png` automatically when that file exists: the picture is cropped to a square, given the same transparent rounded corners and embedded at every icon size. Without that file it keeps the drawn dial as a fallback. The exact picture is not part of this change because the chat upload is not a file in the repository; save it at that path to make the next Windows build carry it.

## What was new in build 13

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
* **The HUD dial (ORB).** The owner's animated ring, drawn as a dot matrix: a 2 by 4 grid of Braille dots in every cell, and only the dots that fall on a ring are lit, so the panel's own background is the only background. Seven concentric rings, green from the pre-market through the post-market and red at every other hour, an empty centre, three thick cut seams that turn through every ring, dashed rings crawling in opposite directions and one bright glint sweeping around. Outside the session the same dial is red. There is no sun, no wireframe, no radar sweep and no crosshair, because the GIF has none. The reference is `windows/assets/orb-online-green-refined.gif`. It is on HOME only; the SCANNER gives its width to the search, the SECTORS tile and the list. The application icon is the owner's teal dial artwork, drawn by `tools/mkicon_hud.py` in the Windows workflow.

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
| 2 ALERTS | 2, F2 | BIG BUYING NOW in green and BIG SELLING NOW in red, side by side (stacked when narrow), and the ALERT LOG with times, BUY or SELL and the sentence. LEFT and RIGHT pick the list the keys scroll | |
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

**Pre-market and post-market.** The app scans from 08:55 to the post-market close, and the relay keeps a frame when its own tick falls inside a regular trading band (09:32 to 15:30 Monday to Thursday, 09:17 to 12:00 and 14:32 to 16:30 on Friday) plus five minutes of grace, inside the exchange's pre-open auction (09:15 to 09:30 Monday to Thursday, 09:00 to 09:15 and 14:15 to 14:30 on Friday) or inside the published Post-Close Session (15:35 to 15:50 Monday to Thursday, 16:35 to 16:50 on Friday). That is what you asked for on 2026-11-09: the broker's feed carries pre and post volume, so the day's buying and selling include it and the totals keep moving through both. A tick after the post-close window ends is still refused, which is the 2026-10-31 order that keeps an after-hours tail out of the day's numbers. The ring turns through pre and post because the quant is online then.

**The W/L tile** shows what the relay reports in `/market` as `win_loss`, refreshed every 5 seconds. It cannot know more than the relay does.

## Requests and the free Cloudflare quota

The free tier allows 100,000 requests per UTC day (the counter resets at 05:00 Karachi). The pace: `/quotes` every second inside the scanning window, `/market` and `/signals` every 5 seconds, `/health` every 15 seconds, `/prices` every 2 seconds only while Scanner or Search is open, and every 30 seconds (never later than the next 08:55) outside the window or when the relay says it is not a trading day. A console left open for 24 hours uses about **44,700 requests** on the Home screen on a Monday to Thursday and **49,500** on a Friday. With Scanner or Search open all day that becomes about **59,200** and **65,600**. The phone app polls every second too while it is on screen, so leave the phone off the Home screen when the console is running if you are close to the cap. Telemetry shows today's count and turns amber at 80,000.

The app stops itself at **90,000**. That is a hard stop, not a warning: once the count reaches it the app sends nothing at all until the counter resets at 05:00 PKT, keeps the last answer on screen and shows the cap in telemetry and in Settings. The remaining 10,000 of the day belong to the phone app and the relay's own work, so the allowance is never exhausted.

## Things that differ from the phone, on purpose

* The signal card also shows the symbol, and its stock live.
* A card from another day shows no prices, and says which date it carries.
* If the relay stops answering, the last reading stays on screen labelled `STALE 47s`.
* Telemetry, the orb, the alerts and the mouse are new.

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

Source map: `signaltext.go` and `rank.go` port the app's signal and ranking rules, `relay.go` is the relay client, `session.go` is the PSX session law (pre, trading, break and post times) and the scan window, `flow.go` is the big buying detector, `live.go` holds flashes, feed health and the mouse, `screens*.go`, `orb.go` (the ring), `orderflow_data.go` and `screens_orderflow.go` (the ORDER FLOW tab), `feedstats.go` and `feedwatch.go` (feed ages and the diagnostic) and `spark.go` draw the HUD, `term_windows.go` is the Windows console layer.

## Brief for the repo agent: SECTORS

If you want the SECTORS tab, the relay needs one more answer: `GET /sectors`, returning for each KMIALL symbol its sector as the exchange publishes it, with the source and the date it was read. The desktop tab is then a grouped list. Rules for the agent: read the sector from an official or licensed source only, write down which one, never infer a sector from a company name, and return `unknown` for a symbol the source does not cover instead of guessing.
