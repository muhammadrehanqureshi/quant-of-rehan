package main

import (
	"testing"
	"time"
)

// Owner order 2026-11-08 (build 27): the quant mark is the refined dial from
// windows/assets/orb-online-green-refined.gif in the market's own colour.
// Green through the pre-market, the trading session and the post-market; red
// at every other hour and day.
func TestOrbInkIsGreenInTheMarketWindowAndRedOutsideIt(t *testing.T) {
	for _, tone := range []float64{0, 0.35, 0.7, 1} {
		green := hudInk(tone, true)
		if green.G <= green.R || green.G < 150 {
			t.Errorf("tone %.2f paints %v, which is not the owner's green", tone, green)
		}
		red := hudInk(tone, false)
		if red.R <= red.G || red.R < 200 {
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
			if green && (ce.FG.G < 150 || ce.FG.G <= ce.FG.R) {
				t.Fatalf("a green dot paints %v", ce.FG)
			}
			if !green && (ce.FG.R < 200 || ce.FG.R <= ce.FG.G) {
				t.Fatalf("a red dot paints %v", ce.FG)
			}
		}
		if lit == 0 {
			t.Fatalf("green=%v: the dial painted no dots at all", green)
		}
	}
}

func TestOrbIsGreenOnlyInThePreOpenPostMarket(t *testing.T) {
	cases := []struct {
		name string
		at   time.Time
		want bool
	}{
		{"pre-market", time.Date(2026, 11, 2, 9, 15, 0, 0, pkt), true},
		{"session", time.Date(2026, 11, 2, 10, 0, 0, 0, pkt), true},
		{"post-market", time.Date(2026, 11, 2, 15, 40, 0, 0, pkt), true},
		{"break", time.Date(2026, 11, 6, 12, 0, 0, 0, pkt), false},
		{"closed", time.Date(2026, 11, 8, 12, 0, 0, 0, pkt), false},
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
