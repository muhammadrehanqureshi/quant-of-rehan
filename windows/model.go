package main

import "time"

// appVersion mirrors the Android app this build is ported from.
const appVersion = "4.0.21"

// hudBuild is the build number of this Windows HUD port. Owner order
// 2026-11-10: the bar and size build is 3.0.1, the toast encoding fix that
// follows it is 3.0.2, the return to build 21's bars is 3.0.3, the short
// centred bar that stays inside its own box is 3.0.4, the ten box flat bar
// with the price before it on the KSE100 tile is 3.0.5, the longer bar with the
// right aligned tile row is 3.0.6, the source orb, the new close times and the
// BUY= FLOW row are 3.0.7, the ten box bar, the left aligned ORDER FLOW
// headings and the bigger orb are 3.0.8, the signal SCORE, the longer box
// pitch and the aligned leader block are 3.0.9, the full dot face, the
// ten percent slower turn, the unbroken bars and MARKET OPENING are 3.0.38,
// the 3D orb return, the continuous centred bar rule and the KSE100 breadth
// thresholds are 3.2.3, TOP PERFORMERS, the symmetrical frame and the half
// speed globe are 3.2.4, the matching left tiles, the five eighths bars and the
// unsigned NET DELTA are 3.2.5, the separate SEARCH and SECTORS tiles, the blue
// cursors, the pre and post market times and the half block bars are 3.2.6, and
// the centred bars, the day's market times, the single diamond and the denser
// globe are 3.2.7, the lit globe and the taller bold bars are 3.2.8, the right
// aligned telemetry, the B/S/U FLOW row and the ALERTS LOG search are 3.2.9,
// and the restored 3.2.6 globe, the centred rectangle bars and the day's FLOW
// sides are 3.3.0, the seamless full-cell bars, the two scanner sorts, the
// VERSION before RELAY order and the leader PKR label are 3.3.1, the centred
// heavy-rule bars and the even 900 dot globe are 3.3.2, the KSE100 style
// CUSTOM SCRIPS OF VOLUME with its six sorts, the fifteen second LIVE window,
// the clock on the index line, the 15:49 and 16:49 close and the 100,000
// request tile are 3.3.3, the ten percent taller bold bar, the one column sort
// list and the trimmed RELAY and REQUESTS rows are 3.3.4, and the clock above
// the index line and the traded volume gate on TOP PERFORMERS are 3.3.5, and
// the one bar on every page, green for the buyers' share and red for the
// sellers', with the NET DELTA after it and in a column of its own on ORDER
// FLOW, is 3.3.6, and the withdrawn / searches hint, the left aligned NET
// DELTA and the one live price and change pair on ORDER FLOW are 3.3.7, and
// the one measured pair behind every bar, the 09:00 scan start, the fixed
// change column on the scanner and the withdrawn ESC clears note are 3.3.8,
// and the three withdrawn hints, the withdrawn scrip count and the capital feed
// note are 3.3.9, the centred rectangle bars are 3.4.0, and the diamond in the
// search list, the withdrawn search prompt and the full block bars are 3.4.1,
// and the rectangle bars, the UNCLEAR column and the one gutter are 3.4.2, and
// the seamless bars and the one second index are 3.4.3, and the slash search
// key on every page that has a search box is 3.4.4, the two step-back hints of
// 2026-11-12 are 3.4.5, the owner's new icon picture is 3.4.6, the themes
// column, the home footer and the board floor are 3.4.7, and the facts column
// with a NET DELTA on every bar is 3.4.8, and the leader bar back on the
// KSE100 tile with one price column is 3.4.9, and the three PRICE ALERT slots
// with their own chime on the ALERTS page and the C calculator on the SCANNER
// page are 3.5.0, and the 08:55 scan start, the Friday 09:00 market opening,
// the scanner's sector percentages, the ORDER FLOW NET DELTA order and the
// KSE100 layout with an unsigned NET DELTA are 3.5.1, and the bar split on its
// own cells, the SCRIP label, the calculator tile below CUSTOM SCRIPS and the
// six sector rows are 3.5.2, and the protected ALERTS LOG, the right hand sector
// percentages, the numbered sort menu, the calculator hints and the KSE100
// column repair are 3.5.3, and the relay's live status, the search tile's one
// volume line, the arrowed sector percentages, the equal ALERTS boards and the
// red break orb are 3.5.4, and the green P footer key, the quiet ALERTS LOG
// with its blank row, the uncut log and the full ORDER FLOW U sentence are
// 3.5.5, and the 20 percent shorter search boxes with their centred hints, the
// C calculator key and the A price-alert key are 3.5.6, and the ORDER FLOW
// NET DELTA % column and sort are 3.5.7, and the weekend telemetry, the left
// fitted search hints, the quieter PRICE ALERTS form and the KSE100 inset are
// 3.5.8, and the padded search hints, the unbracketed alert sentence and the
// full NET DELTA label are 3.5.9, the stored-session sentence, the KSE100
// right shift and its broker-feed footer are 3.5.10, and the KSE100 value
// group's two cell shift, the blank rows around every search box and the full
// arrow-key instruction are 3.5.11, and the W/L record on LATEST SIGNAL, the
// KSE100 bar on the percentage row without NET DELTA, the quiet ALERTS and
// calculator frames, the bare PSX'S KMIALL INDEX line and the CUSTOM SCRIPS
// hint without its full stop are 3.6.2, and the SECTORS UP and DOWN selection,
// the CUSTOM SCRIPS LEFT and RIGHT selection, ENTER on either tile and the one
// fixed B, S, U and T column set are 3.6.3. Build 115 is 3.7.0, the
// share-based big-order alert and the calculator and volume-column layout.
// Build 116 is 3.7.1, the feed light that follows the quotes feed alone.
// Build 117 is 3.7.2, the session words, the KSE100 footer and the split
// board and alert floors. Build 118 is 3.7.3, the full-market quote answer
// that no longer freezes the FEED row. Build 119 is 3.7.4, the quiet empty
// boards and the KSE100 price and U alignment. Build 120 is 3.7.5, the scan
// clock and the quote watchdog that keep pre, live and post moving. Build 121
// is 3.7.6, the priced ALERT boards, the owner's alert sentence and the wider
// ORDER FLOW percentage. Build 122 is 3.7.7, the aligned B/S/U/T fields, the
// fixed sector arrow column and the equal ALERT boards. Build 123 is 3.7.8,
// the feed that says LAGGING when its values stand still, the one diamond in
// CUSTOM SCRIPS and the two cell gutter after every B, S, U and T value.
// Build 124 is 3.7.9, the calculator's six cell price-to-quantity gap, the
// owner's B/S/U/T spacing, the UNCLEAR order chip, the shortened REQ row and
// the quantity-based large-print footer. Build 125 is 3.8.0, the PRICE
// DIFFERENCE tile in front of POSITION CALCULATOR, the halved SCANNER row, the
// one blank row between ALERTS LOG entries and the single shade red orb.
// Build 126 is 3.8.1, the owner's new QoR.png as the application icon.
// Build 127 is 3.8.2, the two second big-order flash, consecutive ALERTS LOG
// rows with the current day move, the 08:00 stored-session clear, the
// calculator pair's new order and gutter, D for PRICE DIFFERENCE and the new
// FIRST PRICE and SECOND PRICE fields. Build 128 is 3.8.3, the three second
// live poll, the slower metadata tiles, and a LIVE window that covers one
// broker cycle instead of expiring after five seconds. Build 129 is 3.8.4, the
// five space calculator gaps, the PKR dash order, the full PRICE DIFFERENCE
// label, one blank row above the calculator pair, the nine digit KSE100 volume
// fields, and the pre-open ORDER FLOW rows that keep every KMIALL scrip listed.
// Build 130 is 3.8.5, the one dash on an empty PRICE DIFFERENCE, the KSE100
// values written immediately after their '=' with the padding after them, and
// the comma after S and U while their labels stay on the same cells. Build 131
// is 3.8.6, the SEARCH and SECTORS boxes without the row above them, the three
// scrips and six sorts at the owner's short window, the KSE100 B/S/U/T shape on
// every list, and the stored session cleared only from 08:00 to 08:55. Build
// 132 is 3.8.7, the comma after B and S in their value ink and the ALERTS LOG
// search box without the row above it. Build 133 is 3.8.8, the stored session
// cleared at 08:55 on every market day, including on a window opened late.
// Build 134 is 3.8.9, the ALERTS LOG beside the scanner's SEARCH tile, the
// calculator's PKR only on a total, and the unsigned difference in its
// direction ink. Build 135 is 3.8.10, the four second big-order banner and the
// soft comma after B, S and U on every list. Build 136 is 3.8.11, the U comma
// withdrawn because the ampersand already separates U from T, the SEARCH tile
// without its key instruction, the right aligned SECTORS percentages, the
// CUSTOM SCRIPS scrips on the right of their menu, and the five space gap
// before the ALERTS LOG price group. Build 137 is 3.8.12, the ALERTS LOG
// search box restored, the SEARCH tile's T, BARS, NET DELTA and NET DELTA %
// ledger, the persisted REQ total and the five second LIVE window. Build 138
// is 3.8.13, the side-capture correction: the previous book decides an
// increment, and the boards use the relay's own measured pair. Build 139 is
// 3.8.14, the one second live poll and the exact timing on the SCANNING tile:
// the relay is read every second, and the broker refreshes one stock every
// 23.98 seconds. Build 140 is 3.8.15, the ALERTS and SCANNER search ledgers
// split by page, the S key on the ALERTS SEARCH tile, the five space sector
// price gap, the scrip spacing on CUSTOM SCRIPS and the KSE100 bar above the
// current price. Build 141 is 3.8.16, the exact SCANNING sentence, the right
// side open-sector price, the aligned down percentage, the CUSTOM SCRIPS quote
// on the T column, the right side ALERTS LOG price and percentage, HIGH & LOW,
// the left SEARCH bar and EVERY SECOND on TELEMETRY and KSE100. Build 142 is
// 3.8.17, the post-market phase starting at 15:32 Monday to Thursday and 16:32
// on Friday instead of the trading close two minutes earlier. Build 143 is
// 3.8.18, one quote group on every tile: a spaced NET DELTA, the word at before
// the ALERTS LOG price, the KSE100 NET DELTA in front of the percentage, the
// SECTORS and CUSTOM SCRIPS price columns, and the standard heading diamond on
// both big-order boards. Build 144 is 3.8.19, the SCANNER SEARCH tile joining
// NET DELTA and NET DELTA % with an ampersand and exactly one cell after the
// label, and the KSE100 quote keeping both figures on a tile too narrow to
// hold them beside the price. Build 145 is 3.8.20, the KSE100 quote group on
// the tile's right edge, both SEARCH tiles reading NET DELTA= and NET DELTA %=
// with an ampersand between them, five scrips in an open SECTORS list with the
// rest a scroll away, the diamond back on the SECTORS heading, the LATEST
// SIGNAL score re-scored on every scan, and MARKET BREADTH's bullish mark at
// +1000 points. Build 148 is 3.8.23, the SECTORS tile opening the group the
// arrows marked instead of the row under a resting pointer, its list wrapping
// from the last sector to the first, and the PRICE ALERTS number and EMPTY word
// standing on the BIG BUYING NOW board's own cells. Build 149 is 3.8.24, both
// ALERTS boards holding PKR on one column with the price right aligned in its
// own field, the CUSTOM SCRIPS quote group standing on the tile's own right
// edge, and ORDER FLOW ending PRICE, CHANGE, HIGH, LOW, BID and ASK on their
// column's right edge so the two cells a short figure left behind are gone.
// Build 150 is 3.8.25, ORDER FLOW without its serial column so the table
// starts on SYMBOL, its five price fields measured at eight cells so SYMBOL to
// PRICE, CHANGE to HIGH, HIGH to LOW, LOW to BID and BID to ASK each stand one
// cell closer, the closed SECTORS tile's overall percentage one cell further
// right, and MARKET BREADTH reading BULLISH at or over +1000 points and BEARISH
// at or under -1 point, with FLAT between them.
// Build 151 is 3.8.26, the Friday break's banner and notification naming the
// 14:15 restart, and the red globe's one shade from its middle to its edge.
// Build 152 is 3.8.27, the day's three calls each scored above 80 out of 100,
// and the executable's file version stamped from the HUD build instead of the
// fixed 3.8.20.0 every earlier build carried.
// Build 153 is 3.8.28, ORDER FLOW's "#" numbering back on the panel's first
// cell with the SYMBOL to PRICE gap two cells tighter, the CUSTOM SCRIPS NET
// DELTA right aligned so every M ends on one cell, the green orb in one shade
// like the red one, and the FEED row reading NO FEED when the relay answers
// without any quotes table.
// Build 154 is 3.8.29, NAVY BLUE & WHITE deleted so the palette is the phone's
// own three, ORDER FLOW's numbers on the "#" cell with a full stop after each,
// the CUSTOM SCRIPS NET DELTA in a field only as wide as its widest figure and
// two cells inside the tile, and the STALE words dropped from ORDER FLOW's
// rows.
// Build 155 is 3.8.30, the console window wearing the build's own icon on the
// title bar, in Alt+Tab and on the taskbar while it runs, with the icons it had
// put back on exit.
// Build 147 is 3.8.22, the KSE100 quote group on the line that
// carries T at the owner's own window with its bar above the price, the volumes
// giving up their thousands commas there rather than any digit, and ORDER FLOW
// keeping its BARS, NET DELTA and NET DELTA % columns with one cell between the
// columns. Build 146 is 3.8.21, HIGH and LOW on ORDER FLOW after CHANGE,
// four scrips in an open SECTORS list, the CUSTOM SCRIPS scrip on two rows with
// its quote against the tile's right edge, the KSE100 quote group on the volume
// line with NET DELTA last and its bar above the price, the PRICE ALERTS boxes
// naming the scrip and the price with the scrip box listing every match, no
// broker refresh line on the BUILD VERSION & RELAY tile, the boards putting the
// percentage beside the price, and an ALERTS LOG that keeps the price and the
// percentage it was written with. Build 158 is 3.8.33, the password gate the
// owner asked for and the green globe in one shade of green. Build 159 is
// 3.8.35, the LATEST SIGNAL tile's three calls side by side with six cells
// between them, and the opening range law's calls. Build 161 is 3.8.36, the
// ALERTS boards' price, percentage, quantity and bar stepped left as one group
// with NET DELTA and its figure right after the bar.
//
// 3.8.34, the gate drawn as one of the build's own tiles with its blinking box
// cursor, and the KSE100 leaders' U= and & T= back on shared columns.
//
// Build 172 is 4.3.4, the owner's 2026-11-25 orders: the yellow diamond the
// flagged rows carried is gone from BIG BUYING NOW and BIG SELLING NOW, each
// row's NET DELTA is the reading at the moment that transaction printed
// instead of the live pair restamped onto it, the PRICE ALERTS tile wears the
// boards' own alternating shades, a price alert reads "<scrip> hit its price
// alert of PKR <price>", an opened SECTORS tile keeps one blank line under its
// search box with the scrips one cell further right, and T's figure is bold
// like B's and S's.
//
// Build 171 is 4.3.3, the owner's 2026-11-25 next order: the post-market
// window (15:32 to 15:49 Monday to Thursday, 16:32 to 16:49 on Friday) is a
// scanning window whose post-close session prints real trades, so the HUD's
// detector counts them and the boards, the KSE100 leaders and the ALERTS LOG
// move after the close instead of holding the 15:30 rows.
//
// Build 170 is 4.3.2, the owner's 2026-11-25 order: the percentage and the PKR
// label step one cell left on BIG BUYING NOW and BIG SELLING NOW while each
// price keeps its own field, the ALERTS LOG opens one more space between the
// scrip and were bought or were sold and holds one width for the verb so at
// starts on one cell for either side, and a value the relay never sent reads
// N/A instead of n/a.
//
// Build 169 is 4.3.1, the same day's next order: both ALERTS boards wear the
// heading ink every other tile wears, each transaction at or above 50k stands as
// its own row, the ALERTS LOG reads in columns from the quantity onwards, and the
// percentage is right aligned in its field on every page.
//
// Build 168 is 4.3.0, the same day's next order: CUSTOM SCRIPS OF VOLUME starts
// every NET DELTA figure on the one cell the widest figure starts on, the WATCH
// LIST drops the MY ORDER chip and reads its seven ORDER FLOW orders, and both
// ALERTS boards keep the price and the percentage each transaction printed at.
//
// Build 167 is 4.2.10, the same day's next order: the WATCH LIST's footer
// sentence is one ink, the word del included.
//
// Build 166 is 4.2.9, the same day's next order: the ORDER chips read CHANGE,
// NET DELTA, NET DELTA %, BUYING VOLUME, SELLING VOLUME, TOTAL VOLUME and
// UNCLEAR on ORDER FLOW and WATCH LIST alike, and the WATCH LIST tile says
// Press "/" to add.
//
// Build 165 is 4.2.8, the same day's next order: BIG BUYING NOW and BIG SELLING
// NOW name each observed transaction at or above 50k as its own row instead of a
// stock's running minute total, the WATCH LIST keeps one blank line under its
// box, its instruction stands on the panel's own last row, and the tab bar
// carries TAB, R and Q on that page again.
//
// Build 164 is 4.2.7, the same day's next order: the WATCH LIST's box asks for
// a KMIALL scrip and its footer carries the one sentence that says how to take
// a scrip out, its rows are numbered as ORDER FLOW numbers its own with no
// diamond under the #, its list takes the ORDER line of chips, the bar column is
// headed BAR everywhere, and SCRIP keeps one more blank cell before PRICE on
// ORDER FLOW and WATCH LIST alike.
//
// Build 163 is 4.2.6, the same day's next order: the LATEST SIGNAL tile writes
// each call as its own block, CALL n/3 over SCRIP, SCORE, ENTRY TIME, ENTRY
// PRICE, TARGET PRICE and STOP LOSS, five blank cells after the longest line of
// the block before it, and every page's footer carries TAB, R and Q alone.
//
// Build 162 is 4.2.5, the owner's 2026-11-24 orders: the ORDER FLOW page's
// first column is headed SCRIP and its values stand on the left, under the
// headings that name them, with the five price fields one cell narrower; the
// ALERTS LOG names its 100k floor and the slash key on its own edge; the
// boards carry the NET DELTA figure alone, right after the bar, one space
// tighter in front of it; the gate is headed SIGN IN; and the WATCH LIST page
// stands before SETTINGS.
// Build 173 is 4.3.5, the owner's 2026-11-25 orders: every percentage in the
// build starts its figure on one cell, so a 10% move and above stands on the
// column a 9% move stands on in the ALERTS LOG and on both boards; the WATCH
// LIST page keeps one more cell between its CHANGE column and HIGH, so a two
// digit change never runs into the high beside it.
// Build 174 is 4.3.6, the owner's 2026-11-26 orders: the WATCH LIST page's box
// searches as he types, so one letter puts every scrip that starts with it on
// the page and a tap adds the one he picks; the TELEMETRY tile closes the LINK
// latency with a full stop and opens Synced with a capital; and the right
// password shows the basmala in Arabic, then QUANT OF REHAN, before the HUD.
// Build 175 is 4.3.7, the same day's correction: the sign in banner carries the
// basmala alone, the owner's own words drawn as joined Arabic so the console
// shows them in their own reading order, and nothing is drawn after them.
// Build 176 is 4.3.8, the owner's 2026-11-26 correction: the console cut every
// Arabic letter at its cell's edge, so the banner is now a picture of the same
// words drawn as braille dots, whole and joined, and nothing follows it.
// Build 177 is 4.3.9, the same day's order: the banner stands at half the
// width, so the words sit in the middle of the gate as a mark.
// Build 178 is 4.4.0, the same day's six corrections: the banner is solid
// blocks with one mark for the whole phrase, the LINK line keeps one space
// before Synced, the FEED row drops the typical stock's age, the ADV/DEC slash
// is white, the CUSTOM SCRIPS quote group is measured on the whole table so all
// six sub menus line up, PKR keeps one space before a two digit price, and the
// WATCH LIST's search answers in its own box.
// Build 182 is 4.4.4, the owner's 2026-11-27 order after two rejected banners:
// "these are not even the words as I told you. do this type "chcp 65001" type
// "echo ﷽" ... make bigger, the banner should take about 40% of the screen."
// The banner is the one ligature character U+FDFD, and the gate draws its own
// shape, asked of Windows' text engine, as solid blocks across about 40% of the
// gate's rows; if that shape cannot be drawn the ligature itself stands on the
// middle row. Nothing else is drawn on the gate either way.
// Build 183 is 4.4.5: the same order carried further, "can you display PNG/JPG/
// JPEG pictures as the display banner if I give you?", with his own artwork in
// windows/assets/banner taking the gate instead of any glyph rebuilt from a
// font, and ONLINE, ON and the big order size green on SETTINGS.
// Build 184 is 4.4.6, the owner's 2026-11-27 correction of that banner: "this
// is not right. this is right image ... only use this image as the welcome
// image, DO NOT RENDER IT, just have this exact image as the welcome banner."
// The sampled blocks are gone from the welcome: the picture itself is shown in
// a window of its own over the gate, every pixel the file's own, and the cell
// banner is only the fallback for a platform or a run without that window.
// Build 185 is 4.4.7, the owner's report on 184: "you have made the picture too
// wide and also, the program crashed after just showing the banner", with the
// theme names white and the SECTORS list's PKR placed as CUSTOM SCRIPS OF
// VOLUME places its own. The picture's window now answers its messages, so
// Windows no longer calls the programme hung; it measures in screen pixels, so
// Windows' display scaling no longer widens it; and it never stands wider than
// the window the gate is drawn in.
// Build 186 is 4.4.8, the owner's report on 185: "these are the changes for the
// windows build, the application still got hung for about 1 or 2 seconds,
// reduce the banner's image size by 35% from it's current size." The picture is
// 4417 by 1282 pixels, and reading it, laying its 5.7 million pixels over the
// gate's colour and making and painting its window all ran on the gate's own
// thread before its first frame: that was the second or two the programme stood
// still. Every step of it happens on a thread of its own now, so the gate draws
// and answers while the picture is made. The picture itself stands at 65% of
// the size it stood at on 185, whichever of its file, the console's width or
// the screen's work area decided that size.
// Build 187 is 4.4.9, the owner's order of 2026-11-27: on TELEMETRY's FLOW row
// only the three values keep an ink, green for B, red for S and yellow for U,
// while the letters, both equals signs, the ampersand and the commas wear
// FLOW's own soft ink; the WATCH LIST writes the average change of its scrips
// four blank rows under the last of them; and a row with no figure keeps one
// dash in each of its NET DELTA columns instead of two in the second.
// Build 188 is 4.5.0, the owner's order of 2026-11-28: the welcome is his
// picture's own ink drawn in one dot a cell, the picture's window withdrawn
// because it hung the build; the WATCH LIST's average change reads two
// decimals with no quotes two blank rows under its last scrip; the ALERTS
// boards and log stand one space after PKR with every figure starting on the
// one cell; and the build's console opens on the middle of its monitor.
// Build 189 is 4.5.1, the owner's order of 2026-11-28: "the build's
// screen/interface is still not in the center of the console", so the window
// the build is seen in is watched for the first seconds and kept on the middle
// of its monitor through the size Windows gives it late, and the welcome banner
// is withdrawn from the build, so the right password opens the HUD at once.
// Build 190 is 4.5.2, the owner's order of 2026-11-28: ORDER FLOW's foot drops
// the centred dot and says "and above." one space after the full stop; the
// opened SECTORS list carries PKR and its figures one cell further left; the
// PHASE word wears the law of its side, OPEN green and CLOSED red; and both
// lock sorts hold the exchange's own circuit instead of the app's capped move
// mark, so a five percent scrip is no longer named as locked.
//
// Owner order 2026-11-24: the HUD ships as 4.2.5. The version never reads a
// part above ten on either build: 3.10.10 is followed by 4.0.0, and .11 never
// exists.
const hudBuild = "4.5.2"

