package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-17: the SEARCH and SECTORS boxes lose the row before
// them, so at the owner's 122x36 window CUSTOM SCRIPS shows all six sorts and
// all three scrips.
func TestScannerShowsThreeScripsAndAllSortsAt122x36(t *testing.T) {
	a := demoApp(t, 122, 36)
	a.screen = scrScanner
	a.scanChoice, a.scanCursor = 1, 0
	rows := rowsOf(a)
	for _, name := range scanChoices {
		found := false
		for _, row := range rows {
			if strings.Contains(row, name) {
				found = true
				break
			}
		}
		if !found {
			t.Errorf("the six sorts lost %q at 122x36:\n%s", name, strings.Join(rows, "\n"))
		}
	}
	values, sCol := 0, -1
	for _, row := range rows {
		if !strings.Contains(row, "B=") || !strings.Contains(row, "&  T=") {
			continue
		}
		values++
		if at := strings.Index(row, "S="); at >= 0 {
			if sCol < 0 {
				sCol = at
			} else if at != sCol {
				t.Errorf("S= starts on cell %d, want %d: %q", at, sCol, row)
			}
		}
	}
	if values != 3 {
		t.Fatalf("CUSTOM SCRIPS shows %d scrips at 122x36, want three:\n%s", values, strings.Join(rows, "\n"))
	}
	for i, row := range rows {
		if strings.Contains(row, scripSearchHint) && i > 0 && blankSearchRow(rows[i-1]) {
			t.Errorf("the blank row before the SEARCH box is still there: %q", rows[i-1])
		}
		if strings.Contains(row, "Search for a sector") && i > 0 && blankSearchRow(rows[i-1]) {
			t.Errorf("the blank row before the SECTORS box is still there: %q", rows[i-1])
		}
	}
}