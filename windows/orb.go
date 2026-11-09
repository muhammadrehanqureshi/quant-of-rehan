package main

import "math"

// The quant mark is the owner's refined dial from
// windows/assets/orb-online-green-refined.gif: every frame of the GIF, sampled
// into orbpattern.go on the same 55 by 50 dot grid, played back at the GIF's
// own delay. Every cell holds a 2 by 4 grid of Braille dots, and nothing is
// filled, so the panel's own background shows through between the dots.
//
// Owner order 2026-11-09 (build 31): the mark is the GIF itself, dot for dot,
// with the GIF's own TWO green shades (the earlier four were invented), the
// GIF's own rotation instead of a drawn glint, two red shades outside the
// market, and the ten percent enlargement of build 29.

var cellAspect = defaultCellAspect

const defaultCellAspect = 2.22

// hudForceLive keeps the app refreshing the dial at the live cadence in every
// state, so the owner can inspect it while the market is closed.
const hudForceLive = true

// orbGrowth is the owner's ten percent enlargement over build 28.
const orbGrowth = 1.10

// OrbMode says whether the quant is online. The ink comes from orbGreen; the
// mode is kept for the rest of the HUD and the existing tests.
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

// rgbFromHex turns the generated 0xRRGGBB palette into a console colour.
func rgbFromHex(v uint32) RGB {
	return RGB{uint8(v >> 16), uint8(v >> 8), uint8(v)}
}

// The dial's colours are exactly two per palette, because the GIF has exactly
// two green shades. The greens are the GIF's own measured pixels; the reds are
// the same two brightness steps in the owner's red (order 2026-11-09: "there
// are 2 different shades of GREEN so in the same way there are 2 different
// shades of RED").
var (
	hudGreenDim    = rgbFromHex(orbGreenDim)
	hudGreenBright = rgbFromHex(orbGreenBright)

	hudRedDim    = RGB{150, 8, 8}
	hudRedBright = RGB{255, 64, 64}
)

// hudInk gives the ink for one dot. A dim dot is the dim shade, a bright dot
// is the bright one; there is no third or fourth tint.
func hudInk(tone float64, green bool) RGB {
	dim, bright := hudRedDim, hudRedBright
	if green {
		dim, bright = hudGreenDim, hudGreenBright
	}
	if clamp01(tone) >= 0.5 {
		return bright
	}
	return dim
}

// ringHalfBlocks turns the mark back to two pixels per cell, drawn with the
// upper and lower half block. It is the -halfblock flag, for a font that cannot
// draw Braille.
var ringHalfBlocks bool

// orbDrawSize is the dot-matrix size that fits a w by h cell box. It grows the
// build 28 matrix by orbGrowth and then clamps to the box, so a larger panel
// gives the owner the full ten percent and a smaller one stays inside its frame.
// The box is the panel's inner rectangle; no cell of margin is reserved, because
// the home panel's fourteen inner rows are exactly enough for the enlarged dial.
func orbDrawSize(w, h int) (int, int) {
	if len(orbFrames) == 0 || len(orbFrames[0]) != orbCols*orbRows || w <= 0 || h <= 0 {
		return 0, 0
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
	// A dot cell is two dots wide and four dots tall. Use the panel's whole
	// inner box: at the 120 by 30 home size the old one cell margin on each
	// side clamped build 29 back to build 28's height, so the owner's ten
	// percent enlargement never reached the screen.
	availW := float64(max(1, w)*2) / float64(dw)
	availH := float64(max(1, h)*4) / float64(dh)
	scale := math.Min(orbGrowth, math.Min(availW, availH))
	if scale <= 0 {
		return 0, 0
	}
	outW := int(math.Round(float64(dw) * scale))
	outH := int(math.Round(float64(dh) * scale))
	if outW < 1 || outH < 1 {
		return 0, 0
	}
	return outW, outH
}

// orbFrameIndex picks the GIF frame on screen after t seconds, honouring each
// frame's own delay, and loops forever.
func orbFrameIndex(t float64, count int) int {
	if count <= 1 {
		return 0
	}
	millis := int(t * 1000)
	if millis < 0 {
		millis = 0
	}
	total := 0
	for _, delay := range orbDelays {
		if delay > 0 {
			total += delay
		}
	}
	if total <= 0 {
		return (millis / 80) % count
	}
	millis %= total
	elapsed := 0
	for index, delay := range orbDelays {
		if delay <= 0 {
			delay = 80
		}
		elapsed += delay
		if millis < elapsed {
			return index
		}
	}
	return count - 1
}

// orbGrid places one GIF frame in a grid of w by h cells. The GIF's 55 by 50
// dots are square as a picture; a terminal dot is half a column wide and a
// quarter of a cell tall, so the rows are stretched to keep the orb round at
// the measured cell shape. The dots and the motion are both the GIF's own:
// the frame index follows the source delay, and nothing is rotated, waved or
// glinted on top of it (owner order 2026-11-09).
func orbGrid(w, h int, t float64) *dotGrid {
	g := newDotGrid(w, h)
	dw, dh := orbDrawSize(w, h)
	if dw < 1 || dh < 1 {
		return g
	}
	frame := orbFrames[orbFrameIndex(t, len(orbFrames))]
	ox, oy := (g.w-dw)/2, (g.h-dh)/2
	for y := 0; y < dh; y++ {
		sy := int((float64(y) + 0.5) * float64(orbRows) / float64(dh))
		if sy < 0 || sy >= orbRows {
			continue
		}
		for x := 0; x < dw; x++ {
			sx := int((float64(x) + 0.5) * float64(orbCols) / float64(dw))
			if sx < 0 || sx >= orbCols {
				continue
			}
			level := frame[sy*orbCols+sx]
			if level == 0 {
				continue
			}
			// The two GIF shades, kept apart by the ink threshold.
			tone := 0.25
			if level >= 2 {
				tone = 1.0
			}
			g.set(ox+x, oy+y, float32(tone))
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
	_ = mode // the ink, not the mode, selects the colour
	if ringHalfBlocks {
		drawOrbHalves(c, x0, y0, w, h, t, green)
		return
	}
	g := orbGrid(w, h, t)
	// A zero glow leaves every cell's background exactly as the panel drew it.
	g.blitRamp(c, x0, y0, func(tone float64) RGB { return hudInk(tone, green) }, th.Panel)
}

// drawOrbHalves draws the same dial when Braille is not available: two pixels
// per cell, again leaving every unlit cell transparent.
func drawOrbHalves(c *Canvas, x0, y0, w, h int, t float64, green bool) {
	g := orbGrid(w, h, t)
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
