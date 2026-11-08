package main

import "testing"

// Owner order 2026-11-08 (build 25): the quant mark is the owner's refined
// green dial from windows/assets/orb-online-green-refined.gif at every hour and
// on every day. The red palette and the 08:55 to 17:00 colour rule are gone.
func TestOrbInkIsAlwaysTheOwnersGreen(t *testing.T) {
	for _, tone := range []float64{0, 0.35, 0.7, 1} {
		ink := hudInk(tone)
		if ink.G <= ink.R || ink.G < 150 {
			t.Errorf("tone %.2f paints %v, which is not the owner's green", tone, ink)
		}
	}
}

func TestOrbDrawsGreenDots(t *testing.T) {
	th := themeAt(0)
	c := NewCanvas(38, 14, th.Panel)
	drawOrb(c, 0, 0, 38, 14, 2, OrbBurning, th)
	lit := 0
	for _, ce := range c.Cells {
		if ce.Ch < 0x2800 || ce.Ch > 0x28ff {
			continue
		}
		lit++
		if ce.FG.G < 150 || ce.FG.G <= ce.FG.R {
			t.Fatalf("a dot paints %v, which is not the owner's green", ce.FG)
		}
	}
	if lit == 0 {
		t.Fatal("the dial painted no dots at all")
	}
}
