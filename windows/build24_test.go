package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-18: the KSE100 bar stands above the price line, starts
// on the current price's cell, and never reaches the tile's inner edge.
func TestKSE100BarSitsAboveTheCurrentPrice(t *testing.T) {
	a := busyApp(t, 158, 41, 3)
	rows := rowsOf(a)
	inside := false
	found := 0
	for i, row := range rows {
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
		if pkr < 0 || !strings.Contains(row[pkr:], "%") || i == 0 {
			continue
		}
		nameRow := rows[i-1]
		at := col(row, "PKR ")
		barAt := col(nameRow, string(barBlock))
		if barAt != at {
			t.Errorf("the bar starts on cell %d, the current price on %d: %q", barAt, at, nameRow)
			continue
		}
		border := strings.LastIndex(nameRow, "│")
		if border < 0 {
			continue
		}
		barEnd := barAt + strings.Count(nameRow, string(barBlock))
		borderCell := runeLen(nameRow[:border])
		if barEnd > borderCell-1 {
			t.Errorf("the bar reaches cell %d, the tile's inner edge is %d: %q", barEnd-1, borderCell-1, nameRow)
		}
		found++
	}
	if found < 2 {
		t.Fatalf("only %d leader name rows carried a bar:\n%s",
			found, strings.Join(rows, "\n"))
	}
}

func blankSearchRow(row string) bool {
	s := strings.TrimSpace(row)
	s = strings.Trim(s, "│")
	return strings.TrimSpace(s) == ""
}

func checkSearchBoxGaps(t *testing.T, name string, rows []string, needle string, before bool) {
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
		if before {
			if !blankSearchRow(rows[i-1]) {
				t.Errorf("%s: no blank row before the search box: %q", name, rows[i-1])
			}
		} else if blankSearchRow(rows[i-1]) {
			t.Errorf("%s: the withdrawn row before the search box is still blank: %q", name, rows[i-1])
		}
		if !blankSearchRow(rows[i+1]) {
			t.Errorf("%s: no blank row after the search box: %q", name, rows[i+1])
		}
	}
	if hits == 0 {
		t.Fatalf("%s: search box %q is missing", name, needle)
	}
}

// Owner order 2026-11-18: the blank row before the SEARCH and SECTORS boxes is
// withdrawn; ORDER FLOW keeps its breathing row.
func TestEverySearchBoxHasABlankRowOnEachSide(t *testing.T) {
	cases := []struct {
		name   string
		screen screenID
		w, h   int
		needle string
		before bool
	}{
		{"scanner", scrScanner, 120, 42, scripSearchHint, false},
		{"sectors", scrScanner, 120, 42, "Search for a sector", false},
		{"order flow", scrOrderFlow, 120, 40, scripSearchHint, true},
		// Owner order 2026-11-18: the ALERTS page carries two search boxes.
		// TestAlertsHasBothSearchBoxes checks both of them.
	}
	for _, tc := range cases {
		a := demoApp(t, tc.w, tc.h)
		a.screen = tc.screen
		checkSearchBoxGaps(t, tc.name, rowsOf(a), tc.needle, tc.before)
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
