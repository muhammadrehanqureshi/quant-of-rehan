package main

import (
	"math"
	"strings"
)

// wordmarkWords are the three lines of the mark, one word to a line, in the
// order they are drawn from the top of the tile down.
var wordmarkWords = [3]string{"QUANT", "OF", "REHAN"}

// wordmarkFont is the point grid of every letter the mark needs, five points
// wide and seven tall, with '#' for a lit point. The points are not cells: each
// one is turned into a block of dots below, so the letters are drawn in the fine
// dots the tile's Braille cells carry rather than one whole cell per point.
var wordmarkFont = map[rune][7]string{
	'Q': {
		".###.",
		"#...#",
		"#...#",
		"#...#",
		"#.#.#",
		"#..#.",
		".##.#",
	},
	'U': {
		"#...#",
		"#...#",
		"#...#",
		"#...#",
		"#...#",
		"#...#",
		".###.",
	},
	'A': {
		".###.",
		"#...#",
		"#...#",
		"#####",
		"#...#",
		"#...#",
		"#...#",
	},
	'N': {
		"#...#",
		"##..#",
		"#.#.#",
		"#.#.#",
		"#..##",
		"#...#",
		"#...#",
	},
	'T': {
		"#####",
		"..#..",
		"..#..",
		"..#..",
		"..#..",
		"..#..",
		"..#..",
	},
	'O': {
		".###.",
		"#...#",
		"#...#",
		"#...#",
		"#...#",
		"#...#",
		".###.",
	},
	'F': {
		"#####",
		"#....",
		"#....",
		"####.",
		"#....",
		"#....",
		"#....",
	},
	'R': {
		"####.",
		"#...#",
		"#...#",
		"####.",
		"#.#..",
		"#..#.",
		"#...#",
	},
	'E': {
		"#####",
		"#....",
		"#....",
		"####.",
		"#....",
		"#....",
		"#####",
	},
	'H': {
		"#...#",
		"#...#",
		"#...#",
		"#####",
		"#...#",
		"#...#",
		"#...#",
	},
}

// wordmarkPoints builds the whole mark as one point grid: the three words one
// under the other, one blank point between two letters, one blank point row
// between two words, and every word centred in the grid's own width, so OF
// stands in the middle of the tile and not against its left edge.
func wordmarkPoints() []string {
	const letterH = 7
	var lines [][]string
	width := 0
	for _, word := range wordmarkWords {
		rows := make([]string, letterH)
		for i, r := range word {
			g := wordmarkFont[r]
			for y := 0; y < letterH; y++ {
				if i > 0 {
					rows[y] += "."
				}
				rows[y] += g[y]
			}
		}
		if n := len(rows[0]); n > width {
			width = n
		}
		lines = append(lines, rows)
	}
	out := make([]string, 0, len(lines)*(letterH+1))
	for li, rows := range lines {
		for y := 0; y < letterH; y++ {
			pad := width - len(rows[y])
			left := pad / 2
			out = append(out, strings.Repeat(".", left)+rows[y]+strings.Repeat(".", pad-left))
		}
		if li < len(lines)-1 {
			out = append(out, strings.Repeat(".", width))
		}
	}
	return out
}

// wordmarkDots expands the points so that every point is a block of scale by
// scale dots. At two the mark is 58 dots wide and 46 tall, which is 29 by 12
// cells: small in its tile, and fine enough that the letters read as dots. One
// is the fallback for a tile too short to carry the finer grid.
func wordmarkDots(scale int) []string {
	pts := wordmarkPoints()
	if scale < 1 {
		scale = 1
	}
	out := make([]string, 0, len(pts)*scale)
	for _, row := range pts {
		var b strings.Builder
		for _, ch := range row {
			for k := 0; k < scale; k++ {
				b.WriteRune(ch)
			}
		}
		for k := 0; k < scale; k++ {
			out = append(out, b.String())
		}
	}
	return out
}

// brailleBit is the bit each dot of a Braille cell carries, indexed by its row
// in the cell and then its column.
var brailleBit = [4][2]byte{{0x01, 0x08}, {0x02, 0x10}, {0x04, 0x20}, {0x40, 0x80}}

// wordmarkVisible is the sweep: the mark appears from the left edge across the
// tile, is held whole for a moment, then disappears from the left edge across,
// on a five second cycle. It returns the half open band of dot columns lit.
func wordmarkVisible(t float64, w int) (int, int) {
	const cycle = 5.0
	p := math.Mod(t, cycle) / cycle
	if p < 0 {
		p += 1
	}
	switch {
	case p < 0.45: // appearing, left to right
		return 0, int(float64(w) * (p / 0.45))
	case p < 0.52: // held whole
		return 0, w
	case p < 0.97: // disappearing, left to right
		return int(float64(w) * ((p - 0.52) / 0.45)), w
	}
	return w, w // the blank moment before it starts again
}

// drawWordmark paints QUANT OF REHAN in dots into the rectangle (x0,y0,w,h),
// each word on a line of its own and centred, with the left to right sweep of
// wordmarkVisible. The mark is drawn at its own small size in the middle of the
// tile rather than stretched to fill it, and never draws outside it. green
// selects the market's green; outside the market window the mark is red.
func drawWordmark(c *Canvas, x0, y0, w, h int, t float64, green bool, th *Theme) {
	if w < 6 || h < 4 {
		return
	}
	dots := wordmarkDots(2)
	dw, dh := len(dots[0]), len(dots)
	cw, ch := (dw+1)/2, (dh+3)/4
	if cw > w || ch > h {
		dots = wordmarkDots(1)
		dw, dh = len(dots[0]), len(dots)
		cw, ch = (dw+1)/2, (dh+3)/4
	}
	if cw > w || ch > h {
		return
	}
	ink := th.Bad
	if green {
		ink = th.Good
	}
	ox := x0 + (w-cw)/2
	oy := y0 + (h-ch)/2
	from, to := wordmarkVisible(t, dw)
	for by := 0; by < ch; by++ {
		for bx := 0; bx < cw; bx++ {
			var bits byte
			for row := 0; row < 4; row++ {
				dy := by*4 + row
				if dy >= dh {
					break
				}
				line := []rune(dots[dy])
				for col := 0; col < 2; col++ {
					dx := bx*2 + col
					if dx >= dw || dx < from || dx >= to {
						continue
					}
					if dx < len(line) && line[dx] == '#' {
						bits |= brailleBit[row][col]
					}
				}
			}
			if bits != 0 {
				c.Put(ox+bx, oy+by, rune(0x2800+int(bits)), ink, false)
			}
		}
	}
}
