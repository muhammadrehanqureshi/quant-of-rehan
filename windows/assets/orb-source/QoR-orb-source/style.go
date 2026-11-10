package main

import (
	"errors"
	"image"
	"image/color"
	"image/gif"
	"image/png"
	"io"
	"math"
)

// Style says how a canvas of Braille cells becomes a picture. The defaults are
// the numbers of Windows Terminal at its stock font: a cell is 9 by 20 pixels
// and a dot is a round disc of radius 1.55 pixels, at the usual places of the
// Braille grid (a quarter and three quarters across a cell, an eighth, three
// eighths, five eighths and seven eighths down it).
type Style struct {
	CellW, CellH int     // pixels of one cell at 1x
	Scale        int     // picture pixels per terminal pixel
	DotR         float64 // dot radius in terminal pixels
	Side         int     // side of the square picture in terminal pixels; 0 is the canvas size
	BG           RGB     // the flat colour behind the dots
	NudgeX       int     // picture pixels to shift the canvas right, set by Centre
	NudgeY       int     // picture pixels to shift the canvas down, set by Centre
}

// DefaultStyle is a 296 pixel square picture (a 3x scale gives 888) of a Windows
// Terminal cell grid on the HUD's panel colour.
func DefaultStyle() Style {
	return Style{CellW: 9, CellH: 20, Scale: 3, DotR: 1.55, Side: 296, BG: RGB{4, 18, 27}}
}

// size is the picture's width and height in pixels and where the canvas starts
// in it.
func (s Style) size(c *Canvas) (w, h, ox, oy int, err error) {
	cw, ch := c.W*s.CellW*s.Scale, c.H*s.CellH*s.Scale
	if s.Side == 0 {
		return cw, ch, 0, 0, nil
	}
	side := s.Side * s.Scale
	if side < cw || side < ch {
		return 0, 0, 0, 0, errors.New("the picture side is smaller than the canvas")
	}
	return side, side, (side-cw)/2 + s.NudgeX, (side-ch)/2 + s.NudgeY, nil
}

// Centre returns the style shifted so the box round every lit dot of all the
// canvases sits in the middle of the square picture. The ring is not perfectly
// symmetric (the layers' centres differ by a few pixels in the reference), so
// this puts the same margin on every side. It moves the whole picture, never a
// dot against another dot.
func (s Style) Centre(cs ...*Canvas) Style {
	s.NudgeX, s.NudgeY = 0, 0
	if s.Side == 0 || len(cs) == 0 {
		return s
	}
	minx, miny, maxx, maxy := math.MaxInt32, math.MaxInt32, math.MinInt32, math.MinInt32
	for _, c := range cs {
		w, h, ox, oy, err := s.size(c)
		if err != nil {
			return s
		}
		s.plotDots(c, ox, oy, func(x, y int, cov float64, _ RGB) {
			if cov < 0.5 || x < 0 || y < 0 || x >= w || y >= h {
				return
			}
			minx, maxx = min(minx, x), max(maxx, x)
			miny, maxy = min(miny, y), max(maxy, y)
		})
	}
	if maxx < minx {
		return s
	}
	side := s.Side * s.Scale
	s.NudgeX = (side - (minx + maxx + 1)) / 2
	s.NudgeY = (side - (miny + maxy + 1)) / 2
	return s
}

// dotX and dotY are the centre of a dot in picture pixels.
func (s Style) dotX(cx, dx, ox int) float64 {
	return float64(ox) + float64(s.Scale)*(float64(cx*s.CellW)+float64(s.CellW)*(0.25+0.5*float64(dx)))
}
func (s Style) dotY(cy, dy, oy int) float64 {
	return float64(oy) + float64(s.Scale)*(float64(cy*s.CellH)+float64(s.CellH)*(0.125+0.25*float64(dy)))
}

// bitPos is where each Braille bit sits, as a column and a row of the 2 by 4 grid.
var bitPos = [8][2]int{{0, 0}, {0, 1}, {0, 2}, {1, 0}, {1, 1}, {1, 2}, {0, 3}, {1, 3}}

