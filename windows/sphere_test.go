package main

import (
	"math"
	"strings"
	"testing"
)

// Owner order 2026-11-10 (latest): the QUANT CORE tile carries a dot sphere
// that reads as three dimensional and turns clockwise, in place of the
// QUANT OF REHAN wordmark.

func TestSpherePointsAreAUniformShell(t *testing.T) {
	pts := spherePoints()
	if len(pts) < 200 {
		t.Fatalf("the globe is built from only %d dots", len(pts))
	}
	for _, p := range pts {
		r := math.Sqrt(p.x*p.x + p.y*p.y + p.z*p.z)
		if math.Abs(r-1) > 1e-9 {
			t.Fatalf("a dot sits at radius %.9f, not on the unit sphere", r)
		}
	}
}

func TestSphereTurnsClockwise(t *testing.T) {
	// The dot facing the viewer moves to its right as time runs, which is the
	// clockwise turn the owner asked for, and it comes towards the viewer.
	front := spherePoint{x: 0, y: 0, z: 1}
	sin, cos := math.Sincos(0.2)
	p := sphereRotate(front, sin, cos)
	if p.x <= 0 {
		t.Fatalf("the front of the globe moved left (x %.3f), so it turns anticlockwise", p.x)
	}
	if p.z >= 1 {
		t.Fatalf("the front of the globe moved away from the viewer (z %.3f)", p.z)
	}
	// A full turn returns the front dot to the front.
	sin, cos = math.Sincos(2 * math.Pi)
	back := sphereRotate(front, sin, cos)
	if math.Abs(back.x) > 1e-9 || math.Abs(back.z-1) > 1e-9 {
		t.Fatalf("a full turn left the front dot at %.3f, %.3f", back.x, back.z)
	}
}

func TestSphereDrawsShadedDots(t *testing.T) {
	a := demoApp(t, 100, 40)
	c := NewCanvas(40, 14, RGB{})
	drawSphere(c, 1, 1, 38, 12, 3.0, true, a.th)
	dots, inks := 0, map[RGB]bool{}
	for _, ce := range c.Cells {
		if ce.Ch >= 0x2800 && ce.Ch <= 0x28ff {
			dots++
			inks[ce.FG] = true
		}
		if ce.Ch == ' ' {
			continue
		}
		if x := ce.Ch; x < 0x2800 || x > 0x28ff {
			t.Fatalf("the globe painted %q, which is not a dot", string(ce.Ch))
		}
	}
	if dots < 30 {
		t.Fatalf("the globe drew only %d dot cells", dots)
	}
	if len(inks) < 2 {
		t.Fatalf("the globe drew %d ink(s), so it has no depth shading", len(inks))
	}
}

func TestSphereStaysInsideItsTile(t *testing.T) {
	a := demoApp(t, 100, 40)
	c := NewCanvas(30, 10, RGB{})
	drawSphere(c, 2, 1, 26, 8, 5.0, true, a.th)
	for y := 0; y < c.H; y++ {
		for x := 0; x < c.W; x++ {
			ce := c.Cells[y*c.W+x]
			if ce.Ch == ' ' {
				continue
			}
			if x < 2 || x >= 28 || y < 1 || y >= 9 {
				t.Fatalf("the globe painted outside its tile at %d,%d", x, y)
			}
		}
	}
}

func TestHomeCoreTileIsTheSphereAndNotTheWordmark(t *testing.T) {
	a := demoApp(t, 158, 41)
	a.screen = scrHome
	s := plain(a)
	if strings.Contains(s, "QUANT OF REHAN") {
		t.Errorf("the wordmark is still drawn in the QUANT CORE tile")
	}
	dots := 0
	for _, r := range s {
		if r >= 0x2800 && r <= 0x28ff {
			dots++
		}
	}
	if dots < 20 {
		t.Fatalf("the home screen carries only %d dot cells", dots)
	}
}
