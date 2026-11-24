package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-21: ORDER FLOW carries its numbering again, as a "#"
// column on the panel's very first cell. Owner order 2026-11-21 (second pass):
// every number starts on the "#"'s own cell and carries a full stop after it.
func TestBuild153OrderFlowStartsWithTheNumbering(t *testing.T) {
	a := orderFlowApp(t, 200, 50, flowSample150)
	rows := rowsOf(a)
	head := -1
	for i, row := range rows {
		if strings.Contains(row, "SCRIP") && strings.Contains(row, "BUYING (B)") {
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
	if len(h) < ix+flowNumW+flowGutter+len("SCRIP") {
		t.Fatalf("the heading row is too short to carry the table: %q", rows[head])
	}
	if got := string(h[ix : ix+flowNumW]); got != "#  " {
		t.Errorf("the first column reads %q, want the # heading on its first cell: %q", got, rows[head])
	}
	// Owner order 2026-11-24: the column is headed SCRIP.
	if got := string(h[ix+flowNumW+flowGutter : ix+flowNumW+flowGutter+len("SCRIP")]); got != "SCRIP" {
		t.Errorf("SCRIP does not follow the # column: %q", rows[head])
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
	for _, want := range []string{"1. ", "2. "} {
		found := false
		for _, got := range serials {
			if got == want {
				found = true
			}
		}
		if !found {
			t.Errorf("no row carried %q, want the number on the # cell with a full stop: %v", want, serials)
		}
	}
}

// Owner order 2026-11-21: the SYMBOL field is the heading's own cells instead of
// build 152's eight, so the gap from SYMBOL to PRICE is tighter, and a longer
// name is drawn into the cells the field gave up. Owner order 2026-11-24
// (later): the field is one cell wider again, so one blank cell stands between
// SCRIP and the gutter.
func TestBuild153SymbolToPriceGapIsTwoCellsTighter(t *testing.T) {
	flowDropHL = false
	rows := []FlowRow{{Symbol: "AAA", Price: 10, Buy: i64(60), Sell: i64(40),
		Volume: i64(100), Method: methodMeasured}}
	cols, _ := flowColumns(rows)
	// Owner order 2026-11-24 (later): the field is one cell wider than build 162's
	// six, so a blank cell stands between the longest heading and the gutter.
	if flowSymW != 7 {
		t.Fatalf("the SCRIP field is %d cells, want SCRIP and the one blank cell", flowSymW)
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
	// blank cells and the gutter before PRICE; the field is three cells narrower
	// than that now, and one cell wider than build 162's.
	if old := flowSymX + 8 + flowGutter; cols[0].x != old-1 {
		t.Fatalf("PRICE starts on cell %d, want one cell left of build 152's %d", cols[0].x, old)
	}
}

// Owner order 2026-11-24 (later): CUSTOM SCRIPS OF VOLUME left aligns its NET
// DELTA, so 4.8M and 3M start on the same cell, the field's own first cell.
// That is the owner's own sentence: 2.8M and 8.51k must start where 268.31k
// starts.
func TestBuild153CustomScripsNetDeltaStartsOnOneCell(t *testing.T) {
	a := demoApp(t, 158, 41)
	c := NewCanvas(60, 2, a.th.Panel)
	a.shareBarNetLeft(c, 0, 0, shareBarWidth, 5_000_000, 200_000) // 4.8M
	a.shareBarNetLeft(c, 0, 1, shareBarWidth, 3_200_000, 200_000) // 3M
	rows := c.PlainRows()
	// The bar's block is three bytes, so a cell is its rune index.
	at := func(row string, ch rune) int {
		for i, r := range []rune(row) {
			if r == ch {
				return i
			}
		}
		return -1
	}
	one, two := at(rows[0], '4'), at(rows[1], '3')
	if one < 0 || two < 0 {
		t.Fatalf("a NET DELTA figure is missing:\n%q\n%q", rows[0], rows[1])
	}
	if one != two {
		t.Fatalf("the figures start on cell %d and %d, want one cell:\n%q\n%q", one, two, rows[0], rows[1])
	}
	if want := shareBarSpan + shareBarGap; one != want {
		t.Fatalf("the figure starts on cell %d, want the field's first cell %d", one, want)
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
