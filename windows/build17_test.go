package main

import (
	"strings"
	"testing"
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
	// Owner order 2026-11-18: the percentage is right aligned, so the arrow
	// and the figure no longer sit against each other.
	for _, want := range []string{"▲", "▼", "2.50%", "1.50%"} {
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

// Owner order 2026-11-16: the two ALERTS boards are equal width, so the share
// quantities and the bars end on one column. Owner order 2026-11-23 (latest):
// NET DELTA stands after each bar, and the two boards measure their fields
// together, so the selling columns stand exactly one board pitch after the
// buying ones whether or not either board scrolls.
func TestAlertBoardsShareTheRightHandColumns(t *testing.T) {
	a := demoApp(t, 160, 40)
	a.screen = scrAlerts
	// The demo snapshot can be all buying. Seed one sell-dominant stock so both
	// boards carry a row and the right-hand columns are what is measured.
	a.flow.sym["SELLX"] = &symFlow{have: true, t: a.now, px: 10, vol: 250_000,
		evts: []flowEvt{{t: a.now, dv: 250_000, px: 10, side: -1}}}
	rows := rowsOf(a)
	left, right := -1, -1
	for _, row := range rows {
		// A board row carries two prices and two bars, one for each board. The
		// share quantity ends two cells before its own bar's first cell.
		if strings.Count(row, "PKR ") < 2 {
			continue
		}
		runes := []rune(row)
		var starts []int
		for i, r := range runes {
			if r == barBlock && (i == 0 || runes[i-1] != barBlock) {
				starts = append(starts, i)
			}
		}
		if len(starts) < 2 {
			continue
		}
		left = starts[0] - 3
		right = starts[1] - 3
		break
	}
	if left < 0 || right < 0 {
		t.Fatalf("the ALERTS boards carry no share rows to measure:\n%s", strings.Join(rows, "\n"))
	}
	if got := right - left; got != a.alertSplitX {
		t.Errorf("the selling quantity ends %d cells after the buying one, want the board pitch %d", got, a.alertSplitX)
	}
}
