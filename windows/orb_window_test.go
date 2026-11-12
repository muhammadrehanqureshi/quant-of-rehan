package main

import (
	"testing"
	"time"
)

// Owner order 2026-11-10 (latest): the mark is the owner's own orb source, so
// its colours are the source's two palettes, untouched: three stops each, the
// dim line work, the main ink and the highlight.
func TestOrbPalettesAreTheSources(t *testing.T) {
	green := ringPalette(true)
	if green.dim != (RGB{6, 92, 56}) || green.mid != (RGB{22, 238, 134}) ||
		green.hot != (RGB{206, 255, 232}) || green.gain != 1 {
		t.Errorf("the green palette drifted from the source: %+v", green)
	}
	red := ringPalette(false)
	if red.dim != (RGB{86, 14, 22}) || red.mid != (RGB{255, 52, 66}) ||
		red.hot != (RGB{255, 196, 202}) || red.gain != 0.9 {
		t.Errorf("the red palette drifted from the source: %+v", red)
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
			if green && (ce.FG.G < 60 || ce.FG.G <= ce.FG.R) {
				t.Fatalf("a green dot paints %v", ce.FG)
			}
			if !green && (ce.FG.R < 60 || ce.FG.R <= ce.FG.G) {
				t.Fatalf("a red dot paints %v", ce.FG)
			}
		}
		if lit == 0 {
			t.Fatalf("green=%v: the dial painted no dots at all", green)
		}
	}
}

// Green turns, red rests: the source's own stateFor.
func TestOrbGreenTurnsAndRedRests(t *testing.T) {
	th := themeAt(0)
	diff := func(green bool, a, b float64) int {
		first, second := NewCanvas(38, 14, th.Panel), NewCanvas(38, 14, th.Panel)
		drawOrb(first, 0, 0, 38, 14, a, OrbBurning, green, th)
		drawOrb(second, 0, 0, 38, 14, b, OrbBurning, green, th)
		n := 0
		for i := range first.Cells {
			if first.Cells[i] != second.Cells[i] {
				n++
			}
		}
		return n
	}
	if diff(true, 0, 1.3) < 20 {
		t.Errorf("the green dial barely moved between two moments")
	}
	if diff(false, 0, 9.9) != 0 {
		t.Errorf("the red dial moved, and the source draws it still")
	}
}

func TestOrbIsGreenOnlyInTheOwnersClockWindow(t *testing.T) {
	cases := []struct {
		name string
		at   time.Time
		want bool
	}{
		{"monday before", time.Date(2026, 11, 2, 8, 54, 59, 0, pkt), false},
		{"monday start", time.Date(2026, 11, 2, 9, 0, 0, 0, pkt), true},
		{"monday pre-market", time.Date(2026, 11, 2, 9, 15, 0, 0, pkt), true},
		{"monday session", time.Date(2026, 11, 2, 10, 0, 0, 0, pkt), true},
		{"monday late", time.Date(2026, 11, 2, 15, 48, 59, 0, pkt), true},
		{"monday cut-off", time.Date(2026, 11, 2, 15, 49, 0, 0, pkt), false},
		{"monday evening", time.Date(2026, 11, 2, 20, 0, 0, 0, pkt), false},
		{"friday break", time.Date(2026, 11, 6, 12, 0, 0, 0, pkt), true},
		{"friday afternoon", time.Date(2026, 11, 6, 16, 48, 59, 0, pkt), true},
		{"friday cut-off", time.Date(2026, 11, 6, 16, 49, 0, 0, pkt), false},
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

// A PSX holiday is red all day, even inside the owner's green clock window.
func TestOrbIsRedOnAHoliday(t *testing.T) {
	a := newTestApp(t)
	a.now = time.Date(2026, 11, 9, 10, 0, 0, 0, pkt) // Iqbal Day, a Monday
	if a.orbGreen() {
		t.Fatal("9 November is a PSX holiday and must be red")
	}
}
