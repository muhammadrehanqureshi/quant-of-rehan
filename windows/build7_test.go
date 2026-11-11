package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-11: a B and S line reads buying, selling and the total,
// with no unclear figure of any kind.
func TestBSTLineCarriesBuySellAndTotal(t *testing.T) {
	a := newTestApp(t)
	c := NewCanvas(80, 1, a.th.Panel)
	b, s, total := int64(600), int64(300), int64(1000)
	a.putBST(c, 0, 0, &b, &s, &total)
	row := c.PlainRows()[0]
	if !strings.Contains(row, "B=600, S=300, T=1,000") {
		t.Fatalf("the line does not read B, S and T: %q", row)
	}
	if strings.Contains(row, "U=") {
		t.Fatalf("an unclear figure is on the line: %q", row)
	}
}

// A stock whose volume adds up exactly reads the same way, with nothing else.
func TestBSTLineSaysTotalWithNoUnclearFigure(t *testing.T) {
	a := newTestApp(t)
	c := NewCanvas(80, 1, a.th.Panel)
	b, s, total := int64(600), int64(300), int64(900)
	a.putBST(c, 0, 0, &b, &s, &total)
	if row := c.PlainRows()[0]; !strings.Contains(row, "T=900") || strings.Contains(row, "U=") {
		t.Fatalf("a fully sided stock must read B, S and T alone: %q", row)
	}
}

// Owner order 2026-11-10 (later): the bar fills its own box, so the colour is
// centred in the box rather than sitting along its bottom edge, and each box
// carries one solid colour.
// Owner order 2026-11-10 (latest): there is exactly one shade of green and one
// of red, ten boxes of one cell each, and no separator glyph at all.
func TestBarsAreBuild21sShadedTabs(t *testing.T) {
	a := demoApp(t, 100, 30)
	c := NewCanvas(40, 1, RGB{})
	a.shareBar(c, 2, 0, shareBarWidth, 0.5)
	row := c.PlainRows()[0]
	// Owner order 2026-11-10 (latest): the bar gained another ten percent of
	// height, so it is the medium rectangle and not the thin rule; no full
	// block glyph stands inside it.
	if barBlock != '▬' {
		t.Fatalf("the bar is %q, not the medium height rectangle", barBlock)
	}
	for _, block := range "█▄▀■" {
		if block == barBlock {
			t.Fatal("a full block glyph is inside the bar again")
		}
	}
	if strings.ContainsRune(row, '│') {
		t.Fatalf("a line is drawn between the boxes again: %q", row)
	}
	inks := map[RGB]bool{}
	for _, ce := range c.Cells {
		if ce.Ch == barBlock {
			inks[ce.FG] = true
		}
	}
	if len(inks) != 2 {
		t.Fatalf("the bar painted %d inks, want exactly one green and one red", len(inks))
	}
}

// Owner order 2026-11-10 (later): the three volume leaders carry the same bar
// the order flow carries, and the price follows the T volume rather than
// leading the row.
func TestLeaderBarsAreOrderFlowBarsAndPriceFollowsT(t *testing.T) {
	rows := rowsOf(busyApp(t, 158, 41, 3))
	inMarket, priced := false, 0
	for _, r := range rows {
		switch {
		case strings.Contains(r, "THE TOP 3 SCRIPS OF VOLUME"):
			inMarket = true
			continue
		case strings.Contains(r, "BUYING NOW"):
			inMarket = false
		}
		if !inMarket {
			continue
		}
		ti, pi := strings.Index(r, "& T="), strings.Index(r, "PKR ")
		if ti < 0 || pi < 0 {
			continue
		}
		priced++
		if pi < ti {
			t.Fatalf("the price leads the volume: %q", r)
		}
	}
	if priced == 0 {
		// Print the whole tile, so a failure names the row that lost its
		// price or its T volume instead of only saying that one did.
		var b strings.Builder
		inside := false
		for _, r := range rows {
			switch {
			case strings.Contains(r, "THE TOP 3 SCRIPS OF VOLUME"):
				inside = true
			case strings.Contains(r, "BUYING NOW"):
				inside = false
			}
			if inside {
				b.WriteString(r + "\n")
			}
		}
		t.Fatalf("no leader line carries both a T volume and a price:\n%s", b.String())
	}
}

// Owner order 2026-11-10: the dot meters are gone; short green and red bars
// stand where they were.
func TestBarMeterIsGreenAndRed(t *testing.T) {
	a := newTestApp(t)
	c := NewCanvas(40, 2, a.th.Panel)
	vals := []float64{100, 101, 100.5, 102, 101, 100}
	if !barMeter(c, 0, 0, 28, 2, vals, a.th.Good, a.th.Bad, a.th.Panel) {
		t.Fatal("the meter drew nothing")
	}
	green, red := false, false
	for _, ce := range c.Cells {
		if ce.Ch != '█' && ce.Ch != '▄' {
			continue
		}
		if ce.FG == a.th.Good {
			green = true
		}
		if ce.FG == a.th.Bad {
			red = true
		}
	}
	if !green || !red {
		t.Fatalf("the meter is not both green and red: green %v, red %v", green, red)
	}
}
