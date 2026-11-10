package main

import (
	"strings"
	"testing"
)

// wordmarkCanvas draws the mark at t seconds into a tile of the size given.
func wordmarkCanvas(t *testing.T, w, h int, secs float64, green bool) (*Canvas, *App) {
	t.Helper()
	a := newTestApp(t)
	c := NewCanvas(w, h, a.th.Panel)
	drawWordmark(c, 0, 0, w, h, secs, green, a.th)
	return c, a
}

// markCells counts the lit Braille cells and returns the columns they occupy.
func markCells(c *Canvas) (n, first, last int) {
	first, last = -1, -1
	for y := 0; y < c.H; y++ {
		for x := 0; x < c.W; x++ {
			ch := c.Cells[y*c.W+x].Ch
			if ch < 0x2800 || ch > 0x28ff {
				continue
			}
			n++
			if first < 0 || x < first {
				first = x
			}
			if x > last {
				last = x
			}
		}
	}
	return n, first, last
}

// Owner order 2026-11-10 (latest): the mark is QUANT OF REHAN, three words on
// three lines, and each word is centred in the grid, so OF stands in the middle
// and not against the left edge.
func TestWordmarkIsThreeCentredLines(t *testing.T) {
	pts := wordmarkPoints()
	if len(pts) == 0 {
		t.Fatal("the mark has no points")
	}
	width := len(pts[0])
	var groups [][2]int
	for y, r := range pts {
		if !strings.ContainsRune(r, '#') {
			continue
		}
		if n := len(groups); n > 0 && groups[n-1][1] == y-1 {
			groups[n-1][1] = y
		} else {
			groups = append(groups, [2]int{y, y})
		}
	}
	if len(groups) != 3 {
		t.Fatalf("the mark has %d lines of points, want three words", len(groups))
	}
	for i, g := range groups {
		left, right := width, 0
		for y := g[0]; y <= g[1]; y++ {
			for x, ch := range []rune(pts[y]) {
				if ch != '#' {
					continue
				}
				if x < left {
					left = x
				}
				if x > right {
					right = x
				}
			}
		}
		if d := left - (width - 1 - right); d < -1 || d > 1 {
			t.Fatalf("line %d is not centred: %d points on its left, %d on its right", i+1, left, width-1-right)
		}
	}
}

// Owner order 2026-11-10 (latest): the mark is small in its tile and drawn in
// fine dots, so it carries many more dots than one per cell and leaves a margin
// on every side.
func TestWordmarkDrawsSmallDotMark(t *testing.T) {
	const w, h = 50, 20
	c, a := wordmarkCanvas(t, w, h, 2.4, true) // the held moment, whole
	n, first, last := markCells(c)
	if n < 60 {
		t.Fatalf("the mark lights only %d cells", n)
	}
	if first < 5 || w-1-last < 5 {
		t.Fatalf("the mark fills its tile: columns %d to %d of %d", first, last, w)
	}
	// The fine grid: more dots inside the cells than the cells themselves carry
	// if every point were a whole cell.
	dots := 0
	for y := 0; y < c.H; y++ {
		for x := 0; x < c.W; x++ {
			if ch := c.Cells[y*c.W+x].Ch; ch >= 0x2800 && ch <= 0x28ff {
				for m := ch - 0x2800; m != 0; m &= m - 1 {
					dots++
				}
			}
		}
	}
	if dots < n*3 {
		t.Fatalf("the mark carries %d dots in %d cells, so the grid is not fine", dots, n)
	}
	for _, ce := range c.Cells {
		if ce.Ch >= 0x2800 && ce.Ch <= 0x28ff && ce.FG != a.th.Good {
			t.Fatalf("a market-time dot is %v, not the market's green", ce.FG)
		}
	}
}

// Outside the market window the mark is red, as the orb was.
func TestWordmarkIsRedOutsideTheMarket(t *testing.T) {
	c, a := wordmarkCanvas(t, 50, 20, 2.4, false)
	n := 0
	for _, ce := range c.Cells {
		if ce.Ch < 0x2800 || ce.Ch > 0x28ff {
			continue
		}
		n++
		if ce.FG != a.th.Bad {
			t.Fatalf("a dot outside the market is %v, not red", ce.FG)
		}
	}
	if n == 0 {
		t.Fatal("the red mark drew nothing")
	}
}

// The effect is a left to right wipe: the words appear from the left edge across
// the tile, and the disappearing starts at the left edge as well.
func TestWordmarkSweepsFromTheLeft(t *testing.T) {
	early, _, _ := markCells(mustCanvas(t, 0.1))
	whole, firstWhole, _ := markCells(mustCanvas(t, 2.4))
	if early >= whole {
		t.Fatalf("the mark must appear from the left: %d cells at first, %d once whole", early, whole)
	}
	later, firstLater, _ := markCells(mustCanvas(t, 4.3))
	if later >= whole {
		t.Fatalf("the mark must disappear as the wipe passes: %d cells then %d", later, whole)
	}
	if firstLater <= firstWhole+5 {
		t.Fatalf("the disappearing must start at the left edge: first lit column %d then %d", firstWhole, firstLater)
	}
}

func mustCanvas(t *testing.T, secs float64) *Canvas {
	t.Helper()
	c, _ := wordmarkCanvas(t, 50, 20, secs, true)
	return c
}
