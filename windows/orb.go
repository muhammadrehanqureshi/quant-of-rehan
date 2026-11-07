package main

import "math"

// The quant mark is the HUD dial from the owner's picture: a square teal field
// under concentric pale ice blue rings, with clear gaps between them. At a
// terminal the picture can carry five bands, so the dial keeps the thin outer
// arc, the twelve heavy blocks, the dense tick ring, the bright inner ring and
// the small inner ring. The finer ribs of the picture would turn into speckle
// at this size, so they are left out.
//
// It is drawn as a picture: every cell holds four pixels, and a pixel is either
// ring or field, never a mix, so the rings stay clean instead of dissolving
// into noise at terminal size.

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

// hudRings is the picture from the outside in, reduced to the five bands a
// terminal can draw cleanly. The gaps between the bands are as much a part of
// the picture as the bands themselves.
var hudRings = []hudRing{
	{0.940, 0.990, 1, 0.94, 0.02, 0.004, 0.65},  // the thin outer arc
	{0.720, 0.920, 12, 0.74, 0.00, 0.010, 1.00}, // the twelve heavy blocks
	{0.550, 0.680, 48, 0.42, 0.00, 0.020, 0.85}, // the dense tick ring
	{0.300, 0.500, 6, 0.88, 0.00, 0.030, 1.00},  // the bright inner ring
	{0.120, 0.260, 12, 0.55, 0.00, 0.040, 0.80}, // the small inner ring
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

// orbField is the picture's own square field: teal when the quant is online,
// dimmed in the same blue when it is parked or the relay cannot be reached.
func orbField(mode OrbMode) RGB {
	field := hudTeal
	if mode == OrbParked || mode == OrbFault {
		field = mix(field, RGB{0, 0, 0}, 0.42)
	}
	return field
}

// orbPixels paints the dial into a w by h pixel buffer. h is twice the cell
// rows. The whole rectangle carries the picture's field, exactly as the owner's
// square picture does, and the rings sit on top of it.
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
	field := orbField(mode)
	for j := 0; j < h; j++ {
		for i := 0; i < w; i++ {
			x := (float64(i) + 0.5 - cx) / sx
			y := (float64(j) + 0.5 - cy) * vs
			r := math.Hypot(x, y) / R
			col := field
			if r <= 1 {
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
				if top == bot {
					ch, fg, bg = '█', top, top
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
	field := orbField(mode)
	for cy := 0; cy < h; cy++ {
		for cx := 0; cx < w; cx++ {
			var q [4]RGB
			q[0] = px[(2*cy)*wp+2*cx]
			q[1] = px[(2*cy)*wp+2*cx+1]
			q[2] = px[(2*cy+1)*wp+2*cx]
			q[3] = px[(2*cy+1)*wp+2*cx+1]
			paintOrbCell(c, x0+cx, y0+cy, q, field)
		}
	}
}

// paintOrbCell draws one cell from its four pixels. Each pixel is either the
// picture's field or ring, so the cell is drawn as an exact quadrant: there is
// no averaging and no third colour, which is what keeps the rings crisp instead
// of speckled at terminal size.
func paintOrbCell(c *Canvas, x, y int, q [4]RGB, field RGB) {
	mask := 0
	nf, nb := 0, 0
	var fs, bs [3]float64
	for i, col := range q {
		if col == field {
			bs[0] += float64(col.R)
			bs[1] += float64(col.G)
			bs[2] += float64(col.B)
			nb++
			continue
		}
		mask |= 1 << i
		fs[0] += float64(col.R)
		fs[1] += float64(col.G)
		fs[2] += float64(col.B)
		nf++
	}
	if mask == 0 {
		c.Set(x, y, '█', field, field, false)
		return
	}
	fg, bg := field, field
	if nf > 0 {
		fg = RGB{uint8(fs[0]/float64(nf) + 0.5), uint8(fs[1]/float64(nf) + 0.5), uint8(fs[2]/float64(nf) + 0.5)}
	}
	if nb > 0 {
		bg = RGB{uint8(bs[0]/float64(nb) + 0.5), uint8(bs[1]/float64(nb) + 0.5), uint8(bs[2]/float64(nb) + 0.5)}
	}
	c.Set(x, y, quadrants[mask], fg, bg, false)
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
