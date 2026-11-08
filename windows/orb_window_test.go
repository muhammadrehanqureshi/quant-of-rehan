package main

import (
	"testing"
	"time"
)

// Owner order 2026-11-08: the quant mark is green from 08:55 to 17:00 on a
// market day and red at every other time. The PSX week is Monday to Friday; a
// holiday the relay names today is red too.
func TestOrbGreenWindow(t *testing.T) {
	a := demoApp(t, 80, 26)
	a.relay = nil
	a.market = NewMarket()
	cases := []struct {
		name string
		at   time.Time
		want bool
	}{
		{"monday before 08:55", time.Date(2026, time.November, 9, 8, 54, 0, 0, pkt), false},
		{"monday at 08:55", time.Date(2026, time.November, 9, 8, 55, 0, 0, pkt), true},
		{"monday midday", time.Date(2026, time.November, 9, 12, 0, 0, 0, pkt), true},
		{"monday at 16:59", time.Date(2026, time.November, 9, 16, 59, 0, 0, pkt), true},
		{"monday at 17:00", time.Date(2026, time.November, 9, 17, 0, 0, 0, pkt), false},
		{"saturday midday", time.Date(2026, time.November, 7, 12, 0, 0, 0, pkt), false},
		{"sunday midday", time.Date(2026, time.November, 8, 12, 0, 0, 0, pkt), false},
	}
	for _, c := range cases {
		a.now = c.at
		if got := a.orbGreenWindow(); got != c.want {
			t.Errorf("%s: orbGreenWindow = %v, want %v", c.name, got, c.want)
		}
	}
	// A holiday is a weekday the relay reports closed; it is red even inside
	// the clock window. The next trading day is green again.
	a.market = &Market{Phase: "CLOSED", Date: "2026-11-09", TradingDay: false}
	a.now = time.Date(2026, time.November, 9, 12, 0, 0, 0, pkt)
	if a.orbGreenWindow() {
		t.Error("a holiday must be red inside the clock window")
	}
	a.market.TradingDay = true
	if !a.orbGreenWindow() {
		t.Error("a trading day must be green inside the clock window")
	}
}

func TestOrbInkFollowsTheWindow(t *testing.T) {
	green := hudInk(0.5, OrbBurning, true)
	red := hudInk(0.5, OrbBurning, false)
	if green.G < 150 || green.G <= green.R {
		t.Errorf("inside the window the ink is %v, not green", green)
	}
	if red.R < 150 || red.R <= red.G {
		t.Errorf("outside the window the ink is %v, not red", red)
	}
}

func TestOrbDrawsRedOutsideTheWindow(t *testing.T) {
	th := themeAt(0)
	c := NewCanvas(38, 14, th.Panel)
	drawOrb(c, 0, 0, 38, 14, 2, OrbBurning, false, th)
	for _, ce := range c.Cells {
		if ce.Ch >= 0x2800 && ce.Ch <= 0x28ff && ce.FG.R >= 150 && ce.FG.R > ce.FG.G+40 {
			return
		}
	}
	t.Error("outside the window the dial must paint red dots")
}
