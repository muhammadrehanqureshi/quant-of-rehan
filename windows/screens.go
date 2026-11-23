package main

import (
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
	"time"
)

const (
	minW = 80
	minH = 26
	// Owner order 2026-11-11: the KSE100's own point move decides the
	// telemetry breadth, and the band between the two marks is FLAT.
	// Owner order 2026-11-19: the index stood +1100 points up and the tile
	// still read FLAT, so the bullish mark became +1000.
	// Owner order 2026-11-20 (latest): the marks are the owner's own numbers,
	// both inclusive. At or over +1000 points the breadth is BULLISH, at or
	// under -1 point it is BEARISH, and every point between is FLAT.
	kseBullishPoints = 1000.0
	kseBearishPoints = -1.0
)

func (a *App) animSeconds() float64 {
	if a.animT >= 0 {
		return a.animT
	}
	return a.now.Sub(a.start).Seconds()
}

func (a *App) orbMode() OrbMode {
	switch {
	case a.checking:
		return OrbChecking
	case !a.link:
		return OrbFault
	case a.online():
		return OrbBurning
	}
	return OrbParked
}

// orbGreen says whether the quant mark wears the GIF's refined green. Owner
// order 2026-11-13: green from 08:55 to 15:49 Monday to Thursday and from
// 08:55 to 16:49 on Friday, red outside those windows and all weekend.
// A PSX holiday is not a market day, so it is red all day too, and the relay's
// own trading-day flag can only add a red day, never turn one green.
func (a *App) orbGreen() bool {
	p := a.karachiNow().In(pkt)
	if isWeekend(p) || isPsxHoliday(p) {
		return false
	}
	if a.market != nil && a.market.PhaseKnown() && !a.market.TradingDay {
		return false
	}
	// Owner order 2026-11-13: the mark is red while the exchange is on its
	// midday break, and red while the relay reports a halt. The clock window
	// alone is not enough: Friday's 12:00 break sits inside it.
	if ph := a.quantPhase(); ph == qsBreak || ph == qsHalted {
		return false
	}
	if sessionAt(p) == sesBreak {
		return false
	}
	start := scanOpen // 08:55
	end := 15*60 + 49
	if isFriday(p) {
		end = 16*60 + 49
	}
	m := minuteOf(p)
	return m >= start && m < end
}

// hasRing says whether this screen carries the left column with the quant mark
// and the telemetry. The mark is on the home screen only now: the scanner is
// given the whole width for its search, sectors and list.
func (a *App) hasRing() bool { return a.screen == scrHome }

func (a *App) render() *Canvas {
	th := a.th
	c := NewCanvas(a.w, a.h, th.BG)
	a.hits = a.hits[:0]
	// Owner order 2026-11-23: the password gate is the whole window until the
	// right password is typed, so no tile, tab or click is drawn behind it.
	if a.locked {
		a.drawLogin(c)
		return c
	}
	if a.w < minW || a.h < minH {
		msg := fmt.Sprintf("TERMINAL TOO SMALL: need %dx%d, have %dx%d", minW, minH, a.w, a.h)
		c.Text(max(0, (a.w-runeLen(msg))/2), a.h/2, a.w, msg, th.Warn, true)
		return c
	}
	top, rows := 3, a.h-4
	rx, rw := 1, a.w-2
	if a.w >= 100 && a.hasRing() {
		// The mark is drawn one console dot per GIF dot with one empty dot
		// between, so the GIF's 55 dot wide stipple needs 55 cells of width to
		// show dot for dot. Owner order 2026-11-10 (latest): the column is four
		// cells narrower across and stops at 56, and the mark is scaled into the
		// width it is given rather than cropped, so nothing on either tile is
		// cut off.
		lw := min(max(a.w/3-4, 38), 56)
		a.drawLeft(c, 1, top, lw, rows)
		rx = lw + 2
		rw = a.w - rx - 1
	}
	switch a.screen {
	case scrHome:
		a.drawHome(c, rx, top, rw, rows)
	case scrAlerts:
		a.drawAlerts(c, rx, top, rw, rows)
	case scrOrderFlow:
		a.drawOrderFlow(c, rx, top, rw, rows)
	case scrScanner:
		a.drawScanner(c, rx, top, rw, rows)
	case scrSettings:
		a.drawSettings(c, rx, top, rw, rows)
	}
	// The two forms float over the page, so they fit every window size the
	// build draws.
	if a.priceEdit >= 0 {
		a.drawPriceEditor(c)
	}
	a.drawNav(c, a.h-1)
	a.drawHeader(c) // last, so the banner sits on top and wins the click
	return c
}

// ---------- building blocks ----------

// panel draws a HUD frame, the way the first build did, and returns the inner
// rectangle: heavy corners, a thin line, a bright bar at the right end of both
// the top and the bottom edge, the title after a diamond in the top edge and
// the hint, when there is one, at its right end.
func (a *App) panel(c *Canvas, x, y, w, h int, title, hint string) (ix, iy, iw, ih int) {
	th := a.th
	c.Fill(x, y, w, h, th.Panel)
	ln := th.Line
	tc := th.Accent
	if a.focusNext {
		// The panel the keys act on is drawn with a bright frame and title.
		a.focusNext = false
		ln, tc = mix(th.Line, th.Accent, 0.7), th.Hot
	}
	c.Put(x, y, '┏', ln, false)
	c.Put(x+w-1, y, '┓', ln, false)
	c.Put(x, y+h-1, '┗', ln, false)
	c.Put(x+w-1, y+h-1, '┛', ln, false)
	c.HLine(x+1, y, w-2, '─', ln)
	c.HLine(x+1, y+h-1, w-2, '─', ln)
	// Owner order 2026-11-11: the bright bar sits at the same end of the top
	// and the bottom edge, so the frame is symmetrical top to bottom.
	c.HLine(x+w-4, y+h-1, 3, '━', th.Accent)
	c.HLine(x+w-4, y, 3, '━', th.Accent)
	for r := y + 1; r < y+h-1; r++ {
		c.Put(x, r, '│', ln, false)
		c.Put(x+w-1, r, '│', ln, false)
	}
	if title != "" {
		t := fit(title, w-12)
		c.Put(x+2, y, '◆', th.Hot, false)
		c.Text(x+4, y, w-8, t, tc, true)
	}
	if hint != "" {
		hh := fit(hint, w-runeLen(title)-14)
		c.Text(x+w-5-runeLen(hh), y, runeLen(hh), hh, th.Soft, false)
	}
	return x + 2, y + 1, w - 4, h - 2
}

// Owner order 2026-11-19: one quote group on every tile. PKR keeps its own
// column, the price is right aligned in a shared field, one cell follows, then
// the arrow and exactly one cell before the percentage. The percentage starts
// on the same cell whether the move is a rise or a fall, so every tile reads
// with the same spaces and nothing floats to a different column.
const (
	quoteLabelW    = 4 // "PKR "
	quoteGap       = 1
	quotePctW      = 6 // "99.99%"
	quoteNetLabelW = 9
	quoteNetValW   = 6
)

func quoteWidth(pxW int) int {
	return quoteLabelW + pxW + quoteGap + 1 + 1 + quotePctW
}

func quoteNetWidth(pxW int) int {
	return quoteWidth(pxW) + quoteGap + quoteNetLabelW + 1 + quoteNetValW
}

func pctFixed(pct float64) string {
	return strconv.FormatFloat(math.Abs(pct), 'f', 2, 64) + "%"
}

// drawQuoteStart writes PKR and its price, and returns the cell after the price
// field. The caller adds NET DELTA and the percentage from that cell, so every
// group shares one rule.
func (a *App) drawQuoteStart(c *Canvas, pkrX, y, pxW int, px, pxKey string) int {
	c.Text(pkrX, y, 3, "PKR", a.th.Soft, false)
	a.flashText(c, pkrX+quoteLabelW, y, padLeft(px, pxW), a.th.Text, true, pxKey)
	return pkrX + quoteLabelW + pxW
}

func (a *App) drawQuotePct(c *Canvas, x, y int, pct float64) int {
	ink := a.dirColor(pct)
	c.Text(x, y, 1, arrow(pct), ink, true)
	c.Text(x+2, y, quotePctW, pctFixed(pct), ink, true)
	return x + 1 + 1 + quotePctW
}

func (a *App) drawQuote(c *Canvas, pkrX, y, pxW int, px string, pct *float64, pxKey string) {
	x := a.drawQuoteStart(c, pkrX, y, pxW, px, pxKey)
	if pct != nil {
		a.drawQuotePct(c, x+quoteGap, y, *pct)
	}
}

