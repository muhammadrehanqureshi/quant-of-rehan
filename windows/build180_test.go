package main

import (
	"strings"
	"testing"
	"time"
)

// findCells returns where a word stands on the canvas, or -1, -1.
func findCells(c *Canvas, word string) (int, int) {
	target := []rune(word)
	for y := 0; y < c.H; y++ {
		for x := 0; x+len(target) <= c.W; x++ {
			hit := true
			for i, r := range target {
				if c.Cells[y*c.W+x+i].Ch != r {
					hit = false
					break
				}
			}
			if hit {
				return y, x
			}
		}
	}
	return -1, -1
}

// Owner order 2026-11-27: on SETTINGS everything on the left hand side wears
// the ink of the small print beside the switches, and every value on the right
// hand side is white.
func TestBuild180SettingsReadsLeftSoftAndRightWhite(t *testing.T) {
	a := demoApp(t, 140, 44)
	a.screen = scrSettings
	c := a.render()
	y, x := findCells(c, "NOTIFICATIONS")
	if y < 0 {
		t.Fatalf("the SETTINGS tile has no NOTIFICATIONS row:\n%s",
			strings.Join(c.PlainRows(), "\n"))
	}
	if got := c.Cells[y*c.W+x].FG; got != a.th.Soft {
		t.Fatalf("the NOTIFICATIONS label wears %v, want the small print ink %v",
			got, a.th.Soft)
	}
	// Owner order 2026-11-27 (build 183): the switch's ON is green now, so the
	// white law is checked where it still holds, on the sentence after it.
	dy, dx := findCells(c, "Windows pop-ups")
	if dy < 0 {
		t.Fatalf("the switch's small print is gone")
	}
	if got := c.Cells[dy*c.W+dx].FG; got != inkWhite {
		t.Fatalf("the small print wears %v, want white %v", got, inkWhite)
	}
}

// Owner order 2026-11-27: the THEMES names take the left hand ink too, and the
// theme that is ON is the tile's one bold name.
func TestBuild180ThemesTakeTheLeftInkAndTheChosenIsBold(t *testing.T) {
	a := demoApp(t, 140, 44)
	a.screen = scrSettings
	c := a.render()
	name := themes[a.cfg.Theme].Name
	y, x := findCells(c, name)
	if y < 0 {
		t.Fatalf("the theme %q is not on the page", name)
	}
	if got := c.Cells[y*c.W+x].FG; got != a.th.Soft {
		t.Fatalf("the chosen theme wears %v, want the left hand ink %v", got, a.th.Soft)
	}
	if !c.Cells[y*c.W+x].Bold {
		t.Fatalf("the theme that is ON is not bold: %q", strings.Join(c.PlainRows(), "\n"))
	}
	other := themes[(a.cfg.Theme+1)%len(themes)].Name
	oy, ox := findCells(c, other)
	if oy < 0 {
		t.Fatalf("the theme %q is not on the page", other)
	}
	if c.Cells[oy*c.W+ox].Bold {
		t.Fatalf("the theme that is OFF is bold as well: %q", other)
	}
	if got := c.Cells[oy*c.W+ox].FG; got != a.th.Soft {
		t.Fatalf("the off theme wears %v, want the left hand ink %v", got, a.th.Soft)
	}
}

// Owner order 2026-11-27: on TELEMETRY the word SYNCED is green and bold.
func TestBuild180SyncedIsGreenAndBold(t *testing.T) {
	a := demoApp(t, 122, 40)
	a.link, a.checking = true, false
	a.rtt = 42 * time.Millisecond
	a.now = time.Date(2026, 11, 27, 11, 0, 0, 0, pkt)
	a.lastMarketOK = a.now.Add(-5 * time.Second)
	c := a.render()
	y, x := findCells(c, "SYNCED")
	if y < 0 {
		t.Fatalf("the LINK line carries no SYNCED:\n%s", strings.Join(c.PlainRows(), "\n"))
	}
	cell := c.Cells[y*c.W+x]
	if cell.FG != a.th.Good {
		t.Fatalf("SYNCED wears %v, want the green %v", cell.FG, a.th.Good)
	}
	if !cell.Bold {
		t.Fatalf("SYNCED is not bold")
	}
}

// Owner order 2026-11-27: the values in front of BUYING NOW are as bold as the
// names on that line.
func TestBuild180BuyingNowValuesAreBold(t *testing.T) {
	a := busyApp(t, 158, 41, 3)
	c := a.render()
	y, x := findCells(c, "BUYING NOW")
	if y < 0 {
		t.Fatalf("the KSE100 tile carries no BUYING NOW line:\n%s",
			strings.Join(c.PlainRows(), "\n"))
	}
	// The names wear the hot ink and the values the buy ink, so the ink is
	// what tells a value from the scrip's own digits.
	bold, found := false, false
	for i := x + len("BUYING NOW"); i < c.W; i++ {
		cell := c.Cells[y*c.W+i]
		if cell.FG != a.th.Good {
			continue
		}
		found = true
		if cell.Bold {
			bold = true
			break
		}
	}
	if !found {
		t.Fatalf("the BUYING NOW line carries no value")
	}
	if !bold {
		t.Fatalf("the BUYING NOW values are not bold")
	}
}
