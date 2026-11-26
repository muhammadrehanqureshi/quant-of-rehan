package main

import (
	"bytes"
	_ "embed"
	"image"
	_ "image/png"
	"math"
	"strings"
)

// The sign in banner's own words, and the picture of them.
//
// Owner order 2026-11-26: the banner carries his words, بسم الله الرحمن الرحيم,
// and nothing after them. A console cell grid gives each glyph one fixed cell
// and cuts everything wider than that cell, which is why the phrase came out
// clipped when it was drawn as text. The words are therefore drawn here as
// braille dots: two dots across and four down in every cell, so the letters
// stand whole, joined and in their own reading order, with nothing cut at a
// cell's edge.
//
// windows/assets/basmala.png is Windows' own Arabic text engine drawing those
// words in Segoe UI (right to left, joined), cut to the ink. Nothing in the
// build retypes the phrase: the banner is a picture of it.

// basmalaWords is the phrase as text, kept beside the picture for the tests and
// for a window too small to carry the art.
const basmalaWords = "بسم الله الرحمن الرحيم"

//go:embed assets/basmala.png
var basmalaPNG []byte

// basmalaInk is the picture as a mask of dots, already cut to the ink so the
// banner fills the width it is given.
var basmalaInk = decodeInk(basmalaPNG)

// inkMask is one bit per picture dot: true where the phrase has ink.
type inkMask struct {
	w, h int
	dot  []bool
}

// decodeInk reads the picture and keeps only what is drawn, so the art has no
// margins of its own and its width is the width of the words.
func decodeInk(b []byte) *inkMask {
	if len(b) == 0 {
		return nil
	}
	img, err := pngDecode(b)
	if err != nil || img == nil {
		return nil
	}
	bnd := img.Bounds()
	w, h := bnd.Dx(), bnd.Dy()
	if w < 1 || h < 1 {
		return nil
	}
	lit := make([]bool, w*h)
	minX, minY, maxX, maxY := w, h, -1, -1
	for y := 0; y < h; y++ {
		for x := 0; x < w; x++ {
			r, g, bl, _ := img.At(bnd.Min.X+x, bnd.Min.Y+y).RGBA()
			if (r+g+bl)/3 <= 0x3000 {
				continue
			}
			lit[y*w+x] = true
			if x < minX {
				minX = x
			}
			if x > maxX {
				maxX = x
			}
			if y < minY {
				minY = y
			}
			if y > maxY {
				maxY = y
			}
		}
	}
	if maxX < 0 || maxY < 0 {
		return nil
	}
	cw, ch := maxX-minX+1, maxY-minY+1
	m := &inkMask{w: cw, h: ch, dot: make([]bool, cw*ch)}
	for y := 0; y < ch; y++ {
		copy(m.dot[y*cw:(y+1)*cw], lit[(minY+y)*w+minX:(minY+y)*w+minX+cw])
	}
	return m
}

func pngDecode(b []byte) (image.Image, error) {
	return image.Decode(bytes.NewReader(b))
}

// brailleDots are the eight dots of a braille cell: two across, four down.
var brailleDots = [...]struct {
	x, y int
	bit  rune
}{
	{0, 0, 0x01}, {0, 1, 0x02}, {0, 2, 0x04}, {1, 0, 0x08},
	{1, 1, 0x10}, {1, 2, 0x20}, {0, 3, 0x40}, {1, 3, 0x80},
}

// basmalaArt draws the phrase into a grid of cols cells by at most rows lines.
// A braille dot is square in a cell two characters high, so the picture keeps
// the shape it was drawn with, and every cell carries its own dots instead of
// one clipped glyph.
func basmalaArt(cols, rows int) []string {
	m := basmalaInk
	if m == nil || cols < 8 || rows < 4 {
		return nil
	}
	dw, dh := cols*2, rows*4
	h := int(math.Round(float64(dw) * float64(m.h) / float64(m.w)))
	if h > dh {
		dw = int(math.Round(float64(dw) * float64(dh) / float64(h)))
		h = dh
	}
	dw -= dw % 2
	h -= h % 4
	if dw < 2 || h < 4 {
		return nil
	}
	// Every dot takes the share of the picture under it, so a thin stroke
	// survives the shrink instead of falling between two dots.
	fill := make([]bool, dw*h)
	for y := 0; y < h; y++ {
		y0 := y * m.h / h
		y1 := (y + 1) * m.h / h
		if y1 <= y0 {
			y1 = y0 + 1
		}
		for x := 0; x < dw; x++ {
			x0 := x * m.w / dw
			x1 := (x + 1) * m.w / dw
			if x1 <= x0 {
				x1 = x0 + 1
			}
			n, on := 0, 0
			for yy := y0; yy < y1 && yy < m.h; yy++ {
				for xx := x0; xx < x1 && xx < m.w; xx++ {
					n++
					if m.dot[yy*m.w+xx] {
						on++
					}
				}
			}
			fill[y*dw+x] = n > 0 && on*100 >= n*38
		}
	}
	lines := make([]string, 0, h/4)
	for cy := 0; cy < h; cy += 4 {
		var b strings.Builder
		for cx := 0; cx < dw; cx += 2 {
			var bits rune
			for _, d := range brailleDots {
				if fill[(cy+d.y)*dw+cx+d.x] {
					bits |= d.bit
				}
			}
			b.WriteRune(0x2800 + bits)
		}
		lines = append(lines, b.String())
	}
	return lines
}