// appVersionLabel is the version the SETTINGS page names. Owner order
// 2026-11-09: the page shows 2.8 alone, with no Windows build number and no
// ported app version beside it.
const appVersionLabel = hudBuild

// scripSearchHint is the same search line on every desktop search box.
const scripSearchHint = "Search for a KMIALL scrip"

// pressSearchHint names the key that gives a page's search box the keys, on
// every page that has one (owner order 2026-11-12: the slash is that key).
const pressSearchHint = "Press \"/\" to search"

// alertSearchHint is the key that gives the ALERTS page's SEARCH tile the
// keys. Owner order 2026-11-18: S opens it, while the ALERTS LOG keeps the
// slash key for its own box.
const alertSearchHint = `Press "S" to search`

// sectorMoveHint names the keys that move the SECTORS selection, in the
// owner's own words (order 2026-11-15).
const sectorMoveHint = `Press "DOWN & UP ARROW KEYS" to move`

// A terminal has one font size for the whole window, so the title is set in the
// theme's accent and closed by a diamond on either side. The owner asked for the
// diamonds close to the words, so there is one space inside each one; the glyph
// height is fixed by the console.
const headerTitle = "◆ QUANT OF REHAN ◆"

// headerTag is the index line under the title. Owner order 2026-11-09 (build
// 29): the line is in the same console font as the rest of the build, so the
// small-capital letterforms of build 27 are gone. A Windows console draws one
// glyph size per window, so this is the plain line, unbolded and in the soft
// ink, exactly like the other labels.
const headerTag = "PSX'S KMIALL INDEX"

