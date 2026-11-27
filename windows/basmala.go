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
// blocks: each cell carries the top half of a mark, the bottom half, or both,
// so the letters stand whole, joined and in their own reading order, with
// nothing cut at a cell's edge.
//
// Owner order 2026-11-26 (later): the dotted render is withdrawn. A grid of
// separate dots across the words read as speckle, and it gave the letters more
// dots than the Arabic carries. The whole phrase is now one kind of mark, the
// solid block, so the only dots on the banner are the ones the letters own.
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
	img, _, err := image.Decode(bytes.NewReader(b))
	return img, err
}

// basmalaDot is the one mark the banner is drawn with. Owner order 2026-11-27:
// the block art read as a bad render, so the phrase is drawn here as continuous
// dots, one single dot for the entire banner, with no half block and no whole
// block anywhere in it.
const basmalaDot = '●'

// basmalaArt draws the phrase into at most cols cells by at most rows lines.
// Every mark is the same mark, basmalaDot, so the whole picture is made of one
// continuous line of dots: a cell carries a dot where the picture has ink and a
// space where it does not, and the words keep the shape they were drawn with.
func basmalaArt(cols, rows int) []string {
	m := basmalaInk
	if m == nil || cols < 8 || rows < 3 {
		return nil
	}
	dw, dh := cols, rows
	h := int(math.Round(float64(dw) * float64(m.h) / float64(m.w)))
	if h > dh {
		dw = int(math.Round(float64(dw) * float64(dh) / float64(h)))
		h = dh
	}
	if dw < 4 || h < 2 {
		return nil
	}
	// Every mark takes the share of the picture under it, so a thin stroke
	// survives the shrink instead of falling between two cells.
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
			fill[y*dw+x] = n > 0 && on*100 >= n*30
		}
	}
	lines := make([]string, 0, h)
	for y := 0; y < h; y++ {
		var b strings.Builder
		for x := 0; x < dw; x++ {
			if fill[y*dw+x] {
				b.WriteRune(basmalaDot)
			} else {
				b.WriteRune(' ')
			}
		}
		lines = append(lines, b.String())
	}
	return lines
}
