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

// Owner order 2026-11-15: every sort uses one fixed set of B, S, U and T
// columns, even in a window that used to fall back to packed values.
func TestScannerValuesShareColumnsAtEveryWidth(t *testing.T) {
	a := demoApp(t, 90, 40)
	a.screen = scrScanner
	for _, choice := range []int{1, 2} {
		a.scanChoice = choice
		a.lvScan = listView{}
		rows := strings.Split(plain(a), "\n")
		var b, s, u, tot []int
		for _, row := range rows {
			if !strings.Contains(row, "B=") || !strings.Contains(row, "S=") ||
				!strings.Contains(row, "U=") || !strings.Contains(row, "& T=") {
				continue
			}
			b = append(b, strings.Index(row, "B="))
			s = append(s, strings.Index(row, "S="))
			u = append(u, strings.Index(row, "U="))
			tot = append(tot, strings.Index(row, "& T="))
		}
		if len(b) != 3 {
			t.Fatalf("sort %d drew %d value rows, want three:\n%s", choice, len(b), strings.Join(rows, "\n"))
		}
		for i := 1; i < 3; i++ {
			if b[i] != b[0] || s[i] != s[0] || u[i] != u[0] || tot[i] != tot[0] {
				t.Fatalf("sort %d row %d columns B,S,U,T = %d,%d,%d,%d, want %d,%d,%d,%d",
					choice, i, b[i], s[i], u[i], tot[i], b[0], s[0], u[0], tot[0])
			}
		}
	}
}
