package main

import (
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

// Owner order 2026-11-12: the globe carries fewer dots, evenly spaced over the
// sphere. The Fibonacci lattice replaces the latitude rings that looked
// inconsistent at terminal size.
func TestSphereKeepsAnEvenDotGrid(t *testing.T) {
	n := len(spherePoints())
	if n < 850 || n > 950 {
		t.Fatalf("the globe draws %d dots, want the 900 dot even lattice", n)
	}
}

// sphereLuma is a colour's brightness, used only to compare two shades.
func sphereLuma(c RGB) float64 {
	return 0.2126*float64(c.R) + 0.7152*float64(c.G) + 0.0722*float64(c.B)
}

// Owner order 2026-11-11 (eleventh pass): the three depth bands are back. The
// near side is the brightest, the far side the dimmest, and one frame carries
// the banding that gives the globe its depth.
func TestSphereShadesByDepth(t *testing.T) {
	th := themeAt(0)
	near, mid, far := th.Good, mix(th.Good, th.Soft, 0.45), mix(th.Good, th.Soft, 0.78)
	if got := sphereInk(1, near, mid, far); got != near {
		t.Fatalf("the front of the globe is not the bright band: %v", got)
	}
	if got := sphereInk(0, near, mid, far); got != mid {
		t.Fatalf("the middle of the globe is not the middle band: %v", got)
	}
	if got := sphereInk(-1, near, mid, far); got != far {
		t.Fatalf("the back of the globe is not the dim band: %v", got)
	}
	if !(sphereLuma(near) > sphereLuma(mid) && sphereLuma(mid) > sphereLuma(far)) {
		t.Fatal("the three bands do not step down from the front to the back")
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
	if len(inks) < 2 {
		t.Fatalf("the globe drew %d ink(s), so it has no depth shading", len(inks))
	}
}
