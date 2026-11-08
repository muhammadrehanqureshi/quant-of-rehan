package main

import "math"

// The quant mark is the owner's refined dial from
// windows/assets/orb-online-green-refined.gif: the actual 55 by 50 dot matrix
// sampled into orbpattern.go, not a drawing of rings that resembles it. Every
// cell holds a 2 by 4 grid of Braille dots, and nothing is filled, so the
// panel's own background shows through between the dots.
//
// Owner order 2026-11-08 (build 28): the dial must be the GIF. The earlier
// hand-drawn bands were only an approximation and never matched the picture.
// The sampled frame is still; hudInk paints it in the GIF's refined green
// during the pre-market, the session and the post-market, and in the owner's
// saturated red at every other hour and day.

var cellAspect = defaultCellAspect

const defaultCellAspect = 2.22

// hudForceLive keeps the app refreshing the dial at the live cadence in every
// state, so the owner can inspect it while the market is closed.
const hudForceLive = true

// OrbMode says whether the quant is online. The mode once decided the motion;
// the sampled GIF frame is still, and the ink comes from orbGreen.
type OrbMode int

const (
	OrbBurning  OrbMode = iota // quant online (pre-market, trading or post-market)
	OrbParked                  // relay answering, quant offline
	OrbChecking                // no answer yet
	OrbFault                   // relay unreachable
)

func clamp01(x float64) float64 {
	if x < 0 {
		return 0
	}
	if x > 1 {
		return 1
	}
	return x
}

// The dial's colours: the refined green of
// windows/assets/orb-online-green-refined.gif for the pre-market, the session
// and the post-market, and the owner's saturated red at every other hour.
var (
	hudPale    = RGB{132, 255, 190}
	hudMid     = RGB{18, 220, 112}
	hudRedPale = RGB{255, 64, 64}
	hudRedMid  = RGB{255, 4, 4}
)

// hudInk gives the ink for one tone: the refined green while the quant is in
// its pre-market, trading or post-market, the saturated red at every other
// time. The pale shade is for the brightest dots.
func hudInk(tone float64, green bool) RGB {
	if green {
		return mix(hudMid, hudPale, clamp01(tone))
	}
	return mix(hudRedMid, hudRedPale, clamp01(tone))
}

// ringHalfBlocks turns the mark back to two pixels per cell, drawn with the
// upper and lower half block. It is the -halfblock flag, for a font that cannot
// draw Braille.
var ringHalfBlocks bool

// orbGrid places the sampled matrix in a grid of w by h cells. The GIF's 55 by
// 50 dots are square as a picture; a terminal dot is half a column wide and a
// quarter of a cell tall, so the rows are stretched to keep the orb round at
// the measured cell shape. The matrix is never enlarged past its own dots.
func orbGrid(w, h int) *dotGrid {
	g := newDotGrid(w, h)
	if len(orbLevels) != orbCols*orbRows {
		return g
	}
	aspect := cellAspect
	if aspect <= 0 {
		aspect = defaultCellAspect
	}
	stretch := 2.2 / aspect
	if stretch < 0.5 {
		stretch = 0.5
	}
	if stretch > 1.6 {
		stretch = 1.6
	}
	dw := orbCols
	dh := int(math.Round(float64(orbRows) * stretch))
	if dh < 1 {
		dh = 1
	}
	scale := math.Min(1, math.Min(float64(g.w-2)/float64(dw), float64(g.h-2)/float64(dh)))
	dw = int(float64(dw) * scale)
	dh = int(float64(dh) * scale)
	if dw < 1 || dh < 1 {
		return g
	}
	ox, oy := (g.w-dw)/2, (g.h-dh)/2
	for y := 0; y < dh; y++ {
		sy := y * orbRows / dh
		for x := 0; x < dw; x++ {
			sx := x * orbCols / dw
			level := orbLevels[sy*orbCols+sx]
			if level > 0 {
				g.set(ox+x, oy+y, float32(level)/3)
			}
		}
	}
	return g
}

// drawOrb paints the mark into the rectangle (x0,y0,w,h) of cells. Only dots
// are written: every other cell keeps whatever background the panel already
// painted, which is why there is no field behind the dial. green selects the
// refined GIF palette; false paints the same dial in the owner's red.
func drawOrb(c *Canvas, x0, y0, w, h int, t float64, mode OrbMode, green bool, th *Theme) {
	if w < 6 || h < 3 {
		return
	}
	_ = t    // the sampled frame is still
	_ = mode // the ink, not the mode, selects the colour
	if ringHalfBlocks {
		drawOrbHalves(c, x0, y0, w, h, green)
		return
	}
	g := orbGrid(w, h)
	// A zero glow leaves every cell's background exactly as the panel drew it.
	g.blitRamp(c, x0, y0, func(tone float64) RGB { return hudInk(tone, green) }, th.Panel)
}

// drawOrbHalves draws the same dial when Braille is not available: two pixels
// per cell, again leaving every unlit cell transparent.
func drawOrbHalves(c *Canvas, x0, y0, w, h int, green bool) {
	g := orbGrid(w, h)
	for row := 0; row < h; row++ {
		for col := 0; col < w; col++ {
			var toneT, toneB float32
			okT, okB := false, false
			for dxi := 0; dxi < 2; dxi++ {
				for dyi := 0; dyi < 4; dyi++ {
					i := (row*4+dyi)*g.w + col*2 + dxi
					if !g.on[i] {
						continue
					}
					if dyi < 2 {
						okT = true
						if g.tone[i] > toneT {
							toneT = g.tone[i]
						}
					} else {
						okB = true
						if g.tone[i] > toneB {
							toneB = g.tone[i]
						}
					}
				}
			}
			switch {
			case okT && okB:
				tone := toneT
				if toneB > tone {
					tone = toneB
				}
				c.Put(x0+col, y0+row, '█', hudInk(float64(tone), green), false)
			case okT:
				c.Put(x0+col, y0+row, '▀', hudInk(float64(toneT), green), false)
			case okB:
				c.Put(x0+col, y0+row, '▄', hudInk(float64(toneB), green), false)
			}
		}
	}
}
