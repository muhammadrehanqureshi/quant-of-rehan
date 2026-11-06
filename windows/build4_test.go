package main

import (
	"fmt"
	"math"
	"net/http"
	"regexp"
	"strings"
	"testing"
	"time"
)

// busyApp is a demo app whose flow board holds n stocks being bought, the
// biggest first, so lists have more rows than the window can show.
func busyApp(t *testing.T, w, h, n int) *App {
	t.Helper()
	a := demoApp(t, w, h)
	a.now = time.Date(2026, 10, 30, 11, 42, 18, 0, pkt)
	a.flow.sym = map[string]*symFlow{}
	for i := 1; i <= n; i++ {
		sym := fmt.Sprintf("S%02d", i)
		a.flow.sym[sym] = &symFlow{have: true, px: 10, t: a.now,
			evts: []flowEvt{{t: a.now.Add(-5 * time.Second), dv: int64(1_000_000 * (n + 1 - i)), px: 10, side: 1}}}
	}
	return a
}

func TestScannerFlowListScrollsAndNeverCutsAnItem(t *testing.T) {
	a := busyApp(t, 122, 30, 30)
	a.screen, a.scanChoice = scrScanner, 3
	if s := plain(a); !strings.Contains(s, "  1. S01") {
		t.Fatalf("the first stock must be numbered 1:\n%s", s)
	}
	view := a.lvScan.view
	if view < 3 || view >= 30 {
		t.Fatalf("the list should show a few stocks and scroll for the rest, view %d", view)
	}
	// Every shown item has both of its rows: a title row and a B, S and T row.
	rows := rowsOf(a)
	titles, bst := 0, 0
	for _, r := range rows {
		if regexp.MustCompile(`^.*\s\d+\. S\d\d`).MatchString(r) && strings.Contains(r, "PKR") {
			titles++
		}
		if strings.Contains(r, "B=") {
			bst++
		}
	}
	if titles != view || bst != view {
		t.Errorf("view %d: %d title rows and %d B, S & T rows", view, titles, bst)
	}
	a.onKey(Key{Kind: KEnd})
	last := plain(a)
	if !strings.Contains(last, " 30. S30") || strings.Contains(last, "  1. S01") {
		t.Errorf("End must reach stock 30:\n%s", last)
	}
	a.onKey(Key{Kind: KHome})
	if !strings.Contains(plain(a), "  1. S01") {
		t.Errorf("Home must come back to stock 1")
	}
	a.onKey(Key{Kind: KPgDn})
	if a.lvScan.off != view-1 {
		t.Errorf("page down moves one page less a row of overlap: %d", a.lvScan.off)
	}
	a.onKey(Key{Kind: KUp})
	if a.lvScan.off != view-2 {
		t.Errorf("up moves one stock: %d", a.lvScan.off)
	}
	for i := 0; i < 100; i++ {
		a.onKey(Key{Kind: KMouse, X: 60, Y: 20, Btn: MouseWheelDown})
	}
	if a.lvScan.off != 30-view {
		t.Errorf("the wheel stops at the end: %d", a.lvScan.off)
	}
	for i := 0; i < 100; i++ {
		a.onKey(Key{Kind: KMouse, X: 60, Y: 20, Btn: MouseWheelUp})
	}
	if a.lvScan.off != 0 {
		t.Errorf("the wheel stops at the top: %d", a.lvScan.off)
	}
}

