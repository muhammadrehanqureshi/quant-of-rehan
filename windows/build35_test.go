package main

import (
	"math"
	"strings"
	"testing"
	"time"
)

// Owner order 2026-11-17: a second price tells the percentage move from the
// first. 78 to 78.9 is +1.15%, and a fall is negative.
func TestPercentChangeFromTheFirstPrice(t *testing.T) {
	got, ok := pctChange("78", "78.9")
	if !ok || math.Abs(got-1.1538461538) > 1e-9 {
		t.Fatalf("78 to 78.9 is %v (%v), want +1.1538%%", got, ok)
	}
	if signedPercent(got) != "+1.15%" {
		t.Fatalf("the tile would read %q, want +1.15%%", signedPercent(got))
	}
	fall, ok := pctChange("100", "90")
	if !ok || math.Abs(fall+10) > 1e-9 || signedPercent(fall) != "-10.00%" {
		t.Fatalf("100 to 90 is %v (%v), want -10.00%%", fall, ok)
	}
	for _, pair := range [][2]string{{"", "78"}, {"78", ""}, {"0", "78"}, {"78", "0"}, {"x", "78"}} {
		if _, ok := pctChange(pair[0], pair[1]); ok {
			t.Errorf("%q to %q must not give a percentage", pair[0], pair[1])
		}
	}
}

// The new tile stands in front of POSITION CALCULATOR, and the two split the
// page width equally.
func TestPriceDifferenceStandsBeforeTheCalculator(t *testing.T) {
	a := demoApp(t, 120, 36)
	a.screen = scrScanner
	diffRow, diffCol, calcRow, calcCol := -1, -1, -1, -1
	for i, row := range rowsOf(a) {
		if j := strings.Index(row, "PRICE DIFFERENCE"); j >= 0 {
			diffRow, diffCol = i, j
		}
		if j := strings.Index(row, "POSITION CALCULATOR"); j >= 0 {
			calcRow, calcCol = i, j
		}
	}
	if diffRow < 0 || calcRow < 0 {
		t.Fatalf("the scanner is missing one of the two tiles:\n%s", strings.Join(rowsOf(a), "\n"))
	}
	if diffRow != calcRow || diffCol >= calcCol {
		t.Fatalf("PRICE DIFFERENCE is at row %d col %d, POSITION CALCULATOR at row %d col %d",
			diffRow, diffCol, calcRow, calcCol)
	}

	c := NewCanvas(80, 4, a.th.Panel)
	a.drawCalcPair(c, 0, 0, 80, 4)
	corners := []int{}
	for i, r := range []rune(c.PlainRows()[0]) {
		if r == '┏' {
			corners = append(corners, i)
		}
	}
	if len(corners) != 2 {
		t.Fatalf("the pair drew %d frames, want two: %q", len(corners), c.PlainRows()[0])
	}
	const gap = 2
	if left, right := corners[1]-corners[0]-gap, 80-corners[1]; left != right {
		t.Fatalf("the two tiles are %d and %d cells wide, want equal", left, right)
	}
}

// F6 gives the difference tile the keys, and C still gives them to the
// calculator. The two forms never hold the keys together.
func TestF6OpensThePriceDifferenceTile(t *testing.T) {
	a := demoApp(t, 122, 36)
	a.screen = scrScanner
	a.onKey(Key{Kind: KF6})
	if !a.pctOpen || a.calcOpen {
		t.Fatalf("F6 must open PRICE DIFFERENCE alone: pct %v calc %v", a.pctOpen, a.calcOpen)
	}
	for _, r := range "78" {
		a.onKey(Key{Kind: KRune, R: r})
	}
	a.onKey(Key{Kind: KTab})
	for _, r := range "78.9" {
		a.onKey(Key{Kind: KRune, R: r})
	}
	if s := plain(a); !strings.Contains(s, "DIFF  +1.15%") {
		t.Fatalf("78 to 78.9 did not read +1.15%%:\n%s", s)
	}
	a.onKey(Key{Kind: KRune, R: 'c'})
	if !a.calcOpen || a.pctOpen {
		t.Fatalf("C must open POSITION CALCULATOR alone: pct %v calc %v", a.pctOpen, a.calcOpen)
	}
}

// Owner order 2026-11-17: one blank row between ALERTS LOG entries, not two.
func TestAlertsLogLeavesOneBlankRowBetweenEntries(t *testing.T) {
	a := demoApp(t, 120, 34)
	a.screen = scrAlerts
	a.flow.Log = []Flag{
		{Time: a.now, Kind: "order", Side: "BUY", Text: "FIRST ALERT"},
		{Time: a.now.Add(-time.Second), Kind: "order", Side: "SELL", Text: "SECOND ALERT"},
	}
	first, second := -1, -1
	for i, row := range rowsOf(a) {
		if strings.Contains(row, "FIRST ALERT") {
			first = i
		}
		if strings.Contains(row, "SECOND ALERT") {
			second = i
		}
	}
	if first < 0 || second < 0 {
		t.Fatalf("the two log entries are missing:\n%s", strings.Join(rowsOf(a), "\n"))
	}
	if second-first != 2 {
		t.Fatalf("the second alert starts %d rows below the first, want one blank row", second-first)
	}
}

// Owner order 2026-11-17: every red dot is the one shade most of the red orb
// already used, including the outer side.
func TestRedOrbUsesOneShade(t *testing.T) {
	a := demoApp(t, 122, 36)
	c := NewCanvas(38, 14, a.th.Panel)
	drawOrb(c, 0, 0, 38, 14, 0, OrbFault, false, a.th)
	want := RGB{255, 52, 66}
	lit := 0
	for _, ce := range c.Cells {
		if ce.Ch < 0x2800 || ce.Ch > 0x28ff {
			continue
		}
		lit++
		if ce.FG != want {
			t.Fatalf("a red dot is %v, want the one shade %v", ce.FG, want)
		}
	}
	if lit == 0 {
		t.Fatal("the red orb painted no dots")
	}
}
