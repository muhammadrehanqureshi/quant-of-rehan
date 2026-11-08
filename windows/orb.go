package main

import "math"

// The quant mark is the animated dial from the owner's GIF: a dot matrix, not a
// picture. Every cell holds a 2 by 4 grid of Braille dots, and the dial is the
// dots that fall on concentric rings around an empty centre. Nothing is filled:
// a dot is either lit or it is not, so the panel's own background shows through
// and there is no square field under the rings.
//
// Three thick seams cut every ring and turn with it, the dashed rings crawl in
// opposite directions, and one bright glint sweeps around the outside, so the
// mark is alive while the market is live. From 08:55 to 17:00 on a market day
// the owner's dial is green; outside that window it is red. hudForceLive keeps
// it turning in every state while he checks the desktop build.

var cellAspect = defaultCellAspect

const defaultCellAspect = 2.22

// OrbMode says whether the quant is online. The colour is the owner's 08:55 to
// 17:00 market rule, not the mode; the mode still decides the motion when
// hudForceLive is off.
type OrbMode int

const (
	OrbBurning  OrbMode = iota // quant online (pre-market, trading or post-market)
	OrbParked                  // relay answering, quant offline
	OrbChecking                // no answer yet
	OrbFault                   // relay unreachable
)

// hudForceLive keeps the dial turning in every state. Owner order 2026-11-07:
// he is checking the desktop build while the market is closed and needs to see
// it move. Set this to false to leave it still outside a live market. The
// colour is the owner's 08:55 to 17:00 rule, not this switch.
const hudForceLive = true

func clamp01(x float64) float64 {
	if x < 0 {
		return 0
	}
	if x > 1 {
		return 1
	}
	return x
}

// The dial's colours: the owner's refined green inside his 08:55 to 17:00
// market window, and the familiar red outside it.
var (
	// Owner order 2026-11-08: the green palette is for his 08:55 to 17:00
	// market window. The pale shade is mint and the core is saturated spring
	// green. The red palette below is for every other time.
	hudPale = RGB{132, 255, 190}
	hudMid  = RGB{18, 220, 112}
	// The owner's pre-build-23 red, still the off shade when hudForceLive
	// is false.
	hudRedPale = RGB{255, 64, 64}
	hudRedMid  = RGB{255, 4, 4}
	hudRedDark = RGB{52, 6, 6}
)

// orbGreenTo is 17:00, the end of the owner's ORB window. The window starts at
// scanOpen, 08:55, the same minute the scanner starts.
const orbGreenTo = 17 * 60

// hudBand is one ring of dots. r0 and r1 are fractions of the dial's radius.
// dashes above zero breaks the ring into that many arcs, of which fill is lit.
// speed is turns a second, negative to run the other way. tone picks the ink.
type hudBand struct {
	r0, r1 float64
	dashes int
	fill   float64
	speed  float64
	tone   float64
}

// hudBands is the GIF from the outside in: a thin rim, a broad broken band, a
// middle rim, a tick ring, the bright inner ring, fine inner ticks and the core
// ring. The gaps between the rings and the empty centre are part of the mark.
var hudBands = []hudBand{
	{0.945, 1.000, 0, 1, 0.000, 0.55},      // the thin outer rim
	{0.835, 0.930, 8, 0.62, 0.055, 0.95},   // the broad outer blocks
	{0.745, 0.805, 0, 1, 0.000, 0.70},      // the middle rim
	{0.645, 0.705, 24, 0.55, -0.062, 0.55}, // the dense tick ring
	{0.505, 0.605, 6, 0.70, 0.072, 1.00},   // the bright inner ring
	{0.405, 0.465, 36, 0.58, -0.055, 0.60}, // the fine inner ticks
	{0.290, 0.350, 0, 1, 0.000, 0.78},      // the core ring, empty inside
}

const (
	hudSeams     = 3
	hudSeamHalf  = 0.013 // half the width of one cut, in turns
	hudSeamStart = 0.035
	hudSeamSpeed = 0.060 // turns a second, clockwise
)

// hudCut says whether an angle falls in one of the dial's three thick cut
// seams. The seams turn with the dial, so the picture never stands still.
func hudCut(turn, t float64) bool {
	turn -= math.Floor(turn)
	for k := 0; k < hudSeams; k++ {
		centre := float64(k)/hudSeams + hudSeamStart + hudSeamSpeed*t
		d := math.Abs(turn - centre)
		d -= math.Floor(d) // distance the short way round, however many turns
		if d > 0.5 {
			d = 1 - d
		}
		if d <= hudSeamHalf {
			return true
		}
	}
	return false
}

// hudTime is the clock the dial runs on. With hudForceLive on it runs in every
// state for the owner's check; otherwise only a live market turns it, and a
// closed, checking or unreachable market leaves it still.
func hudTime(mode OrbMode, t float64) float64 {
	if !hudForceLive && mode != OrbBurning {
		return 0
	}
	return t
}

