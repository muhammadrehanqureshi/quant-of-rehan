package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-18: the SEARCH tile's scrip values begin on the search
// box's own row instead of two rows below it.
func TestSearchTileValuesStartOnTheSearchBoxRow(t *testing.T) {
	a := demoApp(t, 122, 36)
	a.screen = scrScanner
	a.searchText, a.searchCursor = "", 0
	a.selectedSym, a.selectedSt = "ALFA", "ok"
	a.selectedInfo = demoStock("ALFA")
	c := NewCanvas(90, 20, a.th.Panel)
	a.drawSearchTile(c, 0, 0, 90, 20)
	found := false
	for _, row := range c.PlainRows() {
		if strings.Contains(row, scripSearchHint) && strings.Contains(row, "PKR ") {
			found = true
			break
		}
	}
	if !found {
		t.Fatalf("the scrip values do not start on the search box row:\n%s",
			strings.Join(c.PlainRows(), "\n"))
	}
}

// Owner order 2026-11-19: an open sector puts the price and the percentage on
// the right, and a fall ends on the same cell as a rise.
func TestOpenSectorPriceAndPercentageStandOnTheRight(t *testing.T) {
	a := demoApp(t, 158, 41)
	a.screen = scrScanner
	a.sectorOpen, a.sectorChoice = true, 1
	a.lvSectorStk.top()
	c := NewCanvas(120, 12, a.th.Panel)
	a.drawSectorOpen(c, 0, 0, 120, 12)
	found := 0
	pctEnd, arrowCol := -1, -1
	for _, row := range c.PlainRows() {
		pkrAt := col(row, "PKR ")
		if pkrAt < 0 {
			continue
		}
		if pkrAt < 80 {
			t.Errorf("the open sector price starts on cell %d, want the right side: %q", pkrAt, row)
		}
		pctAt := col(row, "%")
		if pctAt < 0 {
			continue
		}
		if arrowAt := col(row, "▲"); arrowAt >= 0 {
			if arrowCol < 0 {
				arrowCol = arrowAt
			} else if arrowAt != arrowCol {
				t.Errorf("a rise starts on cell %d, want %d: %q", arrowAt, arrowCol, row)
			}
		} else if arrowAt := col(row, "▼"); arrowAt >= 0 {
			if arrowCol < 0 {
				arrowCol = arrowAt
			} else if arrowAt != arrowCol {
				t.Errorf("a fall starts on cell %d, want %d: %q", arrowAt, arrowCol, row)
			}
		}
		if pctEnd < 0 {
			pctEnd = pctAt
		} else if pctAt != pctEnd {
			t.Errorf("a percentage ends on cell %d, want %d: %q", pctAt, pctEnd, row)
		}
		found++
	}
	if found == 0 {
		t.Fatal("the open sector showed no price and percentage row")
	}
}

// Owner order 2026-11-18: CUSTOM SCRIPS keeps one blank row between a scrip's
// name and its B, S, U and T values.
func TestCustomScripsKeepABlankRowBeforeTheValues(t *testing.T) {
	a := demoApp(t, 158, 41)
	a.screen = scrScanner
	a.scanChoice = 1
	syms := rankedSpeedSymbols(a.scanTable())
	if len(syms) == 0 {
		t.Fatal("the first sort names no scrip")
	}
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
	want := "1. " + syms[0]
	for i := start + 1; i+2 < len(rows); i++ {
		if !strings.Contains(rows[i], want) || !strings.Contains(rows[i], "PKR ") {
			continue
		}
		if strings.Contains(rows[i+1], "B=") {
			t.Fatalf("the values still stand immediately under the scrip: %q then %q",
				rows[i], rows[i+1])
		}
		if !strings.Contains(rows[i+2], "B=") {
			t.Fatalf("the B, S, U and T row is not under the blank row: %q", rows[i+2])
		}
		return
	}
	t.Fatalf("the first sort did not reveal %q:\n%s", want, strings.Join(rows[start:], "\n"))
}