func TestAlertsBoardIsNumberedAndScrolls(t *testing.T) {
	a := busyApp(t, 122, 30, 25)
	a.screen = scrAlerts
	s := plain(a)
	for _, want := range []string{`\b1\.\s+S01`, `\b2\.\s+S02`, `\b3\.\s+S03`} {
		if !regexp.MustCompile(want).MatchString(s) {
			t.Errorf("the big buying board must carry sequence numbers, missing %q:\n%s", want, s)
		}
	}
	last := regexp.MustCompile(`\b25\.\s+S25`)
	if last.MatchString(s) {
		t.Fatalf("25 rows cannot fit at first")
	}
	a.onKey(Key{Kind: KEnd})
	if s := plain(a); !last.MatchString(s) {
		t.Errorf("End must reach the last stock:\n%s", s)
	}
	// The keys follow the focus: RIGHT moves to the log, which has nothing to scroll.
	a.onKey(Key{Kind: KRight})
	a.onKey(Key{Kind: KHome})
	if a.lvBoard.off == 0 {
		t.Errorf("Home must scroll the log now, not the board")
	}
	a.onKey(Key{Kind: KLeft})
	a.onKey(Key{Kind: KHome})
	if a.lvBoard.off != 0 {
		t.Errorf("Home must scroll the board when it has the focus: %d", a.lvBoard.off)
	}
}

// B, S and T are written one way on every screen: B=1, S=2 & T=3.
func TestBSTFormatEverywhere(t *testing.T) {
	good := regexp.MustCompile(`B=[\d,]+, S=[\d,]+ & T=[\d,]+`)
	bad := regexp.MustCompile(`B=[\d,]+\s{2,}S=|S=[\d,]+\s{2,}T=|\(B=|\)\s*$`)
	for _, c := range []struct {
		name string
		set  func(a *App)
	}{
		{"home", func(a *App) {}},
		{"scanner rising", func(a *App) { a.screen, a.scanChoice = scrScanner, 1 }},
		{"scanner buyers", func(a *App) { a.screen, a.scanChoice = scrScanner, 2 }},
		{"scanner flow", func(a *App) { a.screen, a.scanChoice = scrScanner, 3 }},
		{"search", func(a *App) {
			a.screen = scrScanner
			for _, r := range "alf" {
				a.onKey(Key{Kind: KRune, R: r})
			}
			a.onKey(Key{Kind: KEnter})
		}},
	} {
		a := busyApp(t, 122, 30, 6)
		c.set(a)
		s := plain(a)
		if !good.MatchString(s) {
			t.Errorf("%s: no 'B=1, S=2 & T=3' anywhere:\n%s", c.name, s)
		}
		if loc := bad.FindString(s); loc != "" {
			t.Errorf("%s: old spacing %q still on screen", c.name, loc)
		}
	}
}

func TestHomeWordingAndLayoutAt122x30(t *testing.T) {
	a := busyApp(t, 122, 30, 3)
	rows := rowsOf(a)
	s := strings.Join(rows, "\n")
	if !strings.Contains(s, "KSE100 INDEX & THE TOP 3 SCRIPS OF VOLUME") {
		t.Errorf("the market tile has the new title")
	}
	for _, gone := range []string{"Live from your broker feed", "B and S are estimates", "as of ", "Karachi:", "KSE100 & TOP 3"} {
		if strings.Contains(s, gone) {
			t.Errorf("%q must be gone", gone)
		}
	}
	// The greeting and status tiles are separated by one blank row, and so are
	// the status and signal tiles. A thirty row window shows the first two
	// leaders; the third arrives when the window is tall enough.
	var greet, status, signal int
	for y, r := range rows {
		switch {
		case strings.Contains(r, "GREETING"):
			greet = y
		case strings.Contains(r, "QUANT STATUS"):
			status = y
		case strings.Contains(r, "LATEST SIGNAL"):
			signal = y
		}
	}
	if status-greet != 4 || signal-(status+3) != 2 {
		t.Errorf("greeting %d, status %d, signal %d: want one blank row between the three tiles", greet, status, signal)
	}
	for _, n := range []string{"1. ", "2. "} {
		if !strings.Contains(s, n) {
			t.Errorf("leader %q is missing at 122x30", n)
		}
	}
	tall := busyApp(t, 158, 41, 3)
	for _, n := range []string{"1. ", "2. ", "3. "} {
		if !strings.Contains(strings.Join(rowsOf(tall), "\n"), n) {
			t.Errorf("leader %q is missing at 158x41", n)
		}
	}
	if len(rows) != 30 {
		t.Errorf("rows: %d", len(rows))
	}
}

