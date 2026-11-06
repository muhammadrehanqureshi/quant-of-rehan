package main

import (
	"math"
	"sort"
)

// The quant mark is the gold sun inside a wireframe network sphere, after the
// owner's picture. It is drawn as a picture rather than dots: every character
// cell holds four pixels, so the curves stay smooth at terminal size.
//
// There is no radar sweep, no antenna beam and no crosshair. The only movement
// is the slow turn of the wireframe sphere. The sun itself stays still, as in
// the picture, and the mark stays gold in every state; the status pill and the
// text carry the online or offline state.

var cellAspect = defaultCellAspect

const defaultCellAspect = 2.22

// OrbMode mirrors the Android ThinkingOrb gate: it burns while the quant is
// online and parks when it is not.
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

// radarPal is the colour set of one state. The three stops are the dim line
// work, the main ink and the brightest highlight.
type radarPal struct {
	dim, mid, hot RGB
	gain          float64
}

func (p radarPal) at(tone float64) RGB {
	tone = clamp01(tone * p.gain)
	if tone < 0.5 {
		return mix(p.dim, p.mid, tone/0.5)
	}
	return mix(p.mid, p.hot, (tone-0.5)/0.5)
}

// The mark is gold in every state, as the owner's picture is. Offline is a
// dimmer gold rather than a different hue.
func radarPalette(mode OrbMode) radarPal {
	switch mode {
	case OrbParked, OrbFault:
		return radarPal{dim: RGB{70, 14, 14}, mid: RGB{200, 40, 40}, hot: RGB{255, 140, 140}, gain: 0.9}
	case OrbChecking:
		return radarPal{dim: RGB{60, 60, 16}, mid: RGB{200, 190, 50}, hot: RGB{255, 245, 160}, gain: 1}
	}
	return radarPal{dim: RGB{14, 70, 30}, mid: RGB{40, 200, 90}, hot: RGB{150, 255, 180}, gain: 1}
}

// radarState is what animates. When moving is false the sphere stays where it
// stopped.
type radarState struct {
	t      float64 // seconds of motion
	moving bool
}

// markNode is one vertex of the wireframe sphere.
type markNode struct {
	x, y, z float64
}

// markNodes builds a Fibonacci sphere: evenly spread points, which look like a
// network rather than a regular grid. The list is fixed, so the picture is
// stable from frame to frame.
func markNodes() []markNode {
	const n = 46
	out := make([]markNode, 0, n)
	ga := math.Pi * (3 - math.Sqrt(5))
	for i := 0; i < n; i++ {
		y := 1 - 2*(float64(i)+0.5)/n
		rad := math.Sqrt(math.Max(0, 1-y*y))
		a := ga * float64(i)
		out = append(out, markNode{math.Cos(a) * rad, y, math.Sin(a) * rad})
	}
	return out
}

// markEdges joins each node to its nearest neighbours, giving a constellation
// mesh. Each pair is kept once.
func markEdges(nodes []markNode) [][2]int {
	type pair struct {
		i, j int
		d    float64
	}
	var pairs []pair
	for i := range nodes {
		for j := i + 1; j < len(nodes); j++ {
			dx := nodes[i].x - nodes[j].x
			dy := nodes[i].y - nodes[j].y
			dz := nodes[i].z - nodes[j].z
			pairs = append(pairs, pair{i, j, dx*dx + dy*dy + dz*dz})
		}
	}
	sort.Slice(pairs, func(a, b int) bool { return pairs[a].d < pairs[b].d })
	seen := make([]int, len(nodes))
	var out [][2]int
	for _, p := range pairs {
		if seen[p.i] >= 2 && seen[p.j] >= 2 {
			continue
		}
		if seen[p.i] >= 3 || seen[p.j] >= 3 {
			continue
		}
		seen[p.i]++
		seen[p.j]++
		out = append(out, [2]int{p.i, p.j})
	}
	return out
}

var markVerts = markNodes()
var markLinks = markEdges(markVerts)

