package main

import (
	"strconv"
	"strings"
)

// Cell is one character cell.
type Cell struct {
	Ch   rune
	FG   RGB
	BG   RGB
	Bold bool
}

// Canvas is a grid the screens draw into. It is serialised to ANSI once per
// frame, and rows that did not change are not sent again.
type Canvas struct {
	W, H  int
	Cells []Cell
}

func NewCanvas(w, h int, bg RGB) *Canvas {
	c := &Canvas{W: w, H: h, Cells: make([]Cell, w*h)}
	for i := range c.Cells {
		c.Cells[i] = Cell{Ch: ' ', FG: bg, BG: bg}
	}
	return c
}

func (c *Canvas) in(x, y int) bool { return x >= 0 && y >= 0 && x < c.W && y < c.H }

// safeRune keeps hostile text from reaching the terminal. Everything shown
// here, including text the relay sends, goes through Set or Put, so control
// characters (which could start an escape sequence that retitles the window,
// moves the cursor or writes to the clipboard) and the invisible bidi and
// zero width marks that can disguise text are drawn as a dot instead.
func safeRune(r rune) rune {
	switch {
	case r == 0:
		return ' '
	case r < 0x20, r == 0x7f, r >= 0x80 && r <= 0x9f:
		return '·'
	case r >= 0x200b && r <= 0x200f, r >= 0x202a && r <= 0x202e,
		r >= 0x2060 && r <= 0x2064, r >= 0x2066 && r <= 0x2069, r == 0xfeff:
		return '·'
	}
	return r
}

// Set writes a full cell.
func (c *Canvas) Set(x, y int, ch rune, fg, bg RGB, bold bool) {
	if c.in(x, y) {
		c.Cells[y*c.W+x] = Cell{safeRune(ch), fg, bg, bold}
	}
}

// Put writes a rune and ink but keeps the background already there.
func (c *Canvas) Put(x, y int, ch rune, fg RGB, bold bool) {
	if c.in(x, y) {
		i := y*c.W + x
		c.Cells[i].Ch, c.Cells[i].FG, c.Cells[i].Bold = safeRune(ch), fg, bold
	}
}

// BGAt returns the background already painted at (x, y).
func (c *Canvas) BGAt(x, y int) RGB {
	if c.in(x, y) {
		return c.Cells[y*c.W+x].BG
	}
	return RGB{}
}

// Fill paints a rectangle with a background and blanks it.
func (c *Canvas) Fill(x, y, w, h int, bg RGB) {
	for yy := y; yy < y+h; yy++ {
		for xx := x; xx < x+w; xx++ {
			c.Set(xx, yy, ' ', bg, bg, false)
		}
	}
}

// Text writes s starting at x, at most maxW cells, and returns cells written.
func (c *Canvas) Text(x, y, maxW int, s string, fg RGB, bold bool) int {
	n := 0
	for _, r := range s {
		if n >= maxW || r == '\n' {
			break
		}
		c.Put(x+n, y, r, fg, bold)
		n++
	}
	return n
}

// Span is a run of text in one colour.
type Span struct {
	S    string
	FG   RGB
	Bold bool
}

// Spans writes several coloured runs one after another.
func (c *Canvas) Spans(x, y, maxW int, spans []Span) int {
	n := 0
	for _, sp := range spans {
		if n >= maxW {
			break
		}
		n += c.Text(x+n, y, maxW-n, sp.S, sp.FG, sp.Bold)
	}
	return n
}

// HLine draws a run of one rune.
func (c *Canvas) HLine(x, y, w int, ch rune, fg RGB) {
	for i := 0; i < w; i++ {
		c.Put(x+i, y, ch, fg, false)
	}
}

// Row serialises one row as ANSI with 24 bit colour.
func (c *Canvas) Row(y int) string {
	var b strings.Builder
	var lf, lb RGB
	var lbold, first = false, true
	for x := 0; x < c.W; x++ {
		ce := c.Cells[y*c.W+x]
		if first || ce.FG != lf || ce.BG != lb || ce.Bold != lbold {
			b.WriteString("\x1b[0")
			if ce.Bold {
				b.WriteString(";1")
			}
			b.WriteString(";38;2;")
			b.WriteString(strconv.Itoa(int(ce.FG.R)))
			b.WriteByte(';')
			b.WriteString(strconv.Itoa(int(ce.FG.G)))
			b.WriteByte(';')
			b.WriteString(strconv.Itoa(int(ce.FG.B)))
			b.WriteString(";48;2;")
			b.WriteString(strconv.Itoa(int(ce.BG.R)))
			b.WriteByte(';')
			b.WriteString(strconv.Itoa(int(ce.BG.G)))
			b.WriteByte(';')
			b.WriteString(strconv.Itoa(int(ce.BG.B)))
			b.WriteByte('m')
			lf, lb, lbold, first = ce.FG, ce.BG, ce.Bold, false
		}
		ch := ce.Ch
		if ch == 0 {
			ch = ' '
		}
		b.WriteRune(ch)
	}
	b.WriteString("\x1b[0m")
	return b.String()
}

// PlainRows returns the text of every row, for tests and snapshots.
func (c *Canvas) PlainRows() []string {
	out := make([]string, c.H)
	for y := 0; y < c.H; y++ {
		var b strings.Builder
		for x := 0; x < c.W; x++ {
			ch := c.Cells[y*c.W+x].Ch
			if ch == 0 {
				ch = ' '
			}
			b.WriteRune(ch)
		}
		out[y] = b.String()
	}
	return out
}
