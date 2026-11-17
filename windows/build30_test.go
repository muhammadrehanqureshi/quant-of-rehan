package main

import (
	"testing"
	"time"
)

// Owner order 2026-11-16: pre-market, live and post-market scanning follows the
// Karachi clock. A stale metadata flag can never switch the scan off.
func TestScanClockOutranksMetadata(t *testing.T) {
	a := newTestApp(t)
	a.link, a.checking = true, false
	a.market = marketIn("CLOSED")
	a.market.TradingDay = false
	// Pre-market, live and post-market on an ordinary Monday.
	for _, clock := range []time.Time{
		time.Date(2026, 11, 2, 9, 20, 0, 0, pkt),
		time.Date(2026, 11, 2, 11, 0, 0, 0, pkt),
		time.Date(2026, 11, 2, 15, 40, 0, 0, pkt),
	} {
		a.now = clock
		if !a.scanning() {
			t.Errorf("%s: scanning stopped despite the session clock", clock.Format("15:04"))
		}
		if w, _ := a.scanStatus(); w != "EVERY 3 SECONDS" {
			t.Errorf("%s: SCAN reads %q", clock.Format("15:04"), w)
		}
	}
	// A real holiday still closes the scan.
	a.now = time.Date(2026, 11, 9, 11, 0, 0, 0, pkt)
	if a.scanning() {
		t.Fatal("the scan ran on a PSX holiday")
	}
	if w, _ := a.scanStatus(); w != "MARKET IS CLOSED TODAY" {
		t.Errorf("holiday SCAN reads %q", w)
	}
}

// Owner order 2026-11-16: the quote watchdog asks again at once when the last
// answer is old, and it frees a request that has hung past its timeout.
func TestQuoteWatchdogKeepsTheFeedMoving(t *testing.T) {
	a := newTestApp(t)
	a.link, a.checking = true, false
	a.market = marketIn("OPEN")
	a.now = time.Date(2026, 11, 2, 11, 0, 0, 0, pkt)
	a.quotes = &Quotes{OK: true, FetchedAt: a.now.Add(-20 * time.Second)}
	a.fails["quotes"] = 4
	a.next["quotes"] = a.now.Add(time.Hour)

	a.watchQuotes(a.now)

	if got := a.fails["quotes"]; got != 0 {
		t.Errorf("the watchdog left the failure backoff at %d", got)
	}
	if got := a.next["quotes"]; !got.IsZero() {
		t.Errorf("the watchdog left the next ask at %v, want now", got)
	}

	a.inflight["quotes"] = true
	a.sentAt["quotes"] = a.now.Add(-quoteRequestCeiling - time.Second)
	a.next["quotes"] = a.now.Add(time.Hour)
	a.watchQuotes(a.now)

	if a.inflight["quotes"] {
		t.Error("a quotes request hung past its ceiling and stayed in flight")
	}
	if got := a.next["quotes"]; !got.IsZero() {
		t.Errorf("a hung request was freed but the next ask waits until %v", got)
	}
}

// While scanning, a failed quotes answer retries at the live pace.
func TestQuoteRetryUsesTheLivePace(t *testing.T) {
	a := newTestApp(t)
	a.market = marketIn("OPEN")
	a.now = time.Date(2026, 11, 2, 11, 0, 0, 0, pkt)
	a.fails["quotes"] = 6
	if got := a.interval("quotes"); got != quoteRetry {
		t.Fatalf("failed quotes retry is %v, want %v while scanning", got, quoteRetry)
	}
}
