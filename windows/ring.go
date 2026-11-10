package main

// The orb the owner handed over in QoR-orb-source.zip (order 2026-11-10: "the
// ORB is still not the same ORB that I gave you... just have to copy it in to
// the code"). ring.go, ring_data.go and assets/ring were copied from that
// source: six turning layers cut from the reference picture, each lit by how
// much of it a dot covers, and drawn as Braille dots. The only thing changed
// here is what the app already has in common with the source: brailleBit lives
// in spark.go, clamp01 in orb.go, and mix in the theme.

import (
	"embed"
	"image"
	"image/png"
	"math"
	"sync"
)

//go:embed assets/ring/*.png
var ringFS embed.FS

// ringTex is the side of the base texture of every layer, in texels.
const ringTex = 512

// ringLayer is one turning layer: its settings and its picture at several sizes
// (level 0 is ringTex by ringTex, every next level half the size), so a pixel
// that covers many texels reads an average and not one point of it.
type ringLayer struct {
	spec ringLayerSpec
	lv   [][]float32
	size []int
	// thin marks the layers drawn with hairlines (the outer arcs, the tick ring
	// and the small dial). Their strokes are narrower than a dot, so they are
	// lit by how much of the dot they touch. The solid layers (the blocks, the
	// thick glass ring and the inner arcs) are lit by which side of an edge the
	// middle of the dot falls on, which keeps their edges where the picture has
	// them.
	thin bool
}

var (
	ringLayers []ringLayer
	ringOnce   sync.Once
)

func loadRing() {
	var out []ringLayer
	for _, sp := range ringLayerSpecs {
		f, err := ringFS.Open("assets/ring/" + sp.file)
		if err != nil {
			return
		}
		img, err := png.Decode(f)
		f.Close()
		if err != nil {
			return
		}
		g, ok := img.(*image.Gray)
		if !ok || g.Bounds().Dx() != ringTex || g.Bounds().Dy() != ringTex {
			return
		}
		base := make([]float32, ringTex*ringTex)
		for y := 0; y < ringTex; y++ {
			for x := 0; x < ringTex; x++ {
				base[y*ringTex+x] = float32(g.Pix[y*g.Stride+x]) / 255
			}
		}
		l := ringLayer{spec: sp, lv: [][]float32{base}, size: []int{ringTex}}
		switch sp.file {
		case "layer0_small.png", "layer2_ticks.png", "layer5_arcs.png":
			l.thin = true
		}
		for n := ringTex; n > 32; n /= 2 {
			prev, h := l.lv[len(l.lv)-1], n/2
			next := make([]float32, h*h)
			for y := 0; y < h; y++ {
				for x := 0; x < h; x++ {
					next[y*h+x] = (prev[2*y*n+2*x] + prev[2*y*n+2*x+1] + prev[(2*y+1)*n+2*x] + prev[(2*y+1)*n+2*x+1]) / 4
				}
			}
			l.lv = append(l.lv, next)
			l.size = append(l.size, h)
		}
		out = append(out, l)
	}
	ringLayers = out
}

// sample reads a layer at (u, v) texels of level lv, bilinear, zero outside.
func (l *ringLayer) sample(lv int, u, v float64) float64 {
	n := l.size[lv]
	u -= 0.5
	v -= 0.5
	x0, y0 := int(math.Floor(u)), int(math.Floor(v))
	fx, fy := u-float64(x0), v-float64(y0)
	px := l.lv[lv]
	at := func(x, y int) float64 {
		if x < 0 || y < 0 || x >= n || y >= n {
			return 0
		}
		return float64(px[y*n+x])
	}
	a := at(x0, y0)*(1-fx) + at(x0+1, y0)*fx
	b := at(x0, y0+1)*(1-fx) + at(x0+1, y0+1)*fx
	return a*(1-fy) + b*fy
}

// ringRadius is the radius of the ring in columns. Zero, which is what the app
// uses, fits the ring to the area it is drawn in; the source's own size sets it
// so the orb has a size of its own.
var ringRadius float64

// ringGeom is the set up every way of drawing the ring shares: where the
// centre is, how big a pixel is, which layer size to read and how far every layer
// has turned.
type ringGeom struct {
	cx, cy, k, pw, ph float64
	lv                int
	sin, cos          []float64
	offs              []float64
	W, H, ss          int
}

