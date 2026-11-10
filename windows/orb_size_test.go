package main

import (
	"math"
	"testing"
)

// Owner order 2026-11-10 (latest): the mark is the owner's own orb source at
// the source's own size. OrbGrow is the source's 1.11, and the two later grows
// invented after the handover are withdrawn.
func TestOrbIsTheSourceSize(t *testing.T) {
	if math.Abs(OrbGrow-1.11) > 1e-9 {
		t.Fatalf("OrbGrow is %v, want the source's 1.11", OrbGrow)
	}
	want := (float64(13)*2.22/2 - 0.5) * 1.11
	if got := OrbRadius(OrbGrow); math.Abs(got-want) > 1e-9 {
		t.Fatalf("OrbRadius(1.11) is %v, want the source's %.2f columns", got, want)
	}
}

// The mark fills the tile's 14 rows at the source's size, because 15.46 columns
// needs 14 rows of a 2.22 tall cell.
func TestMarkTakesTheWholeTile(t *testing.T) {
	th := themeAt(0)
	c := NewCanvas(38, 14, th.Panel)
	drawOrb(c, 0, 0, 38, 14, 2, OrbBurning, true, th)
	rows := map[int]bool{}
	for y := 0; y < c.H; y++ {
		for x := 0; x < c.W; x++ {
			if ce := c.Cells[y*c.W+x]; ce.Ch >= 0x2800 && ce.Ch <= 0x28ff {
				rows[y] = true
			}
		}
	}
	if len(rows) < 13 {
		t.Errorf("the mark reaches %d of the tile's 14 rows, not the source's size", len(rows))
	}
	if ringRadius != 0 {
		t.Errorf("ringRadius was left at %v", ringRadius)
	}
}
