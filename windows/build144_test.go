package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-19: the SCANNER SEARCH tile reads its two figures as one
// line, an ampersand between them with two cells on each side.
func TestBuild144ScannerSearchJoinsNetDeltaWithAmpersand(t *testing.T) {
	a := demoApp(t, 140, 34)
	c := NewCanvas(120, 6, a.th.Panel)
	a.drawSearchLedger(c, 0, 0, 120, 6, i64(999_900), i64(0), i64(999_900), true)
	rows := c.PlainRows()
	row := ""
	for _, r := range rows {
		if strings.Contains(r, "NET DELTA %") {
			row = r
		}
	}
	if row == "" {
		t.Fatalf("the scanner ledger carries no NET DELTA percentage:\n%s", strings.Join(rows, "\n"))
	}
	r := []rune(row)
	at := col(row, "&")
	if at < 0 {
		t.Fatalf("the ledger has no ampersand between the two figures: %q", row)
	}
	if at < 2 || r[at-1] != ' ' || r[at-2] != ' ' {
		t.Errorf("the ampersand leaves fewer than two cells before it: %q", row)
	}
	if at+2 >= len(r) || r[at+1] != ' ' || r[at+2] != ' ' {
		t.Errorf("the ampersand leaves fewer than two cells after it: %q", row)
	}
}

// Owner order 2026-11-19: the NET DELTA % label keeps exactly one cell before
// its value, never the two the right aligned field used to leave.
func TestBuild144ScannerSearchKeepsOneCellAfterNetDeltaPct(t *testing.T) {
	a := demoApp(t, 140, 34)
	c := NewCanvas(120, 6, a.th.Panel)
	a.drawSearchLedger(c, 0, 0, 120, 6, i64(999_900), i64(0), i64(999_900), true)
	for _, row := range c.PlainRows() {
		lbl := col(row, "NET DELTA %")
		if lbl < 0 {
			continue
		}
		r := []rune(row)
		if lbl+11 >= len(r) || r[lbl+11] != ' ' {
			t.Errorf("NET DELTA %% and its value touch: %q", row)
		}
		if lbl+12 >= len(r) || r[lbl+12] == ' ' {
			t.Errorf("NET DELTA %% leaves more than one cell before its value: %q", row)
		}
	}
}

// Owner order 2026-11-19: every KSE100 leader keeps NET DELTA and the
// percentage after its price. A tile too narrow to hold the group beside the
// volumes puts the quote on the line under them instead of dropping it.
func TestBuild144KSE100KeepsTheQuoteWhenTheTileIsTight(t *testing.T) {
	for _, sz := range [][2]int{{158, 41}, {140, 41}, {120, 34}} {
		a := busyApp(t, sz[0], sz[1], 3)
		inside, found := false, 0
		for _, row := range rowsOf(a) {
			switch {
			case strings.Contains(row, "KSE100 INDEX & THE TOP 3 SCRIPS OF VOLUME"):
				inside = true
				continue
			case strings.Contains(row, "BUYING NOW"):
				inside = false
			}
			if !inside {
				continue
			}
			at := strings.Index(row, "PKR ")
			if at < 0 {
				continue
			}
			found++
			rest := row[at:]
			if !strings.Contains(rest, "NET DELTA") {
				t.Errorf("%dx%d: the leader price lost NET DELTA: %q", sz[0], sz[1], row)
			}
			if !strings.Contains(rest, "%") {
				t.Errorf("%dx%d: the leader price lost its percentage: %q", sz[0], sz[1], row)
			}
		}
		if found == 0 {
			t.Fatalf("%dx%d: no leader price line was found:\n%s", sz[0], sz[1], plain(a))
		}
	}
}
