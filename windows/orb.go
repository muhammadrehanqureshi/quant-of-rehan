package main

import "math"

// The quant mark is the HUD dial from the owner's picture: a teal field under
// concentric pale ice blue rings, clear gaps between them, a ring of heavy
// blocks, a ribbed ring, two tick rings, a bright inner ring and a small inner
// ring, with an empty centre.
//
// It is drawn as a picture: every cell holds four pixels, and only two colours
// are ever mixed in one cell, so the rings stay clean instead of breaking into
// speckle at terminal size.

var cellAspect = defaultCellAspect

const defaultCellAspect = 2.22

// OrbMode says whether the quant is online. The dial keeps the picture's own
// blue in every state; offline it is dimmed rather than recoloured.
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

// The dial's own colours, from the owner's picture: a deep teal field and pale
// ice blue rings.
var (
	hudTeal = RGB{10, 96, 130}
	hudPale = RGB{232, 246, 251}
	hudMid  = RGB{176, 214, 230}
	hudDim  = RGB{96, 150, 176}
)

// hudRing is one concentric band. count above 1 draws that many segments around
// the circle, and a low fill makes them thin radial ticks rather than blocks.
type hudRing struct {
	r0, r1 float64 // inner and outer radius as a fraction of the dial's radius
	count  int     // segments around the circle
	fill   float64 // the painted part of each segment, 0 to 1
	offset float64 // where the segments start, in turns
	speed  float64 // turns a second, clockwise
	tone   float64 // 0 dim, 1 the brightest pale
}

// hudRings is the picture from the outside in. The bands are wide enough to
// read at terminal size; the tick rings use few, thick ticks rather than a
// dense fringe that would turn into noise.
var hudRings = []hudRing{
	{0.960, 0.995, 1, 0.74, 0.02, 0.004, 0.60},
	{0.795, 0.945, 10, 0.58, 0.01, 0.012, 0.95},
	{0.665, 0.760, 20, 0.70, 0.00, 0.018, 0.62},
	{0.560, 0.645, 20, 0.30, 0.00, 0.026, 0.88},
	{0.385, 0.500, 5, 0.78, 0.02, 0.034, 1.00},
	{0.265, 0.345, 14, 0.34, 0.00, 0.044, 0.74},
	{0.140, 0.225, 3, 0.84, 0.00, 0.052, 0.88},
}

// radarState is what animates. When moving is false the rings stay where they
// stopped.
type radarState struct {
	t      float64 // seconds of motion
	moving bool
}

// hudInk gives the ink for one tone at this mode: the picture's ice blue when
// online, dimmed when the quant is parked, softer while the relay is checked.
func hudInk(tone float64, mode OrbMode) RGB {
	c := mix(hudMid, hudPale, clamp01(tone))
	switch mode {
	case OrbParked, OrbFault:
		return mix(hudDim, c, 0.40)
	case OrbChecking:
		return mix(hudDim, c, 0.72)
	}
	return c
}

// orbPixels paints the dial into a w by h pixel buffer and returns the colours
// to add to the background. h is twice the cell rows. A zero RGB means "outside
// the dial", which keeps the panel behind it untouched.
func orbPixels(w, h int, sx float64, st radarState, mode OrbMode) []RGB {
	vs := cellAspect / 2
	cx, cy := float64(w)/2, float64(h)/2
	R := math.Min(cx/sx, cy*vs) - 0.5
	if R < 4 {
		return nil
	}
	buf := make([]RGB, w*h)
	t := st.t
	if !st.moving {
		t = 0
	}
	field := hudTeal
	if mode == OrbParked || mode == OrbFault {
		field = mix(field, RGB{0, 0, 0}, 0.42)
	}
	for j := 0; j < h; j++ {
		for i := 0; i < w; i++ {
			x := (float64(i) + 0.5 - cx) / sx
			y := (float64(j) + 0.5 - cy) * vs
			r := math.Hypot(x, y) / R
			if r > 1 {
				continue
			}
			col := field
			turn := math.Atan2(y, x)/(2*math.Pi) + 1
			for _, g := range hudRings {
				if r < g.r0 || r > g.r1 {
					continue
				}
				if g.count > 0 {
					slot := (turn + g.offset + g.speed*t) * float64(g.count)
					if slot-math.Floor(slot) > g.fill {
						continue
					}
				}
				col = hudInk(g.tone, mode)
				break
			}
			buf[j*w+i] = col
		}
	}
	return buf
}

// ringHalfBlocks turns the mark back to one pixel per column, drawn with the
// upper half block. It is the -halfblock flag, for a font that cannot draw the
// quadrant characters.
var ringHalfBlocks bool

