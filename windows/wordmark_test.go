package main

import (
	"testing"
)

// wordmarkCount is how many dots the mark lights at t seconds, and the leftmost
// column that carries one.
func wordmarkLit(t *testing.T, secs float64, green bool) (dots, first int) {
	t.Helper()
	a := newTestApp(t)
	c := NewCanvas(60, 24, a.th.Panel)
	drawWordmark(c, 0, 0, 60, 24, secs, green, a.th)
	first = -1
	for y := 0; y < c.H; y++ {
		for x := 0; x < c.W; x++ {
			if c.Cells[y*c.W+x].Ch != wordmarkDot {
				continue
			}
			dots++
			if first < 0 || x < first {
				first = x
			}
		}
	}
	return dots, first
}

// Owner order 2026-11-10 (latest): QUANT OF REHAN stands in the QUANT CORE tile
// in dots, each word on a line of its own, in place of the orb.
func TestWordmarkIsThreeDotLines(t *testing.T) {
	a := newTestApp(t)
	th := a.th
	c := NewCanvas(60, 24, th.Panel)
	drawWordmark(c, 0, 0, 60, 24, 2.0, true, th)
	lines := map[int]bool{}
	for y := 0; y < c.H; y++ {
		for x := 0; x < c.W; x++ {
			ce := c.Cells[y*c.W+x]
			if ce.Ch != wordmarkDot {
				continue
			}
			lines[y] = true
			if ce.FG != th.Good {
				t.Fatalf("a market-time dot is %v, not the market's green", ce.FG)
			}
		}
	}
	// Three words, so the ink covers three bands of rows rather than one.
	if len(lines) < 15 {
		t.Fatalf("the mark covers %d rows, want the three word lines", len(lines))
	}
}

// Outside the market window the mark is red, as the orb was.
func TestWordmarkIsRedOutsideTheMarket(t *testing.T) {
	a := newTestApp(t)
	th := a.th
	c := NewCanvas(60, 24, th.Panel)
	drawWordmark(c, 0, 0, 60, 24, 2.0, false, th)
	seen := 0
	for _, ce := range c.Cells {
		if ce.Ch != wordmarkDot {
			continue
		}
		seen++
		if ce.FG != th.Bad {
			t.Fatalf("a dot outside the market is %v, not red", ce.FG)
		}
	}
	if seen == 0 {
		t.Fatal("the red mark drew nothing")
	}
}

// The effect is a left to right wipe: the words appear from the left edge across
// the tile, and the disappearing starts at the left edge as well.
func TestWordmarkSweepsFromTheLeft(t *testing.T) {
	early, firstEarly := wordmarkLit(t, 0.1, true)
	whole, firstWhole := wordmarkLit(t, 2.2, true)
	if early >= whole {
		t.Fatalf("the mark must appear from the left: %d dots at first, %d once whole", early, whole)
	}
	if firstEarly != 0 || firstWhole != 0 {
		t.Fatalf("the whole mark starts on the left edge: first lit column %d and %d", firstEarly, firstWhole)
	}
	fewer, firstLate := wordmarkLit(t, 4.3, true)
	if fewer >= whole {
		t.Fatalf("the mark must disappear as the wipe passes: %d dots then %d", fewer, whole)
	}
	if firstLate < 20 {
		t.Fatalf("the disappearing must start at the left edge: first lit column %d", firstLate)
	}
}
