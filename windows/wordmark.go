package main

import (
	"math"
	"strings"
)

// wordmarkDot is the glyph every lit point of the mark is drawn with, so the
// three words read as dots rather than as letters made of blocks.
const wordmarkDot = '•'

// wordmarkWords are the three lines of the mark, one word to a line, in the
// order they are drawn from the top of the tile down.
var wordmarkWords = [3]string{"QUANT", "OF", "REHAN"}

// wordmarkFont is the dot grid of every letter the mark needs, five points wide
// and seven tall, with '#' for a lit point.
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

// wordmarkSource builds the whole mark as one dot grid: the three words one
// under the other, one blank point between two letters and one blank point row
// between two words. It is 29 points wide and 23 tall.
func wordmarkSource() []string {
	const letterH = 7
	lines := make([][]string, 0, len(wordmarkWords))
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
		if n := runeLen(rows[0]); n > width {
			width = n
		}
		lines = append(lines, rows)
	}
	out := make([]string, 0, len(lines)*(letterH+1))
	for li, rows := range lines {
		for y := 0; y < letterH; y++ {
			out = append(out, rows[y]+strings.Repeat(".", width-runeLen(rows[y])))
		}
		if li < len(lines)-1 {
			out = append(out, strings.Repeat(".", width))
		}
	}
	return out
}

// wordmarkVisible is the sweep: the mark appears from the left edge across the
// tile, is held whole for a moment, then disappears from the left edge across,
// on a five second cycle. It returns the half open band of columns that is lit.
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
// each word on its own line, with the left to right sweep of wordmarkVisible.
// The mark is stretched into the room it is given, so it fills the tile on a
// short window and on a tall one and never draws outside it. green selects the
// market's green; outside the market window the mark is red, as the orb was.
func drawWordmark(c *Canvas, x0, y0, w, h int, t float64, green bool, th *Theme) {
	src := wordmarkSource()
	if w < 3 || h < 3 || len(src) == 0 {
		return
	}
	sh, sw := len(src), runeLen(src[0])
	if sw == 0 {
		return
	}
	ink := th.Bad
	if green {
		ink = th.Good
	}
	from, to := wordmarkVisible(t, w)
	for j := 0; j < h; j++ {
		sy := j * sh / h
		row := []rune(src[sy])
		for i := 0; i < w; i++ {
			if i < from || i >= to {
				continue
			}
			sx := i * sw / w
			if sx >= len(row) || row[sx] != '#' {
				continue
			}
			c.Put(x0+i, y0+j, wordmarkDot, ink, false)
		}
	}
}
