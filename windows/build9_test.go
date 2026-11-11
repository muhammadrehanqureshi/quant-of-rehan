package main

import (
	"strings"
	"testing"
	"time"
)

// Owner order 2026-11-11: the telemetry tile carries the exchange's daily
// market hours, the KSE100's breadth, the advancers and decliners, and the
// whole market's net delta, and the old NEXT line is gone.
func TestTelemetryCarriesMarketHoursBreadthAndDelta(t *testing.T) {
	a := newTestApp(t)
	a.w, a.h = 120, 34
	a.link, a.checking = true, false
	a.now = time.Date(2026, 11, 2, 10, 0, 0, 0, pkt)
	a.market = marketIn("OPEN")
	a.quotes = &Quotes{FetchedAt: a.now, Index: &IndexQuote{
		Value: 166409.25, Change: 1600, ChangePct: 0.96, Fresh: true,
	}, Items: map[string]LiveQuote{
		"AAA": {Price: 10, Fresh: true, ChangePct: f64(1.2)},
		"BBB": {Price: 20, Fresh: true, ChangePct: f64(-0.8)},
		"CCC": {Price: 30, Fresh: true, ChangePct: f64(2.0)},
	}}
	a.prices = map[string]Quote{
		"AAA": {Price: 10, ChangePct: f64(1.2), Buy: i64(700), Sell: i64(200)},
		"BBB": {Price: 20, ChangePct: f64(-0.8), Buy: i64(100), Sell: i64(900)},
	}
	s := plain(a)
	for _, want := range []string{
		"MARKET OPENING", "PRE 09:00 OPEN 09:32", "MARKET CLOSING", "15:30 POST 16:00",
		"MARKET BREADTH", "BULLISH", "ADV/DEC", "2/1",
		"NET DELTA", "-300", "TOP PERFORMERS", "CCC, AAA & BBB",
	} {
		if !strings.Contains(s, want) {
			t.Errorf("telemetry is missing %q:\n%s", want, s)
		}
	}
	// Owner order 2026-11-11: the KSE100's own point move decides the
	// telemetry breadth, not the count of advancers.
	a.quotes.Index.Change = -600
	if got := plain(a); !strings.Contains(got, "BEARISH") || strings.Contains(got, "BULLISH") {
		t.Errorf("KSE100 -600 points must read BEARISH:\n%s", got)
	}
	a.quotes.Index.Change = 0
	if got := plain(a); !strings.Contains(got, "FLAT") {
		t.Errorf("KSE100 flat must read FLAT:\n%s", got)
	}
	for _, row := range rowsOf(a) {
		if strings.Contains(row, "NEXT") && !strings.Contains(row, "TAB NEXT") {
			t.Errorf("the NEXT line is still in the build: %q", row)
		}
	}
	// Owner order 2026-11-11: SCAN follows PHASE, and TOP PERFORMERS follows
	// NET DELTA.
	at := func(sub string) int {
		for i, row := range rowsOf(a) {
			if strings.Contains(row, sub) {
				return i
			}
		}
		return -1
	}
	if !(at("PHASE") < at("EVERY SECOND") && at("EVERY SECOND") < at("MARKET OPENING")) {
		t.Errorf("SCAN does not follow PHASE:\n%s", s)
	}
	if !(at("NET DELTA") < at("TOP PERFORMERS") && at("TOP PERFORMERS") < at("BUY=")) {
		t.Errorf("TOP PERFORMERS does not follow NET DELTA:\n%s", s)
	}
}

// The phase word is OPEN in the session and PRE or POST in the exchange's
// pre-open and post-close windows.
func TestTelemetryPhaseUsesPreAndPost(t *testing.T) {
	a := newTestApp(t)
	a.w, a.h = 120, 34
	a.link, a.checking = true, false
	a.marketOpen = false
	a.market = marketIn("PRE_OPEN")
	a.market.TradingDay = true
	a.now = time.Date(2026, 11, 2, 9, 20, 0, 0, pkt)
	if got := a.quantPhase(); got != qsPre {
		t.Fatalf("09:20 phase: %q want %q", got, qsPre)
	}
	a.now = time.Date(2026, 11, 2, 15, 45, 0, 0, pkt)
	a.market = marketIn("POST_CLOSE")
	a.market.TradingDay = true
	if got := a.quantPhase(); got != qsPost {
		t.Fatalf("15:45 phase: %q want %q", got, qsPost)
	}
}

