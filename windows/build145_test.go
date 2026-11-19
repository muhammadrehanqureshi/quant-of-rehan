package main

import (
	"strings"
	"testing"
	"time"
)

// Owner order 2026-11-19 (latest): the SEARCH tile on ALERTS and the one on
// SCANNER read their two figures the same way, an equals sign hard against each
// label, the figures on one line, and an ampersand with two cells on each side
// between them.
func TestBuild145BothSearchTilesReadNetDeltaTheSameWay(t *testing.T) {
	for _, scanner := range []bool{false, true} {
		a := demoApp(t, 140, 34)
		c := NewCanvas(120, 6, a.th.Panel)
		a.drawSearchLedger(c, 0, 0, 120, 6, i64(1_200_000), i64(400_000), i64(1_600_000), scanner)
		row := ""
		for _, r := range c.PlainRows() {
			if strings.Contains(r, "NET DELTA %=") {
				row = r
			}
		}
		if row == "" {
			t.Fatalf("scanner %v: no NET DELTA percentage line:\n%s",
				scanner, strings.Join(c.PlainRows(), "\n"))
		}
		netAt, pctAt := strings.Index(row, "NET DELTA="), strings.Index(row, "NET DELTA %=")
		if netAt < 0 {
			t.Errorf("scanner %v: NET DELTA carries no equals sign: %q", scanner, row)
		}
		if netAt > pctAt {
			t.Errorf("scanner %v: NET DELTA comes after NET DELTA %%: %q", scanner, row)
		}
		if !strings.Contains(row[netAt:pctAt], "  &  ") {
			t.Errorf("scanner %v: the two figures are not joined by an ampersand with two cells each side: %q", scanner, row)
		}
	}
}

// Owner order 2026-11-19 (latest): the KSE100 leader's price, bar, percentage
// and NET DELTA stand together on the tile's right edge instead of floating to
// the left after the volumes.
func TestBuild145KSE100QuotesStandOnTheRightEdge(t *testing.T) {
	a := busyApp(t, 158, 41, 3)
	c := NewCanvas(120, 26, a.th.Panel)
	a.drawMarket(c, 0, 0, 120, 26)
	found := 0
	for _, row := range c.PlainRows() {
		at := col(row, "PKR ")
		if at < 0 || !strings.Contains(row[at:], "%") {
			continue
		}
		found++
		last := len([]rune(strings.TrimRight(row, " "))) - 1
		// The tile's inner right edge is cell 116 on a 120 wide frame.
		if last < 115 {
			t.Errorf("the leader quote ends on cell %d, not on the tile's right edge: %q", last, row)
		}
		if at < 70 {
			t.Errorf("PKR starts on cell %d, so the group is not on the right: %q", at, row)
		}
	}
	if found < 2 {
		t.Fatalf("only %d leader quote lines were found:\n%s", found, strings.Join(c.PlainRows(), "\n"))
	}
}

// Owner order 2026-11-19 (latest): an opened sector shows five scrips whatever
// height the tile is given, and the rest of its scrips are a scroll away.
func TestBuild145OpenSectorShowsFiveScripsAtEveryHeight(t *testing.T) {
	syms := []string{"AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH", "III"}
	for _, h := range []int{13, 20, 26} {
		a := demoApp(t, 158, 41)
		a.demo = false
		a.quotes = nil
		a.screen = scrScanner
		a.sectors = &Sectors{OK: true, Items: []Sector{{Name: "TEST", Symbols: syms}}}
		a.prices = map[string]Quote{"AAA": {Price: 10, ChangePct: f64(1)}}
		a.symbols = nil
		a.sectorOpen, a.sectorChoice = true, 0
		a.lvSectorStk.top()
		c := NewCanvas(120, h, a.th.Panel)
		a.drawSectorOpen(c, 0, 0, 120, h)
		if a.lvSectorStk.total != 9 {
			t.Fatalf("h %d: the open sector lists %d scrips, want 9", h, a.lvSectorStk.total)
		}
		if a.lvSectorStk.view != 5 {
			t.Fatalf("h %d: the open sector shows %d scrips, want five", h, a.lvSectorStk.view)
		}
	}
}

// Owner order 2026-11-19 (latest): the SECTORS title carries the panel's own
// hot diamond, the one every other tile's heading has.
func TestBuild145SectorsTitleCarriesTheDiamond(t *testing.T) {
	a := demoApp(t, 122, 36)
	a.screen = scrScanner
	a.sectors = nil
	c := NewCanvas(60, 12, a.th.Panel)
	a.drawSectorTile(c, 0, 0, 60, 12)
	if got := c.Cells[2]; got.Ch != '◆' || got.FG != a.th.Hot {
		t.Fatalf("the SECTORS heading carries %q, want the standard diamond", got.Ch)
	}

	a.sectors = &Sectors{OK: true, Items: []Sector{{Name: "TEST", Symbols: []string{"AAA", "BBB"}}}}
	a.symbols = nil
	a.sectorOpen, a.sectorChoice = true, 0
	c = NewCanvas(60, 12, a.th.Panel)
	a.drawSectorOpen(c, 0, 0, 60, 12)
	if got := c.Cells[2]; got.Ch != '◆' || got.FG != a.th.Hot {
		t.Fatalf("an opened SECTORS heading carries %q, want the standard diamond", got.Ch)
	}
}

// Owner order 2026-11-19 (latest): the index stood 1100 points up and the
// telemetry still read FLAT, so the bullish mark is +1000 points. The band
// between the two marks is still FLAT, and -500 is still BEARISH.
func TestBuild145BreadthReadsTheIndexMoveAt1100(t *testing.T) {
	a := newTestApp(t)
	a.w, a.h = 120, 34
	a.link, a.checking = true, false
	a.now = time.Date(2026, 11, 19, 10, 0, 0, 0, pkt)
	a.market = marketIn("OPEN")
	a.quotes = &Quotes{FetchedAt: a.now, Index: &IndexQuote{
		Value: 166409.25, Change: 1100, ChangePct: 0.67, Fresh: true,
	}, Items: map[string]LiveQuote{
		"AAA": {Price: 10, Fresh: true, ChangePct: f64(1.2)},
		"BBB": {Price: 20, Fresh: true, ChangePct: f64(-0.8)},
	}}
	if got := plain(a); !strings.Contains(got, "BULLISH") {
		t.Fatalf("KSE100 +1100 points must read BULLISH:\n%s", got)
	}
	a.quotes.Index.Change = 900
	if got := plain(a); !strings.Contains(got, "FLAT") || strings.Contains(got, "BULLISH") {
		t.Fatalf("KSE100 +900 points must stay FLAT:\n%s", got)
	}
	a.quotes.Index.Change = -600
	if got := plain(a); !strings.Contains(got, "BEARISH") {
		t.Fatalf("KSE100 -600 points must read BEARISH:\n%s", got)
	}
}