// drawQuoteGroup writes the quote group with NET DELTA in front of the
// percentage. net reserves the NET DELTA columns even on a row whose leader
// carries no split, so every row's percentage lands on the same cell.
func (a *App) drawQuoteGroup(c *Canvas, pkrX, y, pxW int, px, pxKey string, net bool, buy, sell *int64, pct *float64) int {
	return a.drawQuoteTail(c, a.drawQuoteStart(c, pkrX, y, pxW, px, pxKey), y, net, buy, sell, pct)
}

// drawQuoteTail writes NET DELTA and the percentage after a price that ends on
// pxEnd, on the one quote rule every tile uses.
func (a *App) drawQuoteTail(c *Canvas, pxEnd, y int, net bool, buy, sell *int64, pct *float64) int {
	x := pxEnd
	if net {
		x += quoteGap
		if buy != nil && sell != nil {
			val, ink, bold := a.searchNet(*buy, *sell)
			c.Text(x, y, quoteNetLabelW, "NET DELTA", a.th.Soft, false)
			rightAlign(c, x+quoteNetLabelW+1, y, quoteNetValW, []Span{{val, ink, bold}})
		}
		x += quoteNetLabelW + 1 + quoteNetValW
	}
	if pct != nil {
		x = a.drawQuotePct(c, x+quoteGap, y, *pct)
	}
	return x
}

// drawQuoteNetLast is the KSE100 tile's quote group. Owner order 2026-11-20: on
// that tile NET DELTA stands at the end of the group, after the percentage, its
// equals sign hard against the label and its figure on the cell after it. The
// rest of the group keeps the one rule every tile uses: PKR, its price field,
// one cell, the arrow, one cell, the percentage, then a gutter before NET DELTA.
func (a *App) drawQuoteNetLast(c *Canvas, pkrX, y, pxW int, px, pxKey string, buy, sell *int64, pct *float64) int {
	x := a.drawQuoteStart(c, pkrX, y, pxW, px, pxKey)
	if pct != nil {
		x = a.drawQuotePct(c, x+quoteGap, y, *pct)
	}
	if buy != nil && sell != nil {
		x += quoteGap
		val, ink, bold := a.searchNet(*buy, *sell)
		c.Text(x, y, quoteNetLabelW, "NET DELTA", a.th.Soft, false)
		c.Text(x+quoteNetLabelW, y, 1, "=", a.th.Soft, false)
		c.Text(x+quoteNetLabelW+1, y, runeLen(val), val, ink, bold)
		x += quoteNetLabelW + 1 + quoteNetValW
	}
	return x
}

func rightAlign(c *Canvas, x, y, w int, spans []Span) {
	n := 0
	for _, s := range spans {
		n += runeLen(s.S)
	}
	c.Spans(x+max(0, w-n), y, min(w, n), spans)
}

func centerText(c *Canvas, x, y, w int, s string, fg RGB, bold bool) {
	s = fit(s, w)
	c.Text(x+(w-runeLen(s))/2, y, w, s, fg, bold)
}

func (a *App) dirColor(v float64) RGB {
	if v >= 0 {
		return a.th.Good
	}
	return a.th.Bad
}

// flashAny gives the strongest live flash among keys.
func (a *App) flashAny(keys ...string) (k float64, dir int) {
	for _, key := range keys {
		if kk, d := a.flashAmount(key); kk > k {
			k, dir = kk, d
		}
	}
	return
}

// flashText draws s at (x, y) the way a live number should look: when the value
// behind any of keys has just changed it flashes bright with a faint tint of
// the direction behind it, then fades back to its own colour over a second. It
// returns the width drawn.
func (a *App) flashText(c *Canvas, x, y int, s string, fg RGB, bold bool, keys ...string) int {
	th := a.th
	k, dir := a.flashAny(keys...)
	n := 0
	for _, r := range s {
		bg := c.BGAt(x+n, y)
		ink := fg
		if k > 0 {
			tint := th.Good
			if dir < 0 {
				tint = th.Bad
			}
			bg = mix(bg, tint, 0.18*k)
			ink = mix(fg, th.Hot, 0.9*k)
		}
		c.Set(x+n, y, r, ink, bg, bold)
		n++
	}
	return n
}

// flashRight is flashText with the text ending at column right (exclusive).
func (a *App) flashRight(c *Canvas, right, y int, s string, fg RGB, bold bool, keys ...string) int {
	return a.flashText(c, right-runeLen(s), y, s, fg, bold, keys...)
}

// ---------- chrome ----------

// drawHeader is the top of the window: the name centred between two diamonds
// in the brightest ink, and the date and 24 hour clock on the right in a
// darker shade, with the clock itself green and UTC+5 after it. The index the
// quant watches is centred on the next line, and the rule with a bright
// segment sweeping along it closes the header. Owner order 2026-11-11: the
// LIVE/LAGGING counter is gone from the top left. Owner order 2026-11-15: the
// thin rules on either side of the index line are withdrawn.
func (a *App) drawHeader(c *Canvas) {
	th := a.th
	title := headerTitle
	c.Text((c.W-runeLen(title))/2, 0, runeLen(title), title, th.Accent, true)

	k := a.karachiNow().In(pkt)
	layout := "Mon 02 Jan 2006"
	if c.W < 100 {
		layout = "02 Jan 06"
	}
	date := strings.ToUpper(k.Format(layout))
	clock := k.Format("15:04:05")
	// Owner order 2026-11-07: one space between the date and the time, the time
	// itself green, and the UTC+5 tag still in the darker shade.
	ink := mix(th.Soft, th.BG, 0.28)
	// Owner order 2026-11-12 (latest): the date and the clock stand above the
	// PSX'S KMIALL INDEX line, on the top row and at the window's right edge,
	// so the index line never cuts the clock.
	rightAlign(c, 0, 0, c.W-1, []Span{{date + " ", ink, false}, {clock, th.Good, true}, {" UTC+5", ink, false}})

	tag := headerTag
	if a.demo {
		tag += "  ·  DEMO DATA"
	}
	tag = fit(tag, c.W)
	tagX := max(0, (c.W-runeLen(tag))/2)
	c.Text(tagX, 1, runeLen(tag), tag, th.Soft, false)
	// Owner order 2026-11-15: the thin rules on either side of the index line
	// are withdrawn; PSX'S KMIALL INDEX stands alone above the sweeping rule.

	// Rule with a bright segment sweeping along it.
	c.HLine(0, 2, c.W, '━', th.Line)
	t := a.animSeconds()
	pos := int(t*28)%(c.W+24) - 12
	for i := 0; i < 12; i++ {
		x := pos + i
		if x >= 0 && x < c.W {
			kk := math.Sin(math.Pi * float64(i) / 11)
			c.Put(x, 2, '━', mix(th.Line, th.Hot, kk), false)
		}
	}
	if a.now.Before(a.bannerUntil) && a.bannerTitle != "" {
		flash := (a.now.UnixMilli()/450)%2 == 0
		bg, fg := th.Warn, th.BG
		if a.bannerKind == "flow" {
			bg = th.Good
			if a.bannerSell {
				bg = th.Bad
			}
		}
		if !flash {
			bg, fg = th.Panel, bg
		}
		by := 1
		for x := 0; x < c.W; x++ {
			c.Set(x, by, ' ', fg, bg, true)
		}
		txt := "! " + sentence(a.bannerTitle)
		if b := firstLine(a.bannerBody); b != "" {
			txt += " " + sentence(b)
		}
		c.Text(1, by, c.W-2, fit(txt, c.W-2), fg, true)
		a.addHit(0, by, c.W, 1, func() {
			if a.bannerKind == "flow" || a.bannerKind == "price" {
				a.setScreen(scrAlerts)
			}
			a.bannerUntil = time.Time{}
		})
	}
}

func firstLine(s string) string {
	if i := strings.IndexByte(s, '\n'); i >= 0 {
		s = s[:i]
	}
	return strings.TrimSpace(s)
}

