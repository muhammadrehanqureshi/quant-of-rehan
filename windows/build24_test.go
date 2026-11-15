package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-15: the KSE100 bar ends on the tile's last inner cell
// and shares the percentage's row, with NET DELTA withdrawn.
func TestKSE100BarEndsAtTheTilesInnerEdge(t *testing.T) {
	a := busyApp(t, 158, 41, 3)
	rows := rowsOf(a)
	inside := false
	found := 0
	for _, row := range rows {
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
		pkr := strings.Index(row, "PKR ")
		if pkr < 0 || !strings.Contains(row[pkr:], "%") {
			continue
		}
		border := strings.LastIndex(row, "│")
		if border <= pkr {
			continue
		}
		barEnd := runeLen(strings.TrimRight(row[:border], " "))
		borderCell := runeLen(row[:border])
		// barEnd is one past the last bar cell, and the border is two cells
		// after the last inner cell, so a bar that fills that cell ends on
		// borderCell-1.
		if barEnd != borderCell-1 {
			t.Errorf("the bar ends on cell %d, the tile's last inner cell ends on %d: %q",
				barEnd-1, borderCell-2, row)
		}
		found++
	}
	if found < 2 {
		t.Fatalf("only %d leader percentage rows carried a bar:\n%s",
			found, strings.Join(rows, "\n"))
	}
}

func blankSearchRow(row string) bool {
	s := strings.TrimSpace(row)
	s = strings.Trim(s, "│")
	return strings.TrimSpace(s) == ""
}

func checkSearchBoxGaps(t *testing.T, name string, rows []string, needle string) {
	t.Helper()
	hits := 0
	for i, row := range rows {
		if !strings.Contains(row, needle) {
			continue
		}
		hits++
		if i == 0 || i+1 >= len(rows) {
			t.Errorf("%s: the search box has no room for breathing rows", name)
			continue
		}
		if !blankSearchRow(rows[i-1]) {
			t.Errorf("%s: no blank row before the search box: %q", name, rows[i-1])
		}
		if !blankSearchRow(rows[i+1]) {
			t.Errorf("%s: no blank row after the search box: %q", name, rows[i+1])
		}
	}
	if hits == 0 {
		t.Fatalf("%s: search box %q is missing", name, needle)
	}
}

// Owner order 2026-11-14 (latest): every search box in the build carries one
// blank row before it and one after it.
func TestEverySearchBoxHasABlankRowOnEachSide(t *testing.T) {
	cases := []struct {
		name   string
		screen screenID
		w, h   int
		needle string
	}{
		{"scanner", scrScanner, 120, 42, scripSearchHint},
		{"sectors", scrScanner, 120, 42, "Search for a sector"},
		{"order flow", scrOrderFlow, 120, 40, scripSearchHint},
		{"alerts log", scrAlerts, 120, 34, scripSearchHint},
	}
	for _, tc := range cases {
		a := demoApp(t, tc.w, tc.h)
		a.screen = tc.screen
		checkSearchBoxGaps(t, tc.name, rowsOf(a), tc.needle)
	}
}

// Owner order 2026-11-14 (latest): the CUSTOM SCRIPS hint carries the owner's
// exact words and the key names in capitals.
func TestCustomScripsNamesTheArrowKeys(t *testing.T) {
	a := demoApp(t, 120, 42)
	a.screen = scrScanner
	s := plain(a)
	want := "Press " + `"` + "LEFT & RIGHT ARROW KEYS" + `"` + " to move"
	if !strings.Contains(s, want) {
		t.Fatalf("the CUSTOM SCRIPS instruction is missing:\n%s", s)
	}
	if strings.Contains(s, "Press LEFT & RIGHT arrow keys") {
		t.Fatalf("the old CUSTOM SCRIPS instruction is still on screen:\n%s", s)
	}
}
