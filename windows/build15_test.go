package main

import (
	"fmt"
	"strings"
	"testing"
)

// Owner order 2026-11-13: the bar splits the pair it prints, on its own cells.
// PRL's 884,017 buys against 1,376,954 sells is 39.1 percent, six of sixteen
// green cells, not the four of ten boxes that drew a false 50/50.
func TestShareBarSplitsOnThePairItPrints(t *testing.T) {
	cases := []struct {
		name       string
		buy, sell  int64
		span, want int
	}{
		{"PRL's printed pair", 884017, 1376954, shareBarSpan, 6},
		{"an even pair", 5, 5, shareBarSpan, 8},
		{"the sellers alone", 0, 100, shareBarSpan, 0},
		{"the buyers alone", 100, 0, shareBarSpan, 16},
		{"the boards' compact bar", 884017, 1376954, 10, 4},
	}
	for _, c := range cases {
		if got := shareGreenCells(c.buy, c.sell, c.span); got != c.want {
			t.Errorf("%s: %d buys and %d sells drew %d green of %d, want %d",
				c.name, c.buy, c.sell, got, c.span, c.want)
		}
	}
}

func TestShareBarPaintsTheExactSplit(t *testing.T) {
	a := demoApp(t, 120, 30)
	c := NewCanvas(40, 1, a.th.Panel)
	a.shareBar(c, 2, 0, shareBarWidth, 884017, 1376954)
	green, red := 0, 0
	for x := 2; x < 2+shareBarSpan; x++ {
		switch c.Cells[x].FG {
		case a.th.Good:
			green++
		case a.th.Bad:
			red++
		}
	}
	if green != 6 || red != 10 {
		t.Fatalf("PRL's bar painted %d green and %d red cells, want 6 and 10", green, red)
	}
}

// Owner order 2026-11-13: the SECTORS tile shows six groups and scrolls the
// rest, and the calculator stands as its own tile under CUSTOM SCRIPS.
func TestScannerShowsSixSectorsAndTheCalculatorTile(t *testing.T) {
	a := demoApp(t, 158, 41)
	a.demo = false
	a.screen = scrScanner
	items := make([]Sector, 0, 13)
	for i := 0; i < 13; i++ {
		items = append(items, Sector{Name: fmt.Sprintf("GROUP %02d", i)})
	}
	a.sectors = &Sectors{OK: true, Items: items}
	s := plain(a)
	if a.sectorH != 10 {
		t.Fatalf("the SECTORS tile is %d rows, want ten for its six list rows", a.sectorH)
	}
	if a.lvSector.view != 6 {
		t.Fatalf("the SECTORS tile shows %d groups, want six", a.lvSector.view)
	}
	if !strings.Contains(s, "POSITION CALCULATOR") || !strings.Contains(s, "TOTAL") {
		t.Fatalf("the calculator tile is missing under CUSTOM SCRIPS:\n%s", s)
	}
	rows := rowsOf(a)
	if len(rows) == 0 || strings.Contains(rows[len(rows)-1], "CALC") {
		t.Fatalf("the SCANNER footer still carries a CALC key: %q", rows[len(rows)-1])
	}
}

// Owner order 2026-11-13: the PRICE ALERTS form names its first box SCRIP.
func TestPriceAlertFormNamesTheScrip(t *testing.T) {
	a := demoApp(t, 120, 30)
	a.screen = scrAlerts
	a.startPriceEdit(0)
	rows := rowsOf(a)
	at := -1
	for i, row := range rows {
		if strings.Contains(row, "PRICE ALERT 1 OF 3") {
			at = i
			break
		}
	}
	if at < 0 || at+1 >= len(rows) {
		t.Fatalf("the PRICE ALERTS form is missing:\n%s", strings.Join(rows, "\n"))
	}
	if !strings.Contains(rows[at+1], "SCRIP") {
		t.Fatalf("the form's first box is not named SCRIP: %q", rows[at+1])
	}
	if strings.Contains(rows[at+1], "SYMBOL") {
		t.Fatalf("the form still says SYMBOL: %q", rows[at+1])
	}
}
