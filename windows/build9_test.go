package main

import (
	"strings"
	"testing"
	"time"
)

// Owner order 2026-11-11: the telemetry tile carries the exchange's daily
// market hours, the market's breadth, the advancers and decliners, and the
// whole market's net delta, and the old NEXT line is gone.
func TestTelemetryCarriesMarketHoursBreadthAndDelta(t *testing.T) {
	a := newTestApp(t)
	a.w, a.h = 120, 34
	a.link, a.checking = true, false
	a.now = time.Date(2026, 11, 2, 10, 0, 0, 0, pkt)
	a.market = marketIn("OPEN")
	a.quotes = &Quotes{FetchedAt: a.now, Items: map[string]LiveQuote{
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
		"MARKET OPENING", "09:32", "MARKET CLOSING", "15:30",
		"MARKET BREADTH", "BULLISH", "ADV/DEC", "2 / 1",
		"NET DELTA", "-300",
	} {
		if !strings.Contains(s, want) {
			t.Errorf("telemetry is missing %q:\n%s", want, s)
		}
	}
	for _, row := range rowsOf(a) {
		if strings.Contains(row, "NEXT") && !strings.Contains(row, "TAB NEXT") {
			t.Errorf("the NEXT line is still in the build: %q", row)
		}
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

// The LIVE/LAGGING counter is gone from the top left; row zero carries only
// the centred title.
func TestHeaderHasNoLiveCounter(t *testing.T) {
	a := demoApp(t, 120, 30)
	row := rowsOf(a)[0]
	if strings.Contains(row, "LIVE") || strings.Contains(row, "LAGGING") {
		t.Errorf("row 0 still carries the feed counter: %q", row)
	}
}
