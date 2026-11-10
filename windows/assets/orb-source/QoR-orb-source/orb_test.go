package main

import (
	"bufio"
	"bytes"
	"fmt"
	"image"
	"image/gif"
	"math"
	"os"
	"strings"
	"testing"
)

// golden reads the cells cut from the app's own output.
func golden(t *testing.T, file string) map[[2]int][4]int {
	t.Helper()
	f, err := os.Open("testdata/" + file)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	m := map[[2]int][4]int{}
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		if strings.HasPrefix(sc.Text(), "#") {
			continue
		}
		var x, y, ch, r, g, b int
		if _, err := fmt.Sscan(sc.Text(), &x, &y, &ch, &r, &g, &b); err != nil {
			t.Fatal(err)
		}
		m[[2]int{x, y}] = [4]int{ch, r, g, b}
	}
	return m
}

func orbOn(w, h int, tt float64, mode OrbMode, grow float64) *Canvas {
	c := NewCanvas(w, h, DefaultStyle().BG)
	DrawOrbSized(c, 0, 0, w, h, tt, mode, grow)
	return c
}

// TestMatchesApp: at grow 1 the orb is the app's orb, cell for cell, in glyph and
// in colour. The golden files were cut from the app's -snapshot output.
func TestMatchesApp(t *testing.T) {
	for _, tc := range []struct {
		file string
		mode OrbMode
		t    float64
	}{{"app_green_t0.golden", OrbGreen, 0}, {"app_green_t3.7.golden", OrbGreen, 3.7}, {"app_red.golden", OrbRed, 0}} {
		want := golden(t, tc.file)
		c := orbOn(38, originalRows, tc.t, tc.mode, 1)
		got := map[[2]int][4]int{}
		for y := 0; y < c.H; y++ {
			for x := 0; x < c.W; x++ {
				ce := c.Cells[y*c.W+x]
				if ce.Ch >= 0x2800 && ce.Ch <= 0x28ff {
					got[[2]int{x, y}] = [4]int{int(ce.Ch), int(ce.FG.R), int(ce.FG.G), int(ce.FG.B)}
				}
			}
		}
		if len(got) != len(want) {
			t.Errorf("%s: %d cells, the app has %d", tc.file, len(got), len(want))
		}
		for k, w := range want {
			if got[k] != w {
				t.Errorf("%s: cell %v is %v, the app has %v", tc.file, k, got[k], w)
				break
			}
		}
	}
}

// extent is the size, in terminal pixels, of the box round all the lit dots.
func extent(c *Canvas) (w, h float64, dots int) {
	s := DefaultStyle()
	minx, miny, maxx, maxy := math.Inf(1), math.Inf(1), math.Inf(-1), math.Inf(-1)
	for cy := 0; cy < c.H; cy++ {
		for cx := 0; cx < c.W; cx++ {
			ce := c.Cells[cy*c.W+cx]
			if ce.Ch < 0x2800 || ce.Ch > 0x28ff {
				continue
			}
			for b, p := range bitPos {
				if int(ce.Ch-0x2800)&(1<<b) == 0 {
					continue
				}
				x := float64(cx*s.CellW) + float64(s.CellW)*(0.25+0.5*float64(p[0]))
				y := float64(cy*s.CellH) + float64(s.CellH)*(0.125+0.25*float64(p[1]))
				minx, maxx = math.Min(minx, x), math.Max(maxx, x)
				miny, maxy = math.Min(miny, y), math.Max(maxy, y)
				dots++
			}
		}
	}
	return maxx - minx, maxy - miny, dots
}

// meanExtent is the size of the lit dots' box, averaged over the whole 16 s loop,
// because the outer arcs turn and the box changes by a dot as they go.
func meanExtent(w, h int, mode OrbMode, grow float64) (float64, float64) {
	var sw, sh float64
	const n = 160
	for i := 0; i < n; i++ {
		ew, eh, _ := extent(orbOn(w, h, float64(i)*0.1, mode, grow))
		sw, sh = sw+ew, sh+eh
	}
	return sw / n, sh / n
}

// TestTenPercentBigger measures the picture: the orb must look 10% bigger than
// the app's. The dots are about 2% of the orb across, so each side is allowed a
// dot, and the two together must average 10%.
func TestTenPercentBigger(t *testing.T) {
	ow, oh := meanExtent(38, originalRows, OrbGreen, 1)
	cols, rows := OrbCols(OrbGrow), OrbRows(OrbGrow)
	nw, nh := meanExtent(cols, rows, OrbGreen, OrbGrow)
	rw, rh := nw/ow, nh/oh
	t.Logf("app %.1f x %.1f px, new %.1f x %.1f px: %.1f%% wider, %.1f%% higher; canvas %d x %d cells", ow, oh, nw, nh, (rw-1)*100, (rh-1)*100, cols, rows)
	for name, r := range map[string]float64{"width": rw, "height": rh} {
		if r < 1.08 || r > 1.12 {
			t.Errorf("%s is %.3f times the app's, want about 1.10", name, r)
		}
	}
	if m := (rw + rh) / 2; m < 1.095 || m > 1.115 {
		t.Errorf("on average the orb is %.3f times the app's, want 1.10", m)
	}
	if cols != 32 || rows != 14 {
		t.Errorf("canvas is %d x %d cells, want 32 x 14", cols, rows)
	}
	if r := OrbRadius(OrbGrow) / originalRadius(); math.Abs(r-OrbGrow) > 1e-9 {
		t.Errorf("radius ratio %.4f", r)
	}
}

