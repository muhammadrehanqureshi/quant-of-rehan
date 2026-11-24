package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-24: both ALERTS boards drop the words NET DELTA and keep
// only its figure, which stands right after the bar and closes the row. The
// percentage, the quantity, the bar and the figure keep one column down the
// board.
func TestBuild161BoardsCarryTheNetDeltaFigureAfterTheBar(t *testing.T) {
	a := demoApp(t, 160, 40)
	// The demo snapshot can be all buying. Seed one sell-dominant stock so the
	// selling board has a priced row too.
	a.flow.sym["SELLX"] = &symFlow{have: true, t: a.now, px: 10, vol: 250_000,
		evts: []flowEvt{{t: a.now, dv: 250_000, px: 10, side: -1}}}
	for _, side := range []int{sideBuy, sideSell} {
		c := NewCanvas(79, 20, a.th.Panel)
		a.drawBoardPanel(c, 0, 0, 79, 20, side)
		rows := c.PlainRows()
		seen := 0
		pkrAt, pctAt, barFrom, figAt := -1, -1, -1, -1
		for _, row := range rows {
			if !strings.Contains(row, "PKR ") || !strings.ContainsRune(row, barBlock) {
				continue
			}
			if strings.Contains(row, "NET DELTA") {
				t.Fatalf("side %d: the board still writes NET DELTA: %q", side, row)
			}
			// The board's own frame closes the row, so it and the blanks before
			// it are dropped before the row's last ink is measured.
			r := []rune(strings.TrimRight(row, " "))
			for len(r) > 0 && (r[len(r)-1] == '│' || r[len(r)-1] == ' ') {
				r = r[:len(r)-1]
			}
			from := -1
			for i, ch := range r {
				if ch == barBlock {
					from = i
					break
				}
			}
			if from < 0 {
				continue
			}
			to := from
			for to+1 < len(r) && r[to+1] == barBlock {
				to++
			}
			if to-from+1 < 6 {
				t.Fatalf("side %d: the bar is %d cells, too short to read: %q",
					side, to-from+1, row)
			}
			start := to + 1
			for start < len(r) && r[start] == ' ' {
				start++
			}
			// The figure stands exactly one cell after the bar, never two.
			if start != to+2 {
				t.Fatalf("side %d: the figure stands %d cells after the bar, want 1: %q",
					side, start-to-1, row)
			}
			fig := strings.TrimSpace(string(r[start:]))
			if fig == "" || strings.Contains(fig, " ") {
				t.Fatalf("side %d: the row carries no single NET DELTA figure: %q", side, row)
			}
			if seen == 0 {
				pkrAt, pctAt, barFrom, figAt = col(row, "PKR "), col(row, "%"), from, start
			} else {
				if col(row, "PKR ") != pkrAt || from != barFrom || start != figAt {
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