// plotDots calls plot for every pixel a lit dot touches, with how much of the
// pixel the dot covers (0 to 1), and the ink of its cell. Dots never overlap.
func (s Style) plotDots(c *Canvas, ox, oy int, plot func(x, y int, cov float64, ink RGB)) {
	r := s.DotR * float64(s.Scale)
	for cy := 0; cy < c.H; cy++ {
		for cx := 0; cx < c.W; cx++ {
			ce := c.Cells[cy*c.W+cx]
			if ce.Ch < 0x2800 || ce.Ch > 0x28ff {
				continue
			}
			m := int(ce.Ch - 0x2800)
			for b, p := range bitPos {
				if m&(1<<b) == 0 {
					continue
				}
				px, py := s.dotX(cx, p[0], ox), s.dotY(cy, p[1], oy)
				for y := int(math.Floor(py - r - 1)); y <= int(math.Ceil(py+r+1)); y++ {
					for x := int(math.Floor(px - r - 1)); x <= int(math.Ceil(px+r+1)); x++ {
						d := math.Hypot(float64(x)+0.5-px, float64(y)+0.5-py)
						if cov := clamp01(r + 0.5 - d); cov > 0 {
							plot(x, y, cov, ce.FG)
						}
					}
				}
			}
		}
	}
}

// RGBA draws the canvas as a full colour picture.
func (s Style) RGBA(c *Canvas) (*image.RGBA, error) {
	w, h, ox, oy, err := s.size(c)
	if err != nil {
		return nil, err
	}
	img := image.NewRGBA(image.Rect(0, 0, w, h))
	bg := color.RGBA{s.BG.R, s.BG.G, s.BG.B, 255}
	for i := 0; i < len(img.Pix); i += 4 {
		img.Pix[i], img.Pix[i+1], img.Pix[i+2], img.Pix[i+3] = bg.R, bg.G, bg.B, 255
	}
	s.plotDots(c, ox, oy, func(x, y int, cov float64, ink RGB) {
		if x < 0 || y < 0 || x >= w || y >= h {
			return
		}
		v := mix(s.BG, ink, cov)
		o := img.PixOffset(x, y)
		img.Pix[o], img.Pix[o+1], img.Pix[o+2] = v.R, v.G, v.B
	})
	return img, nil
}

// The GIF palette has the background, then every ink of a mode (inkSteps along
// its dim to hot ramp) at each of edgeSteps strengths of dot edge. That is 241
// colours, which fits a GIF, and it holds every colour the dots can have, so
// nothing is dithered or banded.
const (
	inkSteps  = 40
	edgeSteps = 6
)

// Palette is the GIF palette of a mode on this style's background.
func (s Style) Palette(pal radarPal) color.Palette {
	p := make(color.Palette, 0, 1+inkSteps*edgeSteps)
	p = append(p, color.RGBA{s.BG.R, s.BG.G, s.BG.B, 255})
	for k := 1; k <= edgeSteps; k++ {
		for j := 0; j < inkSteps; j++ {
			v := mix(s.BG, pal.at(float64(j)/(inkSteps-1)), float64(k)/edgeSteps)
			p = append(p, color.RGBA{v.R, v.G, v.B, 255})
		}
	}
	return p
}

// Paletted draws the canvas as a GIF frame with the palette of the mode.
func (s Style) Paletted(c *Canvas, pal radarPal) (*image.Paletted, error) {
	w, h, ox, oy, err := s.size(c)
	if err != nil {
		return nil, err
	}
	img := image.NewPaletted(image.Rect(0, 0, w, h), s.Palette(pal))
	ramp := make([]RGB, inkSteps)
	for j := range ramp {
		ramp[j] = pal.at(float64(j) / (inkSteps - 1))
	}
	nearest := func(v RGB) int {
		best, bd := 0, math.MaxInt32
		for j, r := range ramp {
			dr, dg, db := int(v.R)-int(r.R), int(v.G)-int(r.G), int(v.B)-int(r.B)
			if d := dr*dr + dg*dg + db*db; d < bd {
				best, bd = j, d
			}
		}
		return best
	}
	s.plotDots(c, ox, oy, func(x, y int, cov float64, ink RGB) {
		if x < 0 || y < 0 || x >= w || y >= h {
			return
		}
		k := int(math.Round(cov * edgeSteps))
		if k == 0 {
			return
		}
		img.Pix[y*img.Stride+x] = uint8(1 + (k-1)*inkSteps + nearest(ink))
	})
	return img, nil
}

// WriteGIF writes frames as a looping GIF, delay hundredths of a second apart.
func WriteGIF(w io.Writer, frames []*image.Paletted, delay int) error {
	g := &gif.GIF{LoopCount: 0}
	for _, f := range frames {
		g.Image = append(g.Image, f)
		g.Delay = append(g.Delay, delay)
	}
	return gif.EncodeAll(w, g)
}

// WritePNG writes one picture as a PNG.
func WritePNG(w io.Writer, img image.Image) error { return png.Encode(w, img) }