func TestRound(t *testing.T) {
	for _, m := range []OrbMode{OrbGreen, OrbRed} {
		w, h, _ := extent(orbOn(OrbCols(OrbGrow), OrbRows(OrbGrow), 0, m, OrbGrow))
		if r := w / h; r < 0.97 || r > 1.03 {
			t.Errorf("%v orb is %.1f wide and %.1f high pixels: not round", m, w, h)
		}
	}
}

func same(a, b *Canvas) bool {
	for i := range a.Cells {
		if a.Cells[i] != b.Cells[i] {
			return false
		}
	}
	return true
}

func TestMotion(t *testing.T) {
	cols, rows := OrbCols(OrbGrow), OrbRows(OrbGrow)
	if !same(orbOn(cols, rows, 0, OrbRed, OrbGrow), orbOn(cols, rows, 7.3, OrbRed, OrbGrow)) {
		t.Error("the red orb moved: it must be completely still")
	}
	if same(orbOn(cols, rows, 0, OrbGreen, OrbGrow), orbOn(cols, rows, 3, OrbGreen, OrbGrow)) {
		t.Error("the green orb did not turn")
	}
	if !same(orbOn(cols, rows, 0, OrbGreen, OrbGrow), orbOn(cols, rows, 16, OrbGreen, OrbGrow)) {
		t.Error("the green orb does not loop after 16 seconds")
	}
}

// TestNothingCut: the smallest canvas holds every dot. A canvas with room all
// round it lights the same dots.
func TestNothingCut(t *testing.T) {
	cols, rows := OrbCols(OrbGrow), OrbRows(OrbGrow)
	for _, m := range []OrbMode{OrbGreen, OrbRed} {
		for _, tt := range []float64{0, 2.5, 9.1} {
			_, _, tight := extent(orbOn(cols, rows, tt, m, OrbGrow))
			_, _, wide := extent(orbOn(cols+6, rows+4, tt, m, OrbGrow))
			if tight != wide {
				t.Errorf("%v at %.1f s: %d dots on the small canvas, %d on the roomy one", m, tt, tight, wide)
			}
		}
	}
}

func TestPictures(t *testing.T) {
	st := DefaultStyle()
	cols, rows := OrbCols(OrbGrow), OrbRows(OrbGrow)
	pal := radarPalette(OrbGreen)
	const fs = 3
	var buf bytes.Buffer
	var list []*image.Paletted
	for i := 0; i < fs; i++ {
		f, err := st.Paletted(orbOn(cols, rows, float64(i)*0.1, OrbGreen, OrbGrow), pal)
		if err != nil {
			t.Fatal(err)
		}
		list = append(list, f)
	}
	if err := WriteGIF(&buf, list, 10); err != nil {
		t.Fatal(err)
	}
	g, err := gif.DecodeAll(&buf)
	if err != nil {
		t.Fatal(err)
	}
	if len(g.Image) != fs || g.LoopCount != 0 {
		t.Errorf("%d frames, loop count %d", len(g.Image), g.LoopCount)
	}
	b := g.Image[0].Bounds()
	if b.Dx() != 888 || b.Dy() != 888 {
		t.Errorf("picture is %d x %d, want 888 x 888", b.Dx(), b.Dy())
	}
	if n := len(g.Image[0].Palette); n > 256 {
		t.Errorf("palette has %d colours", n)
	}
	r, gg, bb, _ := g.Image[0].At(0, 0).RGBA()
	if uint8(r>>8) != st.BG.R || uint8(gg>>8) != st.BG.G || uint8(bb>>8) != st.BG.B {
		t.Error("the corner of the picture is not the background")
	}
	rgba, err := st.RGBA(orbOn(cols, rows, 0, OrbRed, OrbGrow))
	if err != nil {
		t.Fatal(err)
	}
	if rgba.Bounds().Dx() != 888 {
		t.Errorf("PNG is %d wide, want 888", rgba.Bounds().Dx())
	}
	var lit int
	for i := 0; i < len(rgba.Pix); i += 4 {
		if rgba.Pix[i] > 120 {
			lit++
		}
	}
	if lit < 1000 {
		t.Errorf("the red picture has only %d red pixels", lit)
	}
}
