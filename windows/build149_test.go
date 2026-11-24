package main

import (
	"strings"
	"testing"
	"time"
	"unicode/utf8"
)

// Owner order 2026-11-20 (latest): both ALERTS boards write PKR on one column
// and the price right aligned in its own field, so a scrip carrying fewer
// digits no longer pulls the label left across the board.
func TestBuild149BoardsHoldThePkrColumn(t *testing.T) {
	a := demoApp(t, 158, 41)
	a.now = time.Date(2026, 10, 30, 11, 42, 18, 0, pkt)
	prices := map[string]float64{"AAA": 286.71, "BBB": 26.09, "CCC": 8.35}
	if a.quotes == nil || a.quotes.Items == nil {
		a.quotes = &Quotes{OK: true, Items: map[string]LiveQuote{}}
	}
	a.flow.sym = map[string]*symFlow{}
	shares := int64(700_000)
	for sym, px := range prices {
		p := px
		a.quotes.Items[sym] = LiveQuote{Price: p, Fresh: true, ChangePct: f64(2.51)}
		a.flow.sym[sym] = &symFlow{have: true, px: p, t: a.now,
			evts: []flowEvt{{t: a.now.Add(-5 * time.Second), dv: shares, px: p, side: 1}}}
		shares -= 100_000
	}
	a.screen = scrAlerts
	rows := rowsOf(a)
	// Only the board's own rows count: the ALERTS LOG below writes PKR and an
	// arrow in its sentences too, on its own columns.
	from := -1
	for i, row := range rows {
		if strings.Contains(row, "BIG BUYING NOW") || strings.Contains(row, "BIG SELLING NOW") {
			from = i
			break
		}
	}
	if from < 0 {
		t.Fatalf("the ALERTS boards are missing:\n%s", strings.Join(rows, "\n"))
	}
	pkrAt, endAt, arrowAt := -1, -1, -1
	seen := 0
	for _, row := range rows[from:] {
		if seen > 0 && col(row, "┛") >= 0 {
			break // the boards' bottom edge: every board row is above it
		}
		at := col(row, "PKR")
		arrow := strings.IndexAny(row, "▲▼")
		if at < 0 || arrow < 0 {
			continue
		}
		body := []rune(row)[:utf8.RuneCountInString(row[:arrow])]
		if len(body) < 2 || body[len(body)-1] != ' ' {
			t.Fatalf("the price leaves no gutter before its arrow: %q", row)
		}
		// The price is right aligned in its own field, so its digits end on the
		// field's last cell and one blank stands between them and the arrow.
		end := len(body) - 1
		for end > 0 && body[end-1] == ' ' {
			end--
		}
		arrowAtRow := utf8.RuneCountInString(row[:arrow])
		if seen == 0 {
			pkrAt, endAt, arrowAt = at, end, arrowAtRow
		} else if at != pkrAt || end != endAt || arrowAtRow != arrowAt {
			t.Errorf("a board row left the quote column: PKR %d of %d, price ends %d of %d, arrow %d of %d: %q",
				at, pkrAt, end, endAt, arrowAtRow, arrowAt, row)
		}
		seen++
	}
	if seen < 3 {
		t.Fatalf("the boards showed %d priced rows, want three:\n%s", seen, strings.Join(rows, "\n"))
	}
	// Every price here is six cells or shorter, so the shared field is six wide
	// and its last cell is where the digits end. endAt is the cell after the
	// last digit.
	if want := pkrAt + quoteLabelW + 6 - 1; endAt-1 != want {
		t.Errorf("PKR stands on %d and the price ends on %d, want the field's last cell %d",
			pkrAt, endAt-1, want)
	}
}

