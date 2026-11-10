package main

import "math"

// barMeter is the owner's replacement for the dot meter (order 2026-11-10:
// "remove the dot shaped frequency meter and have green/red bars in front of
// them"). It draws the same readings as sparkline in the same box, but as short
// half-height columns: a column is green when the reading rose on the one
// before it and red when it fell, and every bar keeps the box's full width, so
// nothing is moved or shortened.
func barMeter(c *Canvas, x, y, w, h int, vals []float64, good, bad, panel RGB) bool {
	if len(vals) < 3 || w < 2 || h < 1 {
		return false
	}
	cols := w / 2
	if cols < 1 {
		cols = 1
	}
	lo, hi := vals[0], vals[0]
	for _, v := range vals {
		lo, hi = math.Min(lo, v), math.Max(hi, v)
	}
	span := hi - lo
	// A quiet stock must not blow a one tick wobble up to full height.
	if minSpan := math.Abs(hi) * 0.0005; span < minSpan {
		mid := (hi + lo) / 2
		lo, hi = mid-minSpan/2, mid+minSpan/2
		span = hi - lo
	}
	at := func(i int) float64 {
		pos := float64(i) * float64(len(vals)-1) / float64(max(1, cols-1))
		j := int(pos)
		if j >= len(vals)-1 {
			return vals[len(vals)-1]
		}
		f := pos - float64(j)
		return vals[j]*(1-f) + vals[j+1]*f
	}
	prev := at(0)
	for i := 0; i < cols; i++ {
		v := at(i)
		ink := bad
		if v >= prev {
			ink = good
		}
		_ = panel
		prev = v
		cells := 1
		if span > 0 && h > 1 {
			cells = 1 + int(math.Round((v-lo)/span*float64(h-1)))
		}
		for r := 0; r < h; r++ {
			if r < h-cells {
				continue
			}
			ch := '█'
			if r == h-cells {
				// The top of every bar is a half cell, the same half height the
				// buy and sell bars use.
				ch = '▄'
			}
			c.Put(x+i*2, y+r, ch, ink, false)
		}
	}
	return true
}
