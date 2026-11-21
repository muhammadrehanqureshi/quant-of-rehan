package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-21: ORDER FLOW carries its numbering again, as a "#"
// column on the panel's very first cell, with each row's own number right
// aligned in it.
func TestBuild153OrderFlowStartsWithTheNumbering(t *testing.T) {
	a := orderFlowApp(t, 200, 50, flowSample150)
	rows := rowsOf(a)
	head := -1
	for i, row := range rows {
		if strings.Contains(row, "SYMBOL") && strings.Contains(row, "BUYING (B)") {
			head = i
			break
		}
	}
	if head < 0 {
		t.Fatalf("the ORDER FLOW heading is missing:\n%s", strings.Join(rows, "\n"))
	}
	// The page starts on cell 1 and the panel's frame and one cell of pad come
	// before its inner rectangle, so the table starts on rune 3.
	const ix = 3
	h := []rune(rows[head])
	if len(h) < ix+flowNumW+flowGutter+len("SYMBOL") {
		t.Fatalf("the heading row is too short to carry the table: %q", rows[head])
	}
	if got := string(h[ix : ix+flowNumW]); got != "#  " {
		t.Errorf("the first column reads %q, want the # heading on its first cell: %q", got, rows[head])
	}
	if got := string(h[ix+flowNumW+flowGutter : ix+flowNumW+flowGutter+len("SYMBOL")]); got != "SYMBOL" {
		t.Errorf("SYMBOL does not follow the # column: %q", rows[head])
	}
	var serials []string
	for _, row := range rows[head+1:] {
		if !strings.Contains(row, "AAA") && !strings.Contains(row, "BBB") {
			continue
		}
		r := []rune(row)
		if len(r) < ix+flowNumW {
			continue
		}
		serials = append(serials, string(r[ix:ix+flowNumW]))
	}
	if len(serials) < 2 {
		t.Fatalf("the two stock rows are missing:\n%s", strings.Join(rows[head:], "\n"))
	}
	for _, want := range []string{"  1", "  2"} {
		found := false
		for _, got := range serials {
			if got == want {
				found = true
			}
		}
		if !found {
			t.Errorf("no row carried %q, want the number right aligned in the # column: %v", want, serials)
		}
	}
}

// Owner order 2026-11-21: the SYMBOL field is the heading's six cells instead
// of build 152's eight, so the gap from SYMBOL to PRICE is two cells tighter,
// and a longer name is drawn into the cells the field gave up.
func TestBuild153SymbolToPriceGapIsTwoCellsTighter(t *testing.T) {
	flowDropHL = false
	rows := []FlowRow{{Symbol: "AAA", Price: 10, Buy: i64(60), Sell: i64(40),
		Volume: i64(100), Method: methodMeasured}}
	cols, _ := flowColumns(rows)
	if flowSymW != len("SYMBOL") {
		t.Fatalf("the SYMBOL field is %d cells, want the heading's %d", flowSymW, len("SYMBOL"))
	}
	if flowSymDrawW < len("PAKQATAR") {
		t.Fatalf("a long ticker would be cut at %d cells, want at least %d", flowSymDrawW, len("PAKQATAR"))
	}
	if gap := cols[0].x - (flowSymX + flowSymW); gap != flowGutter {
		t.Fatalf("SYMBOL to PRICE leaves %d cells, want the one gutter", gap)
	}
	if want := flowSymX + flowSymW + flowGutter; cols[0].x != want {
		t.Fatalf("PRICE starts on cell %d, want %d", cols[0].x, want)
	}
	// Build 152 held the field at eight cells, so a six letter heading left two
	// blank cells and the gutter before PRICE.
	if old := flowSymX + 8 + flowGutter; cols[0].x != old-2 {
		t.Fatalf("PRICE starts on cell %d, want two cells left of build 152's %d", cols[0].x, old)
	}
}

// Owner order 2026-11-21: CUSTOM SCRIPS OF VOLUME right aligns its NET DELTA, so
// 4.8M and 3M end with the M on the same cell, the field's own last cell.
func TestBuild153CustomScripsNetDeltaEndsOnOneCell(t *testing.T) {
	a := demoApp(t, 158, 41)
	c := NewCanvas(60, 2, a.th.Panel)
	a.shareBarNetRight(c, 0, 0, shareBarWidth, 5_000_000, 200_000) // 4.8M
	a.shareBarNetRight(c, 0, 1, shareBarWidth, 3_200_000, 200_000) // 3M
	rows := c.PlainRows()
	at := func(row string) int { return strings.Index(row, "M") }
	one, two := at(rows[0]), at(rows[1])
	if one < 0 || two < 0 {
		t.Fatalf("a NET DELTA unit is missing:\n%q\n%q", rows[0], rows[1])
	}
	if one != two {
		t.Fatalf("the M ends on cell %d and %d, want one cell:\n%q\n%q", one, two, rows[0], rows[1])
	}
	if want := shareBarWidth - 1; one != want {
		t.Fatalf("the M ends on cell %d, want the field's last cell %d", one, want)
	}
}

// Owner order 2026-11-21: a relay that answers but sends no quotes table at all
// leaves the FEED row reading NO FEED, never a dash.
func TestBuild153FeedRowSaysNoFeedWithoutATable(t *testing.T) {
	a := demoApp(t, 122, 36)
	a.demo = false
	a.checking = false
	a.link = true
	a.quotes = nil
	a.lastMarketOK = a.now
	found := false
	for _, row := range rowsOf(a) {
		if strings.Contains(row, "FEED") && strings.Contains(row, "NO FEED") {
			found = true
		}
	}
	if !found {
		t.Fatalf("the FEED row does not say NO FEED:\n%s", strings.Join(rowsOf(a), "\n"))
	}
}