// pkt is Pakistan time, fixed UTC+5 (no daylight saving), same as the session law.
var pkt = time.FixedZone("PKT", 5*3600)

// Leader is one of the top volume scrips the relay reports.
type Leader struct {
	Symbol      string
	Buy         *int64
	Sell        *int64
	Volume      *int64
	Price       *float64
	ChangePct   *float64
	SplitMethod string
}

func (l Leader) HasSplit() bool  { return l.Buy != nil && l.Sell != nil }
func (l Leader) HasVolume() bool { return l.Volume != nil }

// Market is the parsed /market answer (plus phase data from /health).
type Market struct {
	Answered            bool
	FeedHalted          bool
	FeedStatusFresh     bool
	IndexChange         *float64
	IndexPct            *float64
	IndexValue          *float64
	Open                bool
	Phase               string
	TransitionDelivered bool
	Date                string
	Condition           string
	ConditionText       string
	TradingDay          bool
	IndexAsOf           string
	IndexSource         string
	FeedStatus          string
	FeedStatusRaw       string
	FeedStatusAsOf      string
	TransitionState     string
	TransitionEvidence  string
	Leaders             []Leader
	Basis               string
	SplitBasis          string
	Note                string
	CacheAgeSeconds     int
	KarachiNow          string
	NextEvent           string
	Members             int
	WinLoss             *WinLoss
	QuoteSnapshotStale  bool
}

