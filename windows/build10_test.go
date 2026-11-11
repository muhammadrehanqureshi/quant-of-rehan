package main

import (
	"math"
	"strings"
	"testing"
)

// Owner order 2026-11-11: one diamond per row. The cursor and the chosen row
// were both drawn with a diamond, so the selected theme and the chosen sort
// carried two blue diamonds side by side.
func TestOnlyOneDiamondOnTheCursorRow(t *testing.T) {
	a := demoApp(t, 140, 40)
	a.screen = scrSettings
	a.setCursor = settingsItems + a.cfg.Theme
	c := NewCanvas(120, 40, a.th.Panel)
	a.drawSettings(c, 0, 0, 120, 40)
	name := themes[a.cfg.Theme].Name
	found := false
	for _, row := range c.PlainRows() {
		if !strings.Contains(row, name) {
			continue
		}
		found = true
		if n := strings.Count(row, "◆"); n != 1 {
			t.Fatalf("the selected theme row carries %d diamonds: %q", n, row)
		}
	}
	if !found {
		t.Fatalf("no row carries the selected theme %q", name)
	}

	a.screen, a.scanChoice, a.scanCursor = scrScanner, 1, 0
	c = NewCanvas(122, 34, a.th.Panel)
	a.drawScanner(c, 0, 0, 122, 26)
	// The chosen sort is also the list's heading lower down, and that heading
	// carries no diamond. The menu row is the one with the cursor, so it must
	// carry exactly one.
	menuRows := 0
	for _, row := range c.PlainRows() {
		if !strings.Contains(row, scanChoices[0]) || !strings.Contains(row, "◆") {
			continue
		}
		menuRows++
		if n := strings.Count(row, "◆"); n != 1 {
			t.Fatalf("the chosen sort row carries %d diamonds: %q", n, row)
		}
	}
	if menuRows != 1 {
		t.Fatalf("the chosen sort menu row was drawn %d times", menuRows)
	}
}

// Owner order 2026-11-11: the middle of the orb must be full of dots, so the
// surface grid carries about twice the points it did in build 3.2.6.
func TestSphereGridIsDenseEnoughForTheMiddle(t *testing.T) {
	if n := len(spherePoints()); n < 1800 {
		t.Fatalf("the globe draws %d dots, too few for a solid ball", n)
	}
}

// sphereLuma is a colour's brightness, used only to compare two shades.
func sphereLuma(c RGB) float64 {
	return 0.2126*float64(c.R) + 0.7152*float64(c.G) + 0.0722*float64(c.B)
}

// Owner order 2026-11-11 (eighth pass): the doubled grid had flattened the
// globe into one bright mesh, so the ink follows a lamp at the upper left. The
// lit side must be brighter than the shadow side and the front brighter than
// the back, and one frame must carry enough shades to be a gradient.
func TestSphereIsLitFromTheUpperLeft(t *testing.T) {
	th := themeAt(0)
	bright, dark := th.Good, mix(th.Good, th.Panel, 0.62)
	s := math.Sqrt(0.5)
	lit := sphereInk(spherePoint{x: -0.5, y: -0.5, z: s}, bright, dark)
	shadow := sphereInk(spherePoint{x: 0.5, y: 0.5, z: s}, bright, dark)
	if sphereLuma(lit) <= sphereLuma(shadow) {
		t.Fatalf("the upper left (%.0f) is not brighter than the lower right (%.0f)",
			sphereLuma(lit), sphereLuma(shadow))
	}
	front := sphereInk(spherePoint{z: 1}, bright, dark)
	back := sphereInk(spherePoint{z: -1}, bright, dark)
	if sphereLuma(front) <= sphereLuma(back) {
		t.Fatalf("the front (%.0f) is not brighter than the back (%.0f)",
			sphereLuma(front), sphereLuma(back))
	}

	a := demoApp(t, 100, 40)
	c := NewCanvas(40, 14, RGB{})
	drawSphere(c, 1, 1, 38, 12, 3.0, true, a.th)
	inks := map[RGB]bool{}
	for _, ce := range c.Cells {
		if ce.Ch >= 0x2800 && ce.Ch <= 0x28ff {
			inks[ce.FG] = true
		}
	}
	if len(inks) < 5 {
		t.Fatalf("the globe drew %d shade(s), too few for a lit ball", len(inks))
	}
}
