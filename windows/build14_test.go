package main

import (
	"strings"
	"testing"
	"time"
)

// Owner order 2026-11-13: TELEMETRY's MARKET OPENING is the exchange's first
// pre-open, which is 09:15 Monday to Thursday and 09:00 on Friday.
func TestTelemetryMarketOpeningOnFriday(t *testing.T) {
	a := busyApp(t, 158, 41, 3)
	a.now = time.Date(2026, 11, 6, 10, 0, 0, 0, pkt) // a Friday
	found := false
	for _, row := range rowsOf(a) {
		if !strings.Contains(row, "MARKET OPENING") {
			continue
		}
		found = true
		if !strings.Contains(row, "09:00") {
			t.Fatalf("Friday's market opening is not 09:00: %q", row)
		}
	}
	if !found {
		t.Fatal("the telemetry tile carries no MARKET OPENING row")
	}
}

// Owner order 2026-11-13: the SECTORS tile orders its groups by the day's
// overall percentage, highest first, and prints that percentage in front of
// each group. A group with no priced scrip yet goes last.
func TestScannerOrdersSectorsByOverallPercentage(t *testing.T) {
	a := demoApp(t, 122, 36)
	a.demo = false
	a.quotes = nil
	a.screen = scrScanner
	a.sectors = &Sectors{OK: true, Items: []Sector{
		{Name: "CEMENT", Symbols: []string{"AAA"}},
		{Name: "AUTOMOBILE", Symbols: []string{"BBB"}},
		{Name: "BANKS", Symbols: []string{"CCC"}},
		{Name: "EMPTY", Symbols: []string{"ZZZ"}},
	}}
	a.prices = map[string]Quote{
		"AAA": {Price: 10, ChangePct: f64(-1.5)},
		"BBB": {Price: 10, ChangePct: f64(2.5)},
		"CCC": {Price: 10, ChangePct: f64(0.5)},
	}
	var got []string
	items := a.sectors.Items
	for _, i := range a.visibleSectorIndices() {
		got = append(got, items[i].Name)
	}
	want := []string{"AUTOMOBILE", "BANKS", "CEMENT", "EMPTY"}
	if strings.Join(got, ",") != strings.Join(want, ",") {
		t.Fatalf("sectors read %v, want %v (highest percentage first)", got, want)
	}
	s := plain(a)
	for _, pct := range []string{"▲ 2.50%", "▲ 0.50%", "▼ 1.50%"} {
		if !strings.Contains(s, pct) {
			t.Errorf("the sector list is missing %q:\n%s", pct, s)
		}
	}
	if strings.Contains(s, "+2.50%") || strings.Contains(s, "-1.50%") {
		t.Errorf("the sector list still carries a sign instead of an arrow:\n%s", s)
	}
	// The strongest group's row comes before the weakest.
	if strings.Index(s, "AUTOMOBILE") > strings.Index(s, "CEMENT") {
		t.Errorf("AUTOMOBILE does not stand above CEMENT:\n%s", s)
	}
}

// Owner order 2026-11-13: ORDER FLOW carries a NET DELTA order, highest
// positive delta first and unmeasured rows last, and ENTER on the page puts
// the list in that order.
func TestOrderFlowSortsByNetDelta(t *testing.T) {
	a := orderFlowApp(t, 122, 30, sampleOrderFlow)
	a.ofSort = flowSortNetDelta
	rows := a.sortedFlow()
	// AAA +300 and BBB +3100 are measured; CCC's split is an estimate, so it
	// sorts with the unmeasured rows, as it does under every measured order.
	if len(rows) < 4 {
		t.Fatalf("only %d flow rows", len(rows))
	}
	if rows[0].Symbol != "BBB" || rows[1].Symbol != "AAA" {
		t.Errorf("by net delta: %s %s", rows[0].Symbol, rows[1].Symbol)
	}
	if last := rows[len(rows)-1].Symbol; last != "DDD" {
		t.Errorf("a row with no measured delta must go last, not %s", last)
	}
	// ENTER with the search box empty sorts by NET DELTA.
	a.ofSort = 0
	a.ofQuery, a.ofSearch = "", false
	a.onKey(Key{Kind: KEnter})
	if a.ofSort != flowSortNetDelta {
		t.Fatalf("ENTER did not order by NET DELTA: %d", a.ofSort)
	}
	// While a search is typed, ENTER keeps its old job and closes the field.
	a.ofSearch, a.ofQuery = true, "AA"
	a.onKey(Key{Kind: KEnter})
	if a.ofSearch {
		t.Fatal("ENTER with a typed search must close the search field")
	}
}
