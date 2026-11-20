package main

import (
	"fmt"
	"strings"
	"testing"
	"time"
)

// flowSample150 carries the widest quote an answer can hold (a scrip at
// 26,600.00) beside the common five cell price, so the price field's own width
// is the one ORDER FLOW measures for the whole answer.
const flowSample150 = `{"ok":true,"day":"2026-11-20","as_of":"2026-11-20T10:15:04.000Z",
"counts":{"universe":2,"included":2,"missing":0,"fresh":2},
"rows":[
 {"symbol":"AAA","price":26600.0,"high":26600.0,"low":26600.0,"bid":26600.0,"ask":26600.0,"change_pct":1.2,"volume":1000,"buy_volume":600,"sell_volume":300,"classified_volume":900,"unclassified_volume":100,"split_method":"quote_rule","fresh":true},
 {"symbol":"BBB","price":27.26,"high":27.4,"low":26.6,"bid":27.27,"ask":27.28,"change_pct":1.2,"volume":1000,"buy_volume":600,"sell_volume":300,"classified_volume":900,"unclassified_volume":100,"split_method":"quote_rule","fresh":true}
]}`

// Owner order 2026-11-20 (latest): the ORDER FLOW serial column is gone, so the
// table starts on SYMBOL on the panel's first cell and no row carries a number.
func TestBuild150OrderFlowHasNoSerialColumn(t *testing.T) {
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
	if at := col(rows[head], "#"); at >= 0 {
		t.Errorf("the # heading is still on the page at cell %d: %q", at, rows[head])
	}
	// The panel's left border and its one cell of pad come before the table,
	// and after them the first thing on the page is SYMBOL.
	if body := strings.TrimLeft(rows[head], " │"); !strings.HasPrefix(body, "SYMBOL") {
		t.Errorf("the table does not start on SYMBOL: %q", rows[head])
	}
	seen := 0
	for _, row := range rows[head+1:] {
		body := strings.TrimLeft(row, " │")
		if !strings.HasPrefix(body, "AAA") && !strings.HasPrefix(body, "BBB") {
			continue
		}
		// The serial was drawn as "1.", "2." on the row's first cell.
		if len(body) > 1 && body[0] >= '1' && body[0] <= '9' && body[1] == '.' {
			t.Errorf("a serial number is still drawn on the row: %q", row)
		}
		seen++
	}
	if seen < 2 {
		t.Fatalf("the two stock rows are missing:\n%s", strings.Join(rows[head:], "\n"))
	}
}

// Owner order 2026-11-20 (latest): a price field is eight cells wide, so the
// widest quote in the answer keeps every digit and simply gives up its
// thousands separator, which takes one cell out of the gap before it.
func TestBuild150OrderFlowPriceFieldGivesUpOnlyTheSeparator(t *testing.T) {
	a := orderFlowApp(t, 200, 50, flowSample150)
	big, small := "", ""
	for _, row := range rowsOf(a) {
		switch {
		case strings.Contains(row, "AAA"):
			big = row
		case strings.Contains(row, "BBB"):
			small = row
		}
	}
	if big == "" || small == "" {
		t.Fatalf("the two stock rows are missing")
	}
	if !strings.Contains(big, "26600.00") {
		t.Errorf("the 26,600 figure lost digits: %q", big)
	}
	if strings.Contains(big, "26,600.00") {
		t.Errorf("a figure wider than the field kept its separator: %q", big)
	}
	if !strings.Contains(small, "27.26") {
		t.Errorf("the common price is missing: %q", small)
	}
}

// Owner order 2026-11-20 (latest): with only the groups on the tile, the
// overall percentage moves one cell right, onto the content's last cell beside
// the scrollbar.
func TestBuild150SectorPercentageMovesOneCellRight(t *testing.T) {
	a := demoApp(t, 122, 36)
	a.demo = false
	a.quotes = nil
	a.screen = scrScanner
	items := make([]Sector, 0, 12)
	for i := 0; i < 12; i++ {
		items = append(items, Sector{Name: fmt.Sprintf("GROUP %02d", i),
			Symbols: []string{"AAA"}})
	}
	a.sectors = &Sectors{OK: true, Items: items}
	a.symbols = nil
	a.prices = map[string]Quote{"AAA": {Price: 10, ChangePct: f64(1.5)}}
	rows := rowsOf(a)
	scrAt, pctAt, row := -1, -1, ""
	for _, line := range rows {
		if !strings.Contains(line, "GROUP") || !strings.Contains(line, "%") ||
			!strings.ContainsAny(line, "▲▼") {
			continue
		}
		for i, r := range []rune(line) {
			if r == '%' {
				pctAt = i
			}
			if r == '┃' && scrAt < 0 {
				scrAt = i
			}
		}
		row = line
		break
	}
	if scrAt < 0 || pctAt < 0 {
		t.Fatalf("the closed SECTORS tile carries no percentage:\n%s", strings.Join(rows, "\n"))
	}
	// The scrollbar owns the tile's last inner column and the two cells before
	// it are the tile's right pad, so the order's one cell takes the figure from
	// four cells left of the scrollbar to three.
	if want := scrAt - 3; pctAt != want {
		t.Errorf("the sector percentage ends on %d, want %d, three cells left of the scrollbar: %q",
			pctAt, want, row)
	}
}

// Owner order 2026-11-20 (latest): MARKET BREADTH reads BULLISH at or over
// +1000 points, BEARISH at or under -1 point, and FLAT between them.
func TestBuild150BreadthMarksTheOwnersPoints(t *testing.T) {
	cases := []struct {
		change float64
		want   string
	}{
		{1000, "BULLISH"},
		{1100, "BULLISH"},
		{999.99, "FLAT"},
		{0.5, "FLAT"},
		{-0.99, "FLAT"},
		{-1, "BEARISH"},
		{-600, "BEARISH"},
	}
	for _, c := range cases {
		a := newTestApp(t)
		a.w, a.h = 120, 34
		a.link, a.checking = true, false
		a.now = time.Date(2026, 11, 20, 10, 0, 0, 0, pkt)
		a.market = marketIn("OPEN")
		a.quotes = &Quotes{FetchedAt: a.now, Index: &IndexQuote{
			Value: 166409.25, Change: c.change, ChangePct: 0.67, Fresh: true,
		}, Items: map[string]LiveQuote{
			"AAA": {Price: 10, Fresh: true, ChangePct: f64(1.2)},
			"BBB": {Price: 20, Fresh: true, ChangePct: f64(-0.8)},
		}}
		got := plain(a)
		for _, other := range []string{"BULLISH", "BEARISH", "FLAT"} {
			if other != c.want && strings.Contains(got, other) {
				t.Fatalf("KSE100 %+.2f points read %s, want %s:\n%s",
					c.change, other, c.want, got)
			}
		}
		if !strings.Contains(got, c.want) {
			t.Fatalf("KSE100 %+.2f points must read %s:\n%s", c.change, c.want, got)
		}
	}
}
