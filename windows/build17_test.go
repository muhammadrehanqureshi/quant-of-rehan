package main

import (
	"strings"
	"testing"
	"unicode/utf8"
)

// Owner order 2026-11-13: RELAY STATUS carries the relay's current state, not
// the old sentence about its health page.
func TestRelayStatusRowShowsTheCurrentState(t *testing.T) {
	a := busyApp(t, 158, 41, 3)
	a.screen = scrSettings
	s := plain(a)
	if strings.Contains(s, "Opens the relay's health page.") {
		t.Fatalf("the old RELAY STATUS sentence is still on screen:\n%s", s)
	}
	if !strings.Contains(s, "RELAY STATUS") || !strings.Contains(s, "ONLINE") {
		t.Fatalf("the RELAY STATUS row does not show ONLINE:\n%s", s)
	}
	a.link, a.checking = false, false
	if s := plain(a); !strings.Contains(s, "RELAY STATUS") || !strings.Contains(s, "OFFLINE") {
		t.Fatalf("the RELAY STATUS row does not show OFFLINE:\n%s", s)
	}
	a.checking = true
	if s := plain(a); !strings.Contains(s, "RELAY STATUS") || !strings.Contains(s, "CHECKING") {
		t.Fatalf("the RELAY STATUS row does not show CHECKING:\n%s", s)
	}
}

// Owner order 2026-11-13: the search tile's separate VOL line is gone. The
// B, S, U and T line under HIGH and LOW already carries the volume.
func TestSearchTileDropsTheSeparateVolumeLine(t *testing.T) {
	a := demoApp(t, 122, 36)
	a.screen = scrScanner
	a.searchText = "ALFA"
	a.searchCursor = 0
	a.selectedSym = "ALFA"
	a.selectedSt = "ok"
	a.selectedInfo = demoStock("ALFA")
	s := plain(a)
	if strings.Contains(s, "VOL ") {
		t.Fatalf("the SEARCH tile still prints a separate VOL line:\n%s", s)
	}
	for _, want := range []string{"HIGH ", "LOW ", "B=", "S=", "U=", "T="} {
		if !strings.Contains(s, want) {
			t.Errorf("the SEARCH tile is missing %q:\n%s", want, s)
		}
	}
}

// Owner order 2026-11-13: sector percentages use arrows, never a plus or
// minus sign, and they end in the same nine cell right hand field as NET DELTA.
func TestSectorPercentagesUseArrows(t *testing.T) {
	a := demoApp(t, 122, 36)
	a.demo = false
	a.quotes = nil
	a.screen = scrScanner
	a.sectors = &Sectors{OK: true, Items: []Sector{
		{Name: "CEMENT", Symbols: []string{"AAA"}},
		{Name: "AUTOMOBILE", Symbols: []string{"BBB"}},
	}}
	a.prices = map[string]Quote{
		"AAA": {Price: 10, ChangePct: f64(-1.5)},
		"BBB": {Price: 10, ChangePct: f64(2.5)},
	}
	s := plain(a)
	for _, want := range []string{"▲ 2.50%", "▼ 1.50%"} {
		if !strings.Contains(s, want) {
			t.Errorf("the sector list is missing %q:\n%s", want, s)
		}
	}
	if strings.Contains(s, "+2.50%") || strings.Contains(s, "-1.50%") {
		t.Errorf("a sector percentage still carries a sign:\n%s", s)
	}
}

// Owner order 2026-11-13: every bar reads the measured day pair from the scan
// table, not the board's last-minute pair, so the same scrip draws the same
// bar on the ALERTS boards and the scanner.
func TestAlertBarsUseTheScannerPair(t *testing.T) {
	buy, sell := int64(200), int64(50)
	tbl := map[string]Quote{"AAA": {Buy: &buy, Sell: &sell}}
	if gotBuy, gotSell := barPair(tbl, "AAA", 1, 99); gotBuy != buy || gotSell != sell {
		t.Errorf("the board bar took %d/%d instead of the scanner's %d/%d", gotBuy, gotSell, buy, sell)
	}
	if gotBuy, gotSell := barPair(nil, "AAA", 1, 99); gotBuy != 1 || gotSell != 99 {
		t.Errorf("the fallback pair is %d/%d, want 1/99", gotBuy, gotSell)
	}
}

// Owner order 2026-11-13: the two ALERTS boards are equal width, so the PKR
// values and the bars end on one column, and their bars carry no NET DELTA
// label: the only question a bar answers is which side owns the B/S pair.
func TestAlertBoardsShareTheRightHandColumns(t *testing.T) {
	a := demoApp(t, 160, 40)
	a.screen = scrAlerts
	rows := rowsOf(a)
	left, right := -1, -1
	for _, row := range rows {
		// Board rows carry the rank, the symbol and PKR. The log and the
		// headings have no PKR on the board row itself.
		at := strings.Index(row, "PKR ")
		if at < 0 {
			continue
		}
		secondRel := strings.Index(row[at+1:], "PKR ")
		if secondRel < 0 {
			continue
		}
		second := at + 1 + secondRel
		left = utf8.RuneCountInString(row[:at])
		right = utf8.RuneCountInString(row[:second])
		break
	}
	if left < 0 || right < 0 {
		t.Fatalf("the ALERTS boards carry no PKR rows to measure:\n%s", strings.Join(rows, "\n"))
	}
	if got := right - a.alertSplitX; got != left-1 {
		t.Errorf("the selling PKR column is %d cells in, the buying one %d", got, left-1)
	}
}
