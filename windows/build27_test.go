package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-16: BIG ORDER SIZE is a share quantity, and the ALERTS
// boards list every stock above the 50k share floor.
func TestBuild115ShareThresholds(t *testing.T) {
	a := demoApp(t, 130, 34)
	a.screen = scrSettings
	if s := plain(a); !strings.Contains(s, "100k shares an order.") {
		t.Fatalf("SETTINGS does not name the share threshold:\n%s", s)
	}
	a.screen = scrAlerts
	s := plain(a)
	for _, want := range []string{"BIG BUYING NOW", "BIG SELLING NOW", "50k shares or above"} {
		if !strings.Contains(s, want) {
			t.Errorf("ALERTS is missing %q:\n%s", want, s)
		}
	}
	if strings.Contains(s, "PKR 1M or above orders") {
		t.Errorf("the old PKR board floor is still on screen:\n%s", s)
	}
}

// Owner order 2026-11-16: the calculator boxes fit their own words with exactly
// one blank cell on each side.
func TestBuild115CalculatorBoxesFitTheirWords(t *testing.T) {
	a := demoApp(t, 122, 36)
	a.screen = scrScanner
	a.calcOpen, a.calcField = true, 0
	c := a.render()
	for _, tc := range []struct {
		word string
		bg   RGB
	}{
		{"Enter price", mix(a.th.Panel, a.th.Accent, 0.3)},
		{"Enter qty", mix(a.th.Panel, a.th.Accent, 0.14)},
	} {
		found := false
		for y, row := range c.PlainRows() {
			x := strings.Index(row, tc.word)
			if x < 1 {
				continue
			}
			found = true
			at := func(px int) Cell { return c.Cells[y*c.W+px] }
			if at(x-1).BG != tc.bg || at(x+len(tc.word)).BG != tc.bg {
				t.Errorf("%q does not have one blank box cell on each side", tc.word)
			}
			if x >= 2 && at(x-2).BG == tc.bg {
				t.Errorf("%q has more than one blank box cell on its left", tc.word)
			}
			if x+len(tc.word)+1 < c.W && at(x+len(tc.word)+1).BG == tc.bg {
				t.Errorf("%q has more than one blank box cell on its right", tc.word)
			}
		}
		if !found {
			t.Fatalf("%q is not on the calculator tile", tc.word)
		}
	}
}
