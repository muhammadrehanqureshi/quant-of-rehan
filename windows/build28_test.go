package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-16: the feed light follows the quote feed, not a separate
// market or health request. One failed metadata call must not paint a live one
// second feed as STALE.
func TestFreshQuotesKeepTheFeedLive(t *testing.T) {
	a := newTestApp(t)
	a.now = flowT0
	a.checking, a.link = false, false
	a.lastMarketOK = a.now.Add(-47 * time.Second)
	a.ingestQuotes(quotesAt(15, 1_000_000))
	if got, _, ok := a.feedState(); got != "LIVE" || !ok {
		t.Fatalf("fresh quotes read %q, want LIVE", got)
	}
	light := ""
	for _, sp := range a.feedLight() {
		light += sp.S
	}
	if strings.Contains(light, "STALE") || !strings.Contains(light, "LIVE") {
		t.Errorf("feed light follows a failed metadata call: %q", light)
	}
	if s := plain(a); strings.Contains(s, "STALE 47s") {
		t.Errorf("the feed row is still stale while quotes are fresh:\n%s", s)
	}
}

// A successful quotes answer is proof the relay is up, so it clears the
// unreachable state left by a failed market or health call at once.
func TestQuotesAnswerClearsUnreachable(t *testing.T) {
	a := newTestApp(t)
	a.checking, a.link = false, false
	a.onMsg(msgQuotes{q: &Quotes{OK: true, FetchedAt: a.now,
		Items: map[string]LiveQuote{"KEL": {Price: 5.79}}}})
	if !a.link || a.relayErr != "" {
		t.Errorf("quotes answer left link %v error %q", a.link, a.relayErr)
	}
}
