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

// Owner order 2026-11-11: the middle of the orb must be full of dots, so the
// surface grid carries about twice the points it did in build 3.2.6.
func TestSphereGridIsDenseEnoughForTheMiddle(t *testing.T) {
	if n := len(spherePoints()); n < 1800 {
		t.Fatalf("the globe draws %d dots, too few for a solid ball", n)
	}
}