// newRingGeom sets up for w by h cells of sx by sy pixels each, with ss by ss
// samples in every pixel. A cell is cellAspect times taller than wide, so the
// ring comes out round. It returns nil when the textures are missing or the
// area is too small for a ring.
func newRingGeom(w, h, sx, sy, ss int, st radarState) *ringGeom {
	ringOnce.Do(loadRing)
	if len(ringLayers) == 0 {
		return nil
	}
	g := &ringGeom{W: w * sx, H: h * sy, ss: ss}
	g.cx, g.cy = float64(w)/2, float64(h)*cellAspect/2 // the centre, in columns
	R := math.Min(g.cx, g.cy) - 0.5
	if ringRadius > 0 {
		R = ringRadius
	}
	if R < 3 {
		return nil
	}
	g.k = ringReach / R                                // picture pixels per column
	g.pw, g.ph = 1/float64(sx), cellAspect/float64(sy) // the pixel's size in columns
	// One sample's spacing in level 0 texels, which picks the layer size.
	fp := g.k * math.Max(g.pw, g.ph) / float64(ss) * ringTex / ringCanvas
	for fp/float64(int(1)<<g.lv) > 1.4 && g.lv < 4 {
		g.lv++
	}
	g.sin = make([]float64, len(ringLayers))
	g.cos = make([]float64, len(ringLayers))
	for i, l := range ringLayers {
		ang := 0.0
		if st.moving {
			ang = l.spec.degPerSec * st.t * math.Pi / 180
		}
		// The inverse turn: a sample reads the layer where it was before it turned.
		g.sin[i], g.cos[i] = math.Sincos(ang)
	}
	g.offs = make([]float64, ss)
	for i := range g.offs {
		g.offs[i] = (float64(i)+0.5)/float64(ss) - 0.5
	}
	return g
}

// alphas reads every layer at the sample (ox, oy) of pixel (i, j), where ox and
// oy run from -0.5 to 0.5 across the pixel, into a.
func (g *ringGeom) alphas(i, j int, ox, oy float64, a []float64) {
	x := (float64(i)+0.5+ox)*g.pw - g.cx
	y := (float64(j)+0.5+oy)*g.ph - g.cy
	X, Y := ringCanvas/2+x*g.k, ringCanvas/2+y*g.k
	for n := range ringLayers {
		l := &ringLayers[n]
		dx, dy := X-l.spec.cx, Y-l.spec.cy
		if r := math.Hypot(dx, dy); r < l.spec.rin || r > l.spec.rout {
			a[n] = 0
			continue
		}
		u := l.spec.cx + dx*g.cos[n] + dy*g.sin[n]
		v := l.spec.cy - dx*g.sin[n] + dy*g.cos[n]
		ts := float64(l.size[g.lv]) / ringCanvas
		a[n] = clamp01(l.sample(g.lv, u*ts, v*ts))
	}
}

// ringCoverage works out how much of every pixel the ring covers, from 0 to 1. A
// cell of the terminal is sx by sy pixels, so the result is (w*sx) by (h*sy) for
// w by h cells, each pixel averaged over ss by ss sample points. It is nil when
// there is no ring to draw.
func ringCoverage(w, h, sx, sy, ss int, st radarState) []float32 {
	g := newRingGeom(w, h, sx, sy, ss, st)
	if g == nil {
		return nil
	}
	a := make([]float64, len(ringLayers))
	out := make([]float32, g.W*g.H)
	for j := 0; j < g.H; j++ {
		for i := 0; i < g.W; i++ {
			var sum float64
			for _, oy := range g.offs {
				for _, ox := range g.offs {
					g.alphas(i, j, ox, oy, a)
					keep := 1.0
					for _, v := range a {
						keep *= 1 - v
					}
					sum += 1 - keep
				}
			}
			out[j*g.W+i] = float32(sum / float64(ss*ss))
		}
	}
	return out
}

// ringPixels is the ring as colours to add to the background, for a plain half
// block fallback.
func ringPixels(w, h, sx, sy int, st radarState, pal radarPal) []RGB {
	cov := ringCoverage(w, h, sx, sy, 2, st)
	if cov == nil {
		return nil
	}
	out := make([]RGB, len(cov))
	for i, a := range cov {
		if a < 0.004 {
			continue
		}
		a = float32(math.Pow(float64(a), ringGamma))
		c := pal.at(float64(a))
		f := clamp01(float64(a) * 1.2)
		out[i] = RGB{uint8(float64(c.R)*f + 0.5), uint8(float64(c.G)*f + 0.5), uint8(float64(c.B)*f + 0.5)}
	}
	return out
}

// ringGamma lifts the thin, faint strokes of the picture so they stay visible at
// terminal size (half block fallback only).
const ringGamma = 0.6

