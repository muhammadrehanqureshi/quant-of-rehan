package main

// The quant core orb, green and red, as a standalone piece of source.
//
// This is the same ring the Windows HUD draws on its HOME and SCANNER screens:
// six turning layers cut from the reference picture (ring.go, ring_data.go and
// assets/ring), drawn as round Braille dots, two dots across and four down in
// every character cell. ring.go is a byte for byte copy of the app's file; the
// only thing this folder adds to the drawing code is DrawOrb below, which picks
// the size of the orb.
//
// Size. In the app the orb fits the tile it sits in: a 38 column tile with 13 rows
// of orb, which makes a ring of originalRadius() columns. Here the radius is
// OrbGrow times that, and it keeps that size whatever canvas the orb is drawn on.
// It needs 14 rows of cells (OrbRows) and 32 columns (OrbCols, even so the centre
// falls on a cell edge, which keeps the dot lattice exactly where the app has it).
//
// Why OrbGrow is 1.11 and not 1.10. The ring is scaled smoothly, but it is drawn
// in dots that sit 4.5 by 5 pixels apart, about 2% of the orb across, so the
// outline you see can only grow in steps of that size. At a scale of 1.10 the
// outline lands just under a step and measures 9% wider and 8% higher than the
// app's orb. At 1.11 it lands on the step above and measures 11% wider and 10%
// higher (averaged over the 16 second loop). That one looks 10% bigger, so it is
// the default. orb_test.go measures this, and -grow lets you try another size.
//
// Colour. Green means online and the layers turn. Red means offline and nothing
// moves at all: every layer rests at the angle the picture drew it. Amber (still
// checking) is kept as a third palette.

// cellAspect is a terminal cell's height divided by its width. 20 / 9 is a
// Windows Terminal cell at its stock font.
var cellAspect = defaultCellAspect

const defaultCellAspect = 2.22

// OrbGrow is the scale of this orb against the app's: the ring radius is 1.11 times
// the app's, which is what looks 10% bigger on the dot grid (see above).
const OrbGrow = 1.11

// originalRows is how many rows of cells the app gives the orb at 122 by 30.
const originalRows = 13

// OrbRows and OrbCols are the cells an orb of OrbGrow needs: the diameter in
// columns, and the diameter in rows (a row is cellAspect columns tall), each
// rounded up to an even count so the centre falls on a cell edge.
func OrbRows(grow float64) int { return evenUp(2 * OrbRadius(grow) / cellAspect) }
func OrbCols(grow float64) int { return evenUp(2*OrbRadius(grow) + 0.5) }

func evenUp(v float64) int {
	n := int(v)
	if float64(n) < v {
		n++
	}
	if n%2 == 1 {
		n++
	}
	return n
}

// originalRadius is the radius, in columns, of the app's orb: the ring fits
// the shorter side of its area less half a column. The tile is wide, so the
// height decides.
func originalRadius() float64 {
	return float64(originalRows)*cellAspect/2 - 0.5
}

// OrbRadius is the radius in columns of an orb grow times the app's.
func OrbRadius(grow float64) float64 { return originalRadius() * grow }

// OrbMode picks the colour set and whether the layers turn.
type OrbMode int

const (
	OrbGreen OrbMode = iota // online: green, the layers turn
	OrbRed                  // offline: red, nothing moves
	OrbAmber                // checking: amber, the layers turn slowly
)

func (m OrbMode) String() string {
	switch m {
	case OrbRed:
		return "red"
	case OrbAmber:
		return "amber"
	}
	return "green"
}

func clamp01(x float64) float64 {
	if x < 0 {
		return 0
	}
	if x > 1 {
		return 1
	}
	return x
}

// radarPal is the colour set of one state. The three stops are the dim line
// work, the main ink and the brightest highlight.
type radarPal struct {
	dim, mid, hot RGB
	gain          float64
}

// at is the ink for a tone from 0 to 1.
func (p radarPal) at(tone float64) RGB {
	tone = clamp01(tone * p.gain)
	if tone < 0.5 {
		return mix(p.dim, p.mid, tone/0.5)
	}
	return mix(p.mid, p.hot, (tone-0.5)/0.5)
}

// radarPalette is the colour set of a mode. These are the app's colours.
func radarPalette(mode OrbMode) radarPal {
	switch mode {
	case OrbRed:
		return radarPal{dim: RGB{86, 14, 22}, mid: RGB{255, 52, 66}, hot: RGB{255, 196, 202}, gain: 0.9}
	case OrbAmber:
		return radarPal{dim: RGB{84, 58, 6}, mid: RGB{255, 178, 34}, hot: RGB{255, 236, 190}, gain: 1}
	}
	return radarPal{dim: RGB{6, 92, 56}, mid: RGB{22, 238, 134}, hot: RGB{206, 255, 232}, gain: 1}
}

// radarState is what animates: the seconds of motion, which turn the layers.
// When moving is false every layer rests at its drawn angle.
type radarState struct {
	t      float64 // seconds of motion
	moving bool
}

// stateFor is the motion of a mode at time t (seconds). Red is completely still
// and does not depend on t.
func stateFor(mode OrbMode, t float64) radarState {
	switch mode {
	case OrbRed:
		return radarState{t: 0, moving: false}
	case OrbAmber:
		return radarState{t: t * 0.6, moving: true}
	}
	return radarState{t: t, moving: true}
}

// DrawOrb paints an orb 10% bigger than the app's (OrbGrow) into the rectangle
// (x0,y0,w,h) of cells, centred in it, at t seconds of motion. The rectangle
// must be at least OrbCols by OrbRows(OrbGrow) cells, or the ring is cut off at
// its edge.
func DrawOrb(c *Canvas, x0, y0, w, h int, t float64, mode OrbMode) {
	DrawOrbSized(c, x0, y0, w, h, t, mode, OrbGrow)
}

// DrawOrbSized is DrawOrb with the size as a multiple of the app's orb. A grow
// of 1 is the orb exactly as the app draws it, which is how the tests check
// this code against the app. It is not safe to call from several goroutines at
// once, because the radius is a package setting of ring.go.
func DrawOrbSized(c *Canvas, x0, y0, w, h int, t float64, mode OrbMode, grow float64) {
	ringRadius = OrbRadius(grow)
	defer func() { ringRadius = 0 }()
	ringDots(c, x0, y0, w, h, stateFor(mode, t), radarPalette(mode))
}