func (a *App) drawNav(c *Canvas, y int) {
	th := a.th
	x := 1
	for i, name := range screenNames {
		label := fmt.Sprintf(" %d %s ", i+1, name)
		id := screenID(i)
		w := runeLen(label)
		fg, bg, bold := th.Soft, c.BGAt(x, y), false
		switch {
		case id == a.screen:
			fg, bg, bold = th.BG, th.Accent, true
		case a.hovering(x, y, w, 1):
			fg, bg, bold = th.Hot, mix(th.Panel, th.Accent, 0.3), true
		}
		for k, r := range label {
			ink := fg
			if k == 1 {
				// Owner order 2026-11-07: the tab numbers are green and bold.
				ink = th.Good
			}
			c.Set(x+k, y, r, ink, bg, bold || k == 1)
		}
		a.addHit(x, y, w, 1, func() { a.setScreen(id) })
		x += w + 1
	}

	// Sound and the two alert flags live only on Settings now. The footer is
	// navigation and a short key hint, nothing that can be switched by accident.
	right := c.W - 1
	hints := []string{"TAB NEXT  R REFRESH  Q QUIT", "R REFRESH  Q QUIT", "Q QUIT"}
	switch a.screen {
	case scrScanner:
		hints = []string{"TAB NEXT  ESC CLEAR  CTRL+C QUIT", "TAB NEXT  ESC CLEAR  CTRL+C QUIT", "CTRL+C QUIT"}
	case scrAlerts:
		hints = []string{"A PRICE ALERT  TAB NEXT  R REFRESH  Q QUIT", "TAB NEXT  R REFRESH  Q QUIT", "Q QUIT"}
	case scrHome:
		// Owner order 2026-11-12 (latest): the D DETAILS hint is withdrawn from
		// the home footer. D itself still flips the card to its raw text.
		hints = []string{"TAB NEXT  R REFRESH  Q QUIT", "R REFRESH  Q QUIT", "Q QUIT"}
	case scrOrderFlow:
		hints = []string{"TAB NEXT  R REFRESH  Q QUIT", "R REFRESH  Q QUIT", "Q QUIT"}
	}
	// The longest hint that leaves a gap after the tabs.
	for _, hint := range hints {
		if right-runeLen(hint) >= x+1 {
			rightAlign(c, 0, y, right+1, hintSpans(hint, th))
			break
		}
	}
}

// hintSpans colours the key tokens in the footer: D, P, R and TAB green, ESC
// yellow, Q and CTRL+C red. Every coloured key is bold. The rest of the hint
// stays in the soft ink, and the spacing is preserved exactly.
func hintSpans(s string, th *Theme) []Span {
	fields := strings.Split(s, " ")
	out := make([]Span, 0, len(fields))
	for i, f := range fields {
		if i > 0 {
			out = append(out, Span{" ", th.Soft, false})
		}
		switch f {
		case "A", "D", "P", "R", "TAB":
			out = append(out, Span{f, th.Good, true})
		case "ESC":
			out = append(out, Span{f, th.Warn, true})
		case "Q", "CTRL+C":
			out = append(out, Span{f, th.Bad, true})
		default:
			out = append(out, Span{f, th.Soft, false})
		}
	}
	return out
}

// scanStatus words what the scanner is doing now, for the telemetry panel, and
// follows the market's own day and clock: the weekend names itself, a trading
// day the exchange has closed says so, and a weekday outside the band says
// whether the scan has started yet or is done for the day.
func (a *App) scanStatus() (string, RGB) {
	th := a.th
	if a.scanning() {
		return "EVERY SECOND", th.Good
	}
	p := a.karachiNow().In(pkt)
	if isWeekend(p) {
		return "OFF ON THE WEEKEND", th.Soft
	}
	switch {
	case a.market != nil && a.market.PhaseKnown() && !a.market.TradingDay:
		// Owner order 2026-11-09: a closed trading day names itself.
		return "MARKET IS CLOSED TODAY", th.Soft
	case secondOf(p) < scanOpen*60:
		return fmt.Sprintf("STARTS AT %02d:%02d", scanOpen/60, scanOpen%60), th.Soft
	}
	return "DONE FOR TODAY", th.Soft
}

// ---------- left column: orb and telemetry ----------

func (a *App) drawLeft(c *Canvas, x, y, w, h int) {
	th := a.th
	// Owner order 2026-11-11: the top tile and the bottom tile are the same
	// height, so the orb and the numbers sit in matching frames and the ORB/HUD
	// reads symmetrical from top to bottom.
	coreH, telH := leftTileHeights(h)
	ix, iy, iw, ih := a.panel(c, x, y, w, coreH, "QUANT CORE", "")
	// Owner order 2026-11-10 (latest): the wordmark is out for now and the tile
	// carries a three dimensional dot sphere turning clockwise.
	drawSphere(c, ix, iy, iw, ih, a.animSeconds(), a.orbGreen(), th)

	tx, ty, tw, tih := a.panel(c, x, y+coreH+1, w, telH, "TELEMETRY", "")
	// Owner order 2026-11-11 (tenth pass): every value ends on the tile's right
	// edge, so a short word and a long row finish on the same column.
	const labelW = 7
	label := func(row int, k string, v []Span) {
		c.Text(tx, ty+row, labelW, k, th.Soft, false)
		rightAlign(c, tx+labelW, ty+row, tw-labelW, v)
	}
	// fullRow carries a long heading on the left and its value on the tile's
	// right edge, for the rows whose heading does not fit the label column.
	fullRow := func(row int, k string, v []Span) {
		c.Text(tx, ty+row, tw, k, th.Soft, false)
		rightAlign(c, tx, ty+row, tw, v)
	}
	// LINK
	switch {
	case a.checking:
		label(0, "LINK", []Span{{"CHECKING", th.Warn, true}})
	case !a.link:
		label(0, "LINK", []Span{{"UNREACHABLE", th.Bad, true}})
	default:
		sync := ""
		if !a.lastMarketOK.IsZero() {
			sync = "  synced " + strconv.Itoa(max(0, int(a.now.Sub(a.lastMarketOK).Seconds()))) + " s ago"
		}
		label(0, "LINK", []Span{{"UP", th.Good, true}, {"  " + strconv.Itoa(int(a.rtt.Milliseconds())) + " ms" + sync, th.Text, false}})
	}
	// FEED: how old the freshest tick is, counting up each second, and how
	// many answers per second are arriving.
	feed := []Span{{"--", th.Soft, false}}
	if a.quotes == nil && !a.link && !a.lastMarketOK.IsZero() {
		// No feed answer at all: say how old the relay's last answer is, on the
		// feed row where the staleness belongs.
		feed = []Span{{"STALE " + strconv.Itoa(max(0, int(a.now.Sub(a.lastMarketOK).Seconds()))) + "s", th.Bad, true}}
	} else if a.quotes != nil && !a.checking {
		state, age, ok := a.feedState()
		fc := th.Good
		switch {
		case !ok:
			fc = th.Bad
		case state == "LAGGING":
			fc = th.Warn
		}
		// Say how old the freshest tick is. A typical stock is older: the
		// broker's wire repeats each symbol about every 24 seconds, so show that
		// too, and the answers per second when the panel is wide enough.
		sinceAnswer := max(0, int(a.now.Sub(a.quotes.FetchedAt).Seconds()))
		old := fmt.Sprintf("  %d s old", age)
		typ := ""
		if a.feed.Median >= 0 {
			typ = fmt.Sprintf("  typical %d s", a.feed.Median+sinceAnswer)
		}
		rate := fmt.Sprintf("  %.1f/s", a.updatesPerSecond())
		room := tw - labelW - runeLen(state)
		detail := old
		switch {
		case runeLen(old+rate+typ) <= room:
			detail = old + rate + typ
		case runeLen(old+typ) <= room:
			detail = old + typ
		case runeLen(old+rate) <= room:
			detail = old + rate
		}
		feed = []Span{{state, fc, true}, {detail, th.Text, false}}
		if state == "NO FEED" {
			feed = []Span{{state, th.Warn, true}}
		}
	} else if !a.checking {
		// Owner order 2026-11-21: a relay that answers but sends no quotes
		// table at all is NO FEED, not a dash. There is no frame to age, so the
		// row must not read as if the feed were fine.
		feed = []Span{{"NO FEED", th.Warn, true}}
	}
	label(1, "FEED", feed)
	// PHASE. Owner order 2026-11-11: OPEN while the exchange trades, and PRE
	// and POST in the exchange's own pre-open and post-close windows.
	ph := a.quantPhase()
	if ph == "" {
		ph = "--"
	}
	pc := th.Text
	switch ph {
	case qsOpen:
		pc = th.Good
	case qsPre, qsPost:
		pc = th.Warn
	}
	label(2, "PHASE", []Span{{ph, pc, true}})
	// Owner order 2026-11-11: SCAN follows PHASE. MARKET OPENING is the
	// exchange's own first pre-open: 09:15 Monday to Thursday and 09:00 on
	// Friday (owner order 2026-11-13). MARKET CLOSING is the day's own end,
	// 15:49 Monday to Thursday and 16:49 on Friday, with no captions.
	sw, sc := a.scanStatus()
	label(3, "SCAN", []Span{{sw, sc, true}})
	hm := func(m int) string { return fmt.Sprintf("%02d:%02d", m/60, m%60) }
	open, close := "N/A", "N/A"
	if !isWeekend(a.karachiNow()) {
		openMin := preWindow.to
		if isFriday(a.karachiNow()) {
			openMin = preWindow.from
		}
		open = hm(openMin)
		close = hm(postWindow(a.karachiNow()).to)
	}
	fullRow(4, "MARKET OPENING", []Span{{open, th.Text, false}})
	fullRow(5, "MARKET CLOSING", []Span{{close, th.Text, false}})
	// Owner order 2026-11-11: MARKET BREADTH is the KSE100's own point move.
	// Owner order 2026-11-20 (latest): at or over +1000 points is BULLISH, at
	// or under -1 point is BEARISH, and every point between them is FLAT.
	// ADV/DEC still reads the whole market table.
	adv, dec := a.marketBreadth()
	breadth, bc := "FLAT", th.Soft
	if _, change, _, _, _, ok := a.effectiveIndex(); ok {
		switch {
		case change >= kseBullishPoints:
			breadth, bc = "BULLISH", th.Good
		case change <= kseBearishPoints:
			breadth, bc = "BEARISH", th.Bad
		}
	}
	fullRow(6, "MARKET BREADTH", []Span{{breadth, bc, true}})
	fullRow(7, "ADV/DEC", []Span{
		{strconv.Itoa(adv), th.Good, true},
		{"/", th.Soft, false},
		{strconv.Itoa(dec), th.Bad, true},
	})
	// FLOW. Owner order 2026-11-11 (eleventh pass): the row must not read zero
	// after the closing bell. The live minute is the first read; when it is
	// empty the relay's day sides take over, so the post market still shows the
	// day's B, S and U. The three sides stay separate and U is always written.
	var buy, sell, unclear int64
	if a.flow != nil {
		buy, sell, unclear = a.flow.WindowSides(a.karachiNow(), time.Minute)
	}
	if buy+sell+unclear == 0 && a.of != nil {
		tot := a.of.Totals()
		buy, sell, unclear = tot.Buy, tot.Sell, tot.Unclassified
	}
	if buy+sell+unclear == 0 {
		for _, q := range a.prices {
			if q.Buy != nil {
				buy += *q.Buy
			}
			if q.Sell != nil {
				sell += *q.Sell
			}
		}
	}
	if buy+sell+unclear > 0 || a.cfg.BigBuy || a.cfg.BigSell {
		label(8, "FLOW", []Span{
			{"B=", th.Good, true}, {compactNum(float64(buy)), th.Text, false},
			{",", th.Good, true}, {"  S=", th.Bad, true}, {compactNum(float64(sell)), th.Text, false},
			{",", th.Bad, true}, {"  & U=", th.Warn, true}, {compactNum(float64(unclear)), th.Text, false},
		})
	} else {
		label(8, "FLOW", []Span{{"OFF", th.Bad, true}})
	}
	// NET DELTA is the whole market's measured buying minus selling, in
	// shares, from the relay's own day pair.
	if net, ok := a.marketNetDelta(); ok {
		nc := th.Text
		switch {
		case net > 0:
			nc = th.Good
		case net < 0:
			nc = th.Bad
		}
		fullRow(9, "NET DELTA", []Span{{signedCompact(net), nc, true}})
	} else {
		fullRow(9, "NET DELTA", []Span{{"--", th.Soft, false}})
	}
	// Owner order 2026-11-11: TOP PERFORMERS follows NET DELTA. A short tile
	// keeps FLOW and REQ and drops only TOP PERFORMERS.
	reqRow := 10
	if tih > 11 {
		names := fit(andList(a.topPerformers()), max(1, tw-16))
		col := th.Text
		if names != "--" {
			col = th.Good
		}
		fullRow(10, "TOP PERFORMERS", []Span{{names, col, true}})
		reqRow = 11
	}
	// REQ
	rq := a.reqToday()
	rc, note := th.Text, " of 100,000"
	switch {
	case rq >= reqHardCap:
		rc, note = th.Bad, " of 100,000, paused until 05:00 PKT"
	case rq > 80000:
		rc = th.Warn
	}
	label(reqRow, "REQ", []Span{{commaInt(rq), rc, false}, {note, th.Soft, false}})
}