func TestStatusWordingFollowsThePart(t *testing.T) {
	at := func(day, h, m int) time.Time { return time.Date(2026, 11, day, h, m, 0, 0, pkt) } // 2 is a Monday, 6 a Friday
	for _, c := range []struct {
		name   string
		t      time.Time
		phase  string
		want   string
		online bool
	}{
		{"before the pre-market", at(2, 8, 30), "PRE_OPEN", "Market is closed and the quant is offline now.", false},
		{"pre-market", at(2, 9, 5), "PRE_OPEN", "Pre-market is running and the quant is online now.", true},
		{"matching gap", at(2, 9, 31), "PRE_OPEN", "Pre-market is running and the quant is online now.", true},
		{"open", at(2, 11, 0), "OPEN", "Market is open and the quant is online now.", true},
		{"post-market", at(2, 15, 40), "POST_CLOSE", "Post-market is running and the quant is online now.", true},
		{"after the post-market", at(2, 15, 50), "POST_CLOSE", "Market is closed and the quant is offline now.", false},
		{"evening", at(2, 20, 0), "POST_CLOSE", "Market is closed and the quant is offline now.", false},
		{"friday break", at(6, 13, 0), "BREAK", "Market is on a break and the quant is offline now.", false},
		{"friday second session", at(6, 15, 0), "OPEN", "Market is open and the quant is online now.", true},
		{"friday post-market", at(6, 16, 40), "POST_CLOSE", "Post-market is running and the quant is online now.", true},
		{"weekend", at(7, 11, 0), "CLOSED", "Market is closed and the quant is offline now.", false},
	} {
		a := newTestApp(t)
		a.now, a.checking, a.link = c.t, false, true
		m := marketIn(c.phase)
		m.TradingDay = c.phase != "CLOSED"
		a.market, a.marketOpen = m, c.phase == "OPEN"
		if got := a.statusNote(); got != c.want {
			t.Errorf("%s: %q, want %q", c.name, got, c.want)
		}
		if a.online() != c.online {
			t.Errorf("%s: online %v, want %v", c.name, a.online(), c.online)
		}
	}
	a := newTestApp(t)
	a.checking, a.link = false, false
	a.relayErr = "The relay did not answer in time. Will retry. (Timeout)"
	if a.online() || a.orbMode() != OrbFault {
		t.Errorf("an unreachable relay means the quant is offline")
	}
}

func TestPhaseAtMatchesTheSessionLaw(t *testing.T) {
	at := func(day, h, m int) time.Time { return time.Date(2026, 11, day, h, m, 0, 0, pkt) }
	for _, c := range []struct {
		t    time.Time
		want string
	}{
		{at(2, 8, 59), qsClosed}, {at(2, 9, 0), qsPre}, {at(2, 9, 31), qsPre}, {at(2, 9, 32), qsOpen},
		{at(2, 15, 29), qsOpen}, {at(2, 15, 30), qsPost}, {at(2, 15, 48), qsPost}, {at(2, 15, 49), qsClosed},
		{at(6, 9, 16), qsPre}, {at(6, 9, 17), qsOpen}, {at(6, 12, 0), qsBreak}, {at(6, 14, 31), qsBreak},
		{at(6, 14, 32), qsOpen}, {at(6, 16, 29), qsOpen}, {at(6, 16, 30), qsPost}, {at(6, 16, 49), qsClosed},
		{at(7, 11, 0), qsClosed}, {at(8, 11, 0), qsClosed},
	} {
		if got := phaseAt(c.t); got != c.want {
			t.Errorf("%v: %s, want %s", c.t.Format("Mon 15:04"), got, c.want)
		}
	}
}