// orbPixels paints the mark into a w by h pixel buffer and returns the colours
// to add to the background. h is twice the cell rows.
func orbPixels(w, h int, sx float64, st radarState, pal radarPal) []RGB {
	vs := cellAspect / 2
	cx, cy := float64(w)/2, float64(h)/2
	R := math.Min(cx/sx, cy*vs) - 0.5
	if R < 3 {
		return nil
	}
	buf := make([][3]float64, w*h)
	put := func(i, j int, tone, alpha float64) {
		if alpha <= 0 || i < 0 || j < 0 || i >= w || j >= h {
			return
		}
		c := pal.at(tone)
		idx := j*w + i
		buf[idx][0] += float64(c.R) / 255 * alpha
		buf[idx][1] += float64(c.G) / 255 * alpha
		buf[idx][2] += float64(c.B) / 255 * alpha
	}

	// A faint halo makes the gold read as light on the dark panel.
	for j := 0; j < h; j++ {
		for i := 0; i < w; i++ {
			x := (float64(i) + 0.5 - cx) / sx
			y := (float64(j) + 0.5 - cy) * vs
			f := math.Hypot(x, y) / R
			if f > 1.18 {
				continue
			}
			put(i, j, 0.08, 0.22*clamp01((1.18-f)/0.28))
		}
	}

	// The sun: a still, glowing disc at the centre of the network.
	sun := 0.27 * R
	for j := 0; j < h; j++ {
		for i := 0; i < w; i++ {
			x := (float64(i) + 0.5 - cx) / sx
			y := (float64(j) + 0.5 - cy) * vs
			r := math.Hypot(x, y)
			if r > sun*2.3 {
				continue
			}
			switch {
			case r <= sun*0.55:
				put(i, j, 0.95, 0.98)
			case r <= sun:
				put(i, j, 0.72, 0.92*clamp01((sun-r)/sun+0.15))
			case r <= sun*1.45:
				put(i, j, 0.5, 0.42*clamp01((sun*1.45-r)/(sun*0.45)))
			default:
				put(i, j, 0.3, 0.20*clamp01((sun*2.3-r)/(sun*0.85)))
			}
		}
	}
	// A few short rays, still part of the sun rather than a sweep.
	for k := 0; k < 12; k++ {
		a := float64(k) * math.Pi / 6
		for d := sun * 1.35; d < sun*1.75; d += 0.45 {
			x := math.Cos(a) * d
			y := math.Sin(a) * d
			i := int(cx + x*sx)
			j := int(cy + y/vs)
			put(i, j, 0.55, 0.18)
		}
	}

	// The wireframe sphere turns slowly around its vertical axis.
	t := st.t
	if !st.moving {
		t = 2.4
	}
	ca, sa := math.Cos(t*0.42), math.Sin(t*0.42)
	tilt := 0.38
	ct, stt := math.Cos(tilt), math.Sin(tilt)
	project := func(n markNode) (float64, float64, float64) {
		x := ca*n.x + sa*n.z
		z := -sa*n.x + ca*n.z
		y := ct*n.y - stt*z
		z = stt*n.y + ct*z
		return x * R * 0.98, y * R * 0.98, z
	}
	// Back edges first, so the front of the sphere reads as the front.
	type edge struct {
		a, b markNode
		d    float64
	}
	edges := make([]edge, 0, len(markLinks))
	for _, e := range markLinks {
		edges = append(edges, edge{markVerts[e[0]], markVerts[e[1]], 0})
	}
	sort.SliceStable(edges, func(i, j int) bool {
		_, _, zi := project(edges[i].a)
		_, _, zj := project(edges[j].a)
		return zi < zj
	})
	for _, e := range edges {
		ax, ay, az := project(e.a)
		bx, by, bz := project(e.b)
		depth := (az + bz) / 2
		alpha := 0.28 + 0.42*clamp01(depth+0.5)
		tone := 0.34 + 0.30*clamp01(depth+0.5)
		const steps = 22
		for s := 0; s <= steps; s++ {
			f := float64(s) / steps
			x := ax + (bx-ax)*f
			y := ay + (by-ay)*f
			i := int(cx + x*sx)
			j := int(cy + y/vs)
			put(i, j, tone, alpha)
			// A one pixel soft edge on each side.
			put(i+1, j, tone*0.96, alpha*0.35)
		}
	}
	for _, n := range markVerts {
		x, y, z := project(n)
		i := int(cx + x*sx)
		j := int(cy + y/vs)
		tone := 0.55 + 0.4*clamp01(z+0.5)
		put(i, j, tone, 0.85)
		put(i-1, j, tone*0.9, 0.4)
		put(i, j-1, tone*0.9, 0.4)
	}

	// Soft clip, so nothing burns to a hard white.
	out := make([]RGB, w*h)
	for i := range out {
		var ch [3]float64
		for c := 0; c < 3; c++ {
			ch[c] = 1 - math.Exp(-1.6*buf[i][c])
		}
		out[i] = RGB{uint8(ch[0]*255 + 0.5), uint8(ch[1]*255 + 0.5), uint8(ch[2]*255 + 0.5)}
	}
	return out
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
	pal := radarPalette(mode)
	st := radarState{t: t, moving: true}
	switch mode {
	case OrbParked, OrbFault:
		st = radarState{t: 2.4, moving: false}
	case OrbChecking:
		st = radarState{t: t * 0.6, moving: true}
	}
	if ringHalfBlocks {
		px := orbPixels(w, 2*h, 1, st, pal)
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
	px := orbPixels(2*w, 2*h, 2, st, pal)
	if px == nil {
		return
	}
	wp := 2 * w
	for cy := 0; cy < h; cy++ {
		for cx := 0; cx < w; cx++ {
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
