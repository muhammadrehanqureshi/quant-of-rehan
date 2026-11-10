package main

import (
	"math"
	"testing"
)

// dotBox is the box round every lit Braille dot of c, in terminal pixels (a cell
// is 9 by 20), and how many dots are lit.
func dotBox(c *Canvas) (w, h float64, dots int) {
	minx, miny, maxx, maxy := math.Inf(1), math.Inf(1), math.Inf(-1), math.Inf(-1)
	for cy := 0; cy < c.H; cy++ {
		for cx := 0; cx < c.W; cx++ {
			ce := c.Cells[cy*c.W+cx]
			if ce.Ch < 0x2800 || ce.Ch > 0x28ff {
				continue
			}
			for dx := 0; dx < 2; dx++ {
				for dy := 0; dy < 4; dy++ {
					if (ce.Ch-0x2800)&brailleBit[dx][dy] == 0 {
						continue
					}
					x, y := float64(cx*9)+9*(0.25+0.5*float64(dx)), float64(cy*20)+20*(0.125+0.25*float64(dy))
					minx, maxx = math.Min(minx, x), math.Max(maxx, x)
					miny, maxy = math.Min(miny, y), math.Max(maxy, y)
					dots++
				}
			}
		}
	}
	return maxx - minx, maxy - miny, dots
}

func orbCanvas(w, h int, fn func(c *Canvas, t float64)) (sw, sh float64) {
	const n = 40
	for i := 0; i < n; i++ {
		c := NewCanvas(w, h, RGB{4, 18, 27})
		fn(c, float64(i)*0.4)
		bw, bh, _ := dotBox(c)
		sw, sh = sw+bw, sh+bh
	}
	return sw / n, sh / n
}

// The orb in the 38 by 14 tile looks 10% bigger than the old one in 38 by 13.
func TestOrbBigSize(t *testing.T) {
	ow, oh := orbCanvas(38, 13, func(c *Canvas, tt float64) { drawOrb(c, 0, 0, 38, 13, tt, OrbBurning, nil) })
	nw, nh := orbCanvas(38, 14, func(c *Canvas, tt float64) { drawOrbBig(c, 0, 0, 38, 14, tt, OrbBurning) })
	rw, rh := nw/ow, nh/oh
	t.Logf("old %.1f x %.1f px, new %.1f x %.1f px (%.1f%% wider, %.1f%% higher)", ow, oh, nw, nh, (rw-1)*100, (rh-1)*100)
	if m := (rw + rh) / 2; m < 1.095 || m > 1.115 {
		t.Errorf("on average the orb is %.3f times the old one, want about 1.10", m)
	}
	if ringRadius != 0 {
		t.Errorf("ringRadius was left at %v", ringRadius)
	}
}

// Nothing is cut off: the tile and a roomier rectangle light the same dots.
func TestOrbBigNothingCut(t *testing.T) {
	for _, mode := range []OrbMode{OrbBurning, OrbParked} {
		for _, tt := range []float64{0, 3.3, 11.7} {
			a, b := NewCanvas(38, 14, RGB{}), NewCanvas(40, 16, RGB{})
			drawOrbBig(a, 0, 0, 38, 14, tt, mode)
			drawOrbBig(b, 0, 0, 40, 16, tt, mode)
			_, _, da := dotBox(a)
			_, _, db := dotBox(b)
			if da != db {
				t.Errorf("mode %v at %.1f s: %d dots in the tile, %d with room to spare", mode, tt, da, db)
			}
		}
	}
}

// With too little room it falls back to drawOrb, the ring that fits.
func TestOrbBigFallsBack(t *testing.T) {
	for _, sz := range [][2]int{{38, 13}, {31, 14}, {20, 8}} {
		a, b := NewCanvas(sz[0], sz[1], RGB{}), NewCanvas(sz[0], sz[1], RGB{})
		drawOrbBig(a, 0, 0, sz[0], sz[1], 2, OrbBurning)
		drawOrb(b, 0, 0, sz[0], sz[1], 2, OrbBurning, nil)
		for i := range a.Cells {
			if a.Cells[i] != b.Cells[i] {
				t.Fatalf("%v: differs from drawOrb at cell %d", sz, i)
			}
		}
	}
}

// Red is completely still.
func TestOrbBigRedStill(t *testing.T) {
	a, b := NewCanvas(38, 14, RGB{}), NewCanvas(38, 14, RGB{})
	drawOrbBig(a, 0, 0, 38, 14, 0, OrbParked)
	drawOrbBig(b, 0, 0, 38, 14, 9.9, OrbParked)
	for i := range a.Cells {
		if a.Cells[i] != b.Cells[i] {
			t.Fatal("the red orb moved")
		}
	}
}
