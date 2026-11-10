package main

import (
	"math"
	"strconv"
	"strings"
)

// RGB is a 24 bit colour.
type RGB struct{ R, G, B uint8 }

// Cell is one character cell of the terminal: a character, its ink and its
// background.
type Cell struct {
	Ch   rune
	FG   RGB
	BG   RGB
	Bold bool
}

// Canvas is a grid of cells. The orb is drawn into one, and a canvas is turned
// into terminal text (ANSI) or into a picture (gif.go).
type Canvas struct {
	W, H  int
	Cells []Cell
}

// NewCanvas makes a canvas of blank cells on the background bg.
func NewCanvas(w, h int, bg RGB) *Canvas {
	c := &Canvas{W: w, H: h, Cells: make([]Cell, w*h)}
	for i := range c.Cells {
		c.Cells[i] = Cell{Ch: ' ', FG: bg, BG: bg}
	}
	return c
}

func (c *Canvas) in(x, y int) bool { return x >= 0 && y >= 0 && x < c.W && y < c.H }

// Set writes one cell. Anything outside the canvas is ignored.
func (c *Canvas) Set(x, y int, ch rune, fg, bg RGB, bold bool) {
	if c.in(x, y) {
		c.Cells[y*c.W+x] = Cell{ch, fg, bg, bold}
	}
}

// BGAt is the background of a cell.
func (c *Canvas) BGAt(x, y int) RGB {
	if c.in(x, y) {
		return c.Cells[y*c.W+x].BG
	}
	return RGB{}
}

func mix(a, b RGB, t float64) RGB {
	if t <= 0 {
		return a
	}
	if t >= 1 {
		return b
	}
	f := func(x, y uint8) uint8 { return uint8(math.Round(float64(x) + (float64(y)-float64(x))*t)) }
	return RGB{f(a.R, b.R), f(a.G, b.G), f(a.B, b.B)}
}

// ANSI turns the canvas into terminal text in 24 bit colour, one line per row,
// each line ending in "\r\n". It changes the colour codes only where the colour
// changes.
func (c *Canvas) ANSI() string {
	var sb strings.Builder
	code := func(fg bool, v RGB) {
		if fg {
			sb.WriteString("\x1b[38;2;")
		} else {
			sb.WriteString("\x1b[48;2;")
		}
		sb.WriteString(strconv.Itoa(int(v.R)) + ";" + strconv.Itoa(int(v.G)) + ";" + strconv.Itoa(int(v.B)) + "m")
	}
	for y := 0; y < c.H; y++ {
		var fg, bg RGB
		first := true
		for x := 0; x < c.W; x++ {
			ce := c.Cells[y*c.W+x]
			if first || ce.BG != bg {
				code(false, ce.BG)
				bg = ce.BG
			}
			if first || ce.FG != fg {
				code(true, ce.FG)
				fg = ce.FG
			}
			first = false
			sb.WriteRune(ce.Ch)
		}
		sb.WriteString("\x1b[0m\r\n")
	}
	return sb.String()
}

// brailleBit gives the bit of the dot at column 0..1, row 0..3 of a Braille cell.
// A cell's character is 0x2800 plus the bits of its lit dots.
var brailleBit = [2][4]rune{{0x01, 0x02, 0x04, 0x40}, {0x08, 0x10, 0x20, 0x80}}
