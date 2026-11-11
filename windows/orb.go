package main

// The quant mark is the owner's own orb source, QoR-orb-source.zip, copied in
// and drawn by its own code and nothing else. Owner order 2026-11-10 (latest):
// "the ORB still doesn't look like the source file... you need to make it
// exactly 100% from the .zip file".
//
// What that means here, in the source's own terms:
//
//   - the size is the source's OrbGrow of 1.11 times the app's 13 row radius,
//     which is 15.46 columns. The two later grows of the same day (1.221 and
//     1.3431) are withdrawn, because they were invented after the handover;
//   - the width is the source's: orbXShrink, which squeezed the mark five
//     percent across, is gone, so the ring is round exactly as the picture is;
//   - the ink is the source's three stops per colour, resolved by ring.go's own
//     radarPal.at, with no band shading and no GIF palette on top;
//   - green turns and red is completely still, which is the source's stateFor.
//
// windows/ring.go, windows/ring_data.go and windows/assets/ring are the
// source's files; the assets are byte for byte the six layer pictures.

var cellAspect = defaultCellAspect

const defaultCellAspect = 2.22

// hudForceLive keeps the app refreshing the dial at the live cadence in every
// state, so the owner can inspect it while the market is closed.
const hudForceLive = true

// ringHalfBlocks is kept for the -halfblock flag. The source draws the ring in
// Braille dots only, so there is no second renderer any more.
var ringHalfBlocks bool

// The source's own size, with the owner's newest order applied to it.
// Owner order 2026-11-11: the mark is fifteen percent smaller than its current
// size and turns fifteen percent slower, so both are one factor off the
// source's own numbers and nothing else about the mark moves.
const (
	orbSizeScale  = 0.85
	orbSpeedScale = 0.85
	OrbGrow       = 1.11 * orbSizeScale
	orbBaseRows   = 13 // the rows the app's first orb had
)

// OrbRadius is the source's radius in columns for a grow factor:
// originalRadius() = 13 * cellAspect / 2 - 0.5, times grow.
func OrbRadius(grow float64) float64 {
	return (float64(orbBaseRows)*cellAspect/2 - 0.5) * grow
}

// OrbMode says whether the quant is online. The ink comes from the window rule
// (a.orbGreen); the mode is kept for the rest of the HUD and its tests.
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

// drawOrb paints the source's orb into the rectangle (x0,y0,w,h) of cells, at t
// seconds of motion. green selects the source's green palette and its turning
// layers; false selects its red palette with every layer at rest. The size is
// the source's OrbGrow, and a rectangle too small for it draws the ring at the
// room it has, so nothing is ever drawn outside the box.
func drawOrb(c *Canvas, x0, y0, w, h int, t float64, mode OrbMode, green bool, th *Theme) {
	if w < 6 || h < 3 {
		return
	}
	_ = mode // the ink, not the mode, selects the colour
	_ = th   // the ring leaves every unlit cell the panel's own background
	want := OrbRadius(OrbGrow)
	room := float64(w) / 2
	if vertical := float64(h) * cellAspect / 2; vertical < room {
		room = vertical
	}
	if room >= 3 {
		ringRadius = want
		if room < want {
			ringRadius = room
		}
		defer func() { ringRadius = 0 }()
	}
	ringDots(c, x0, y0, w, h, ringStateFor(t, green), ringPalette(green))
}
