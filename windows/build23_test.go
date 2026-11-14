package main

import (
	"strings"
	"testing"
	"time"
)

// Owner order 2026-11-14: QUANT STATUS names the stored day with "of", and the
// KSE100 footer carries the one requested sentence whenever feed data shows.
func TestStoredSessionAndFeedFooterWords(t *testing.T) {
	a := newTestApp(t)
	a.now = time.Date(2026, 11, 14, 11, 0, 0, 0, pkt)
	a.sessionAt = time.Date(2026, 11, 13, 15, 30, 0, 0, pkt)
	a.sessionDate = "2026-11-13"
	if got := a.statusNote(); !strings.Contains(got, "Showing the last stored session of 13 NOV 2026.") {
		t.Fatalf("stored session words: %q", got)
	}
	a.quotes = quotesAt(15, 1_000_000)
	if got := a.marketNote(); got != "LAST DATA FROM THE BROKER'S FEED." {
		t.Fatalf("KSE100 footer: %q", got)
	}
}
