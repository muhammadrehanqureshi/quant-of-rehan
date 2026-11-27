package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-27 (build 185): "these are the changes for the windows
// build, turn the themes options white. on the SECTORS tile, make the alignment
// of the values of PKR same as the alignment of PKR and PKR's values like the
// CUSTOM SCRIPS OF VOLUME tile."

// The THEMES names take the page's white value ink, whatever the palette is.
func TestBuild185TheThemeNamesAreWhite(t *testing.T) {
	a := demoApp(t, 122, 36)
	a.screen = scrSettings
	c := a.render()
	for _, th := range themes {
		y, x := findCells(c, th.Name)
		if y < 0 {
			t.Fatalf("the THEMES tile is missing %q", th.Name)
		}
		for _, r := range th.Name {
			if r == ' ' {
				x++
				continue
			}
			if fg := c.Cells[y*c.W+x].FG; fg != inkWhite {
				t.Fatalf("%q stands in %v, want the page's white %v", th.Name, fg, inkWhite)
			}
			x++
		}
	}
}

// drawQuoteLeft keeps the word hard against its figure, the way CUSTOM SCRIPS OF
// VOLUME reads, where drawQuote keeps the price at the end of its own field.
func TestBuild185TheSectorsQuoteRuleIsCustomScripsRule(t *testing.T) {
	a := demoApp(t, 122, 36)
	pct := 1.5
	left := NewCanvas(40, 3, a.th.BG)
	a.drawQuoteLeft(left, 4, 1, 8, "42.94", &pct, "")
	field := NewCanvas(40, 3, a.th.BG)
	a.drawQuote(field, 4, 1, 8, "42.94", &pct, "")
	if got := left.Cells[1*left.W+8].Ch; got != '4' {
		t.Fatalf("drawQuoteLeft put %q on the cell after the word's space, want the price's first digit", got)
	}
	if got := field.Cells[1*field.W+8].Ch; got == '4' {
		t.Fatalf("drawQuote put %q on the cell after the word's space, want the price still in its field", got)
	}
}

// The opened SECTORS list places PKR and its price as CUSTOM SCRIPS OF VOLUME
// places them: the word, one space, and the price's own first cell.
func TestBuild185TheSectorsListPlacesPKRLikeCustomScrips(t *testing.T) {
	a := demoApp(t, 122, 36)
	a.screen = scrScanner
	a.sectors = nil
	clickText(t, a, "CEMENT")
	if !a.sectorOpen {
		t.Fatal("clicking a sector must open it")
	}
	rows := a.render().PlainRows()
	found := 0
	for _, row := range rows {
		i := strings.Index(row, "PKR")
		if i < 0 || !(strings.Contains(row, "CHRL") || strings.Contains(row, "ECHO")) {
			continue
		}
		found++
		if rest := []rune(row[i+3:]); len(rest) < 2 || rest[0] != ' ' || rest[1] == ' ' {
			t.Fatalf("the SECTORS row holds %q after PKR, want one space and the price", row[i:])
		}
	}
	if found == 0 {
		t.Fatalf("the opened sector lists no PKR row:\n%s", strings.Join(rows, "\n"))
	}
}
