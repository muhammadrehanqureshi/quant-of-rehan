package main

import (
	"math"
	"sort"
)

// Owner order 2026-11-10 (latest): "on the QUANT CORE tile, I want you to have
// a circle that would look like 3D sphere and it will be rotating clock wise,
// remove the QUANT OF REHAN from the QUANT CORE for now, and make this 3D
// sphere in the same dots pattern."
//
// The mark is a globe of dots: a latitude and longitude grid on a unit sphere,
// turned about the vertical axis and projected with a small perspective term,
// so the meridians crowd together towards the rim the way a real globe's do.
// Light is carried by the ink: the surface is lit from the upper left, so the
// lit side is bright, the terminator steps down and the far side and the rim
// are dim. That light is what makes the disc read as a sphere instead of a flat
// circle. It is drawn as Braille dots, the same dot pattern the rest of the HUD
// uses, so no block glyph is painted and the panel's own background is the only
// background.
//
// Owner order 2026-11-11 (eighth pass): "this one doesn't look like the 3D
// sphere". The doubled grid had made every cell the same bright ink, so the ink
// now follows the surface's own light: a lamp at the upper left, a soft
// terminator and a dark rim. That light is what carries the ball at any dot
// count, instead of three flat depth bands.

const (
	// sphereTurnSeconds is one full clockwise turn of the globe. Owner order
	// 2026-11-11: the turn is half the speed of build 3.2.3, so the period is
	// doubled and one turn now takes about 60.1 seconds.
	sphereTurnSeconds = 12.0 / 0.85 / 0.85 / 0.85 / 0.85 / 0.85 / 0.90 * 2
	// Owner order 2026-11-11: the QUANT CORE globe is the mark the tile draws,
	// not the ring, so its own size carries the fifteen percent cut.
	sphereSizeScale = 0.85
	// sphereLatStep and sphereLonStep are the grid's spacing in degrees.
	// Owner order 2026-11-11: the middle of the disc looked empty, so the grid
	// is doubled: both steps shrink by 0.70, which puts about twice as many dots
	// on the surface, the front face included. The lit shade below keeps that
	// denser surface reading as a ball rather than an even mesh.
	sphereLatStep = 11.25 * 0.9129 * 0.9325 * 0.9129 * 0.9129 * 0.9129 * 0.9129 * 0.70
	sphereLonStep = 9.0 * 0.9129 * 0.9325 * 0.9129 * 0.9129 * 0.9129 * 0.9129 * 0.70
	// spherePerspective is how much the nearer half of the globe grows.
	spherePerspective = 0.18
)

// sphereDot is the bit each dot of a Braille cell carries, indexed by its dot
// row and then its dot column.
var sphereDot = [4][2]rune{{0x01, 0x08}, {0x02, 0x10}, {0x04, 0x20}, {0x40, 0x80}}

// spherePoint is one dot of the grid: x to the right, y down, z towards the
// viewer, all on the unit sphere.
type spherePoint struct{ x, y, z float64 }

// spherePoints is the grid the globe is built from. Every ring of latitude
// carries as many meridians as its own circumference can hold, so the dots
// stand at an even spacing over the whole surface and the grid closes up
// towards the poles exactly as a real meridian net does.
func spherePoints() []spherePoint {
	var pts []spherePoint
	for lat := -90 + sphereLatStep; lat <= 90-sphereLatStep+1e-9; lat += sphereLatStep {
		rad := lat * math.Pi / 180
		ring := math.Cos(rad)
		height := math.Sin(rad)
		n := int(math.Round(360 * ring / sphereLonStep))
		if n < 3 {
			n = 3
		}
		for i := 0; i < n; i++ {
			lon := 2 * math.Pi * float64(i) / float64(n)
			pts = append(pts, spherePoint{
				x: ring * math.Sin(lon),
				y: -height,
				z: ring * math.Cos(lon),
			})
		}
	}
	return pts
}

// sphereRotate turns a point about the vertical axis by theta radians, given
// its sine and cosine. A positive theta sends the point that faces the viewer
// to its right, which is the clockwise turn the owner asked for.
func sphereRotate(p spherePoint, sin, cos float64) spherePoint {
	return spherePoint{
		x: p.x*cos + p.z*sin,
		y: p.y,
		z: -p.x*sin + p.z*cos,
	}
}

// sphereLight is the direction the globe is lit from: the upper left and in
// front, normalised, in the same axes as spherePoint (y down, z towards the
// viewer). A fixed lamp is right for a turning globe: the surface turns through
// the light while the light itself stays where it is.
var sphereLight = sphereLightDirection()

func sphereLightDirection() spherePoint {
	const x, y, z = -0.28, -0.38, 0.88
	n := math.Sqrt(x*x + y*y + z*z)
	return spherePoint{x: x / n, y: y / n, z: z / n}
}

// sphereShade is how much light a surface point catches: the lambert term of
// its normal against sphereLight, lifted by an ambient floor so the shadow side
// and the rim are dim ink rather than empty space.
func sphereShade(p spherePoint) float64 {
	l := p.x*sphereLight.x + p.y*sphereLight.y + p.z*sphereLight.z
	if l < 0 {
		l = 0
	}
	return 0.30 + 0.70*l
}

// sphereInk blends the theme's dark ink into its bright ink by the shade at p,
// so the disc carries a lit side, a soft terminator and a dark rim.
func sphereInk(p spherePoint, bright, dark RGB) RGB {
	return mix(dark, bright, sphereShade(p))
}

// drawSphere paints the globe into the rectangle (x0,y0,w,h) of cells, at t
// seconds of motion. green selects the market's own green, as the rest of the
// HUD does; outside the market window the same globe is drawn red.
func drawSphere(c *Canvas, x0, y0, w, h int, t float64, green bool, th *Theme) {
	if w < 6 || h < 3 {
		return
	}
	cols, rows := w*2, h*4
	cx, cy := float64(cols-1)/2.0, float64(rows-1)/2.0
	radius := (math.Min(float64(cols)/2.0, float64(rows)/2.0) - 1) * sphereSizeScale
	if radius < 4 {
		return
	}
	bright, dark := th.Good, mix(th.Good, th.Panel, 0.62)
	if !green {
		bright, dark = th.Bad, mix(th.Bad, th.Panel, 0.62)
	}
	sin, cos := math.Sincos(t * 2 * math.Pi / sphereTurnSeconds)
	dots := spherePoints()
	for i := range dots {
		dots[i] = sphereRotate(dots[i], sin, cos)
	}
	// Far side first, so a near dot that lands on the same cell wins it.
	sort.SliceStable(dots, func(i, j int) bool { return dots[i].z < dots[j].z })
	bits := make([]rune, w*h)
	ink := make([]RGB, w*h)
	for _, p := range dots {
		scale := 1.0 / (1.0 - spherePerspective*p.z)
		px := cx + p.x*radius*scale
		py := cy + p.y*radius*scale
		dx, dy := int(math.Round(px)), int(math.Round(py))
		cc, rr := dx/2, dy/4
		if cc < 0 || rr < 0 || cc >= w || rr >= h {
			continue
		}
		cell := rr*w + cc
		bits[cell] |= sphereDot[dy&3][dx&1]
		ink[cell] = sphereInk(p, bright, dark)
	}
	for i, b := range bits {
		if b == 0 {
			continue
		}
		c.Put(x0+i%w, y0+i/w, rune(0x2800)+b, ink[i], false)
	}
}
