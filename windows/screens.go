package main

import (
	"fmt"
	"math"
	"strconv"
	"strings"
	"time"
)

const (
	minW = 80
	minH = 26
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
// order 2026-11-09 (build 29): green from 08:55 to 16:00 Monday to Thursday
// and from 08:55 to 17:00 on Friday, red outside those windows and all weekend.
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
	start := scanOpen // 08:55
	end := 16 * 60
	if isFriday(p) {
		end = 17 * 60
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
		// show dot for dot. The column widens with the window for that reason
		// and stops at 60 cells, keeping 40 at the 120 column home size.
		lw := min(max(a.w/3, 40), 60)
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
// rectangle: heavy corners, a thin line, a bright bar at the top right and the
// bottom left, the title after a diamond in the top edge and the hint, when
// there is one, at its right end.
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
	c.HLine(x+1, y+h-1, 3, '━', th.Accent)
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

// drawHeader is the top of the window: the live feed counter on the left, the
// name centred between two diamonds in the brightest ink, and the date and 24
// hour clock on the right in a darker shade, with the clock itself green and
// UTC+5 after it. The index the quant watches is centred on the next line
// between two thin rules, and the rule with a bright segment sweeping along it
// closes the header.
func (a *App) drawHeader(c *Canvas) {
	th := a.th
	title := headerTitle
	lt := a.feedLight()
	if len(lt) > 0 && c.W >= runeLen(title)+spanW(lt)+4 {
		c.Spans(1, 0, min(c.W-2, spanW(lt)), lt)
	}
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
		hints = []string{"D DETAILS  TAB NEXT  R REFRESH  Q QUIT", "D DETAILS  R REFRESH  Q QUIT", "D DETAILS  Q QUIT", "Q QUIT"}
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
		return "STARTS AT 08:55", th.Soft
	}
	return "DONE FOR TODAY", th.Soft
}

// ---------- left column: orb and telemetry ----------

func (a *App) drawLeft(c *Canvas, x, y, w, h int) {
	th := a.th
	const telH = 9
	orbH := h - telH - 1
	ix, iy, iw, ih := a.panel(c, x, y, w, orbH, "QUANT CORE", "")
	drawOrb(c, ix, iy, iw, ih, a.animSeconds(), a.orbMode(), a.orbGreen(), th)

	tx, ty, tw, _ := a.panel(c, x, y+orbH+1, w, telH, "TELEMETRY", "")
	const labelW = 7
	label := func(row int, k string, v []Span) {
		c.Text(tx, ty+row, labelW, k, th.Soft, false)
		c.Spans(tx+labelW, ty+row, tw-labelW, v)
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
	if a.quotes != nil && !a.checking {
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
	// PHASE
	ph := a.phase()
	if ph == "" {
		ph = "--"
	}
	pc := th.Text
	if a.isLive() {
		pc = th.Good
	}
	label(2, "PHASE", []Span{{ph, pc, true}})
	// NEXT
	next := "--"
	if a.head != nil && a.head.NextEvent != "" {
		next = a.head.NextEvent
	} else if a.market != nil && a.market.NextEvent != "" {
		next = a.market.NextEvent
	}
	label(3, "NEXT", []Span{{fit(friendlyNext(next), tw-7), th.Text, false}})
	// SCAN
	sw, sc := a.scanStatus()
	label(4, "SCAN", []Span{{sw, sc, true}})
	// FLOW. Owner order 2026-11-09 (latest): buying, selling and unclear are
	// three separate numbers. The two sides are never printed as one figure and
	// U never joins either of them; U appears only when some volume in the
	// window could not be sided.
	if a.cfg.BigBuy || a.cfg.BigSell {
		buy, sell, unclear := a.flow.WindowSides(a.karachiNow(), time.Minute)
		spans := []Span{
			{"BUY ", th.Good, true}, {compactNum(float64(buy)), th.Text, false},
			{"  SELL ", th.Bad, true}, {compactNum(float64(sell)), th.Text, false},
		}
		if unclear > 0 {
			spans = append(spans,
				Span{"  U ", th.Warn, true},
				Span{compactNum(float64(unclear)), th.Text, false})
		}
		label(5, "FLOW", spans)
	} else {
		label(5, "FLOW", []Span{{"OFF", th.Bad, true}})
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
	label(6, "REQ", []Span{{commaInt(rq), rc, false}, {note, th.Soft, false}})
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
	sigH := 7
	const marketFull = 14 // two rows of index, a spacer, three leaders, buying, a gap and the note
	if mh := y + h - (gy + sigH + gap); mh < marketFull && w >= 60 {
		sigH = 5
	}
	a.drawSignal(c, x, gy, w, sigH, sigH == 5)
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
	if twoCol {
		mid := ix + iw/2
		put(ix, iy, "SYMBOL", sym, th.Hot)
		put(ix, iy+1, "ENTRY TIME", f.Time, th.Text)
		put(ix, iy+2, "ENTRY PRICE", f.Entry, th.Text)
		put(mid, iy+1, "TAKE PROFIT", f.Exit, th.Good)
		put(mid, iy+2, "STOP LOSS", f.Stop, th.Bad)
	} else {
		put(ix, iy, "SYMBOL", sym, th.Hot)
		put(ix, iy+1, "ENTRY TIME", f.Time, th.Text)
		put(ix, iy+2, "ENTRY PRICE", f.Entry, th.Text)
		put(ix, iy+3, "TAKE PROFIT", f.Exit, th.Good)
		put(ix, iy+4, "STOP LOSS", f.Stop, th.Bad)
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
		return "Data from the broker's feed is being updated every second."
	case a.quotes != nil && len(a.quotes.Items) > 0:
		return "The last data the broker's feed sent."
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
		used := a.putBST(c, ix+3, row, buy, sell, vol, volKey, pxKey)
		vx := ix + 3 + used + 2
		if l.Price != nil {
			vx += a.flashText(c, vx, row, "PKR ", th.Soft, false)
			vx += a.flashText(c, vx, row, commaFloat(*l.Price, 2), th.Text, true, pxKey)
			if l.ChangePct != nil {
				vx += a.flashText(c, vx+1, row, changeText(*l.ChangePct), a.dirColor(*l.ChangePct), true, pxKey) + 1
			}
		}
		// Owner order 2026-11-10 (latest): the bar is last, after the price and
		// the change, so the KSE100 tile reads volume, price, change, then bar.
		if l.HasSplit() {
			if total := *l.Buy + *l.Sell; total > 0 && ix+iw-vx-1 >= shareBarBoxes {
				a.shareBarOnly(c, vx+1, row, shareBarWidth, float64(*l.Buy)/float64(total))
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