// leftTileHeights splits the left column into the QUANT CORE tile and the
// TELEMETRY tile. Owner order 2026-11-11: the two are symmetrical, with one row
// of gap between them and at most one row of difference in height.
func leftTileHeights(h int) (coreH, telH int) {
	coreH = (h - 1) / 2
	if coreH < 5 {
		coreH = 5
	}
	telH = h - coreH - 1
	if telH < 5 {
		telH = 5
	}
	return
}

// topPerformers names the three scrips with the best day so far. The relay's
// whole-market table is the base and a fresh broker tick replaces its own row,
// because the broker's change is the live one. The list is ordered by that
// change, ties by symbol, and a day with no measured change says -- rather than
// inventing a name.
//
// Owner report 2026-11-12: AASM stood at the top of this list with a change and
// no data behind it. A relay row can carry a change for a scrip that has not
// traded at all, so a name is only eligible when the day has traded volume
// behind it: the flow table's, the broker feed's, or the relay's own pair.
func (a *App) topPerformers() []string {
	pct := map[string]float64{}
	traded := map[string]int64{}
	for sym, q := range a.prices {
		if q.ChangePct != nil {
			pct[sym] = *q.ChangePct
		}
		if q.Buy != nil && q.Sell != nil {
			traded[sym] = *q.Buy + *q.Sell
		}
	}
	if a.quotes != nil {
		for sym, q := range a.quotes.Items {
			if !q.Fresh {
				continue
			}
			if q.ChangePct != nil {
				pct[sym] = *q.ChangePct
			}
			if q.Volume > 0 {
				traded[sym] = q.Volume
			}
		}
	}
	if a.of != nil {
		for _, fr := range a.of.Rows {
			switch {
			case fr.Volume != nil && *fr.Volume > 0:
				traded[fr.Symbol] = *fr.Volume
			case fr.Measured():
				traded[fr.Symbol] = *fr.Buy + *fr.Sell
			}
		}
	}
	syms := make([]string, 0, len(pct))
	for sym := range pct {
		if traded[sym] > 0 {
			syms = append(syms, sym)
		}
	}
	sort.Slice(syms, func(i, j int) bool {
		if pct[syms[i]] != pct[syms[j]] {
			return pct[syms[i]] > pct[syms[j]]
		}
		return syms[i] < syms[j]
	})
	if len(syms) > 3 {
		syms = syms[:3]
	}
	return syms
}

// andList joins names the way the owner reads them: MEBL, FFC & PRL.
func andList(names []string) string {
	switch len(names) {
	case 0:
		return "--"
	case 1:
		return names[0]
	}
	return strings.Join(names[:len(names)-1], ", ") + " & " + names[len(names)-1]
}

// ---------- home ----------

func (a *App) drawHome(c *Canvas, x, y, w, h int) {
	// The greeting is a tile in its own right, worded exactly like the status
	// tile, with one blank row between every pair of tiles.
	const greetH, statusH, gap = 3, 4, 1
	a.drawGreeting(c, x, y, w, greetH)
	sy := y + greetH + gap
	a.drawStatus(c, x, sy, w, statusH)
	gy := sy + statusH + gap

	// The signal tile lists SYMBOL, ENTRY TIME, ENTRY PRICE, TAKE PROFIT and
	// STOP LOSS, one under the other. When that would leave the market tile too
	// short for the blank line above its note (a window under 33 rows), the same
	// five go in two columns instead, so nothing is squeezed.
	// Six rows now that SCORE joined the card, so the tile is two rows taller.
	sigH := 8
	const marketFull = 14 // two rows of index, a spacer, three leaders, buying, a gap and the note
	if mh := y + h - (gy + sigH + gap); mh < marketFull && w >= 60 {
		sigH = 6
	}
	a.drawSignal(c, x, gy, w, sigH, sigH == 6)
	my := gy + sigH + gap
	if mh := y + h - my; mh >= 6 {
		a.drawMarket(c, x, my, w, mh)
	}
}

// drawGreeting puts the greeting in a framed tile of its own, so it reads as
// part of the HUD rather than as loose text above it.
func (a *App) drawGreeting(c *Canvas, x, y, w, h int) {
	pk := a.karachiNow().In(pkt)
	ix, iy, iw, ih := a.panel(c, x, y, w, h, "GREETING", "")
	if ih > 0 {
		c.Text(ix, iy, iw, fit(greetingFor(pk.Hour(), pk.Minute()), iw), a.th.Hot, true)
	}
}

