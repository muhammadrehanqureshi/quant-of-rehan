package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-27, after two rejected builds: the banner is the ligature
// he named, the one character U+FDFD, and it "should take about 40% of the
// screen". These tests hold both halves of that: the character, and the size.
func TestTheBannerIsTheLigatureAndNothingElse(t *testing.T) {
	if basmalaBanner != "\uFDFD" {
		t.Fatalf("the banner is %q, want the one ligature character U+FDFD", basmalaBanner)
	}
	if n := runeLen(basmalaBanner); n != 1 {
		t.Fatalf("the banner is %d characters, want the single ligature", n)
	}
	for _, r := range basmalaBanner {
		if r != 0xFDFD {
			t.Fatalf("the banner carries %U, want U+FDFD", r)
		}
	}
}

// syntheticLigature stands in for the glyph Windows would draw, so the size law
// is checked on every machine without asking a text engine for a font.
func syntheticLigature(w, h int) ligatureMask {
	m := ligatureMask{W: w, H: h, Ink: make([]uint8, w*h)}
	for y := h / 4; y < 3*h/4; y++ {
		for x := 0; x < w; x++ {
			if (x/8)%2 == 0 {
				m.Ink[y*w+x] = 255
			}
		}
	}
	return m
}

func withLigatureGlyph(t *testing.T, m ligatureMask) {
	t.Helper()
	old := ligatureGlyph
	ligatureGlyph = func() (ligatureMask, bool) { return m, true }
	t.Cleanup(func() { ligatureGlyph = old })
}

// Owner order 2026-11-27: "make bigger, the banner should take about 40% of the
// screen." The mark fills about two fifths of the gate's rows and stays inside
// the gate's width, on every shape of gate a console can be opened at.
func TestTheMarkTakesAboutFortyPercentOfTheGate(t *testing.T) {
	withLigatureGlyph(t, syntheticLigature(320, 160))
	for _, sz := range [][2]int{{80, 24}, {100, 30}, {120, 40}, {200, 50}} {
		w, h := sz[0], sz[1]
		rows := splashBanner(w, h)
		if len(rows) == 0 {
			t.Fatalf("%dx%d: the gate drew no mark", w, h)
		}
		share := float64(len(rows)) / float64(h)
		if share < 0.35 || share > 0.45 {
			t.Fatalf("%dx%d: the mark takes %d of %d rows, %.0f%%, want about 40%%",
				w, h, len(rows), h, share*100)
		}
		for i, row := range rows {
			if n := runeLen(row); n > w {
				t.Fatalf("%dx%d: row %d of the mark is %d cells wide, wider than the gate",
					w, h, i, n)
			}
		}
	}
}

// The mark is the glyph's shape in cells, never the words retyped or the
// presentation forms of the rejected builds.
func TestTheMarkIsTheShapeNotTheWords(t *testing.T) {
	withLigatureGlyph(t, syntheticLigature(320, 160))
	rows := splashBanner(100, 30)
	if len(rows) == 0 {
		t.Fatal("the gate drew no mark")
	}
	joined := strings.Join(rows, "\n")
	if strings.Contains(joined, basmalaWords) {
		t.Fatalf("the mark is the words retyped:\n%s", joined)
	}
	for _, row := range rows {
		for _, r := range row {
			switch r {
			case ' ', '▀', '▄', '█':
			default:
				t.Fatalf("the mark carries %q, which is not a half block:\n%s", r, joined)
			}
		}
	}
	if !strings.ContainsAny(joined, "▀▄█") {
		t.Fatalf("the mark is blank:\n%s", joined)
	}
}

// Owner order 2026-11-27: the gate shows the mark alone, about 40% of its rows,
// centred, and nothing is drawn after it.
func TestTheGateShowsTheMarkAlone(t *testing.T) {
	withLigatureGlyph(t, syntheticLigature(320, 160))
	a := lockedApp(t, 100, 30)
	typeRunes(a, wantUnlockPassword)
	a.onKey(Key{Kind: KEnter})
	rows := a.render().PlainRows()

	first, last := -1, -1
	for i, row := range rows {
		if strings.ContainsAny(row, "▀▄█") {
			if first < 0 {
				first = i
			}
			last = i
		}
	}
	if first < 0 {
		t.Fatalf("the gate drew no mark:\n%s", strings.Join(rows, "\n"))
	}
	// The shape's box is centred; its ink need not touch every row of the box,
	// so the lit rows are checked to stand inside the box's own rows.
	want := splashBanner(100, 30)
	top := (30 - len(want)) / 2
	if first < top || last > top+len(want)-1 {
		t.Fatalf("the mark's ink stands on rows %d to %d, outside its box on rows %d to %d",
			first, last, top, top+len(want)-1)
	}
	if mid, box := (first+last)/2, top+len(want)/2; mid-box > 1 || box-mid > 1 {
		t.Fatalf("the mark is not centred: its ink's middle is row %d, its box's is row %d", mid, box)
	}
	if strings.Contains(strings.Join(rows, "\n"), "QUANT OF REHAN") {
		t.Fatalf("the gate carries a name after the mark:\n%s", strings.Join(rows, "\n"))
	}
}

// When the shape cannot be drawn the character itself stands on the middle row,
// so the mark is never missing and the gate never breaks.
func TestTheGateFallsBackToTheCharacter(t *testing.T) {
	old := ligatureGlyph
	ligatureGlyph = func() (ligatureMask, bool) { return ligatureMask{}, false }
	t.Cleanup(func() { ligatureGlyph = old })

	if rows := splashBanner(100, 30); len(rows) != 0 {
		t.Fatalf("the gate claims to have drawn the shape without one: %v", rows)
	}
	a := lockedApp(t, 100, 30)
	typeRunes(a, wantUnlockPassword)
	a.onKey(Key{Kind: KEnter})
	for i, row := range a.render().PlainRows() {
		if strings.Contains(row, basmalaBanner) {
			if i != 15 {
				t.Fatalf("the ligature stands on row %d, want the gate's middle row 15", i)
			}
			return
		}
	}
	t.Fatal("the gate drew neither the shape nor the ligature")
}