// drawOrb paints the mark into the rectangle (x0,y0,w,h) of cells.
func drawOrb(c *Canvas, x0, y0, w, h int, t float64, mode OrbMode, th *Theme) {
	if w < 6 || h < 3 {
		return
	}
	st := radarState{t: t, moving: true}
	switch mode {
	case OrbParked, OrbFault:
		st = radarState{t: 0, moving: false}
	case OrbChecking:
		st = radarState{t: t * 0.6, moving: true}
	}
	if ringHalfBlocks {
		px := orbPixels(w, 2*h, 1, st, mode)
		if px == nil {
			return
		}
		for cy := 0; cy < h; cy++ {
			for cx := 0; cx < w; cx++ {
				top, bot := px[(2*cy)*w+cx], px[(2*cy+1)*w+cx]
				ch, fg, bg := '▀', top, bot
				switch {
				case top == (RGB{}) && bot == (RGB{}):
					continue
				case top == (RGB{}):
					ch, fg, bg = '▄', bot, c.BGAt(x0+cx, y0+cy)
				case bot == (RGB{}):
					ch, fg, bg = '▀', top, c.BGAt(x0+cx, y0+cy)
				}
				c.Set(x0+cx, y0+cy, ch, fg, bg, false)
			}
		}
		return
	}
	px := orbPixels(2*w, 2*h, 2, st, mode)
	if px == nil {
		return
	}
	wp := 2 * w
	for cy := 0; cy < h; cy++ {
		for cx := 0; cx < w; cx++ {
			var q [4]RGB
			q[0] = px[(2*cy)*wp+2*cx]
			q[1] = px[(2*cy)*wp+2*cx+1]
			q[2] = px[(2*cy+1)*wp+2*cx]
			q[3] = px[(2*cy+1)*wp+2*cx+1]
			paintOrbCell(c, x0+cx, y0+cy, q)
		}
	}
}

// paintOrbCell draws one cell from its four pixels. Every pixel is either the
// panel behind the dial or one of the dial's two or three colours, so the cell
// is drawn as an exact quadrant rather than an average. That is what keeps the
// rings crisp instead of speckled.
func paintOrbCell(c *Canvas, x, y int, q [4]RGB) {
	var cols []RGB
	var masks []int
	for i := 0; i < 4; i++ {
		col := q[i]
		found := -1
		for k, have := range cols {
			if have == col {
				found = k
				break
			}
		}
		if found < 0 {
			cols = append(cols, col)
			masks = append(masks, 0)
			found = len(cols) - 1
		}
		masks[found] |= 1 << i
	}
	if len(cols) == 1 {
		if cols[0] == (RGB{}) {
			return
		}
		c.Set(x, y, '█', cols[0], cols[0], false)
		return
	}
	outside := -1
	for k, col := range cols {
		if col == (RGB{}) {
			outside = k
		}
	}
	if len(cols) == 2 {
		fg, bg := cols[0], cols[1]
		mask := masks[0]
		if outside == 0 {
			bg = c.BGAt(x, y)
			fg, mask = cols[1], masks[1]
		} else if outside == 1 {
			bg = c.BGAt(x, y)
		}
		c.Set(x, y, quadrants[mask], fg, bg, false)
		return
	}
	// Three colours in one cell is a ring boundary. Fall back to the best
	// quadrant, with the panel behind the dial in place of the outside.
	var qq [4]RGB
	for i := range qq {
		qq[i] = q[i]
		if qq[i] == (RGB{}) {
			qq[i] = c.BGAt(x, y)
		}
	}
	ch, fg, bg := quadrantCell(qq)
	c.Set(x, y, ch, fg, bg, false)
}

// quadrants[m] is the character whose lit quarters are the bits of m: 1 upper
// left, 2 upper right, 4 lower left, 8 lower right.
var quadrants = [16]rune{' ', '▘', '▝', '▀', '▖', '▌', '▞', '▛', '▗', '▚', '▐', '▜', '▄', '▙', '▟', '█'}

// quadrantMask gives the bits of the quarters a character lights, or ok false
// when the character is not a quadrant character.
func quadrantMask(ch rune) (m int, ok bool) {
	for i, r := range quadrants {
		if r == ch {
			return i, true
		}
	}
	return 0, false
}

// quadrantCell picks the character and the two colours that best draw four
// pixels: for every way to split the four into two groups, each group takes its
// own average, and the split with the least error wins.
func quadrantCell(q [4]RGB) (ch rune, fg, bg RGB) {
	best := -1.0
	for m := 0; m < 15; m++ {
		var sf, sb [3]float64
		nf, nb := 0, 0
		for i := 0; i < 4; i++ {
			c := [3]float64{float64(q[i].R), float64(q[i].G), float64(q[i].B)}
			if m&(1<<i) != 0 {
				for k := range c {
					sf[k] += c[k]
				}
				nf++
			} else {
				for k := range c {
					sb[k] += c[k]
				}
				nb++
			}
		}
		var f, b [3]float64
		for k := 0; k < 3; k++ {
			if nf > 0 {
				f[k] = sf[k] / float64(nf)
			}
			if nb > 0 {
				b[k] = sb[k] / float64(nb)
			}
		}
		e := 0.0
		for i := 0; i < 4; i++ {
			c := [3]float64{float64(q[i].R), float64(q[i].G), float64(q[i].B)}
			ref := b
			if m&(1<<i) != 0 {
				ref = f
			}
			for k := 0; k < 3; k++ {
				e += (c[k] - ref[k]) * (c[k] - ref[k])
			}
		}
		if m == 0 && (best < 0 || e < best) {
			best, ch, fg, bg = e, ' ', RGB{uint8(b[0] + 0.5), uint8(b[1] + 0.5), uint8(b[2] + 0.5)}, RGB{uint8(b[0] + 0.5), uint8(b[1] + 0.5), uint8(b[2] + 0.5)}
			continue
		}
		if m != 0 && (best < 0 || e < best-1e-9) {
			best, ch = e, quadrants[m]
			fg = RGB{uint8(f[0] + 0.5), uint8(f[1] + 0.5), uint8(f[2] + 0.5)}
			bg = RGB{uint8(b[0] + 0.5), uint8(b[1] + 0.5), uint8(b[2] + 0.5)}
		}
	}
	return ch, fg, bg
}
