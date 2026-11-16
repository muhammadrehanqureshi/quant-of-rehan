package main

import (
	"strings"
	"testing"
	"time"
)

// Owner order 2026-11-16: the FEED light must follow the values, not only the
// relay's timestamp. A table that stops moving reads LAGGING after five seconds
// even while every answer still calls its rows fresh.
func TestFeedGoesLaggingWhenValuesStandStill(t *testing.T) {
	a := newTestApp(t)
	a.link, a.checking = true, false
	a.now = flowT0
	a.ingestQuotes(quotesAt(15, 1_000_000))

	for _, step := range []struct {
		at   time.Duration
		want string
	}{
		{5 * time.Second, "LIVE"},
		{6 * time.Second, "LAGGING"},
		{20 * time.Second, "LAGGING"},
	} {
		a.now = flowT0.Add(step.at)
		q := quotesAt(15, 1_000_000)
		q.FetchedAt = a.now
		a.ingestQuotes(q)
		if got, age, _ := a.feedState(); got != step.want {
			t.Errorf("after %s with no move: %s %ds, want %s", step.at, got, age, step.want)
		}
	}

	// One real change returns the light to LIVE at once.
	a.now = flowT0.Add(21 * time.Second)
	q := quotesAt(15.05, 1_001_000)
	q.FetchedAt = a.now
	a.ingestQuotes(q)
	if got, _, _ := a.feedState(); got != "LIVE" {
		t.Errorf("a moved quote reads %s, want LIVE", got)
	}
}

// Owner order 2026-11-16: the CUSTOM SCRIPS list carries one diamond, on the
// cursor's own left edge, never a second inline diamond for the chosen sort.
func TestCustomScripsCarriesOneDiamond(t *testing.T) {
	a := demoApp(t, 122, 40)
	a.screen = scrScanner
	a.scanChoice, a.scanCursor = 2, 1
	total := 0
	for _, row := range rowsOf(a) {
		named := false
		for _, name := range scanChoices {
			if strings.Contains(row, name) {
				named = true
				break
			}
		}
		if !named {
			continue
		}
		total += strings.Count(row, "◆")
	}
	if total != 1 {
		t.Fatalf("the CUSTOM SCRIPS list carries %d diamonds, want one:\n%s", total, plain(a))
	}
}