// WinLoss is the closed signal record the relay reports since app 3.6.0.
type WinLoss struct {
	Wins, Losses int
	Closed       *int
	RatePct      *int
}

func NewMarket() *Market {
	return &Market{TradingDay: true, FeedStatus: "UNKNOWN", CacheAgeSeconds: -1}
}

func (m *Market) HasIndex() bool {
	return m.IndexValue != nil && m.IndexChange != nil && m.IndexPct != nil
}

func (m *Market) PhaseKnown() bool { return m.Phase != "" }

func (m *Market) IsLive() bool { return m.Open && m.Phase != "BREAK" }

// Head is the parsed /health answer.
type Head struct {
	Reachable  bool
	MarketOpen bool
	Detail     string
	KarachiNow string
	NextEvent  string
	Phase      *Market
}

// Online is true only when the relay answers and a session is live.
func (h *Head) Online() bool { return h.Reachable && h.MarketOpen }

// Quote is one row of the /prices table, with the broker feed's traded total
// laid over it when the feed carries one.
type Quote struct {
	Price     float64
	ChangePct *float64
	Buy       *int64
	Sell      *int64
	// Volume is the traded total the scanner ranks a scrip by and draws as its
	// T. It is the measured buy and sell pair when the capture sided the row,
	// otherwise the broker feed's own volume.
	Volume *int64
}

