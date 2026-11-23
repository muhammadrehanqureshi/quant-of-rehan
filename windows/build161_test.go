package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-23 (latest): the BIG BUYING NOW and BIG SELLING NOW
// boards step their price, percentage, quantity and bar left as one group, and
// close every row with NET DELTA and its figure right after the bar. The
// figure's last cell stands on the row's last content cell, and the price, the
// percentage, the bar and the figure keep one column down the board.
func TestBuild161BoardsCarryNetDeltaAfterTheBar(t *testing.T) {
	a := demoApp(t, 160, 40)
	// The demo snapshot can be all buying. Seed one sell-dominant stock so the
	// selling board has a priced row too.
	a.flow.sym["SELLX"] = &symFlow{have: true, t: a.now, px: 10, vol: 250_000,
		evts: []flowEvt{{t: a.now, dv: 250_000, px: 10, side: -1}}}
	for _, side := range []int{sideBuy, sideSell} {
		c := NewCanvas(79, 20, a.th.Panel)
		a.drawBoardPanel(c, 0, 0, 79, 20, side)
		rows := c.PlainRows()
		frame := -1
		for _, row := range rows {
			if f := col(row, "┓"); f >= 0 {
				frame = f
				break
			}
		}
		if frame < 0 {
			t.Fatalf("side %d: the board has no frame:\n%s", side, strings.Join(rows, "\n"))
		}
		seen := 0
		priceAt, pctAt, netAt, barFrom, barTo := -1, -1, -1, -1, -1
		for _, row := range rows {
			if !strings.Contains(row, "PKR ") || !strings.ContainsRune(row, barBlock) {
				continue
			}
			r := []rune(row)
			last := len(r) - 1
			for last > 0 && r[last] == ' ' {
				last--
			}
			if last >= frame-1 {
				t.Fatalf("side %d: the row runs into the frame: %q", side, row)
			}
			at := col(row, "NET DELTA=")
			if at < 0 {
				t.Fatalf("side %d: the row carries no NET DELTA: %q", side, row)
			}
			from := col(row, string(barBlock))
			if from < 0 {
				t.Fatalf("side %d: the row carries no bar: %q", side, row)
			}
			to := from
			for to+1 < len(r) && r[to+1] == barBlock {
				to++
			}
			// The bar ends one blank cell before the label, so NET DELTA stands
			// right after it.
			if to >= at || to+1 != at-1 {
				t.Fatalf("side %d: the bar ends on %d and NET DELTA starts on %d: %q",
					side, to, at, row)
			}
			if to-from+1 < 6 {
				t.Fatalf("side %d: the bar is %d cells, too short to read: %q",
					side, to-from+1, row)
			}
			// The bar keeps the two cell gutter the quantity had before it.
			if from >= 2 && (r[from-1] != ' ' || r[from-2] != ' ') {
				t.Fatalf("side %d: the bar lost its two cell gutter: %q", side, row)
			}
			// Nothing stands after the figure: its last cell is the row's last ink.
			if last < at+netLabelEq {
				t.Fatalf("side %d: NET DELTA carries no figure: %q", side, row)
			}
			fig := strings.TrimSpace(string(r[at+netLabelEq : last+1]))
			if fig == "" || strings.Contains(fig, " ") {
				t.Fatalf("side %d: NET DELTA carries no single figure: %q", side, row)
			}
			if col(row, "PKR ") < 16 {
				t.Fatalf("side %d: PKR steps onto the symbol: %q", side, row)
			}
			if col(row, "PKR ") > at {
				t.Fatalf("side %d: the price stands after NET DELTA: %q", side, row)
			}
			if seen == 0 {
				priceAt, pctAt, netAt, barFrom, barTo = col(row, "PKR "), col(row, "%"), at, from, to
			} else {
				if col(row, "PKR ") != priceAt || at != netAt || from != barFrom || to != barTo {
					t.Fatalf("side %d: the columns moved from the first row: %q", side, row)
				}
				if pct := col(row, "%"); pct >= 0 && pctAt >= 0 && pct != pctAt {
					t.Fatalf("side %d: the percentage moved: %q", side, row)
				}
			}
			seen++
		}
		if seen == 0 {
			t.Fatalf("side %d: no priced board row was found:\n%s", side, strings.Join(rows, "\n"))
		}
	}
}
