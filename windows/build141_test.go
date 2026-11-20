package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-19: the SETTINGS scanning line is the owner's exact
// sentence, and TELEMETRY and the KSE100 footer say EVERY SECOND.
func TestBuild141Wording(t *testing.T) {
	a := demoApp(t, 160, 42)
	a.screen = scrSettings
	set := plain(a)
	if want := "1 second relay poll from 08:55 to 15:49 on Mon-Thu and on Friday till 16:49."; !strings.Contains(set, want) {
		t.Fatalf("the SETTINGS scanning line is missing %q:\n%s", want, set)
	}
	if w, _ := a.scanStatus(); w != "EVERY SECOND" {
		t.Fatalf("TELEMETRY reads %q, want EVERY SECOND", w)
	}
	if strings.Contains(set, "EVERY 1 SECOND") {
		t.Fatalf("the build still says EVERY 1 SECOND:\n%s", set)
	}
	a.demo = false
	a.market = marketIn("OPEN")
	a.market.TradingDay = true
	a.quotes = quotesAt(15, 1_000_000)
	if got := a.marketNote(); got != "DATA FROM THE BROKER'S FEED IS BEING SCANNED EVERY SECOND." {
		t.Fatalf("the KSE100 footer reads %q", got)
	}
}

// Owner order 2026-11-19: a fall's percentage ends on the same cell as a
// rise's in an open sector, and both arrows keep one column.
func TestBuild141OpenSectorDownPercentageAlignment(t *testing.T) {
	a := demoApp(t, 158, 41)
	a.demo = false
	a.quotes = nil
	a.screen = scrScanner
	a.sectors = &Sectors{OK: true, Items: []Sector{{Name: "TEST", Symbols: []string{"AAA", "BBB"}}}}
	a.prices = map[string]Quote{
		"AAA": {Price: 10, ChangePct: f64(1.5)},
		"BBB": {Price: 10, ChangePct: f64(-1.5)},
	}
	a.symbols = nil
	a.sectorOpen, a.sectorChoice = true, 0
	a.lvSectorStk.top()
	c := NewCanvas(120, 12, a.th.Panel)
	a.drawSectorOpen(c, 0, 0, 120, 12)
	pctEnd, arrowCol := -1, -1
	up, down := false, false
	for _, row := range c.PlainRows() {
		if col(row, "PKR ") < 0 {
			continue
		}
		pctAt := col(row, "%")
		if pctAt < 0 {
			continue
		}
		arrowAt := col(row, "▲")
		if arrowAt >= 0 {
			up = true
		} else if arrowAt = col(row, "▼"); arrowAt >= 0 {
			down = true
		}
		if arrowAt < 0 {
			continue
		}
		if pctEnd < 0 {
			pctEnd = pctAt
		} else if pctAt != pctEnd {
			t.Errorf("a percentage ends on cell %d, want %d: %q", pctAt, pctEnd, row)
		}
		if arrowCol < 0 {
			arrowCol = arrowAt
		} else if arrowAt != arrowCol {
			t.Errorf("an arrow starts on cell %d, want %d: %q", arrowAt, arrowCol, row)
		}
	}
	if !up || !down {
		t.Fatalf("the open sector did not show both a rise and a fall: up %v down %v", up, down)
	}
}

// Owner order 2026-11-19: HIGH and LOW carry an ampersand between them.
func TestBuild141HighAndLowUseAmpersand(t *testing.T) {
	a := demoApp(t, 140, 36)
	a.screen = scrScanner
	a.searchText, a.searchCursor = "AL", 0
	a.selectedSym, a.selectedSt = "ALFA", "ok"
	a.selectedInfo = demoStock("ALFA")
	s := plain(a)
	if !strings.Contains(s, "HIGH ") || !strings.Contains(s, "  &  LOW ") {
		t.Fatalf("the SEARCH tile does not join HIGH and LOW with an ampersand:\n%s", s)
	}
}

// Owner order 2026-11-20: the revealed CUSTOM SCRIPS list carries its price, its
// percentage, its bar and the bar's NET DELTA on the scrip's own row, against
// the tile's right edge, instead of starting on the T column in the middle.
func TestBuild141CustomScripsQuoteStandsOnTheRight(t *testing.T) {
	a := demoApp(t, 158, 41)
	a.screen = scrScanner
	a.scanChoice = 1
	rows := rowsOf(a)
	start := -1
	for i, row := range rows {
		if strings.Contains(row, "CUSTOM SCRIPS OF VOLUME") {
			start = i
			break
		}
	}
	if start < 0 {
		t.Fatal("the CUSTOM SCRIPS tile is missing")
	}
	tChecked := 0
	for i := start + 1; i+1 < len(rows); i++ {
		if !strings.Contains(rows[i], "PKR ") || !strings.Contains(rows[i], "1. ") {
			continue
		}
		// The values stay on the row under the scrip, where their B, S, U and T
		// columns are.
		if !strings.Contains(rows[i+1], "T=") {
			t.Fatalf("the values left the row under the scrip: %q then %q", rows[i], rows[i+1])
		}
		tAt := col(rows[i+1], "T=")
		if got := col(rows[i], "PKR"); got <= tAt {
			t.Fatalf("the quote starts on cell %d, which is not right of the T column %d: %q", got, tAt, rows[i])
		}
		tChecked++
	}
	if tChecked == 0 {
		t.Fatalf("the revealed list showed no priced scrip row:\n%s", strings.Join(rows[start:], "\n"))
	}
}