// winLossSpans is the W/L & W/L RATE tile of app 3.6.2: wins green, losses
// red, and the rate green only when wins beat losses.
func (a *App) winLossSpans() []Span {
	th := a.th
	wl := (*WinLoss)(nil)
	if a.market != nil {
		wl = a.market.WinLoss
	}
	if wl == nil || (wl.Wins+wl.Losses == 0 && (wl.Closed == nil || *wl.Closed == 0)) {
		return []Span{{"NO CLOSED SIGNAL RIGHT NOW", th.Soft, false}}
	}
	rate := "--"
	if wl.RatePct != nil {
		rate = strconv.Itoa(*wl.RatePct)
	}
	rc := th.Bad
	if wl.Wins > wl.Losses {
		rc = th.Good
	}
	return []Span{
		{strconv.Itoa(wl.Wins), th.Good, true}, {"/", th.Soft, false}, {strconv.Itoa(wl.Losses), th.Bad, true},
		{" & ", th.Soft, false}, {rate + "%", rc, true},
	}
}

func spanW(sp []Span) int {
	n := 0
	for _, s := range sp {
		n += runeLen(s.S)
	}
	return n
}

func (a *App) drawStatus(c *Canvas, x, y, w, h int) {
	th := a.th
	ix, iy, iw, _ := a.panel(c, x, y, w, h, "QUANT STATUS", "")

	// Owner order 2026-11-15: the W/L record moved to the LATEST SIGNAL tile,
	// so the status sentence has the whole panel.
	textW := iw

	word, fill, ink := "CHECKING", mix(th.Panel, th.Warn, 0.35), th.Text
	dot := th.Warn
	switch {
	case a.checking:
	case a.online():
		word, fill, ink = "ONLINE", th.GoodFill, th.OnGood
		k := 0.5 + 0.5*math.Sin(a.animSeconds()*2.4)
		dot = mix(th.Good, th.Hot, k)
	default:
		word, fill, ink = "OFFLINE", th.BadFill, th.OnBad
		dot = th.Bad
	}
	pill := " ● " + word + " "
	for i, r := range []rune(pill) {
		fg := ink
		if i == 1 {
			fg = dot
		}
		c.Set(ix+i, iy, r, fg, fill, true)
	}
	// One sentence, which follows the part of the day. No clock here: the only
	// clock on the screen is the one at the top right.
	nc := th.Soft
	switch {
	case a.checking:
		nc = th.Warn
	case a.online():
		nc = th.Good
	default:
		nc = th.Warn
	}
	note := a.statusNote()
	// Owner order 2026-11-10 (latest): when the market is closed, the words that
	// say so are red, not the yellow they were.
	if strings.HasPrefix(note, "Market is closed") {
		nc = th.Bad
	}
	px := ix + runeLen(pill) + 2
	if lines := wrap(note, textW-(px-ix)); len(lines) > 0 && runeLen(note) > textW {
		// A long relay message wraps under the pill instead of being cut.
		c.Text(px, iy, textW-(px-ix), lines[0], nc, false)
		rest := strings.TrimSpace(strings.Join(lines[1:], " "))
		c.Text(ix, iy+1, textW, fit(rest, textW), nc, false)
		return
	}
	c.Text(ix, iy+1, textW, fit(note, textW), nc, false)
}

func (a *App) drawSignal(c *Canvas, x, y, w, h int, twoCol bool) {
	th := a.th
	hint := "[D] RAW"
	if a.showRaw {
		hint = "[D] CARD"
	}
	ix, iy, iw, ih := a.panel(c, x, y, w, h, "LATEST SIGNAL", hint)
	a.addHit(x+w-5-runeLen(hint)-1, y, runeLen(hint)+2, 1, func() { a.showRaw = !a.showRaw })
	if a.showRaw {
		raw := strings.TrimSpace(a.signals)
		if raw == "" {
			raw = "No answer from the relay yet."
		}
		for i, ln := range wrap(raw, iw) {
			if i >= ih {
				break
			}
			c.Text(ix, iy+i, iw, ln, th.Text, false)
		}
		return
	}
	disp := latestSignalDisplay(a.signals, a.relayDate())
	f := parseSignal(a.signals)
	if disp == signalNone || disp == unavailable || f.State != "trade" {
		head, col := signalNone, th.Soft
		if disp == unavailable || (a.signals == "" && !a.checking) {
			head, col = unavailable, th.Warn
		}
		c.Text(ix, iy, iw, head, col, true)
		reason := signalBody(a.signals)
		if reason == "" && !a.checking && a.signals != "" {
			reason = strings.TrimSpace(a.signals)
		}
		if f.State == "trade" {
			// A real trade card from another day. Its prices are never printed
			// under a "no signal" heading; [D] still shows the raw text.
			reason = "The latest card is dated " + cardDate(a.signals) + ", not " + a.relayDate() + ". Press D for the raw text."
		}
		if a.signals == "" {
			reason = "No answer from the relay yet."
			if !a.checking && !a.link {
				reason = "The relay is not answering."
			}
		}
		lines := wrap(reason, iw-7)
		for i := 0; i < len(lines) && i < ih-2; i++ {
			lead := "       "
			if i == 0 {
				lead = "RELAY  "
			}
			c.Text(ix, iy+1+i, 7, lead, th.Line, false)
			c.Text(ix+7, iy+1+i, iw-7, lines[i], th.Soft, false)
		}
		a.drawWinLossRecord(c, ix, iy+ih-1, iw)
		return
	}
	// The five fields, with these exact words.
	const lw = 13 // wide enough for "ENTRY PRICE" and "TAKE PROFIT"
	sym := f.Symbol
	if sym == "" {
		sym = notReported
	}
	put := func(col, row int, k, v string, vc RGB) {
		if row >= iy+ih {
			return
		}
		c.Text(col, row, lw, k, th.Soft, false)
		c.Text(col+lw, row, max(0, ix+iw-col-lw), v, vc, true)
	}
	// Owner order 2026-11-10: SCORE sits directly below ENTRY PRICE. It is the
	// card's own "Score: 72/100" line and nothing is invented when the card
	// carries none: it says not reported, the same as every other missing field.
	score := signalScore(a.signals)
	if twoCol {
		mid := ix + iw/2
		put(ix, iy, "SYMBOL", sym, th.Hot)
		put(ix, iy+1, "ENTRY TIME", f.Time, th.Text)
		put(ix, iy+2, "ENTRY PRICE", f.Entry, th.Text)
		put(ix, iy+3, "SCORE", score, th.Accent)
		put(mid, iy+1, "TAKE PROFIT", f.Exit, th.Good)
		put(mid, iy+2, "STOP LOSS", f.Stop, th.Bad)
	} else {
		put(ix, iy, "SYMBOL", sym, th.Hot)
		put(ix, iy+1, "ENTRY TIME", f.Time, th.Text)
		put(ix, iy+2, "ENTRY PRICE", f.Entry, th.Text)
		put(ix, iy+3, "SCORE", score, th.Accent)
		put(ix, iy+4, "TAKE PROFIT", f.Exit, th.Good)
		put(ix, iy+5, "STOP LOSS", f.Stop, th.Bad)
	}
	// The signal's own stock, live, at the right of the top row: price and where
	// it stands today.
	if f.Symbol != "" {
		if q, ok := a.liveQuote(f.Symbol); ok {
			sp := []Span{{"LIVE  PKR ", th.Soft, false}}
			pxKey := "px:" + f.Symbol
			right := ix + iw
			if q.ChangePct != nil {
				t := "  " + changeText(*q.ChangePct)
				a.flashRight(c, right, iy, t, a.dirColor(*q.ChangePct), true, pxKey)
				right -= runeLen(t)
			}
			ps := commaFloat(q.Price, 2)
			a.flashRight(c, right, iy, ps, th.Hot, true, pxKey)
			c.Spans(right-runeLen(ps)-spanW(sp), iy, spanW(sp), sp)
		}
	}
	a.drawWinLossRecord(c, ix, iy+ih-1, iw)
}

// drawWinLossRecord is the closed signal record, moved from QUANT STATUS to
// the foot of the LATEST SIGNAL tile. The label and the wins, losses and rate
// share the tile's right edge, clear of the card's own fields.
func (a *App) drawWinLossRecord(c *Canvas, x, y, w int) {
	th := a.th
	sp := []Span{{"W/L & W/L RATE  ", th.Soft, false}}
	sp = append(sp, a.winLossSpans()...)
	rightAlign(c, x, y, w, sp)
}

