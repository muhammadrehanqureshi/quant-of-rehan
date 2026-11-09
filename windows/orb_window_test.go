package main

import (
	"testing"
	"time"
)

// Owner order 2026-11-09 (build 29): the quant mark is the refined dial from
// windows/assets/orb-online-green-refined.gif in four green shades from 08:55
// to 16:00 Monday to Thursday and 08:55 to 17:00 on Friday, and in four red
// shades outside those windows.
func TestOrbInkIsGreenInTheMarketWindowAndRedOutsideIt(t *testing.T) {
	for _, tone := range []float64{0, 0.35, 0.7, 1} {
		green := hudInk(tone, true)
		if green.G <= green.R || green.G < 100 {
			t.Errorf("tone %.2f paints %v, which is not the owner's green", tone, green)
		}
		red := hudInk(tone, false)
		if red.R <= red.G || red.R < 120 {
			t.Errorf("tone %.2f paints %v, which is not the owner's red", tone, red)
		}
	}
}

func TestOrbDrawsTheMarketColour(t *testing.T) {
	th := themeAt(0)
	for _, green := range []bool{true, false} {
		c := NewCanvas(38, 14, th.Panel)
		drawOrb(c, 0, 0, 38, 14, 2, OrbBurning, green, th)
		lit := 0
		for _, ce := range c.Cells {
			if ce.Ch < 0x2800 || ce.Ch > 0x28ff {
				continue
			}
			lit++
			if green && (ce.FG.G < 100 || ce.FG.G <= ce.FG.R) {
				t.Fatalf("a green dot paints %v", ce.FG)
			}
			if !green && (ce.FG.R < 120 || ce.FG.R <= ce.FG.G) {
				t.Fatalf("a red dot paints %v", ce.FG)
			}
		}
		if lit == 0 {
			t.Fatalf("green=%v: the dial painted no dots at all", green)
		}
	}
}

func TestOrbIsGreenOnlyInTheOwnersClockWindow(t *testing.T) {
	cases := []struct {
		name string
		at   time.Time
		want bool
	}{
		{"monday before", time.Date(2026, 11, 2, 8, 54, 59, 0, pkt), false},
		{"monday start", time.Date(2026, 11, 2, 8, 55, 0, 0, pkt), true},
		{"monday pre-market", time.Date(2026, 11, 2, 9, 15, 0, 0, pkt), true},
		{"monday session", time.Date(2026, 11, 2, 10, 0, 0, 0, pkt), true},
		{"monday late", time.Date(2026, 11, 2, 15, 59, 59, 0, pkt), true},
		{"monday cut-off", time.Date(2026, 11, 2, 16, 0, 0, 0, pkt), false},
		{"monday evening", time.Date(2026, 11, 2, 20, 0, 0, 0, pkt), false},
		{"friday break", time.Date(2026, 11, 6, 12, 0, 0, 0, pkt), true},
		{"friday afternoon", time.Date(2026, 11, 6, 16, 40, 0, 0, pkt), true},
		{"friday cut-off", time.Date(2026, 11, 6, 17, 0, 0, 0, pkt), false},
		{"saturday", time.Date(2026, 11, 7, 12, 0, 0, 0, pkt), false},
		{"sunday", time.Date(2026, 11, 8, 12, 0, 0, 0, pkt), false},
	}
	for _, c := range cases {
		a := newTestApp(t)
		a.now = c.at
		a.marketOpen = false
		if got := a.orbGreen(); got != c.want {
			t.Errorf("%s: orbGreen() = %v, want %v", c.name, got, c.want)
		}
	}
}

// The four GIF brightness levels must produce four distinct shades in each
// palette, not one flat ink.
func TestOrbUsesFourShades(t *testing.T) {
	for _, green := range []bool{true, false} {
		seen := map[RGB]bool{}
		for _, tone := range []float64{0, 1.0 / 3.0, 2.0 / 3.0, 1} {
			seen[hudInk(tone, green)] = true
		}
		if len(seen) != 4 {
			t.Errorf("green=%v: %d distinct shades, want 4", green, len(seen))
		}
	}
}

// Build 29 grows the sampled matrix by ten percent. At a box with room, the
// draw size must be at least 60 by 55 dots instead of build 28's 55 by 50.
func TestOrbGrowsByTenPercent(t *testing.T) {
	w, h := orbDrawSize(38, 24)
	if w < 60 || h < 55 {
		t.Fatalf("orb draw size is %dx%d, want at least 60x55 (build 28 was 55x50)", w, h)
	}
}

// The dial must actually move: two animation times must not paint the same
// dot grid, or the "animated orb" order is unmet.
func TestOrbAnimates(t *testing.T) {
	a := orbGrid(38, 24, 0)
	b := orbGrid(38, 24, 1.3)
	if len(a.on) != len(b.on) {
		t.Fatal("the two grids have different sizes")
	}
	diff := 0
	for i := range a.on {
		if a.on[i] != b.on[i] || (a.on[i] && (a.tone[i]-b.tone[i] > 0.02 || b.tone[i]-a.tone[i] > 0.02)) {
			diff++
		}
	}
	if diff < 20 {
		t.Fatalf("the dial painted only %d changed dots between two frames", diff)
	}
}
