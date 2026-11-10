// Code generated from the reference picture by tools/ring_export.py. DO NOT EDIT.

package main

// ringCanvas is the side, in picture pixels, of the square every ring layer was cut on.
const ringCanvas = 2300.0

// ringReach is the radius, in picture pixels, of the outermost thin arcs: the ring is scaled so this reaches the edge of its box.
const ringReach = 1112.0

// ringLayerSpec describes one turning layer: where its centre is on the canvas, the radii it covers around that centre, and how fast it turns (degrees per second, clockwise is positive).
type ringLayerSpec struct {
	file      string
	cx, cy    float64
	rin, rout float64
	degPerSec float64
}

var ringLayerSpecs = [...]ringLayerSpec{
	{"layer0_small.png", 1152.50, 1151.50, 249.0, 343.0, -45.0},
	{"layer1_inner.png", 1158.00, 1162.00, 431.0, 531.0, 45.0},
	{"layer2_ticks.png", 1152.50, 1151.50, 559.0, 639.0, -45.0},
	{"layer3_thick.png", 1176.25, 1147.00, 627.0, 843.0, 22.5},
	{"layer4_rects.png", 1148.25, 1148.25, 842.0, 978.0, -22.5},
	{"layer5_arcs.png", 1148.00, 1149.00, 1025.0, 1113.0, 22.5},
}