// The HUD dial turns while the quant is online and is perfectly still while it
// is parked. Its ink is the picture's pale ice blue in every theme; the old
// gold sun, wireframe and radar sweep are gone.
func TestMarkTurnsOnlineAndIsStillOffline(t *testing.T) {
	th := themeAt(0)
	paint := func(mode OrbMode, secs float64) *Canvas {
		c := NewCanvas(38, 14, th.BG)
		drawOrb(c, 0, 0, 38, 14, secs, mode, th)
		return c
	}
	same := func(a, b *Canvas) bool {
		for i := range a.Cells {
			if a.Cells[i] != b.Cells[i] {
				return false
			}
		}
		return true
	}
	if same(paint(OrbBurning, 1.0), paint(OrbBurning, 1.5)) {
		t.Errorf("online, the wireframe sphere must turn")
	}
	for _, m := range []OrbMode{OrbParked, OrbFault} {
		if !same(paint(m, 1.0), paint(m, 9.7)) {
			t.Errorf("offline (mode %d), the mark must be still", m)
		}
	}
	pale := func(c *Canvas) int {
		n := 0
		for _, ce := range c.Cells {
			if _, ok := quadrantMask(ce.Ch); !ok {
				continue
			}
			for _, p := range cellPixels(ce) {
				if p.B >= 180 && p.G >= 150 && p.R >= 120 {
					n++
				}
			}
		}
		return n
	}
	if n := pale(paint(OrbBurning, 2)); n < 150 {
		t.Errorf("online mark: only %d pale blue pixels", n)
	}
	for i := range themes {
		c := NewCanvas(38, 14, themeAt(i).BG)
		drawOrb(c, 0, 0, 38, 14, 2, OrbBurning, themeAt(i))
		if n := pale(c); n < 150 {
			t.Errorf("theme %d: the mark is not the picture's pale blue", i)
		}
	}
}

// A terminal cell is taller than it is wide (cellAspect times), so a round
// ring must be about cellAspect times as many columns across as rows tall. The
// first radar was drawn as if cells were square and came out tall. It is
// checked at the owner's measured shape and at the common 20 / 9.
func TestRadarIsRoundInPixels(t *testing.T) {
	th := themeAt(0)
	was := cellAspect
	defer func() { cellAspect = was }()
	for _, aspect := range []float64{1.90, 20.0 / 9.0, 2.05} {
		cellAspect = aspect
		for _, sz := range [][2]int{{36, 14}, {30, 12}, {38, 25}} {
			c := NewCanvas(sz[0], sz[1], th.BG)
			drawOrb(c, 0, 0, sz[0], sz[1], 2, OrbBurning, th)
			// Find the lit pixels. A cell is 2 by 2 pixels, so a pixel is half a
			// column wide and aspect/2 columns tall.
			lit := func(p RGB) bool { return max(p.R, max(p.G, p.B)) > 70 }
			minX, maxX, minY, maxY := 1<<30, -1, 1<<30, -1
			for y := 0; y < c.H; y++ {
				for x := 0; x < c.W; x++ {
					ce := c.Cells[y*c.W+x]
					if _, ok := quadrantMask(ce.Ch); !ok {
						continue
					}
					for i, p := range cellPixels(ce) {
						if lit(p) {
							px, py := 2*x+i%2, 2*y+i/2
							minX, maxX = min(minX, px), max(maxX, px)
							minY, maxY = min(minY, py), max(maxY, py)
						}
					}
				}
			}
			wpx, hpx := float64(maxX-minX+1)/2, float64(maxY-minY+1)*aspect/2
			if ratio := wpx / hpx; math.Abs(ratio-1) > 0.12 {
				t.Errorf("aspect %.2f, %dx%d cells: ring is %.0f x %.0f units, ratio %.2f", aspect, sz[0], sz[1], wpx, hpx, ratio)
			}
		}
	}
}

