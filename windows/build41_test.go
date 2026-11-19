package main

import (
	"strings"
	"testing"
	"time"
)

// Owner order 2026-11-18: U ends without a comma, because the ampersand
// already separates it from T. B and S keep their soft commas.
func TestUEndsWithoutAComma(t *testing.T) {
	a := newTestApp(t)
	b, s, total := int64(600), int64(300), int64(1000)

	wide := NewCanvas(80, 1, a.th.Panel)
	a.putBST(wide, 0, 0, &b, &s, &total)
	if row := wide.PlainRows()[0]; strings.Contains(row, "U=100,") {
		t.Fatalf("the wide U field still carries a comma: %q", row)
	}

	packed := NewCanvas(80, 1, a.th.Panel)
	a.putBSTPacked(packed, 0, 0, &b, &s, &total)
	if row := packed.PlainRows()[0]; strings.Contains(row, "U=100,") {
		t.Fatalf("the packed U field still carries a comma: %q", row)
	}
}

// Owner order 2026-11-18: the SEARCH tile no longer tells the owner to choose
// with UP and DOWN once there is something to choose.
func TestSearchTileHasNoChooseInstruction(t *testing.T) {
	a := demoApp(t, 140, 40)
	a.screen = scrScanner
	a.searchText, a.searchCursor = "AL", 0
	if s := plain(a); strings.Contains(s, "UP and DOWN choose, ENTER opens") {
		t.Fatalf("the search tile still carries its old instruction:\n%s", s)
	}
}

// Owner order 2026-11-18: every SECTORS percentage ends on the same cell, even
// when a 10.02% stands beside a 0.05%.
func TestSectorPercentagesShareOneRightEdge(t *testing.T) {
	a := demoApp(t, 158, 41)
	a.screen = scrScanner
	inside, count, want := false, 0, -1
	for _, row := range rowsOf(a) {
		switch {
		case strings.Contains(row, "SECTORS"):
			inside = true
			continue
		case strings.Contains(row, "CUSTOM SCRIPS OF VOLUME"):
			inside = false
		}
		if !inside || !strings.Contains(row, "%") || !strings.ContainsAny(row, "▲▼") {
			continue
		}
		// Count cells, not bytes: the selected row's diamond is three bytes but
		// one cell, and the row strings are compared by their cell position.
		at := -1
		for i, r := range []rune(row) {
			if r == '%' {
				at = i
			}
		}
		if want < 0 {
			want = at
		} else if at != want {
			t.Errorf("a sector percentage ends on cell %d, want %d: %q", at, want, row)
		}
		count++
	}
	if count < 3 {
		t.Fatalf("only %d sector percentages were found", count)
	}
}

// Owner order 2026-11-18: the chosen CUSTOM SCRIPS sort reveals its three
// scrips on the right of the six sorts, using the tile's spare width instead of
// the tight space under the menu.
func TestCustomScripsRevealOnTheRight(t *testing.T) {
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
	syms := rankedSpeedSymbols(a.scanTable())
	if len(syms) == 0 {
		t.Fatal("the first sort names no scrip")
	}
	want := "1. " + syms[0]
	for _, row := range rows[start+1:] {
		if at := strings.Index(row, want); at >= 0 {
			if at <= 40 {
				t.Fatalf("the revealed scrip starts on cell %d, want the right side: %q", at, row)
			}
			return
		}
	}
	t.Fatalf("the first sort did not reveal %q:\n%s", want, strings.Join(rows[start:], "\n"))
}

// Owner order 2026-11-19: the ALERTS LOG keeps everything else on the left and
// puts the current price and the percentage on fixed right hand columns, so a
// fall ends on the same cell as a rise and neither is cut off.
func TestAlertLogPriceAndPercentageShareTheRightColumns(t *testing.T) {
	a := demoApp(t, 140, 34)
	a.flow.Log = []Flag{
		{Time: a.now.Add(-time.Second), Symbol: "PRL", Kind: "flow", Side: "BUY", Value: 100_000,
			Price: 114.65, ChangePct: f64(5.08), Text: "100k shares of PRL were bought at PKR 114.65 ▲ 5.08%."},
		{Time: a.now, Symbol: "KEL", Kind: "flow", Side: "SELL", Value: 100_000,
			Price: 9.05, ChangePct: f64(-1.25), Text: "100k shares of KEL were sold at PKR 9.05 ▼ 1.25%."},
	}
	c := NewCanvas(120, 8, a.th.Panel)
	a.drawAlertLog(c, 0, 0, 120, 8)
	rows := c.PlainRows()
	s := strings.Join(rows, "\n")
	if strings.Contains(s, " at PKR ") {
		t.Fatalf("the log still keeps the old price sentence on the left:\n%s", s)
	}
	priceEnd, pctEnd, found := -1, -1, 0
	for _, row := range rows {
		pkrAt := col(row, "PKR ")
		pctAt := col(row, "%")
		if pkrAt < 0 || pctAt < 0 {
			continue
		}
		arrowAt := col(row, "▲")
		if arrowAt < 0 {
			arrowAt = col(row, "▼")
		}
		if arrowAt < 0 {
			continue
		}
		runes := []rune(row)
		end := arrowAt
		for end > pkrAt && runes[end-1] == ' ' {
			end--
		}
		if priceEnd < 0 {
			priceEnd = end
		} else if end != priceEnd {
			t.Errorf("a price ends on cell %d, want %d: %q", end, priceEnd, row)
		}
		if pctEnd < 0 {
			pctEnd = pctAt
		} else if pctAt != pctEnd {
			t.Errorf("a percentage ends on cell %d, want %d: %q", pctAt, pctEnd, row)
		}
		found++
	}
	if found < 2 {
		t.Fatalf("the log showed %d price and percentage rows, want two:\n%s", found, s)
	}
}
