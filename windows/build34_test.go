package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-17: QUANTITY follows PRICE's box after six blank cells,
// and both fields use the same label column and box width.
func TestCalculatorQuantityFollowsPriceBox(t *testing.T) {
	a := newTestApp(t)
	c := NewCanvas(80, 4, a.th.Panel)
	a.drawCalculatorTile(c, 0, 0, 80, 4)

	row := c.PlainRows()[1]
	price := strings.Index(row, "PRICE")
	qty := strings.Index(row, "QUANTITY")
	if price < 0 || qty < 0 {
		t.Fatalf("the calculator lost a field label: %q", row)
	}
	wantQty := price + 12 + 13 + 6
	if qty != wantQty {
		t.Fatalf("QUANTITY starts on cell %d, want %d (six cells after PRICE's box): %q", qty, wantQty, row)
	}
	field := mix(a.th.Panel, a.th.Accent, 0.14)
	cellAt := func(x int) Cell { return c.Cells[c.W*1+x] }
	if cellAt(price+12).BG != field || cellAt(price+12+13-1).BG != field {
		t.Fatalf("PRICE's box is not the fixed 13 cell field: %q", row)
	}
	if cellAt(price+12+13).BG == field || cellAt(price+12+13+5).BG == field {
		t.Fatalf("the six cells after PRICE's box are not blank: %q", row)
	}
	if cellAt(qty+12).BG != field || cellAt(qty+12+13-1).BG != field {
		t.Fatalf("QUANTITY's box is not the same 13 cell field: %q", row)
	}
}

// Owner order 2026-11-17: the ORDER FLOW order chip says UNCLEAR.
func TestOrderFlowUnclearOrderChip(t *testing.T) {
	if flowSorts[3] != "UNCLEAR" {
		t.Fatalf("the third order is %q, want UNCLEAR", flowSorts[3])
	}
	a := orderFlowApp(t, 160, 45, sampleOrderFlow)
	if s := plain(a); strings.Contains(s, "UNCLASSIFIED") {
		t.Fatalf("ORDER FLOW still says UNCLASSIFIED:\n%s", s)
	}
}

// Owner order 2026-11-17: the large-print footer names the 50k share quantity.
func TestOrderFlowLargePrintFooterNamesQuantity(t *testing.T) {
	a := orderFlowApp(t, 160, 45, sampleOrderFlow)
	s := plain(a)
	if !strings.Contains(s, "large prints of QTY 50k and more.") {
		t.Fatalf("the footer does not name QTY 50k and more:\n%s", s)
	}
	if strings.Contains(s, "PKR 1M or more today") {
		t.Fatalf("the old PKR large-print footer is still present:\n%s", s)
	}
}

// Owner order 2026-11-17: TELEMETRY's REQ row drops "today".
func TestTelemetryReqHasNoToday(t *testing.T) {
	a := demoApp(t, 140, 34)
	a.screen = scrHome
	s := plain(a)
	if strings.Contains(s, " of 100,000 today") {
		t.Fatalf("the REQ row still says today:\n%s", s)
	}
}

// Owner order 2026-11-17: both ALERTS boards keep one exact width on an odd
// page width as well as an even one.
func TestAlertBoardsAreEqualAtOddWidth(t *testing.T) {
	a := demoApp(t, 159, 41)
	a.screen = scrAlerts
	boardRow := ""
	for _, row := range rowsOf(a) {
		if strings.Contains(row, "BIG BUYING NOW") && strings.Contains(row, "BIG SELLING NOW") {
			boardRow = row
		}
	}
	if boardRow == "" {
		t.Fatalf("the two boards are not on one row:\n%s", strings.Join(rowsOf(a), "\n"))
	}
	var opens, closes []int
	for i, r := range []rune(boardRow) {
		switch r {
		case '┏':
			opens = append(opens, i)
		case '┓':
			closes = append(closes, i)
		}
	}
	if len(opens) != 2 || len(closes) != 2 {
		t.Fatalf("cannot measure the two board frames: %q", boardRow)
	}
	if buyW, sellW := closes[0]-opens[0], closes[1]-opens[1]; buyW != sellW {
		t.Fatalf("the selling board spans %d cells, the buying board %d", sellW, buyW)
	}
}
