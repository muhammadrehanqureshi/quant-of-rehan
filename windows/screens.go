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
	// telemetry breadth. Above +1500 points is BULLISH, below -500 is
	// BEARISH, and the band between them is FLAT.
	kseBullishPoints = 1500.0
	kseBearishPoints = -500.0
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
// order 2026-11-12: green from 09:00 to 15:49 Monday to Thursday and from
// 09:00 to 16:49 on Friday, red outside those windows and all weekend.
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
	start := scanOpen // 09:00
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
// quant watches is centred on the next line between two thin rules, and the
// rule with a bright segment sweeping along it closes the header. Owner order
// 2026-11-11: the LIVE/LAGGING counter is gone from the top left.
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
	// so the index line keeps its rules to the edge and never cuts the clock.
	rightAlign(c, 0, 0, c.W-1, []Span{{date + " ", ink, false}, {clock, th.Good, true}, {" UTC+5", ink, false}})

	tag := headerTag
	if a.demo {
		tag += "  ·  DEMO DATA"
	}
	tag = fit(tag, c.W)
	tagX := max(0, (c.W-runeLen(tag))/2)
	c.Text(tagX, 1, runeLen(tag), tag, th.Soft, false)
	// Thin rules on both sides of the index line, with a space around the words.
	rule := mix(th.Line, th.BG, 0.25)
	if tagX >= 3 {
		c.HLine(0, 1, tagX-2, '─', rule)
	}
	if end := tagX + runeLen(tag) + 2; end < c.W-1 {
		c.HLine(end, 1, c.W-1-end, '─', rule)
	}

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
			if a.bannerKind == "flow" {
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
		hints = []string{"TAB NEXT  ESC CLEAR  CTRL+C QUIT", "ESC CLEAR  CTRL+C QUIT", "CTRL+C QUIT"}
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

// hintSpans colours the key tokens in the footer: D, R and TAB green, ESC
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
		case "D", "R", "TAB":
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
		return "OFF AT THE WEEKEND", th.Soft
	}
	switch {
	case a.market != nil && a.market.PhaseKnown() && !a.market.TradingDay:
		// Owner order 2026-11-09: a closed trading day names itself.
		return "MARKET IS CLOSED TODAY", th.Soft
	case secondOf(p) < scanOpen*60:
		return "STARTS AT 09:00", th.Soft
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
	if !a.link && !a.lastMarketOK.IsZero() {
		// The header counter is gone, but a dead relay still says how old its
		// last answer is, on the feed row where the staleness belongs.
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
	// exchange's own 09:15 and MARKET CLOSING is the day's own end, 15:49
	// Monday to Thursday and 16:49 on Friday, with no pre and post captions.
	sw, sc := a.scanStatus()
	label(3, "SCAN", []Span{{sw, sc, true}})
	hm := func(m int) string { return fmt.Sprintf("%02d:%02d", m/60, m%60) }
	fullRow(4, "MARKET OPENING", []Span{{hm(preWindow.to), th.Text, false}})
	fullRow(5, "MARKET CLOSING", []Span{{hm(postWindow(a.karachiNow()).to), th.Text, false}})
	// Owner order 2026-11-11: MARKET BREADTH is the KSE100's own point move.
	// Above +1500 points is BULLISH, below -500 is BEARISH, and the band
	// between them is FLAT. ADV/DEC still reads the whole market table.
	adv, dec := a.marketBreadth()
	breadth, bc := "FLAT", th.Soft
	if _, change, _, _, _, ok := a.effectiveIndex(); ok {
		switch {
		case change > kseBullishPoints:
			breadth, bc = "BULLISH", th.Good
		case change < kseBearishPoints:
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
			{", S=", th.Bad, true}, {compactNum(float64(sell)), th.Text, false},
			{" & U=", th.Warn, true}, {compactNum(float64(unclear)), th.Text, false},
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
	rc, note := th.Text, " of 100,000 today"
	switch {
	case rq >= reqHardCap:
		rc, note = th.Bad, " of 100,000 today, paused until 05:00 PKT"
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

	// The record tile sits at the right of the panel.
	wl := a.winLossSpans()
	tileW := max(spanW(wl), runeLen("W/L & W/L RATE"))
	showTile := iw >= 60
	textW := iw
	if showTile {
		textW = iw - tileW - 3
		rightAlign(c, ix, iy, iw, []Span{{"W/L & W/L RATE", th.Soft, false}})
		rightAlign(c, ix, iy+1, iw, wl)
	}

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
		for i := 0; i < len(lines) && i < ih-1; i++ {
			lead := "       "
			if i == 0 {
				lead = "RELAY  "
			}
			c.Text(ix, iy+1+i, 7, lead, th.Line, false)
			c.Text(ix+7, iy+1+i, iw-7, lines[i], th.Soft, false)
		}
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
}

// feedLight is the broker feed's own age, counting each second, shown at the
// top left of every page. It is the one live seconds counter in the window.
func (a *App) feedLight() []Span {
	th := a.th
	switch {
	case a.checking:
		return []Span{{"● ", th.Warn, true}, {"LIVE --", th.Soft, true}}
	case !a.link && !a.lastMarketOK.IsZero():
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
		return "DATA FROM THE BROKER'S FEED IS BEING UPDATED EVERY SECOND."
	case a.quotes != nil && len(a.quotes.Items) > 0:
		return "THE LAST DATA THE BROKER'S FEED SENT."
	}
	// Owner order 2026-11-09: the idle line under the KSE100 tile.
	return "Quant is sleeping till the next market day."
}

// putBST draws "B=1,234, S=5,678, U=12 & T=6,912" at (x, y) the way every list on the
// screen words it, with the live flash on each number. A part that is missing
// is left out. It returns the width drawn.
func (a *App) putBST(c *Canvas, x, y int, buy, sell, total *int64, keys ...string) int {
	th := a.th
	vx := x
	put := func(s string, fg RGB, bold bool) {
		vx += a.flashText(c, vx, y, s, fg, bold, keys...)
	}
	if buy != nil && sell != nil {
		put("B=", th.Soft, false)
		put(commaInt(*buy), th.Good, true)
		put(", S=", th.Soft, false)
		put(commaInt(*sell), th.Bad, true)
		if total != nil {
			// Owner order 2026-11-10: U is on every B and S line, so B + S + U
			// = T can be read at a glance. It is the volume the capture could
			// not side, and it is never folded into B or S.
			un := *total - *buy - *sell
			if un < 0 {
				un = 0
			}
			put(", U=", th.Soft, false)
			put(commaInt(un), th.Warn, un > 0)
			put(" & T=", th.Soft, false)
			put(commaInt(*total), totalBlue, false)
		}
	} else if total != nil {
		put("T=", th.Soft, false)
		put(commaInt(*total), totalBlue, false)
	}
	return vx - x
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
	tot  int // "& T=", after U's number and the gutter
	wid  int // the widest volume's digits, the width of every volume field
}

// bstPad is the gutter between one field's comma and the next field's label.
const bstPad = 2

// bstLeaderCols measures the leaders and returns the columns they share.
func bstLeaderCols(leaders []Leader) bstCols {
	bw, sw, uw := 1, 1, 1
	for _, l := range leaders {
		if !l.HasSplit() {
			continue
		}
		bw = max(bw, runeLen(commaInt(*l.Buy)))
		sw = max(sw, runeLen(commaInt(*l.Sell)))
		if l.HasVolume() {
			uw = max(uw, runeLen(commaInt(*l.Volume)))
		}
	}
	c := bstCols{wid: uw}
	c.sell = c.buy + 2 + bw + 1 + bstPad // "B=", the digits, the comma, the gutter
	c.unc = c.sell + 2 + sw + 1 + bstPad  // "S=", the digits, the comma, the gutter
	c.tot = c.unc + 2 + uw + bstPad       // "U=" and the digits, then the gutter
	return c
}

// putBSTCols writes those four fields into their shared columns and returns the
// cells the block used. A stock with no measured split falls back to putBST.
func (a *App) putBSTCols(c *Canvas, x, y int, buy, sell, total *int64, cols bstCols, keys ...string) int {
	th := a.th
	if buy == nil || sell == nil || total == nil {
		return a.putBST(c, x, y, buy, sell, total, keys...)
	}
	field := func(at int, label, num, tail string, fg RGB, bold bool) {
		w := a.flashText(c, x+at, y, label, th.Soft, false, keys...)
		w += a.flashText(c, x+at+w, y, num, fg, bold, keys...)
		if tail != "" {
			a.flashText(c, x+at+w, y, tail, th.Soft, false, keys...)
		}
	}
	un := *total - *buy - *sell
	if un < 0 {
		un = 0
	}
	field(cols.buy, "B=", commaInt(*buy), ",", th.Good, true)
	field(cols.sell, "S=", commaInt(*sell), ",", th.Bad, true)
	field(cols.unc, "U=", commaInt(un), "", th.Warn, un > 0)
	field(cols.tot, "& T=", commaInt(*total), "", totalBlue, false)
	return cols.tot + 4 + cols.wid
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

	// The bottom of the tile, from the bottom up: the note, one blank line, and
	// the BUYING NOW line. The blank line and the spacer under the index are
	// dropped, in that order of loss, only when the window is too short to keep
	// the three leaders and everything else.
	nL := min(len(leaders), 3)
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
	for i, l := range leaders {
		if row+2 > limit {
			break
		}
		pxKey, volKey := "px:"+l.Symbol, "vol:"+l.Symbol
		c.Spans(ix, row, textW, []Span{{strconv.Itoa(i+1) + ". ", th.Soft, false}, {l.Symbol, th.Hot, true}})
		// Owner order 2026-11-10 (later): no bar stands in front of a stock's
		// name either. The green and red bar belongs on the percentage line.
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
		used := 0
		if iw >= 96 {
			used = a.putBSTCols(c, ix+3, row, buy, sell, vol, cols, volKey, pxKey)
		} else {
			used = a.putBST(c, ix+3, row, buy, sell, vol, volKey, pxKey)
		}
		// Owner order 2026-11-10 (latest): the price, the change and the bar are
		// pushed to the tile's far right and right aligned at one edge, so all
		// three leaders line up and nothing floats in the middle of the row. The
		// bar keeps the same distance from the price on every row.
		// The right edge is the tile's inner width, not textW: textW is the
		// narrow column the symbol line uses, and a price right aligned there
		// painted over the volumes (CI caught "& TPKR 15.24"). Each of the
		// three fields also has a fixed width from that edge, so the price, the
		// change and the bar land on the same cells on every leader row.
		if l.Price != nil {
			const chgW = 8
			end := ix + iw - 1
			// Owner order 2026-11-12 (latest): the bar's field carries its
			// NET DELTA too, so the leader line's last field is the labelled
			// bar and the price and the change step left by its width.
			bw := shareBarWidth
			floor := ix + 3 + used + 1
			barStart := end - bw + 1
			chgRight := barStart - 2
			priceRight := chgRight - chgW - 1
			px := commaFloat(*l.Price, 2)
			// Owner order 2026-11-10 (latest): PKR sits one space from its own
			// price. The price stays right aligned at its own edge, so the label
			// moves and the number does not; the old ten cell field left five
			// empty cells between the two. flashRight's cell is the one after its
			// last character, so the price covers [priceRight-len, priceRight-1]
			// and PKR stands four cells to its left, leaving exactly one space.
			pkrLeft := priceRight - pxW - 4
			priceBlock := 4 + runeLen(px) + chgW + 1
			showPrice := func(pkr, pxRight, chgRight int) {
				// The label is written without its trailing space and the price
				// starts four cells along, so exactly one blank cell stands
				// between them and the row reads "PKR 15.24".
				c.Text(pkr, row, 3, "PKR", th.Soft, false)
				// The price starts one cell after PKR on every leader, so the
				// label and the number stand on the same cells on all three rows.
				a.flashText(c, pkr+4, row, px, th.Text, true, pxKey)
				if l.ChangePct != nil {
					a.flashRight(c, chgRight, row, changeText(*l.ChangePct), a.dirColor(*l.ChangePct), true, pxKey)
				}
			}
			switch {
			case pkrLeft >= floor:
				showPrice(pkrLeft, priceRight, chgRight)
				if l.HasSplit() {
					if total := *l.Buy + *l.Sell; total > 0 {
						bb, bs := a.pairOf(l.Symbol, *l.Buy, *l.Sell)
						// Owner order 2026-11-12 (latest): every bar in the build
						// carries its NET DELTA, the leaders row included.
						a.shareBar(c, barStart, row, bw, bb, bs)
					}
				}
			case end-priceBlock >= floor:
				// Owner order 2026-11-12: PKR never gives up its cells. When
				// the bar cannot fit beside it, the price and the change stay
				// at the tile's right edge and the bar steps out instead.
				showPrice(end-priceBlock, end-chgW-1, end)
			default:
				// Very short: PKR and the price follow the volumes, as they did
				// before, so the row still carries its price beside its T volume.
				pw := runeLen(px)
				pkr := ix + 3 + used + 2
				if pkr+4+pw <= ix+iw {
					c.Text(pkr, row, 3, "PKR", th.Soft, false)
					a.flashText(c, pkr+4, row, px, th.Text, true, pxKey)
				}
			}
		}
		row++
		// Spare rows are shared out as a blank line between leaders.
		if left := len(leaders) - i - 1; limit-row-2*left > left {
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
