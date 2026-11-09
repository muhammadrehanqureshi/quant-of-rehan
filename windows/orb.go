package main

import "math"

// The quant mark is the owner's refined dial from
// windows/assets/orb-online-green-refined.gif: the actual 55 by 50 dot matrix
// sampled into orbpattern.go, not a drawing of rings that resembles it. Every
// cell holds a 2 by 4 grid of Braille dots, and nothing is filled, so the
// panel's own background shows through between the dots.
//
// Owner order 2026-11-09 (build 29): the dial turns and carries a moving
// highlight, its four brightness levels are painted in four green shades in
// the market window and four red shades outside it, and the whole mark is ten
// percent larger than build 28's matrix. The matrix is still the GIF's own
// dots; loading all 160 frames would cost hundreds of megabytes, so the motion
// comes from rotating the sampled frame and sweeping a glint across it.

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

// The dial's colours. Each palette has four stops: dim, mid, pale and hot.
// The owner asked for different shades, not a single flat green or red.
var (
	hudGreenDim  = RGB{0, 110, 55}
	hudGreenMid  = RGB{18, 220, 112}
	hudGreenPale = RGB{132, 255, 190}
	hudGreenHot  = RGB{120, 255, 200}

	hudRedDim  = RGB{125, 0, 0}
	hudRedMid  = RGB{255, 4, 4}
	hudRedPale = RGB{255, 64, 64}
	hudRedHot  = RGB{255, 180, 180}
)

// hudInk gives the ink for one tone. The four GIF brightness levels map onto
// four distinct shades, so the matrix keeps its depth in either palette.
func hudInk(tone float64, green bool) RGB {
	dim, mid, pale, hot := hudRedDim, hudRedMid, hudRedPale, hudRedHot
	if green {
		dim, mid, pale, hot = hudGreenDim, hudGreenMid, hudGreenPale, hudGreenHot
	}
	t := clamp01(tone)
	switch {
	case t <= 1.0/3.0:
		return mix(dim, mid, t*3)
	case t <= 2.0/3.0:
		return mix(mid, pale, (t-1.0/3.0)*3)
	default:
		return mix(pale, hot, (t-2.0/3.0)*3)
	}
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
	if len(orbLevels) != orbCols*orbRows || w <= 0 || h <= 0 {
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

// orbLevelAt samples the GIF's 55 by 50 grid at a fractional dot coordinate.
func orbLevelAt(x, y float64) uint8 {
	ix := int(math.Round(x))
	iy := int(math.Round(y))
	if ix < 0 || iy < 0 || ix >= orbCols || iy >= orbRows {
		return 0
	}
	return orbLevels[iy*orbCols+ix]
}

// orbGrid places the sampled matrix in a grid of w by h cells. The GIF's 55 by
// 50 dots are square as a picture; a terminal dot is half a column wide and a
// quarter of a cell tall, so the rows are stretched to keep the orb round at
// the measured cell shape. The matrix turns slowly and a glint sweeps around
// it; the four brightness levels remain the source of every shade.
func orbGrid(w, h int, t float64) *dotGrid {
	g := newDotGrid(w, h)
	dw, dh := orbDrawSize(w, h)
	if dw < 1 || dh < 1 {
		return g
	}
	ox, oy := (g.w-dw)/2, (g.h-dh)/2
	angle := t * 0.42
	ca, sa := math.Cos(angle), math.Sin(angle)
	cx, cy := float64(orbCols-1)/2, float64(orbRows-1)/2
	for y := 0; y < dh; y++ {
		for x := 0; x < dw; x++ {
			// Read the source through the inverse rotation, so the GIF's dots
			// themselves turn instead of a drawing being redrawn.
			dx := (float64(x) - float64(dw-1)/2) * float64(orbCols) / float64(dw)
			dy := (float64(y) - float64(dh-1)/2) * float64(orbRows) / float64(dh)
			sx := cx + dx*ca - dy*sa
			sy := cy + dx*sa + dy*ca
			level := orbLevelAt(sx, sy)
			if level == 0 {
				continue
			}
			tone := float64(level) / 3
			// A slow shade wave makes the four levels breathe without losing
			// the GIF's own density.
			wave := 0.5 + 0.5*math.Sin(t*2.1+float64(x)*0.33-float64(y)*0.21)
			tone *= 0.72 + 0.28*wave
			// A narrow glint sweeps around the mark, like the highlight in the
			// source animation. The brightest dots reach the hot shade.
			glint := math.Pow(math.Max(0, math.Cos(math.Atan2(dy, dx)-t*1.4)), 14)
			tone = math.Min(1, tone+glint*0.55)
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
