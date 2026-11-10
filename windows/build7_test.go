package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-10: U is on every B and S line, so B + S + U = T reads in
// one glance and the unclassified volume is never missing from a row.
func TestBSTLineCarriesU(t *testing.T) {
	a := newTestApp(t)
	c := NewCanvas(80, 1, a.th.Panel)
	b, s, total := int64(600), int64(300), int64(1000)
	a.putBST(c, 0, 0, &b, &s, &total)
	row := c.PlainRows()[0]
	if !strings.Contains(row, "B=600, S=300, U=100 & T=1,000") {
		t.Fatalf("the line does not read B, S, U and T: %q", row)
	}
	if n := strings.Count(row, "U="); n != 1 {
		t.Fatalf("want one U on the line, found %d: %q", n, row)
	}
}

// A stock whose volume adds up exactly still says U=0 rather than hiding it.
func TestBSTLineSaysUZero(t *testing.T) {
	a := newTestApp(t)
	c := NewCanvas(80, 1, a.th.Panel)
	b, s, total := int64(600), int64(300), int64(900)
	a.putBST(c, 0, 0, &b, &s, &total)
	if row := c.PlainRows()[0]; !strings.Contains(row, "U=0 & T=900") {
		t.Fatalf("a fully sided stock must say U=0: %q", row)
	}
}

// Owner order 2026-11-10: the bars are half a cell tall, and the later order of
// the same day makes every one of them ten boxes centred in its span.
func TestBarsAreHalfHeightTenBoxes(t *testing.T) {
	a := demoApp(t, 100, 30)
	c := NewCanvas(40, 1, RGB{})
	a.shareBar(c, 2, 0, 22, 0.5)
	row := c.PlainRows()[0]
	if barBlock != '▄' {
		t.Fatalf("the bar is %q, not a half cell", barBlock)
	}
	if n := strings.Count(row, string(barBlock)); n != shareBarBoxes {
		t.Fatalf("the bar has %d boxes, want %d: %q", n, shareBarBoxes, row)
	}
	if strings.ContainsRune(row, '█') {
		t.Fatalf("a full cell is still in the bar: %q", row)
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
		t.Fatal("no leader line carries both a T volume and a price")
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