// LiveQuote is one row of the /quotes broker feed.
type LiveQuote struct {
	Price      float64
	ChangePct  *float64
	Fresh      bool
	Change     *float64
	Volume     int64
	High, Low  float64
	Bid, Ask   float64
	// MeasuredBuy and MeasuredSell are the relay capture's own cumulative
	// quote-rule pair. They are present on the live feed, so the ALERTS boards
	// can use exactly the shares the relay already sided instead of guessing
	// from the last price move.
	MeasuredBuy, MeasuredSell *int64
	FlowMethod                string
	AgeSeconds                int // age at the moment the relay answered, -1 when unknown
	SourceTick                string
	ObservedAt                string
}

// RangeSplit is the relay's own buy and sell estimate: the share of the day's
// volume counted as buying is where the price sits inside the day's range.
// For KEL on 2026-10-30 (price 5.79, low 5.76, high 6.03, volume 21,471,271)
// it gives 2,385,697 bought, exactly what the relay reported.
func (q LiveQuote) RangeSplit() (buy, sell int64, ok bool) {
	if q.Volume <= 0 || q.High <= q.Low || q.Price < q.Low || q.Price > q.High {
		return 0, 0, false
	}
	frac := (q.Price - q.Low) / (q.High - q.Low)
	b := int64(float64(q.Volume) * frac)
	return b, q.Volume - b, true
}

// IndexQuote is the broker feed index reading.
type IndexQuote struct {
	Value     float64
	Change    float64
	ChangePct float64
	AsOf      string
	Fresh     bool
}

// Quotes is the parsed /quotes answer.
type Quotes struct {
	OK        bool
	Index     *IndexQuote
	Items     map[string]LiveQuote
	FetchedAt time.Time
}
