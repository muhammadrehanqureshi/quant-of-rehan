package main

import (
	"math"
	"strings"
)

// The gate's mark, drawn large.
//
// Owner order 2026-11-27: the banner is the ligature ﷽, the one character
// U+FDFD, and it "should take about 40% of the screen". A console cell holds
// one glyph at one fixed size, so a single character can never fill a corner of
// the gate: the mark is therefore drawn as the glyph's own ink, sampled into
// the solid blocks a cell carries (a cell's top half, its bottom half, or both).
// Nothing is retyped and no letter is approximated: the shape below is the
// character he named, rendered by Windows' own text engine at ligature size and
// then cut into cells, which is the only way a console can show it large.
//
// When the glyph cannot be drawn the gate falls back to the character itself,
// one line on the middle row, so the words are never lost.

// basmalaShare is the share of the gate's rows the banner takes.
const basmalaShare = 0.40

// ligatureInkCut is the coverage a block needs before it is lit. It is under a
// half so the hairline strokes of the calligraphy survive the sampling.
const ligatureInkCut = 0.30

// ligatureMask is the ligature's ink as a grid of coverage, 0 to 255, already
// cut to the ink's own edges so the banner fills the width it is given.
type ligatureMask struct {
	W, H int
	Ink  []uint8
}

func (m ligatureMask) inkAt(x, y int) uint8 {
	if x < 0 || y < 0 || x >= m.W || y >= m.H {
		return 0
	}
	return m.Ink[y*m.W+x]
}

// ligatureGlyph is where the banner's mark comes from. main sets it to the
// platform renderer, which asks the operating system's own text engine for the
// ligature's shape. Left alone it says the platform cannot draw the glyph, and
// the gate draws the character itself instead.
var ligatureGlyph = func() (ligatureMask, bool) { return ligatureMask{}, false }

// ligatureFit picks the dot grid for a gate: about 40% of the gate's rows tall,
// as wide as the glyph's own proportions make it, never wider than the gate.
// One dot is one cell wide and half a cell tall, which is a square on a
// console's cell, so the glyph keeps the shape it was drawn with.
func ligatureFit(m ligatureMask, w, h int) (int, int) {
	if m.W <= 0 || m.H <= 0 || w <= 2 || h <= 0 {
		return 0, 0
	}
	cellH := int(math.Round(float64(h) * basmalaShare))
	if cellH < 1 {
		cellH = 1
	}
	dh := cellH * 2
	dw := int(math.Round(float64(dh) * float64(m.W) / float64(m.H)))
	if dw > w-2 {
		dw = w - 2
		dh = int(math.Round(float64(dw) * float64(m.H) / float64(m.W)))
		if dh%2 == 1 {
			dh--
		}
	}
	if dw < 2 || dh < 2 {
		return 0, 0
	}
	return dw, dh
}

// ligatureDots samples the ink into a dot grid: every dot is the average
// coverage of the pixels under it, lit when that average passes the cut. This
// is a box filter, so a stroke keeps its weight instead of dropping out.
func ligatureDots(m ligatureMask, dw, dh int) [][]bool {
	dots := make([][]bool, dh)
	for y := range dots {
		dots[y] = make([]bool, dw)
	}
	if m.W <= 0 || m.H <= 0 || dw <= 0 || dh <= 0 {
		return dots
	}
	for y := 0; y < dh; y++ {
		y0 := y * m.H / dh
		y1 := (y + 1) * m.H / dh
		if y1 <= y0 {
			y1 = y0 + 1
		}
		for x := 0; x < dw; x++ {
			x0 := x * m.W / dw
			x1 := (x + 1) * m.W / dw
			if x1 <= x0 {
				x1 = x0 + 1
			}
			sum, n := 0, 0
			for yy := y0; yy < y1 && yy < m.H; yy++ {
				for xx := x0; xx < x1 && xx < m.W; xx++ {
					sum += int(m.inkAt(xx, yy))
					n++
				}
			}
			if n > 0 && float64(sum)/float64(n*255) >= ligatureInkCut {
				dots[y][x] = true
			}
		}
	}
	return dots
}

// ligatureRows turns the dot grid into cells: a lit top dot is the upper half
// block, a lit bottom dot the lower half, both the full block. Two dot rows
// become one cell row, and the rows keep the grid's own width so the banner is
// centred by its cells and not by its ink.
func ligatureRows(dots [][]bool) []string {
	if len(dots) == 0 || len(dots[0]) == 0 {
		return nil
	}
	w := len(dots[0])
	rows := make([]string, 0, (len(dots)+1)/2)
	for y := 0; y < len(dots); y += 2 {
		var b strings.Builder
		for x := 0; x < w; x++ {
			top := dots[y][x]
			bot := y+1 < len(dots) && dots[y+1][x]
			switch {
			case top && bot:
				b.WriteRune('█')
			case top:
				b.WriteRune('▀')
			case bot:
				b.WriteRune('▄')
			default:
				b.WriteByte(' ')
			}
		}
		rows = append(rows, b.String())
	}
	return rows
}

// splashBanner is the gate's banner: the ligature, about 40% of the gate tall.
// It returns nil when the platform cannot draw the glyph, and the gate then
// draws the ligature itself as text.
func splashBanner(w, h int) []string {
	if w < 12 || h < 6 {
		return nil
	}
	m, ok := ligatureGlyph()
	if !ok {
		return nil
	}
	dw, dh := ligatureFit(m, w, h)
	if dw < 2 || dh < 2 {
		return nil
	}
	rows := ligatureRows(ligatureDots(m, dw, dh))
	if len(rows) == 0 || runeLen(rows[0]) != dw {
		return nil
	}
	return rows
}

// basmalaOn says whether a screen carries the banner, drawn or as the
// character itself.
func basmalaOn(rows string) bool {
	if strings.Contains(rows, basmalaBanner) {
		return true
	}
	return strings.ContainsAny(rows, "▀▄█")
}
