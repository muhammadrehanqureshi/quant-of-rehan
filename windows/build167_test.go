package main

import (
	"strings"
	"testing"
	"unicode/utf8"
)

// Owner order 2026-11-24 (later): the WATCH LIST's footer sentence is one ink,
// so the word del is the same colour as the words around it.
func TestBuild167TheWatchFooterIsOneInk(t *testing.T) {
	a := demoApp(t, 158, 41)
	a.screen = scrWatch
	c := a.render()
	// The sentence is found cell by cell, so its own offset is exact whatever
	// the row string does with its edges.
	target := []rune(watchFooter)
	row, at := -1, -1
	for y := 0; y < c.H && row < 0; y++ {
		for x := 0; x+len(target) <= c.W; x++ {
			hit := true
			for i, r := range target {
				if c.Cells[y*c.W+x+i].Ch != r {
					hit = false
					break
				}
			}
			if hit {
				row, at = y, x
				break
			}
		}
	}
	if row < 0 {
		t.Fatalf("the WATCH LIST page carries no footer sentence:\n%s", strings.Join(c.PlainRows(), "\n"))
	}
	first := c.Cells[row*c.W+at].FG
	del := c.Cells[row*c.W+at+utf8.RuneCountInString(`Select a scrip and press `)].FG
	if del != first {
		t.Fatalf("the word del stands in %v, want the sentence's own ink %v", del, first)
	}
	if del == a.th.Warn {
		t.Fatalf("the word del still wears the warn ink %v", a.th.Warn)
	}
	if first != a.th.Soft {
		t.Fatalf("the footer stands in %v, want the soft ink %v", first, a.th.Soft)
	}
}