// feedLight is the broker feed's own age, counting each second, shown at the
// top left of every page. It is the one live seconds counter in the window.
func (a *App) feedLight() []Span {
	th := a.th
	switch {
	case a.checking:
		return []Span{{"● ", th.Warn, true}, {"LIVE --", th.Soft, true}}
	case a.quotes == nil && !a.link && !a.lastMarketOK.IsZero():
		return []Span{{"● ", th.Bad, true}, {"STALE " + strconv.Itoa(max(0, int(a.now.Sub(a.lastMarketOK).Seconds()))) + "s", th.Bad, true}}
	case a.quotes != nil:
		state, age, _ := a.feedState()
		col := th.Good
		switch state {
		case "LAGGING":
			col = th.Warn
		case "STALE", "NO FEED":
			col = th.Bad
		}
		dot := col
		if state == "LIVE" {
			dot = mix(col, th.Hot, 0.5+0.5*math.Sin(a.animSeconds()*2*math.Pi))
		}
		if state == "NO FEED" {
			return []Span{{"● ", dot, true}, {state, col, true}}
		}
		return []Span{{"● ", dot, true}, {fmt.Sprintf("%s %ds", state, age), col, true}}
	}
	return []Span{{"● ", th.Soft, true}, {"LIVE --", th.Soft, true}}
}

// marketNote is the one line at the foot of the market panel. It says where
// the numbers come from, in the app's own words.
func (a *App) marketNote() string {
	switch {
	case a.demo:
		return "Demo mode: every number here is invented."
	case a.quotes != nil && a.scanning():
		// Owner order 2026-11-18: while the quant is scanning, the pre and post
		// market name themselves and the live session says the feed is read
		// every second. The stored-data line belongs only to shut hours.
		switch a.quantPhase() {
		case qsPre:
			return "Pre-market session is on and the quant is online now."
		case qsPost:
			return "Post-market session is on and the quant is online now."
		}
		return "DATA FROM THE BROKER'S FEED IS BEING SCANNED EVERY SECOND."
	case a.quotes != nil:
		// Owner order 2026-11-22: after the last close the foot names the day
		// the numbers belong to, not only the feed they came from.
		return "LAST SESSION'S DATA FROM THE BROKER'S FEED."
	}
	// Owner order 2026-11-09: the idle line under the KSE100 tile.
	return "Quant is sleeping till the next market day."
}

// putBST draws the KSE100 leader shape at (x, y): every value starts against
// its '=' and the fixed nine digit field pads after it, so S, U and T hold the
// same cells on every list, not only the KSE100 tile. A part that is missing is
// left out. It returns the width drawn.
func (a *App) putBST(c *Canvas, x, y int, buy, sell, total *int64, keys ...string) int {
	// Owner order 2026-11-17: one alignment everywhere. The KSE100 writer
	// already places every value against its '=' and pads after it, so every
	// other B, S, U and T line delegates to it instead of repeating the older
	// packed form.
	return a.putBSTWide(c, x, y, buy, sell, total, keys...)
}

// putBSTPacked is the one fallback for a tile too narrow to hold the fixed nine
// digit fields. The KSE100 tile uses it below 96 columns, where the wide field
// would collide with its PKR group; every other list has the room for the one
// alignment.
//
// Owner order 2026-11-23: this form keeps the leaders' columns too. LOADS's
// shorter S used to pull its U and its & T= off the cells TREET and ENGROH
// used, so the three rows no longer read as one table. Each field now starts on
// the cell the widest leader sets, the value still sits hard against its own
// '=', the comma still sits hard against its own number, and only the padding
// between the comma and the next label moves.
func (a *App) putBSTPacked(c *Canvas, x, y int, buy, sell, total *int64, cols bstCols, keys ...string) int {
	th := a.th
	put := func(at int, s string, fg RGB, bold bool) {
		a.flashText(c, at, y, s, fg, bold, keys...)
	}
	if buy != nil && sell != nil {
		buyS, sellS := commaInt(*buy), commaInt(*sell)
		put(x, "B=", th.Soft, false)
		put(x+2, buyS, th.Good, true)
		put(x+2+runeLen(buyS), ",", th.Soft, false)
		put(x+cols.sell, "S=", th.Soft, false)
		put(x+cols.sell+2, sellS, th.Bad, true)
		put(x+cols.sell+2+runeLen(sellS), ",", th.Soft, false)
		if total != nil {
			un := *total - *buy - *sell
			if un < 0 {
				un = 0
			}
			totS := commaInt(*total)
			put(x+cols.unc, "U=", th.Soft, false)
			put(x+cols.unc+2, commaInt(un), th.Warn, un > 0)
			put(x+cols.tot, "&  T=", th.Soft, false)
			put(x+cols.tot+5, totS, totalBlue, false)
			return cols.tot + 5 + runeLen(totS)
		}
		return cols.unc
	} else if total != nil {
		put(x, "T=", th.Soft, false)
		totS := commaInt(*total)
		put(x+2, totS, totalBlue, false)
		return 2 + runeLen(totS)
	}
	return 0
}

// leaderBSTPackedWidth is the cells putBSTPacked uses for one leader on the
// shared shelf. It measures from the columns rather than the row's own digits,
// so the tile can tell whether the form fits before it paints the first row.
func leaderBSTPackedWidth(l Leader, cols bstCols) int {
	if !l.HasSplit() {
		if l.HasVolume() {
			return 2 + runeLen(commaInt(*l.Volume))
		}
		return 0
	}
	if l.HasVolume() {
		return cols.tot + 5 + runeLen(commaInt(*l.Volume))
	}
	return cols.unc
}

// The three ways a KSE100 leader can write its volumes, widest first. Owner
// order 2026-11-20 (latest): the price group shares the volume line on every
// width the tile can hold it at, so the volumes step down through these forms
// before the group gives up the line.
const (
	bstWideForm = iota
	bstPackedForm
	bstBareForm
)

// putBSTBare writes the leaders' four fields with their thousands commas
// withdrawn and one cell between the fields, every digit still written. Owner
// order 2026-11-20 (latest): on the owner's window the KSE100 tile is about 76
// cells wide and the price group must still sit on the line that carries T. The
// commas and the second gutter are the only things that give way there, so
// nothing is rounded, no digit is lost and no column leaves the line.
func (a *App) putBSTBare(c *Canvas, x, y int, buy, sell, total *int64, keys ...string) int {
	th := a.th
	vx := x
	put := func(s string, fg RGB, bold bool) {
		vx += a.flashText(c, vx, y, s, fg, bold, keys...)
	}
	if buy != nil && sell != nil {
		put("B=", th.Soft, false)
		put(strconv.FormatInt(*buy, 10), th.Good, true)
		put(" S=", th.Soft, false)
		put(strconv.FormatInt(*sell, 10), th.Bad, true)
		if total != nil {
			un := *total - *buy - *sell
			if un < 0 {
				un = 0
			}
			put(" U=", th.Soft, false)
			put(strconv.FormatInt(un, 10), th.Warn, un > 0)
			put(" & T=", th.Soft, false)
			put(strconv.FormatInt(*total, 10), totalBlue, false)
		}
	} else if total != nil {
		put("T=", th.Soft, false)
		put(strconv.FormatInt(*total, 10), totalBlue, false)
	}
	return vx - x
}

// leaderBSTBareWidth is the cells putBSTBare uses for one leader.
func leaderBSTBareWidth(l Leader) int {
	digits := func(v int64) int { return len(strconv.FormatInt(v, 10)) }
	if !l.HasSplit() {
		if l.HasVolume() {
			return 2 + digits(*l.Volume)
		}
		return 0
	}
	w := 2 + digits(*l.Buy) + 3 + digits(*l.Sell)
	if l.HasVolume() {
		un := *l.Volume - *l.Buy - *l.Sell
		if un < 0 {
			un = 0
		}
		w += 3 + digits(un) + 5 + digits(*l.Volume)
	}
	return w
}

// bstCols are the leader row's four field offsets, as cells from the row's
// first cell. Owner order 2026-11-10 (latest): the leaders read exactly like
// every other B, S, U and T line, with its commas and its "& T=", and each
// field still starts on the same cell on all three rows. The comma sits hard
// against its own number and the gutter falls after it, so no comma ever floats
// away from the figure it belongs to.
type bstCols struct {
	buy  int // "B="
	sell int // "S=", after B's comma and the gutter
	unc  int // "U=", after S's comma and the gutter
	tot  int // "& T=", after U's own digits and the gutter
	bw   int // B's widest digits
	sw   int // S's widest digits
	uw   int // U's widest digits
	wid  int // the widest total volume's digits
}

// bstPad is the gutter between one field's comma and the next field's label.
const bstPad = 2

// bstLeaderCols measures the leaders and returns the columns they share.
func bstLeaderCols(leaders []Leader) bstCols {
	bw, sw, uw, tw := 1, 1, 1, 1
	for _, l := range leaders {
		if !l.HasSplit() {
			continue
		}
		bw = max(bw, runeLen(commaInt(*l.Buy)))
		sw = max(sw, runeLen(commaInt(*l.Sell)))
		if l.HasVolume() {
			un := *l.Volume - *l.Buy - *l.Sell
			if un < 0 {
				un = 0
			}
			uw = max(uw, runeLen(commaInt(un)))
			tw = max(tw, runeLen(commaInt(*l.Volume)))
		}
	}
	c := bstCols{bw: bw, sw: sw, uw: uw, wid: tw}
	c.sell = c.buy + 2 + bw + 1 + bstPad // "B=", the digits, the comma, the gutter
	c.unc = c.sell + 2 + sw + 1 + bstPad  // "S=", the digits, the comma, the gutter
	c.tot = c.unc + 2 + uw + bstPad       // "U=" and its own digits, then the gutter
	return c
}

