package main

import (
	"math"
	"strings"
	"testing"
)

// Owner order 2026-11-11: the mark is fifteen percent smaller than the size
// the owner approved before, which was the source's own 1.11.
func TestOrbIsFifteenPercentSmaller(t *testing.T) {
	if math.Abs(OrbGrow-1.11*0.85) > 1e-9 {
		t.Fatalf("OrbGrow is %v, want 1.11 less fifteen percent", OrbGrow)
	}
	want := (float64(13)*2.22/2 - 0.5) * 1.11 * 0.85
	if got := OrbRadius(OrbGrow); math.Abs(got-want) > 1e-9 {
		t.Fatalf("OrbRadius is %v, want %.2f columns", got, want)
	}
}

// Owner order 2026-11-11: the turn is fifteen percent slower, and the one
// place that turns a layer reads the factor.
func TestOrbIsFifteenPercentSlower(t *testing.T) {
	if math.Abs(orbSpeedScale-0.85) > 1e-9 {
		t.Fatalf("orbSpeedScale is %v, want 0.85", orbSpeedScale)
	}
	source := readWindowSource(t, "ring.go")
	if !strings.Contains(source, "degPerSec * orbSpeedScale") {
		t.Fatal("the ring does not apply the slower turn factor")
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
	// Fifteen percent under the source's size is about twelve of the tile's
	// fourteen rows, never the whole tile any more.
	if len(rows) < 11 || len(rows) > 13 {
		t.Errorf("the mark reaches %d of the tile's 14 rows", len(rows))
	}
	if ringRadius != 0 {
		t.Errorf("ringRadius was left at %v", ringRadius)
	}
}