// The ring is drawn in dots. A character cell is a 2 by 4 grid of Braille dots, so
// a pixel of the ring is one dot, and every layer of the picture decides for
// itself whether it lights a dot:
//
//   - A hairline layer (the outer arcs, the tick ring, the small dial) lights a dot
//     when its stroke covers at least dotThinLit of it. A stroke is narrower than
//     a dot, so this keeps the lines whole instead of broken into dashes.
//   - A solid layer (the blocks, the thick glass ring, the inner arcs) lights a
//     dot when the middle of the dot is inside the shape, that is when the shape
//     covers at least dotSolidLit of it. Edges stay where the picture has them
//     and the gaps between shapes stay open.
//
// A lit dot is dim or bright by how opaque the layer is in the picture (the glass
// ring is paler than the blocks), and softer at the very rim of a shape. A cell
// has one ink for all its dots, so it takes a mix of its brightest dot and the
// average of its lit dots (dotMax), which also softens the edges.
const (
	dotThinLit  = 0.12 // coverage that lights a dot for a hairline layer
	dotSolidLit = 0.50 // coverage that lights a dot for a solid layer
	dotFloor    = 0.34 // the tone of the faintest dot
	dotTop      = 0.88 // the tone of a dot of a fully opaque layer
	dotRim      = 0.80 // the share of its tone a dot keeps at the very rim of a shape
	dotMax      = 0.55 // how much of a cell's ink follows its brightest dot (the rest, the average)
)

// ringDots draws the ring into the rectangle of cells (x0,y0,w,h) as Braille dots.
// It returns false when there is nothing to draw (the textures are missing or
// the area is too small).
func ringDots(c *Canvas, x0, y0, w, h int, st radarState, pal radarPal) bool {
	const ss = 4
	g := newRingGeom(w, h, 2, 4, ss, st)
	if g == nil {
		return false
	}
	n := len(ringLayers)
	a := make([]float64, n)
	sum := make([]float64, n)
	mx := make([]float64, n)
	// tone[dot] is 0 for a dark dot, else how bright it is.
	tone := make([]float32, g.W*g.H)
	for j := 0; j < g.H; j++ {
		for i := 0; i < g.W; i++ {
			for k := range sum {
				sum[k], mx[k] = 0, 0
			}
			for _, oy := range g.offs {
				for _, ox := range g.offs {
					g.alphas(i, j, ox, oy, a)
					for k, v := range a {
						sum[k] += v
						if v > mx[k] {
							mx[k] = v
						}
					}
				}
			}
			var best float64
			for k := range ringLayers {
				if mx[k] < 0.02 {
					continue
				}
				var t float64
				if ringLayers[k].thin {
					cov := sum[k] / (ss * ss)
					if cov < dotThinLit {
						continue
					}
					t = dotFloor + (dotTop-dotFloor)*clamp01((cov-dotThinLit)/(0.55-dotThinLit))
				} else {
					if mx[k] < 0.2 {
						continue // only the faint fringe of a shape
					}
					geo := sum[k] / (ss * ss * mx[k]) // how much of the dot the shape covers
					if geo < dotSolidLit {
						continue
					}
					op := clamp01((mx[k] - 0.4) / 0.55)
					rim := dotRim + (1-dotRim)*clamp01((geo-dotSolidLit)/0.35)
					t = (dotFloor + (dotTop-dotFloor)*op) * rim
				}
				if t > best {
					best = t
				}
			}
			tone[j*g.W+i] = float32(best)
		}
	}
	for cy := 0; cy < h; cy++ {
		for cx := 0; cx < w; cx++ {
			var mask rune
			var top, total float64
			var lit int
			for dx := 0; dx < 2; dx++ {
				for dy := 0; dy < 4; dy++ {
					t := float64(tone[(cy*4+dy)*g.W+cx*2+dx])
					if t == 0 {
						continue
					}
					mask |= brailleBit[dx][dy]
					total += t
					lit++
					if t > top {
						top = t
					}
				}
			}
			if mask == 0 {
				continue // nothing of the ring here: leave the cell alone
			}
			ink := dotMax*top + (1-dotMax)*total/float64(lit)
			c.Set(x0+cx, y0+cy, 0x2800+mask, pal.at(ink), c.BGAt(x0+cx, y0+cy), false)
		}
	}
	return true
}

// radarPal is the colour set of one state: the dim line work, the main ink and
// the brightest highlight, plus the gain its tones are read through. These are
// the source's own three stops.
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

// radarState is what animates: the seconds of motion, which turn the layers.
// When moving is false every layer rests at the angle the picture drew it.
type radarState struct {
	t      float64
	moving bool
}

// ringStateFor is the motion of the source orb at t seconds: green means the
// quant is online and every layer turns, red means it is offline and nothing
// moves at all, exactly as the source draws it.
func ringStateFor(t float64, green bool) radarState {
	if !green {
		return radarState{t: 0, moving: false}
	}
	return radarState{t: t, moving: true}
}

// ringPalette is the source's green and red colour sets, untouched.
func ringPalette(green bool) radarPal {
	if green {
		return radarPal{dim: RGB{6, 92, 56}, mid: RGB{22, 238, 134}, hot: RGB{206, 255, 232}, gain: 1}
	}
	return radarPal{dim: RGB{86, 14, 22}, mid: RGB{255, 52, 66}, hot: RGB{255, 196, 202}, gain: 0.9}
}