// Owner order 2026-11-11: the panel frame is symmetrical top to bottom, with
// its bright bar at the right end of both edges.
func TestPanelAccentsAreSymmetric(t *testing.T) {
	a := newTestApp(t)
	c := NewCanvas(40, 8, a.th.Panel)
	a.panel(c, 0, 0, 40, 8, "QUANT CORE", "")
	rows := c.PlainRows()
	top, bottom := []rune(rows[0]), []rune(rows[7])
	for _, i := range []int{36, 37, 38} {
		if top[i] != '━' || bottom[i] != '━' {
			t.Fatalf("the edges are not mirrored at column %d: %q / %q", i, rows[0], rows[7])
		}
	}
	if top[1] == '━' || bottom[1] == '━' {
		t.Fatalf("an accent sits at the left end: %q / %q", rows[0], rows[7])
	}
}

// Owner order 2026-11-11: the NET DELTA value carries no plus sign when it is
// positive and keeps its minus when it is negative.
func TestNetDeltaHasNoPlusSign(t *testing.T) {
	if got := signedCompact(300); got != "300" {
		t.Fatalf("a rise reads %q, want 300 with no plus", got)
	}
	if got := signedCompact(-300); got != "-300" {
		t.Fatalf("a fall reads %q, want -300", got)
	}
}

// Owner order 2026-11-11: the top and the bottom of the left column are the
// same height, so the orb and the telemetry sit in matching frames.
func TestLeftColumnTilesAreSymmetric(t *testing.T) {
	for _, h := range []int{26, 30, 41, 60} {
		core, tel := leftTileHeights(h)
		if core+tel+1 != h {
			t.Fatalf("h %d: the tiles take %d rows plus the gap, not %d", h, core+tel, h)
		}
		if d := core - tel; d < -1 || d > 1 {
			t.Fatalf("h %d: the tiles are %d and %d rows, so they are not symmetrical", h, core, tel)
		}
	}
}

// Owner order 2026-11-11: the globe turns at half the speed of build 3.2.3.
func TestSphereTurnIsHalfSpeed(t *testing.T) {
	if sphereTurnSeconds < 60.0 || sphereTurnSeconds > 60.5 {
		t.Fatalf("one turn takes %.2f s, want about 60.1", sphereTurnSeconds)
	}
}

// Owner order 2026-11-11: TOP PERFORMERS names the three best scrips of the
// day, ties by symbol, and never a name without a measured change.
func TestTopPerformersAreTheDaysBestThree(t *testing.T) {
	a := newTestApp(t)
	a.prices = map[string]Quote{
		"AAA": {ChangePct: f64(1.2)},
		"BBB": {ChangePct: f64(-0.8)},
		"CCC": {ChangePct: f64(2.0)},
		"DDD": {ChangePct: f64(0.4)},
	}
	if got := andList(a.topPerformers()); got != "CCC, AAA & DDD" {
		t.Fatalf("top performers read %q, want CCC, AAA & DDD", got)
	}
	if got := andList(nil); got != "--" {
		t.Fatalf("a day with no measured change reads %q, want --", got)
	}
}

// The LIVE/LAGGING counter is gone from the top left; row zero carries only
// the centred title.
func TestHeaderHasNoLiveCounter(t *testing.T) {
	a := demoApp(t, 120, 30)
	row := rowsOf(a)[0]
	if strings.Contains(row, "LIVE") || strings.Contains(row, "LAGGING") {
		t.Errorf("row 0 still carries the feed counter: %q", row)
	}
}
