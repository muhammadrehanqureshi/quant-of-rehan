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
	a := newTestApp(t)
	for _, word := range []string{"Enter price", "Enter qty"} {
		c := NewCanvas(80, 1, a.th.Panel)
		a.inputRow(c, 0, 0, 40, "PRICE", "", word, false, true)
		row := c.PlainRows()[0]
		x := strings.Index(row, word)
		if x < 1 {
			t.Fatalf("%q is not in its input row: %q", word, row)
		}
		field := mix(a.th.Panel, a.th.Accent, 0.14)
		at := func(px int) Cell { return c.Cells[px] }
		if at(x-1).BG != field || at(x+len(word)).BG != field {
			t.Errorf("%q does not have one blank box cell on each side", word)
		}
		if x >= 2 && at(x-2).BG == field {
			t.Errorf("%q has more than one blank box cell on its left", word)
		}
		if x+len(word)+1 < c.W && at(x+len(word)+1).BG == field {
			t.Errorf("%q has more than one blank box cell on its right", word)
		}
	}
}