// leaderVolDigits is the fixed digit field every KSE100 leader volume uses.
// Owner order 2026-11-17: B, S, U and T each keep nine digit positions, commas
// not counted, so S, U and T start on the same cell whatever digits a number
// carries.
const leaderVolDigits = 9

// leaderVolumeField writes a volume immediately after its '=' and pads the
// fixed nine digit and two comma field after the value. Owner order
// 2026-11-17: the padding must not push the number away from its label, and
// the S, U and T labels must not move.
func leaderVolumeField(v int64) string {
	return leaderVolumeText(commaInt(v))
}

// leaderVolumeFieldComma is the B and S field: one comma follows the value,
// then the same fixed width pads the rest of the field. Owner order 2026-11-18:
// U carries no comma, because the ampersand already separates it from T.
func leaderVolumeFieldComma(v int64) string {
	return leaderVolumeText(commaInt(v) + ",")
}

// volumeCommaParts splits a B or S field into its number, its trailing comma
// and the fixed padding. The comma is painted in the label ink, so it reads
// like the '=' instead of taking the value's colour.
func volumeCommaParts(v int64) (value, comma, pad string) {
	value = commaInt(v)
	field := leaderVolumeFieldComma(v)
	if len(field) > len(value) && field[len(value)] == ',' {
		return value, ",", field[len(value)+1:]
	}
	return field, "", ""
}

// volumeCommaSpans is the span form of the same field, with the comma in the
// label ink so a coloured value never colours its punctuation.
func volumeCommaSpans(v int64, fg RGB, bold bool, commaInk RGB) []Span {
	value, comma, pad := volumeCommaParts(v)
	sp := []Span{{value, fg, bold}}
	if comma != "" {
		sp = append(sp, Span{comma, commaInk, false})
	}
	if pad != "" {
		sp = append(sp, Span{pad, fg, bold})
	}
	return sp
}

// volumeFieldSpans is the span form of a field with no comma after it. Owner
// order 2026-11-18: U uses this form on every list, so its value ends before
// the ampersand that separates it from T.
func volumeFieldSpans(v int64, fg RGB, bold bool) []Span {
	return []Span{{leaderVolumeField(v), fg, bold}}
}

func leaderVolumeText(s string) string {
	width := leaderVolDigits + 2
	if n := runeLen(s); n < width {
		return s + strings.Repeat(" ", width-n)
	}
	return s
}

// leaderBSTWidth is the cells putBST or putBSTWide will use for one leader. It
// writes nothing, so the tile can set one price column for all three rows
// before it paints the first of them.
func leaderBSTWidth(l Leader, cols bstCols, wide bool) int {
	_ = cols
	if !l.HasSplit() {
		if l.HasVolume() {
			return 2 + runeLen(commaInt(*l.Volume))
		}
		return 0
	}
	if wide {
		w := 2 + runeLen(leaderVolumeFieldComma(*l.Buy)) +
			4 + runeLen(leaderVolumeFieldComma(*l.Sell))
		if l.HasVolume() {
			un := *l.Volume - *l.Buy - *l.Sell
			if un < 0 {
				un = 0
			}
			w += 4 + runeLen(leaderVolumeField(un)) +
				7 + runeLen(leaderVolumeField(*l.Volume))
		}
		return w
	}
	// The packed form, used only when the tile is too narrow for the fixed
	// fields, keeps the same two cell gutter between every pair.
	w := 2 + runeLen(commaInt(*l.Buy)) + 1 + 4 + runeLen(commaInt(*l.Sell)) + 1
	if l.HasVolume() {
		un := *l.Volume - *l.Buy - *l.Sell
		if un < 0 {
			un = 0
		}
		w += 4 + runeLen(commaInt(un)) + 7 + runeLen(commaInt(*l.Volume))
	}
	return w
}

// putBSTWide writes the KSE100 leaders' four fields with the owner's nine digit
// volume positions. It is the wide tile's only volume writer; the packed
// putBST still serves narrow tiles and every other list.
func (a *App) putBSTWide(c *Canvas, x, y int, buy, sell, total *int64, keys ...string) int {
	th := a.th
	vx := x
	put := func(s string, fg RGB, bold bool) {
		vx += a.flashText(c, vx, y, s, fg, bold, keys...)
	}
	putVolume := func(v int64, fg RGB, bold bool) {
		value, comma, pad := volumeCommaParts(v)
		put(value, fg, bold)
		if comma != "" {
			put(comma, th.Soft, false)
		}
		if pad != "" {
			put(pad, fg, bold)
		}
	}
	if buy != nil && sell != nil {
		put("B=", th.Soft, false)
		putVolume(*buy, th.Good, true)
		put("  S=", th.Soft, false)
		putVolume(*sell, th.Bad, true)
		if total != nil {
			un := *total - *buy - *sell
			if un < 0 {
				un = 0
			}
			put("  U=", th.Soft, false)
			put(leaderVolumeField(un), th.Warn, un > 0)
			put("  &  T=", th.Soft, false)
			put(leaderVolumeField(*total), totalBlue, false)
		}
	} else if total != nil {
		put("T=", th.Soft, false)
		put(leaderVolumeField(*total), totalBlue, false)
	}
	return vx - x
}

// putBSTCols writes those four fields into their shared columns and returns the
// cells the block used. The scanner keeps the packed form; the KSE100 leaders
// call putBSTWide for their fixed nine digit columns.
func (a *App) putBSTCols(c *Canvas, x, y int, buy, sell, total *int64, cols bstCols, keys ...string) int {
	_ = cols
	return a.putBST(c, x, y, buy, sell, total, keys...)
}

