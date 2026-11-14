package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-14 (latest): the KSE100 live price, its percentage and
// NET DELTA move two cells right together, so the widest delta ends on the
// tile's last inner cell and the percentage keeps its two cell gutter.
func TestKSE100ValuesMoveTwoCellsRight(t *testing.T) {
	a := busyApp(t, 158, 41, 3)
	rows := rowsOf(a)
	found := 0
	maxNetEnd, maxNetBorder := -1, -1
	for _, row := range rows {
		pkr := strings.Index(row, "PKR ")
		if pkr < 0 {
			continue
		}
		rest := row[pkr:]
		j := strings.Index(rest, "NET DELTA ")
		if j < 0 {
			continue
		}
		netStart := pkr + j
		border := strings.LastIndex(row, "│")
		if border <= netStart {
			continue
		}
		netStartCell := runeLen(row[:netStart])
		netEndCell := netStartCell + runeLen(strings.TrimRight(row[netStart:border], " "))
		borderCell := runeLen(row[:border])
		if netEndCell > maxNetEnd {
			maxNetEnd, maxNetBorder = netEndCell, borderCell
		}
		pct := strings.LastIndex(row[:netStart], "%")
		if pct < 0 {
			t.Fatalf("a leader price line has no percentage: %q", row)
		}
		pctEndCell := runeLen(row[:pct+1])
		if netStartCell-pctEndCell != 3 {
			t.Errorf("the percentage and NET DELTA gap changed: %d cells: %q",
				netStartCell-pctEndCell, row)
		}
		found++
	}
	if found < 2 {
		t.Fatalf("only %d leader price lines carried a value group:\n%s",
			found, strings.Join(rows, "\n"))
	}
	if maxNetEnd != maxNetBorder-1 {
		t.Fatalf("the widest NET DELTA ends on cell %d, the tile's last inner cell is %d",
			maxNetEnd, maxNetBorder-1)
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
	want := "Press " + `"` + "LEFT & RIGHT ARROW KEYS" + `"` + " to move."
	if !strings.Contains(s, want) {
		t.Fatalf("the CUSTOM SCRIPS instruction is missing:\n%s", s)
	}
	if strings.Contains(s, "Press LEFT & RIGHT arrow keys") {
		t.Fatalf("the old CUSTOM SCRIPS instruction is still on screen:\n%s", s)
	}
}
