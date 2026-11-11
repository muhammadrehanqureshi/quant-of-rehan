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
// Depth is carried by the ink, a point on the near side bright, one on the far
// side dim, and the middle stepping between them, which is what makes the disc
// read as a sphere instead of a flat circle. It is drawn as Braille dots, the
// same dot pattern the rest of the HUD uses, so no block glyph is painted and
// the panel's own background is the only background.

const (
	// sphereTurnSeconds is one full clockwise turn of the globe. Owner order
	// 2026-11-11: the turn is half the speed of build 3.2.3, so the period is
	// doubled and one turn now takes about 60.1 seconds.
	sphereTurnSeconds = 12.0 / 0.85 / 0.85 / 0.85 / 0.85 / 0.85 / 0.90 * 2
	// Owner order 2026-11-11: the QUANT CORE globe is the mark the tile draws,
	// not the ring, so its own size carries the fifteen percent cut.
	sphereSizeScale = 0.85
	// sphereLatStep and sphereLonStep are the grid's spacing in degrees.
	// Owner order 2026-11-11 (eleventh pass): the globe goes back to the build
	// 3.2.6 grid, because the doubled grid filled every cell and flattened the
	// ball. The readable meridian net and the three depth bands are back.
	sphereLatStep = 11.25 * 0.9129 * 0.9325 * 0.9129 * 0.9129 * 0.9129 * 0.9129
	sphereLonStep = 9.0 * 0.9129 * 0.9325 * 0.9129 * 0.9129 * 0.9129 * 0.9129
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

// sphereInk is the ink for a point at depth z: the near side bright and the far
// side dim, so the disc carries its own shading.
func sphereInk(z float64, near, mid, far RGB) RGB {
	switch {
	case z >= 0.45:
		return near
	case z >= -0.1:
		return mid
	}
	return far
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
	near, mid, far := th.Good, mix(th.Good, th.Soft, 0.45), mix(th.Good, th.Soft, 0.78)
	if !green {
		near, mid, far = th.Bad, mix(th.Bad, th.Soft, 0.45), mix(th.Bad, th.Soft, 0.78)
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
		ink[cell] = sphereInk(p.z, near, mid, far)
	}
	for i, b := range bits {
		if b == 0 {
			continue
		}
		c.Put(x0+i%w, y0+i/w, rune(0x2800)+b, ink[i], false)
	}
}