// hudInk gives the ink for one tone: the green palette inside the owner's
// market window and the red palette outside it. A dial with no live market
// is dark only when hudForceLive is false.
func hudInk(tone float64, mode OrbMode, green bool) RGB {
	if green {
		return mix(hudMid, hudPale, clamp01(tone))
	}
	if !hudForceLive && mode != OrbBurning {
		return hudRedDark
	}
	return mix(hudRedMid, hudRedPale, clamp01(tone))
}

// hudGlint is the bright head that sweeps around the dial, one turn every
// twelve seconds. It is a wedge rather than a dot, so the ring it crosses
// flashes without widening.
func hudGlint(turn, r, t float64) float64 {
	if r < 0.40 {
		return 0
	}
	d := math.Abs(turn - (0.10 + 0.085*t))
	d -= math.Floor(d) // distance the short way round, however many turns
	if d > 0.5 {
		d = 1 - d
	}
	if d > 0.045 {
		return 0
	}
	return 1
}

// hudSample gives the dot at one point, measured in dot widths from the dial's
// centre, with y already corrected for the cell's shape. ok is false where the
// dial is empty: outside the rim, between two rings, or inside a cut seam.
func hudSample(dx, dy, R, t float64) (tone float32, ok bool) {
	if R <= 0 {
		return 0, false
	}
	r := math.Hypot(dx, dy) / R
	if r > 1 {
		return 0, false
	}
	turn := math.Atan2(dy, dx)/(2*math.Pi) + 0.5
	if hudCut(turn, t) {
		return 0, false
	}
	for _, b := range hudBands {
		if r < b.r0 || r > b.r1 {
			continue
		}
		if b.dashes > 0 {
			slot := (turn + b.speed*t) * float64(b.dashes)
			if slot-math.Floor(slot) > b.fill {
				return 0, false
			}
		}
		ink := b.tone
		if g := hudGlint(turn, r, t); g > ink {
			ink = g
		}
		return float32(ink), true
	}
	return 0, false
}

// hudRadius is the dial's radius and centre for a grid of cw by ch cells. One
// dot is half a column wide and a quarter of a cell tall, so a dot row is
// cellAspect/2 dot widths high; that factor is what keeps the rings round.
func hudRadius(cw, ch int) (cx, cy, vs, R float64) {
	vs = cellAspect / 2
	cx, cy = float64(cw), float64(2*ch)
	R = math.Min(cx, cy*vs) - 1.2
	return
}

// ringHalfBlocks turns the mark back to two pixels per cell, drawn with the
// upper and lower half block. It is the -halfblock flag, for a font that cannot
// draw Braille.
var ringHalfBlocks bool

// drawOrb paints the mark into the rectangle (x0,y0,w,h) of cells. Only dots
// are written: every other cell keeps whatever background the panel already
// painted, which is why there is no field behind the dial. green selects the
// owner's 08:55 to 17:00 green palette; false paints the same dial red.
func drawOrb(c *Canvas, x0, y0, w, h int, t float64, mode OrbMode, green bool, th *Theme) {
	if w < 6 || h < 3 {
		return
	}
	tt := hudTime(mode, t)
	if ringHalfBlocks {
		drawOrbHalves(c, x0, y0, w, h, tt, mode, green)
		return
	}
	g := newDotGrid(w, h)
	cx, cy, vs, R := hudRadius(w, h)
	for j := 0; j < g.h; j++ {
		dy := (float64(j) + 0.5 - cy) * vs
		for i := 0; i < g.w; i++ {
			if tone, ok := hudSample(float64(i)+0.5-cx, dy, R, tt); ok {
				g.set(i, j, tone)
			}
		}
	}
	// A zero glow leaves every cell's background exactly as the panel drew it.
	g.blitRamp(c, x0, y0, func(tone float64) RGB { return hudInk(tone, mode, green) }, th.Panel)
}

// drawOrbHalves draws the same dial when Braille is not available: two pixels
// per cell, again leaving every unlit cell transparent. green selects the same
// palette as drawOrb.
func drawOrbHalves(c *Canvas, x0, y0, w, h int, tt float64, mode OrbMode, green bool) {
	cx, cy, vs, R := hudRadius(w, h)
	for row := 0; row < h; row++ {
		top := (4*float64(row) + 1 - cy) * vs
		bot := (4*float64(row) + 3 - cy) * vs
		for col := 0; col < w; col++ {
			dx := 2*float64(col) + 1 - cx
			toneT, okT := hudSample(dx, top, R, tt)
			toneB, okB := hudSample(dx, bot, R, tt)
			switch {
			case okT && okB:
				tone := toneT
				if toneB > tone {
					tone = toneB
				}
				c.Put(x0+col, y0+row, '█', hudInk(float64(tone), mode, green), false)
			case okT:
				c.Put(x0+col, y0+row, '▀', hudInk(float64(toneT), mode, green), false)
			case okB:
				c.Put(x0+col, y0+row, '▄', hudInk(float64(toneB), mode, green), false)
			}
		}
	}
}
