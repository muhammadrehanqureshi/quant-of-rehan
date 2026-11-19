package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-19: ALERTS LOG leads from bought or sold into its price
// column with the word at, never a full stop.
func TestBuild143AlertLogSaysAtBeforePrice(t *testing.T) {
	a := demoApp(t, 140, 34)
	a.flow.Log = []Flag{{
		Time: a.now, Symbol: "PRL", Kind: "flow", Side: "BUY", Value: 100_000,
		Price: 114.65, ChangePct: f64(5.08),
		Text: "100k shares of PRL were bought at PKR 114.65 ▲ 5.08%.",
	}}
	c := NewCanvas(140, 8, a.th.Panel)
	a.drawAlertLog(c, 0, 0, 140, 8)
	s := strings.Join(c.PlainRows(), "\n")
	if !strings.Contains(s, "were bought at") {
		t.Fatalf("the log does not lead into its price with at:\n%s", s)
	}
	if strings.Contains(s, "were bought.") {
		t.Fatalf("the log still ends the sentence with a full stop:\n%s", s)
	}
}

// Owner order 2026-11-19: the ALERTS SEARCH ledger keeps one cell between the
// NET DELTA labels and their values, even when the value fills its field.
func TestBuild143SearchLedgerSpacesNetDeltaValues(t *testing.T) {
	a := demoApp(t, 140, 34)
	c := NewCanvas(100, 6, a.th.Panel)
	a.drawSearchLedger(c, 0, 0, 100, 6, i64(999_900), i64(0), i64(999_900), false)
	rows := c.PlainRows()
	for _, row := range rows {
		if at := col(row, "NET DELTA %"); at >= 0 {
			r := []rune(row)
			if at+11 >= len(r) || r[at+11] != ' ' {
				t.Fatalf("NET DELTA %% and its value touch: %q", row)
			}
		}
		if at := col(row, "NET DELTA"); at >= 0 && col(row, "NET DELTA %") < 0 {
			r := []rune(row)
			if at+9 >= len(r) || r[at+9] != ' ' {
				t.Fatalf("NET DELTA and its value touch: %q", row)
			}
		}
	}
}

// Owner order 2026-11-19: the open SECTORS list holds PKR, the price, the arrow
// and the percentage on fixed columns, with exactly one cell after the arrow.
func TestBuild143SectorQuotesUseOneGap(t *testing.T) {
	a := demoApp(t, 158, 41)
	a.demo = false
	a.quotes = nil
	a.screen = scrScanner
	a.sectors = &Sectors{OK: true, Items: []Sector{{Name: "TEST", Symbols: []string{"AAA", "BBB"}}}}
	a.prices = map[string]Quote{
		"AAA": {Price: 71.44, ChangePct: f64(2.03)},
		"BBB": {Price: 127.49, ChangePct: f64(-2.01)},
	}
	a.symbols = nil
	a.sectorOpen, a.sectorChoice = true, 0
	a.lvSectorStk.top()
	c := NewCanvas(120, 12, a.th.Panel)
	a.drawSectorOpen(c, 0, 0, 120, 12)
	pkrAt, pctAt, found := -1, -1, 0
	for _, row := range c.PlainRows() {
		if !strings.Contains(row, "PKR ") || !strings.Contains(row, "%") {
			continue
		}
		found++
		r := []rune(row)
		pkr, pct := col(row, "PKR "), col(row, "%")
		arrow := col(row, "▲")
		if arrow < 0 {
			arrow = col(row, "▼")
		}
		if arrow < 0 {
			t.Fatalf("the sector row carries no arrow: %q", row)
		}
		if arrow+2 >= len(r) || r[arrow+1] != ' ' || r[arrow+2] == ' ' {
			t.Fatalf("the sector arrow and percentage do not keep one cell: %q", row)
		}
		if pkrAt < 0 {
			pkrAt, pctAt = pkr, pct
		} else if pkr != pkrAt || pct != pctAt {
			t.Fatalf("the sector quote group moved: PKR %d/%d, %% %d/%d: %q", pkr, pkrAt, pct, pctAt, row)
		}
	}
	if found < 2 {
		t.Fatalf("only %d sector quote rows were found", found)
	}
}

// Owner order 2026-11-19: the BIG BUYING NOW and BIG SELLING NOW headings keep
// the panel's own hot diamond, in the cell every other tile uses.
func TestBuild143BoardsUseTheStandardDiamond(t *testing.T) {
	a := demoApp(t, 120, 30)
	c := NewCanvas(120, 10, a.th.Panel)
	a.drawBoardPanel(c, 0, 0, 60, 10, sideBuy)
	cell := c.Cells[2] // the heading row, the same cell a.panel marks
	if cell.Ch != '◆' {
		t.Fatalf("the board heading carries %q, want the standard diamond", cell.Ch)
	}
	if cell.FG != a.th.Hot {
		t.Fatalf("the board diamond is not the standard heading ink")
	}
}
