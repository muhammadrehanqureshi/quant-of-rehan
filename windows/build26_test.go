package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-15: the SECTORS selection moves with UP and DOWN, and
// the tile names those keys in the owner's own words.
func TestSectorsMoveWithUpAndDown(t *testing.T) {
	a := demoApp(t, 122, 36)
	a.screen = scrScanner
	s := plain(a)
	if !strings.Contains(s, `Press "DOWN & UP ARROW KEYS" to move`) {
		t.Fatalf("the SECTORS instruction is missing:\n%s", s)
	}
	before := a.sectorChoice
	a.onKey(Key{Kind: KDown})
	if a.sectorChoice == before {
		t.Fatalf("DOWN must move the sector selection from %d", before)
	}
	moved := a.sectorChoice
	a.onKey(Key{Kind: KUp})
	if a.sectorChoice != before {
		t.Fatalf("UP must bring the selection back to %d, got %d", before, a.sectorChoice)
	}
	a.onKey(Key{Kind: KDown})
	a.onKey(Key{Kind: KEnter})
	if !a.sectorOpen || a.sectorChoice != moved {
		t.Fatalf("ENTER must open the selected sector: open %v choice %d want %d",
			a.sectorOpen, a.sectorChoice, moved)
	}
}

// Owner order 2026-11-15: CUSTOM SCRIPS OF VOLUME moves with LEFT and RIGHT
// only. UP and DOWN belong to the SECTORS tile, and ENTER opens the sort the
// LEFT and RIGHT keys reached.
func TestCustomScripsMoveWithLeftAndRightOnly(t *testing.T) {
	a := demoApp(t, 122, 36)
	a.screen = scrScanner
	a.scanChoice, a.scanCursor, a.scanFocus = 0, 0, 0
	a.onKey(Key{Kind: KDown})
	if a.scanChoice != 0 || a.scanCursor != 0 {
		t.Fatalf("DOWN must not move CUSTOM SCRIPS: choice %d cursor %d", a.scanChoice, a.scanCursor)
	}
	a.onKey(Key{Kind: KUp})
	if a.scanChoice != 0 || a.scanCursor != 0 {
		t.Fatalf("UP must not move CUSTOM SCRIPS: choice %d cursor %d", a.scanChoice, a.scanCursor)
	}
	a.onKey(Key{Kind: KRight})
	if a.scanChoice != 0 || a.scanCursor != 1 {
		t.Fatalf("RIGHT must move the sort cursor only: choice %d cursor %d", a.scanChoice, a.scanCursor)
	}
	a.onKey(Key{Kind: KEnter})
	if a.scanChoice != 2 {
		t.Fatalf("ENTER must open the second sort: %d", a.scanChoice)
	}
	a.onKey(Key{Kind: KLeft})
	if a.scanChoice != 2 || a.scanCursor != 0 {
		t.Fatalf("LEFT must move the cursor without closing the sort: choice %d cursor %d", a.scanChoice, a.scanCursor)
	}
	a.onKey(Key{Kind: KEnter})
	if a.scanChoice != 1 {
		t.Fatalf("ENTER must open the first sort: %d", a.scanChoice)
	}
}

// Owner order 2026-11-16: every B, S, U and T field is followed by the same two
// cell gutter, and no label carries a leading space of its own.
func TestScannerValuesUseTheSameGutter(t *testing.T) {
	a := demoApp(t, 90, 40)
	a.screen = scrScanner
	for _, choice := range []int{1, 2} {
		a.scanChoice = choice
		a.lvScan = listView{}
		rows := strings.Split(plain(a), "\n")
		n := 0
		for _, row := range rows {
			if !strings.Contains(row, "B=") || !strings.Contains(row, "S=") ||
				!strings.Contains(row, "U=") || !strings.Contains(row, "& T=") {
				continue
			}
			n++
			for _, want := range []string{"  S=", "  U=", "  &  T="} {
				if !strings.Contains(row, want) {
					t.Errorf("sort %d is missing the two cell gutter %q: %q", choice, want, row)
				}
			}
			for _, label := range []string{"B=", "S=", "U=", "&  T="} {
				at := strings.Index(row, label)
				if at >= 0 && strings.HasPrefix(row[at+len(label):], " ") {
					t.Errorf("sort %d writes a gap after %s: %q", choice, label, row)
				}
			}
		}
		if n != 3 {
			t.Fatalf("sort %d drew %d value rows, want three:\n%s", choice, n, strings.Join(rows, "\n"))
		}
	}
}
