package main

import (
	"strings"
	"testing"
	"time"
)

// Owner order 2026-11-14: the weekend names itself, and both market hours read
// N/A when the exchange does not open.
func TestTelemetryWeekendReadsOffAndNA(t *testing.T) {
	a := newTestApp(t)
	a.w, a.h = 120, 34
	a.link, a.checking = true, false
	a.now = time.Date(2026, 11, 7, 11, 0, 0, 0, pkt) // Saturday
	a.market = marketIn("CLOSED")
	a.market.TradingDay = false
	found := map[string]bool{}
	for _, row := range rowsOf(a) {
		switch {
		case strings.Contains(row, "SCAN"):
			if !strings.Contains(row, "OFF ON THE WEEKEND") {
				t.Errorf("the weekend scan row does not name the weekend: %q", row)
			}
			found["scan"] = true
		case strings.Contains(row, "MARKET OPENING"):
			if !strings.Contains(row, "N/A") {
				t.Errorf("the weekend opening is not N/A: %q", row)
			}
			found["open"] = true
		case strings.Contains(row, "MARKET CLOSING"):
			if !strings.Contains(row, "N/A") {
				t.Errorf("the weekend closing is not N/A: %q", row)
			}
			found["close"] = true
		}
	}
	for _, want := range []string{"scan", "open", "close"} {
		if !found[want] {
			t.Errorf("the telemetry %s row is missing:\n%s", want, plain(a))
		}
	}
}