// Owner order 2026-11-20 (latest): a CUSTOM SCRIPS sub menu puts its price, its
// percentage, its bar and the bar's NET DELTA on the tile's own right edge, two
// cells further right than the scrollbar aware edge it used to stand on. Owner
// order 2026-11-21 (second pass): the group stops two cells inside the frame,
// and the NET DELTA field is only as wide as its widest figure.
func TestBuild149CustomScripsQuoteHoldsTheTileEdge(t *testing.T) {
	a := demoApp(t, 158, 41)
	a.screen = scrScanner
	a.scanChoice = 1
	rows := rowsOf(a)
	top := -1
	for i, row := range rows {
		if strings.Contains(row, "CUSTOM SCRIPS OF VOLUME") {
			top = i
			break
		}
	}
	if top < 0 {
		t.Fatal("the CUSTOM SCRIPS tile is missing")
	}
	frame := col(rows[top], "┓")
	if frame < 0 {
		t.Fatalf("the tile's own right edge is missing: %q", rows[top])
	}
	// Owner order 2026-11-22: the group stands two cells further left, so it ends
	// four cells inside the frame, the NET DELTA's last cell stands on frame-5
	// and the bar begins one gutter and one span before it.
	want := frame - 5
	seen := 0
	for _, row := range rows[top+1:] {
		if col(row, "┛") >= 0 {
			break // the tile's bottom edge: every scrip row is above it
		}
		if !strings.Contains(row, "PKR") || !strings.Contains(row, string(barBlock)) {
			continue
		}
		r := []rune(row)
		last := want
		for last > 0 && r[last] == ' ' {
			last--
		}
		if last != want {
			t.Fatalf("the NET DELTA ends on cell %d, want %d inside the frame: %q", last, want, row)
		}
		start := last
		for start > 0 && r[start-1] != ' ' {
			start--
		}
		// The bar keeps its sixteen cells and the figure's field follows one
		// gutter later. A shorter figure is right aligned in that field, so its
		// ink starts inside it and never on the bar.
		barStart := col(row, string(barBlock))
		if barStart < 0 {
			t.Fatalf("the scrip's bar is missing: %q", row)
		}
		barEnd := barStart + shareBarSpan - 1
		if barEnd >= start || start-barEnd > shareNetW {
			t.Errorf("the bar ends on %d and the NET DELTA starts on %d: %q", barEnd, start, row)
		}
		seen++
	}
	if seen == 0 {
		t.Fatalf("the revealed list carried no bar:\n%s", strings.Join(rows[top:], "\n"))
	}
}

// flowSample149 carries a wide price and a narrow one, so the PRICE, HIGH, LOW,
// BID and ASK columns are wider than the short figures they hold.
const flowSample149 = `{"ok":true,"day":"2026-11-20","as_of":"2026-11-20T10:15:04.000Z",
"counts":{"universe":2,"included":2,"missing":0,"fresh":2},
"rows":[
 {"symbol":"AAA","price":1234.56,"high":1234.56,"low":1234.56,"bid":1234.56,"ask":1234.56,"change_pct":1.2,"volume":1000,"buy_volume":600,"sell_volume":300,"classified_volume":900,"unclassified_volume":100,"split_method":"quote_rule","fresh":true},
 {"symbol":"BBB","price":26.09,"high":26.09,"low":26.09,"bid":26.09,"ask":26.09,"change_pct":1.2,"volume":1000,"buy_volume":600,"sell_volume":300,"classified_volume":900,"unclassified_volume":100,"split_method":"quote_rule","fresh":true}
]}`

// gapBefore counts the blank cells in front of the run that ends on cell end.
func gapBefore(row []rune, end int) int {
	i := end
	for i >= 0 && row[i] != ' ' {
		i--
	}
	n := 0
	for i >= 0 && row[i] == ' ' {
		n++
		i--
	}
	return n
}

// Owner order 2026-11-24: every value starts on its heading's first cell, so
// the figures stand under the columns from where the columns start instead of
// being pushed to the right edge of their fields.
func TestBuild149OrderFlowPriceColumnsStartUnderTheirHeadings(t *testing.T) {
	a := orderFlowApp(t, 200, 50, flowSample149)
	rows := rowsOf(a)
	head := -1
	for i, row := range rows {
		if strings.Contains(row, "SCRIP") && strings.Contains(row, "HIGH") && strings.Contains(row, "ASK") {
			head = i
			break
		}
	}
	if head < 0 {
		t.Fatalf("the ORDER FLOW heading carries no HIGH and ASK columns:\n%s", strings.Join(rows, "\n"))
	}
	starts := map[string]int{}
	for _, hd := range []string{"PRICE", "CHANGE", "HIGH", "LOW", "BID", "ASK"} {
		at := col(rows[head], hd)
		if at < 0 {
			t.Fatalf("the heading lost %q: %q", hd, rows[head])
		}
		starts[hd] = at
	}
	seen := 0
	for _, row := range rows[head+1:] {
		if !strings.Contains(row, "AAA") && !strings.Contains(row, "BBB") {
			continue
		}
		body := []rune(row)
		for _, hd := range []string{"PRICE", "HIGH", "LOW", "BID", "ASK"} {
			if at := starts[hd]; at >= len(body) || body[at] == ' ' {
				t.Errorf("%s does not start on its heading's cell %d: %q", hd, at, row)
			}
		}
		// CHANGE's first cell is its arrow, and the arrow stands on the cell
		// the CHANGE heading starts on.
		arrow := strings.IndexAny(row, "▲▼")
		if arrow < 0 {
			t.Fatalf("an ORDER FLOW row carries no change: %q", row)
		}
		if got := utf8.RuneCountInString(row[:arrow]); got != starts["CHANGE"] {
			t.Errorf("CHANGE starts on %d, want its heading's cell %d: %q", got, starts["CHANGE"], row)
		}
		seen++
	}
	if seen == 0 {
		t.Fatalf("no ORDER FLOW row carried the price columns:\n%s", strings.Join(rows, "\n"))
	}
}