func (a *App) drawMarket(c *Canvas, x, y, w, h int) {
	th := a.th
	ix, iy, iw, ih := a.panel(c, x, y, w, h, "KSE100 INDEX & THE TOP 3 SCRIPS OF VOLUME", "")
	row := iy
	end := iy + ih
	sparkW := 0
	if iw >= 64 {
		sparkW = min(28, iw-44)
	}
	textW := iw
	if sparkW > 0 {
		textW = iw - sparkW - 2
	}

	if v, ch, pct, _, src, ok := a.effectiveIndex(); ok {
		dir := a.dirColor(ch)
		arrow := "▲"
		if ch < 0 {
			arrow = "▼"
		}
		change := fmt.Sprintf("%s %s (%.2f%%)", arrow, commaFloat(math.Abs(ch), 2), math.Abs(pct))
		tag := ""
		switch src {
		case idxLast:
			tag = "LAST TICK"
		case idxCard:
			tag = "DELAYED"
		}
		// One line: the name, the level and the move, all of one height.
		n := c.Text(ix, row, textW, "KSE100  ", th.Soft, false)
		n += a.flashText(c, ix+n, row, commaFloat(v, 2), th.Text, true, "idx")
		n += a.flashText(c, ix+n+2, row, change, dir, true, "idx") + 2
		// Owner order 2026-11-10 (later): no bar stands in front of the index.
		row++
		meta := ""
		if a.market != nil && a.market.Members > 0 {
			meta = strconv.Itoa(a.market.Members) + " KMIALL members"
		}
		if tag != "" {
			c.Text(ix, row, 12, tag, th.Warn, true)
			if meta != "" {
				c.Text(ix+runeLen(tag)+2, row, textW, "·  "+meta, th.Soft, false)
			}
		} else if meta != "" {
			c.Text(ix, row, textW, fit(meta, textW), th.Soft, false)
		}
		row++
	} else {
		c.Text(ix, row, iw, "KSE100: waiting for the broker feed.", th.Soft, false)
		row += 2
	}
	leaders := a.effectiveLeaders()
	if len(leaders) == 0 {
		if ih >= 9 {
			row++
		}
		msg := "Top three by volume load with the next broker-feed update."
		if a.market != nil && a.market.Answered {
			if strings.Contains(a.market.Basis, "has traded yet") {
				msg = "No stock has traded yet this session."
			} else {
				msg = "Volume leaders unavailable right now."
			}
		}
		if a.market != nil && a.market.Note != "" && !a.market.Answered {
			msg = a.market.Note
		}
		for i, ln := range wrap(msg, iw) {
			if row+i < end {
				c.Text(ix, row+i, iw, ln, th.Soft, false)
			}
		}
		return
	}
	notes := wrap(a.marketNote(), iw)
	if len(notes) > 2 {
		notes = notes[:2]
	}
	board := a.boardRows(3)
	cols := bstLeaderCols(leaders)
	// Owner report 2026-11-11: the bottom two leaders put PKR one cell left
	// of the top one because the price was right aligned and a shorter price
	// pushed its label right. The price field now starts on the same cell on
	// every leader, measured from the widest price, exactly as the top row did.
	pxW := 1
	for _, l := range leaders {
		if l.Price != nil {
			pxW = max(pxW, runeLen(commaFloat(*l.Price, 2)))
		}
	}
	nL := min(len(leaders), 3)
	// Owner order 2026-11-13: the three leaders share one set of columns. The
	// widest volume line sets the cell PKR starts on, the widest price sets the
	// price field, and the change is right aligned at the tile's inner edge, so
	// the label, the price and its change stand on the same cells on all three
	// rows whatever digits they carry. On a wide tile the bar shares the price
	// line; a narrow tile keeps it on the name line, where the room is.
	// Owner order 2026-11-20 (latest): the owner's window gives the KSE100 tile
	// about 76 cells, and there the price, its percentage and NET DELTA must
	// stand on the line that carries T, with the bar on the line above the
	// price. Three exact volume forms are measured and the widest one that
	// leaves room in front of the quote wins: the nine digit fields, the packed
	// form, and the packed form with its thousands commas withdrawn. The last
	// one still writes every digit, so nothing is rounded and no value is cut;
	// only the punctuation gives way, and only on a tile this narrow.
	usedWide, usedPacked, usedBare := 0, 0, 0
	for _, l := range leaders[:nL] {
		usedWide = max(usedWide, leaderBSTWidth(l, cols, true))
		usedPacked = max(usedPacked, leaderBSTPackedWidth(l, cols))
		usedBare = max(usedBare, leaderBSTBareWidth(l))
	}
	edge := ix + iw - 2
	// The group's own width, measured from what drawQuoteNetLast writes: PKR, its
	// price field, one cell, the arrow, one cell, the percentage, one cell, NET
	// DELTA, its equals sign and its figure. Measuring it instead of reserving
	// the old fixed fields is what buys the cells that put the group on the T
	// line at the owner's window.
	pctW, netW := 1, 0
	for _, l := range leaders[:nL] {
		if l.ChangePct != nil {
			pctW = max(pctW, runeLen(pctFixed(*l.ChangePct)))
		}
		if l.HasSplit() {
			v, _, _ := a.searchNet(*l.Buy, *l.Sell)
			netW = max(netW, runeLen(v))
		}
	}
	groupW := quoteLabelW + pxW + quoteGap + 1 + 1 + pctW
	if netW > 0 {
		groupW += quoteGap + quoteNetLabelW + 1 + netW
	}
	// Owner order 2026-11-20: the group is placed by its right end, so it never
	// floats in the middle of the row, and every leader lands on the same cells.
	pkrX := max(ix+3, edge-groupW+1)
	// The widest form that still leaves the price group its room on the same
	// line wins; when none does, the volumes keep the widest form their own line
	// can hold and the group takes the name line after the symbol, where it stood
	// before, rather than painting over a figure. One cell between the last
	// figure and PKR, because at the owner's window the bare form lands one cell
	// past a two cell gutter.
	volForm, quoteOnT := bstBareForm, false
	switch {
	case iw >= 96 && ix+3+usedWide+1 <= pkrX:
		volForm, quoteOnT = bstWideForm, true
	case ix+3+usedPacked+1 <= pkrX:
		volForm, quoteOnT = bstPackedForm, true
	case ix+3+usedBare+1 <= pkrX:
		quoteOnT = true
	case iw >= 96 && 3+usedWide <= iw-2:
		volForm = bstWideForm
	case 3+usedPacked <= iw-2:
		volForm = bstPackedForm
	}
	symW := 0
	for _, l := range leaders[:nL] {
		symW = max(symW, runeLen(l.Symbol))
	}

	// The bottom of the tile, from the bottom up: the note, one blank line, and
	// the BUYING NOW line. The blank line and the spacer under the index are
	// dropped, in that order of loss, only when the window is too short to keep
	// the three leaders and everything else.
	bottom := len(notes)
	if len(board) > 0 {
		bottom++
	}
	gap := 0
	if len(board) > 0 && len(notes) > 0 && end-row >= 2*nL+bottom+1 {
		gap = 1
	}
	if end-row >= 2*nL+bottom+gap+1 {
		row++ // spacer under the index
	}
	limit := end - len(notes) - gap // the leaders and the buying line stay above this
	if len(board) > 0 {
		limit--
	}
	// Owner order 2026-11-20: one layout on every width. The name and its bar on
	// the first row, the volumes and the whole quote group on the second, so a
	// leader is two rows tall and nothing wraps to a third.
	need := 2
	barStart := pkrX
	barW := min(shareBarSpan, edge-barStart+1)
	for i, l := range leaders {
		if row+2 > limit {
			break
		}
		pxKey, volKey := "px:"+l.Symbol, "vol:"+l.Symbol
		c.Spans(ix, row, textW, []Span{{strconv.Itoa(i+1) + ". ", th.Soft, false}, {l.Symbol, th.Hot, true}})
		// Owner order 2026-11-18: the bar stands on the name line, above the
		// current price, and starts on the price's own cell.
		// Owner order 2026-11-20 (latest): the bar stands on the name line above
		// the current price whenever the quote shares the volume line, which is
		// every width the tile can hold it at.
		if quoteOnT && l.HasSplit() && barW >= shareBarBoxes &&
			barStart >= ix+3+runeLen(l.Symbol)+2 && *l.Buy+*l.Sell > 0 {
			a.shareBarOnly(c, barStart, row, barW, *l.Buy, *l.Sell)
		}
		nameRow := row
		row++
		var buy, sell *int64
		if l.HasSplit() {
			buy, sell = l.Buy, l.Sell
		}
		var vol *int64
		if l.HasVolume() {
			vol = l.Volume
		}
		// Owner order 2026-11-10: the row reads B, S, U, T, then the live price
		// and its change, and the bar closes the line after them.
		// Owner order 2026-11-10 (latest): B, S, U and T each start on the same
		// cell on every row, and each number sits hard against its own "=". A
		// narrow tile falls back to the packed form.
		switch volForm {
		case bstWideForm:
			a.putBSTWide(c, ix+3, row, buy, sell, vol, volKey, pxKey)
		case bstPackedForm:
			a.putBSTPacked(c, ix+3, row, buy, sell, vol, cols, volKey, pxKey)
		case bstBareForm:
			a.putBSTBare(c, ix+3, row, buy, sell, vol, volKey, pxKey)
		}
		// Owner order 2026-11-10 (latest): the price and the change are pushed
		// to the tile's far right and right aligned at one edge, so all three
		// leaders line up and nothing floats in the middle of the row.
		// The right edge is the tile's inner width, not textW: textW is the
		// narrow column the symbol line uses, and a price right aligned there
		// painted over the volumes (CI caught "& TPKR 15.24"). Each field also
		// has a fixed width from that edge, so the price, the change and the bar
		// land on the same cells on every leader row.
		if l.Price != nil {
			// Owner order 2026-11-20: PKR, the price, the percentage and NET
			// DELTA close the volume line, in that order, on all three rows.
			px := commaFloat(*l.Price, 2)
			switch {
			case quoteOnT:
				a.drawQuoteNetLast(c, pkrX, row, pxW, px, pxKey, buy, sell, l.ChangePct)
			case ix+3+symW+2+groupW-1 <= edge:
				// No room beside the volumes: the group takes the name line, so
				// the price never leaves the tile and the volumes stay whole.
				a.drawQuoteNetLast(c, ix+3+symW+2, nameRow, pxW, px, pxKey, buy, sell, l.ChangePct)
			}
		}
		row++
		// Spare rows are shared out as a blank line between leaders.
		if left := len(leaders) - i - 1; limit-row-need*left > left {
			row++
		}
	}
	// One line of who is being bought hardest right now, when anyone is.
	if len(board) > 0 && limit < end-len(notes) {
		sp := []Span{{"BUYING NOW  ", th.Soft, false}}
		for _, b := range board {
			sp = append(sp, Span{b.Symbol + " ", th.Hot, true}, Span{compactNum(b.BuyValue) + "   ", th.Good, false})
		}
		c.Spans(ix, limit, iw, sp)
	}
	for i, ln := range notes {
		c.Text(ix, end-len(notes)+i, iw, ln, mix(th.Panel, th.Soft, 0.8), false)
	}
}
