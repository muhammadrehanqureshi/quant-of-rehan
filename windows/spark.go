package main

import "math"

// Braille graphics. One character cell holds a 2 by 4 grid of dots, so a
// terminal that is 40 cells wide and 14 rows tall can draw on 80 by 56 points,
// four times the detail of half blocks. The HUD uses it for the orb and for
// live charts of the index and of each leader.

// brailleBit gives the bit of the dot at column 0..1, row 0..3 of a cell.
var brailleBit = [2][4]rune{{0x01, 0x02, 0x04, 0x40}, {0x08, 0x10, 0x20, 0x80}}

// dotGrid is a canvas of braille dots. Each dot carries a tone from 0 to 1
// that picks its colour, and a cell takes the brightest tone among its dots.
type dotGrid struct {
	cw, ch int // size in cells
	w, h   int // size in dots
	on     []bool
	tone   []float32
	glow   []float32 // per cell background strength, 0 to 1
}

func newDotGrid(cw, ch int) *dotGrid {
	return &dotGrid{cw: cw, ch: ch, w: cw * 2, h: ch * 4,
		on: make([]bool, cw*2*ch*4), tone: make([]float32, cw*2*ch*4), glow: make([]float32, cw*ch)}
}

func (g *dotGrid) set(x, y int, tone float32) {
	if x < 0 || y < 0 || x >= g.w || y >= g.h {
		return
	}
	i := y*g.w + x
	g.on[i] = true
	if tone > g.tone[i] {
		g.tone[i] = tone
	}
}

// line draws a connected line of dots from (x0,y0) to (x1,y1).
func (g *dotGrid) line(x0, y0, x1, y1 int, tone float32) {
	dx, dy := x1-x0, y1-y0
	n := max(abs(dx), abs(dy))
	if n == 0 {
		g.set(x0, y0, tone)
		return
	}
	for i := 0; i <= n; i++ {
		g.set(x0+int(math.Round(float64(dx)*float64(i)/float64(n))), y0+int(math.Round(float64(dy)*float64(i)/float64(n))), tone)
	}
}

func abs(a int) int {
	if a < 0 {
		return -a
	}
	return a
}

// blit writes the grid into the canvas at cell (cx, cy). Dots take a colour
// between lo and hi by tone. A cell's background is whatever the canvas
// already has there, lifted toward glowCol by the cell's glow value.
func (g *dotGrid) blit(c *Canvas, cx, cy int, lo, hi, glowCol RGB) {
	for r := 0; r < g.ch; r++ {
		for k := 0; k < g.cw; k++ {
			var mask rune
			var tone float32
			for dxi := 0; dxi < 2; dxi++ {
				for dyi := 0; dyi < 4; dyi++ {
					i := (r*4+dyi)*g.w + k*2 + dxi
					if g.on[i] {
						mask |= brailleBit[dxi][dyi]
						if g.tone[i] > tone {
							tone = g.tone[i]
						}
					}
				}
			}
			bg := c.BGAt(cx+k, cy+r)
			cellBG := bg
			if gl := g.glow[r*g.cw+k]; gl > 0 {
				cellBG = mix(bg, glowCol, float64(gl))
			}
			if mask == 0 {
				if cellBG != bg {
					c.Set(cx+k, cy+r, ' ', cellBG, cellBG, false)
				}
				continue
			}
			c.Set(cx+k, cy+r, 0x2800+mask, mix(lo, hi, float64(tone)), cellBG, false)
		}
	}
}

// blitRamp is blit with a colour function in place of two stops: the brightest
// dot in a cell sets the cell's ink by its tone.
func (g *dotGrid) blitRamp(c *Canvas, cx, cy int, ink func(tone float64) RGB, glowCol RGB) {
	for r := 0; r < g.ch; r++ {
		for k := 0; k < g.cw; k++ {
			var mask rune
			var tone float32
			for dxi := 0; dxi < 2; dxi++ {
				for dyi := 0; dyi < 4; dyi++ {
					i := (r*4+dyi)*g.w + k*2 + dxi
					if g.on[i] {
						mask |= brailleBit[dxi][dyi]
						if g.tone[i] > tone {
							tone = g.tone[i]
						}
					}
				}
			}
			bg := c.BGAt(cx+k, cy+r)
			cellBG := bg
			if gl := g.glow[r*g.cw+k]; gl > 0 {
				cellBG = mix(bg, glowCol, float64(gl))
			}
			if mask == 0 {
				if cellBG != bg {
					c.Set(cx+k, cy+r, ' ', cellBG, cellBG, false)
				}
				continue
			}
			c.Set(cx+k, cy+r, 0x2800+mask, ink(float64(tone)), cellBG, false)
		}
	}
}

// series is a rolling list of readings.
type series struct{ v []float64 }

func (s *series) push(x float64, limit int) {
	s.v = append(s.v, x)
	if len(s.v) > limit {
		copy(s.v, s.v[len(s.v)-limit:])
		s.v = s.v[:limit]
	}
}

// sparkline draws vals as a line chart in the cell box (x, y, w, h): a crisp
// braille line over a soft area that fades toward the bottom. It returns false
// when there is too little data.
func sparkline(c *Canvas, x, y, w, h int, vals []float64, line, panel RGB) bool {
	if len(vals) < 3 || w < 2 || h < 1 {
		return false
	}
	g := newDotGrid(w, h)
	lo, hi := vals[0], vals[0]
	for _, v := range vals {
		lo, hi = math.Min(lo, v), math.Max(hi, v)
	}
	span := hi - lo
	// A chart of a quiet stock would blow a one tick wobble up to full height,
	// so the scale is never tighter than 0.05 percent of the price.
	if minSpan := math.Abs(hi) * 0.0005; span < minSpan {
		mid := (hi + lo) / 2
		lo, hi = mid-minSpan/2, mid+minSpan/2
		span = hi - lo
	}
	at := func(i int) float64 {
		pos := float64(i) * float64(len(vals)-1) / float64(g.w-1)
		j := int(pos)
		if j >= len(vals)-1 {
			return vals[len(vals)-1]
		}
		f := pos - float64(j)
		return vals[j]*(1-f) + vals[j+1]*f
	}
	yOf := func(v float64) int {
		if span <= 0 {
			return g.h / 2
		}
		return int(math.Round((1 - (v-lo)/span) * float64(g.h-1)))
	}
	top := make([]int, g.w)
	prev := yOf(at(0))
	for i := 0; i < g.w; i++ {
		cur := yOf(at(i))
		g.line(max(i-1, 0), prev, i, cur, 1)
		if cur+1 < g.h {
			g.set(i, cur+1, 0.6) // a second dot under the line keeps it solid
		}
		top[i] = cur
		prev = cur
	}
	// The area: every cell below the line takes a tint that fades with depth.
	for k := 0; k < w; k++ {
		t := min(top[k*2], top[k*2+1])
		r0 := t / 4
		for r := r0; r < h; r++ {
			depth := float64(r-r0) / float64(max(1, h-r0))
			a := 0.17 * (1 - 0.8*depth)
			if r == r0 {
				a = 0.05
			}
			g.glow[r*w+k] = float32(a)
		}
	}
	g.blit(c, x, y, mix(panel, line, 0.35), line, mix(panel, line, 0.8))
	return true
}