// Every glyph on every screen must be one the Windows Terminal font draws:
// plain text, the box, block and Braille ranges the terminal draws itself, and
// a few Windows glyph list 4 shapes. The first build's diamond U+25C6 is kept
// on purpose: the owner asked for the first build's look and font.
func TestOnlySafeGlyphsOnScreen(t *testing.T) {
	allowed := func(r rune) bool {
		switch {
		case r >= 0x20 && r < 0x7f:
			return true
		case r >= 0x2500 && r <= 0x259f, r >= 0x2800 && r <= 0x28ff:
			return true
		}
		return strings.ContainsRune("·…▲▼●◆♦♪▪", r)
	}
	for _, sz := range [][2]int{{80, 26}, {122, 30}, {160, 45}} {
		for scr := range screenNames {
			for _, st := range []string{"", "closed", "fault", "alert"} {
				a := busyApp(t, sz[0], sz[1], 8)
				a.screen = screenID(scr)
				if scr == int(scrScanner) {
					a.scanChoice = 3
				}
				snapshotState(a, st)
				for y, row := range rowsOf(a) {
					for _, r := range row {
						if !allowed(r) {
							t.Fatalf("%dx%d screen %d state %q row %d: glyph %U %q is not safe", sz[0], sz[1], scr, st, y, r, string(r))
						}
					}
				}
			}
		}
	}
}

func TestRelayClockFollowsTheEdgeWhenThePCIsWrong(t *testing.T) {
	a := newTestApp(t)
	pc := time.Date(2026, 11, 2, 10, 0, 0, 0, pkt)
	a.now = pc
	if !a.karachiNow().Equal(pc) {
		t.Fatalf("with no answer yet the PC clock is used")
	}
	// The relay says it is 10 minutes later than the PC does.
	for i := 0; i < 5; i++ {
		edge := pc.Add(10 * time.Minute).Add(-400 * time.Millisecond)
		a.relay.noteDate(edge.UTC().Format(http.TimeFormat), pc, pc.Add(60*time.Millisecond))
	}
	got := a.karachiNow().Sub(pc)
	if got < 9*time.Minute+58*time.Second || got > 10*time.Minute+2*time.Second {
		t.Errorf("the clock should be 10 minutes ahead, it is %v", got)
	}
	// A PC that agrees within two seconds keeps its own clock, so the seconds never jitter.
	b := newTestApp(t)
	b.now = pc
	for i := 0; i < 10; i++ {
		b.relay.noteDate(pc.Add(-300*time.Millisecond).UTC().Format(http.TimeFormat), pc, pc.Add(40*time.Millisecond))
	}
	if !b.karachiNow().Equal(pc) {
		t.Errorf("a PC within two seconds keeps its own clock: %v", b.karachiNow().Sub(pc))
	}
}

// The footnote of the market tile is the one sentence the owner asked for, and
// it says so only while the feed is being read every second.
func TestMarketFootnote(t *testing.T) {
	a := newTestApp(t)
	a.now = time.Date(2026, 11, 2, 11, 0, 0, 0, pkt)
	a.market = marketIn("OPEN")
	a.quotes = quotesAt(15, 1_000_000)
	if got := a.marketNote(); got != "Data from the broker's feed is being updated every second." {
		t.Errorf("live footnote: %q", got)
	}
	a.now = time.Date(2026, 11, 2, 20, 0, 0, 0, pkt)
	a.market = marketIn("POST_CLOSE")
	if got := a.marketNote(); got != "The last data the broker's feed sent." {
		t.Errorf("closed footnote: %q", got)
	}
	a.quotes = nil
	if got := a.marketNote(); got != "Waiting for the broker feed." {
		t.Errorf("no feed footnote: %q", got)
	}
}

// cellPixels gives the four pixels a quadrant character shows: upper left,
// upper right, lower left, lower right.
func cellPixels(ce Cell) [4]RGB {
	m, _ := quadrantMask(ce.Ch)
	var q [4]RGB
	for i := range q {
		if m&(1<<i) != 0 {
			q[i] = ce.FG
		} else {
			q[i] = ce.BG
		}
	}
	return q
}
