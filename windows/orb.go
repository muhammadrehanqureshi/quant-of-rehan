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
// GIF's own rotation instead of a drawn glint, and two red shades outside the
// market. The later order of the same day alternates those two shades ring by
// ring: dark at the middle, lighter outward, then dark again, in green and in
// red alike, because one flat tint read as too light.

var cellAspect = defaultCellAspect

const defaultCellAspect = 2.22

// hudForceLive keeps the app refreshing the dial at the live cadence in every
// state, so the owner can inspect it while the market is closed.
const hudForceLive = true

// orbDotPitch is the number of console dots between two dots of the mark. One
// puts a dot on every pixel of the grid, which is how the GIF draws itself: its
// stipple is one dot per point with the file's own gaps between them, and the
// owner asked for exactly that render instead of a thinned copy of it.
const orbDotPitch = 1

// orbScale is the mark's share of its tile: it filled the tile, then the owner
// asked for five percent less and then another five (order 2026-11-09), so the
// lattice is taken down by that much and nothing else about it changes.
const orbScale = 0.90

// orbBands is how many rings of shade run from the middle of the mark out. The
// innermost band is the darker shade, the next the lighter one, and they
// alternate from there (owner order 2026-11-09).
const orbBands = 5

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
// darken scales one shade. Owner order 2026-11-09 (later): the mark read too
// light on the panel, so the dark step of each palette is deepened much more
// than the light one, which only steps down a little.
func darken(c RGB, factor float64) RGB {
	return RGB{
		uint8(math.Round(float64(c.R) * factor)),
		uint8(math.Round(float64(c.G) * factor)),
		uint8(math.Round(float64(c.B) * factor)),
	}
}

// lighten mixes one shade towards white. Owner order 2026-11-09 (latest): only
// the lighter step moves, so it reads clearly apart from the darker one, which
// is left exactly as it was.
func lighten(c RGB, amount float64) RGB {
	mix := func(v uint8) uint8 {
		return uint8(math.Round(float64(v) + (255-float64(v))*amount))
	}
	return RGB{mix(c.R), mix(c.G), mix(c.B)}
}

var (
	// The greens are the GIF's own measured pixels, taken down for the panel.
	hudGreenDim    = darken(rgbFromHex(orbGreenDim), 0.55)
	hudGreenBright = lighten(darken(rgbFromHex(orbGreenBright), 0.82), 0.18)

	// The two reds are the owner's own hex values: #FF0000 for the darker step
	// and #FF5252 for the lighter one (order 2026-11-09).
	hudRedDim    = RGB{0xff, 0x00, 0x00}
	hudRedBright = RGB{0xff, 0x52, 0x52}
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

// orbDotGrid is the lattice the panel draws: one dot of the mark per lattice
// point, one empty console dot between points, and as many points as the w by h
// cell box holds. A terminal dot is half a cell wide and a quarter of a cell
// tall, so a dot is cellAspect/2 times as tall as it is wide and a square
// source needs that many more points across than down to stay square on screen.
func orbDotGrid(w, h int) (cols, rows int) {
	if len(orbFrames) == 0 || w <= 0 || h <= 0 {
		return 0, 0
	}
	aspect := cellAspect
	if aspect <= 0 {
		aspect = defaultCellAspect
	}
	across := aspect / 2
	if across < 0.5 {
		across = 0.5
	}
	if across > 1.6 {
		across = 1.6
	}
	rows = (4 * h) / orbDotPitch
	if limit := int(float64(2*w) / float64(orbDotPitch) / across); limit < rows {
		rows = limit
	}
	if rows > orbRaster {
		rows = orbRaster
	}
	// Ten percent smaller than the tile allows, so the mark sits inside its
	// panel instead of crowding the frame.
	rows = max(1, int(math.Round(float64(rows)*orbScale)))
	if rows < 1 {
		return 0, 0
	}
	cols = int(math.Round(float64(rows) * across))
	if cols > orbRaster {
		cols = orbRaster
	}
	if cols < 1 || cols*orbDotPitch > 2*w {
		return 0, 0
	}
	return cols, rows
}

// orbDrawSize is the box the mark fills on the panel, in console dots.
func orbDrawSize(w, h int) (int, int) {
	cols, rows := orbDotGrid(w, h)
	if cols < 1 || rows < 1 {
		return 0, 0
	}
	return cols * orbDotPitch, rows * orbDotPitch
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

// orbGrid places one GIF frame in a grid of w by h cells, dot for dot. Each
// point of the lattice takes the brightest cell of the GIF it covers, so the
// stipple, its two greens and the gaps between its dots all come from the file,
// and the points are spaced orbDotPitch apart so those gaps survive the panel's
// finer dot grid. The frame index follows each frame's own delay, and nothing
// is rotated, waved or glinted on top of it (owner order 2026-11-09).
func orbGrid(w, h int, t float64) *dotGrid {
	g := newDotGrid(w, h)
	cols, rows := orbDotGrid(w, h)
	if cols < 1 || rows < 1 {
		return g
	}
	frame := orbFrames[orbFrameIndex(t, len(orbFrames))]
	ox := (g.w - cols*orbDotPitch) / 2
	oy := (g.h - rows*orbDotPitch) / 2
	cx, cy := (float64(cols)-1)/2, (float64(rows)-1)/2
	lit := make([]bool, cols*rows)
	radii := make([]float64, cols*rows)
	minR, maxR := math.MaxFloat64, 0.0
	for j := 0; j < rows; j++ {
		sy0 := j * orbRaster / rows
		sy1 := (j + 1) * orbRaster / rows
		if sy1 <= sy0 {
			sy1 = sy0 + 1
		}
		if sy1 > orbRaster {
			sy1 = orbRaster
		}
		for i := 0; i < cols; i++ {
			sx0 := i * orbRaster / cols
			sx1 := (i + 1) * orbRaster / cols
			if sx1 <= sx0 {
				sx1 = sx0 + 1
			}
			if sx1 > orbRaster {
				sx1 = orbRaster
			}
			peak := uint8(0)
			for sy := sy0; sy < sy1; sy++ {
				row := frame[sy*orbRaster : (sy+1)*orbRaster]
				for sx := sx0; sx < sx1; sx++ {
					if row[sx] > peak {
						peak = row[sx]
					}
				}
			}
			if peak == 0 {
				continue
			}
			index := j*cols + i
			lit[index] = true
			radii[index] = math.Hypot(float64(i)-cx, float64(j)-cy)
			if radii[index] < minR {
				minR = radii[index]
			}
			if radii[index] > maxR {
				maxR = radii[index]
			}
		}
	}
	if maxR <= 0 || minR > maxR {
		return g
	}
	// Owner order 2026-11-09 (latest): the bands are measured from where the
	// mark's ink begins, not from the middle of its hole, so the very inside
	// circle is the darker shade every time and the rings alternate outward
	// from it, in green and in red alike.
	span := maxR - minR
	if span <= 0 {
		span = 1
	}
	band := math.Max(1, span/float64(orbBands))
	for j := 0; j < rows; j++ {
		for i := 0; i < cols; i++ {
			index := j*cols + i
			if !lit[index] {
				continue
			}
			tone := 1.0
			if int((radii[index]-minR)/band)%2 == 0 {
				tone = 0.25
			}
			g.set(ox+i*orbDotPitch, oy+j*orbDotPitch, float32(tone))
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
