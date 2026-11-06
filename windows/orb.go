package main

import "math"

// The quant mark is the HUD dial from the owner's picture: a teal field under
// concentric pale rings, a ring of heavy blocks, ribbed and tick rings, and a
// bright inner ring, with an empty centre. It is drawn as a picture: every
// character cell holds four pixels, so the curves stay smooth at terminal size.
//
// There is no gold sun, no wireframe sphere, no radar sweep and no crosshair,
// because the picture has none. The only movement is the slow clockwise turn
// of the rings while the quant is online; they stand still when it is parked,
// which is how the picture itself stands.

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

// The dial's own colours, taken from the owner's picture: a deep teal field
// and pale ice blue rings.
var (
	hudTeal = RGB{12, 104, 140}
	hudPale = RGB{228, 243, 249}
	hudMid  = RGB{176, 212, 228}
	hudDim  = RGB{104, 156, 180}
)

// hudRing is one concentric band of the dial. count 1 draws one arc with a gap;
// count above 1 draws that many segments around the circle, and a low fill
// makes them thin radial ticks instead of blocks.
type hudRing struct {
	r0, r1 float64 // inner and outer radius as a fraction of the dial's radius
	count  int     // segments around the circle
	fill   float64 // the painted part of each segment, 0 to 1
	offset float64 // where the segments start, in turns
	speed  float64 // turns a second, clockwise
	tone   float64 // 0 dim, 1 the brightest pale
}

// hudRings is the picture from the outside in: the thin capped arc, the ring
// of heavy blocks, the ribbed ring, the dense tick ring, the bright ring, the
// second tick ring and the small inner ring.
var hudRings = []hudRing{
	{0.955, 0.990, 1, 0.94, 0.06, 0.004, 0.50},
	{0.800, 0.930, 12, 0.62, 0.01, 0.010, 0.92},
	{0.690, 0.760, 40, 0.84, 0.00, 0.016, 0.68},
	{0.615, 0.700, 64, 0.30, 0.00, 0.022, 0.88},
	{0.455, 0.545, 6, 0.78, 0.02, 0.030, 1.00},
	{0.360, 0.440, 48, 0.28, 0.00, 0.038, 0.76},
	{0.230, 0.290, 36, 0.30, 0.00, 0.048, 0.70},
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
// to add to the background. h is twice the cell rows.
func orbPixels(w, h int, sx float64, st radarState, mode OrbMode) []RGB {
	vs := cellAspect / 2
	cx, cy := float64(w)/2, float64(h)/2
	R := math.Min(cx/sx, cy*vs) - 0.5
	if R < 3 {
		return nil
	}
	buf := make([]RGB, w*h)
	t := st.t
	if !st.moving {
		t = 0
	}
	field := hudTeal
	if mode == OrbParked || mode == OrbFault {
		field = mix(field, RGB{0, 0, 0}, 0.45)
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
			// The rings sit on the teal field, the way the picture's do.
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
				bg := c.BGAt(x0+cx, y0+cy)
				top, bot := over(bg, px[(2*cy)*w+cx]), over(bg, px[(2*cy+1)*w+cx])
				c.Set(x0+cx, y0+cy, '▀', top, bot, false)
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
			// A cell outside the dial keeps the panel behind it, so the mark
			// stays a round dial rather than a filled square.
			if px[(2*cy)*wp+2*cx] == (RGB{}) && px[(2*cy)*wp+2*cx+1] == (RGB{}) &&
				px[(2*cy+1)*wp+2*cx] == (RGB{}) && px[(2*cy+1)*wp+2*cx+1] == (RGB{}) {
				continue
			}
			bg := c.BGAt(x0+cx, y0+cy)
			var q [4]RGB
			q[0] = over(bg, px[(2*cy)*wp+2*cx])
			q[1] = over(bg, px[(2*cy)*wp+2*cx+1])
			q[2] = over(bg, px[(2*cy+1)*wp+2*cx])
			q[3] = over(bg, px[(2*cy+1)*wp+2*cx+1])
			ch, fg, bgc := quadrantCell(q)
			c.Set(x0+cx, y0+cy, ch, fg, bgc, false)
		}
	}
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

// over adds a glow colour to a background: light on dark.
func over(bg, glow RGB) RGB {
	add := func(b, g uint8) uint8 {
		v := int(b) + int(g)
		if v > 255 {
			v = 255
		}
		return uint8(v)
	}
	return RGB{add(bg.R, glow.R), add(bg.G, glow.G), add(bg.B, glow.B)}
}
