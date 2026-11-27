package main

import (
	"bytes"
	"image"
	"image/color"
	"image/jpeg"
	"image/png"
	"strings"
	"testing"
)

// Owner order 2026-11-27 (build 183): on SETTINGS, ONLINE, ON and the big order
// size are green, and the rest of the right hand side stays white.

// inkOf reads the ink of the first cell of word on the drawn screen.
func inkOf(t *testing.T, c *Canvas, word string) RGB {
	t.Helper()
	y, x := findCells(c, word)
	if y < 0 {
		t.Fatalf("%q is not on the screen:\n%s", word, strings.Join(c.PlainRows(), "\n"))
	}
	return c.Cells[y*c.W+x].FG
}

func TestSettingsStatesAreGreen(t *testing.T) {
	a := demoApp(t, 140, 44)
	a.screen = scrSettings
	a.cfg.Notify = true
	a.cfg.BigOrderQty = 100000
	a.checking = false
	a.link = true
	a.head = nil
	c := a.render()
	for _, word := range []string{"ONLINE", "ON", "100k"} {
		if got := inkOf(t, c, word); got != a.th.Good {
			t.Fatalf("%q on SETTINGS wears %v, want the good ink %v", word, got, a.th.Good)
		}
	}
}

// The other side of the order: a switch that is off is still red, and the small
// print beside a switch is still white.
func TestSettingsOffStaysRedAndSmallPrintWhite(t *testing.T) {
	a := demoApp(t, 140, 44)
	a.screen = scrSettings
	a.cfg.Notify = false
	c := a.render()
	if got := inkOf(t, c, "OFF"); got != a.th.Bad {
		t.Fatalf("OFF wears %v, want the bad ink %v", got, a.th.Bad)
	}
	if got := inkOf(t, c, "Windows pop-ups"); got != inkWhite {
		t.Fatalf("the small print wears %v, want white %v", got, inkWhite)
	}
}

// ---------- the banner as a picture ----------

// testPicture draws white artwork on a clear field, the way his own file is
// built: a filled band across the middle of a wide sheet.
func testPicture(w, h int) image.Image {
	img := image.NewNRGBA(image.Rect(0, 0, w, h))
	for y := h / 4; y < 3*h/4; y++ {
		for x := w / 10; x < 9*w/10; x++ {
			if (x/6)%2 == 0 {
				img.Set(x, y, color.NRGBA{R: 255, G: 255, B: 255, A: 255})
			}
		}
	}
	return img
}

func pngBytes(t *testing.T, img image.Image) []byte {
	t.Helper()
	var b bytes.Buffer
	if err := png.Encode(&b, img); err != nil {
		t.Fatalf("cannot build a test png: %v", err)
	}
	return b.Bytes()
}

// Owner order 2026-11-27: "can you display PNG/JPG/JPEG pictures as the display
// banner if I give you?" All three formats are read, by alpha when the sheet is
// clear and by brightness when it is not.
func TestTheBannerReadsPngJpgAndJpeg(t *testing.T) {
	if m, ok := pictureFromBytes(pngBytes(t, testPicture(400, 120))); !ok {
		t.Fatalf("a png is not read as a banner")
	} else if m.W <= 0 || m.H <= 0 || m.W <= m.H {
		t.Fatalf("the png's mask is %dx%d, want the wide shape it was drawn with", m.W, m.H)
	}

	// A jpeg has no alpha channel, so this is the white on a dark field case.
	dark := image.NewRGBA(image.Rect(0, 0, 400, 120))
	for y := 30; y < 90; y++ {
		for x := 40; x < 360; x++ {
			if (x/6)%2 == 0 {
				dark.Set(x, y, color.RGBA{R: 255, G: 255, B: 255, A: 255})
			}
		}
	}
	var b bytes.Buffer
	if err := jpeg.Encode(&b, dark, nil); err != nil {
		t.Fatalf("cannot build a test jpeg: %v", err)
	}
	m, ok := pictureFromBytes(b.Bytes())
	if !ok {
		t.Fatalf("a jpeg is not read as a banner")
	}
	lit := 0
	for _, v := range m.Ink {
		if v >= 128 {
			lit++
		}
	}
	if lit == 0 {
		t.Fatalf("the jpeg's mask carries no ink")
	}
}

// A sheet that is lit edge to edge is not artwork: a blank page or a white one
// must never be printed as a solid block over the gate.
func TestABlankSheetIsNotABanner(t *testing.T) {
	blank := image.NewNRGBA(image.Rect(0, 0, 200, 80))
	for y := 0; y < 80; y++ {
		for x := 0; x < 200; x++ {
			blank.Set(x, y, color.NRGBA{R: 255, G: 255, B: 255, A: 255})
		}
	}
	if _, ok := pictureMask(blank); ok {
		t.Fatalf("a white sheet was taken as a banner")
	}
	empty := image.NewNRGBA(image.Rect(0, 0, 200, 80))
	if _, ok := pictureMask(empty); ok {
		t.Fatalf("an empty sheet was taken as a banner")
	}
}

// His own picture, embedded in the exe, is the banner: it reads, it is wide, and
// the gate shows it at about 40% of its rows.
func TestHisPictureIsTheBannersArtwork(t *testing.T) {
	m, ok := readBannerPicture()
	if !ok {
		t.Fatalf("the artwork in assets/banner is not read")
	}
	if m.W < m.H {
		t.Fatalf("the artwork's mask is %dx%d, want the wide sheet he gave", m.W, m.H)
	}
	for _, sz := range [][2]int{{80, 24}, {100, 30}, {120, 40}, {200, 50}} {
		w, h := sz[0], sz[1]
		dw, dh := ligatureFit(m, w, h)
		rows := ligatureRows(ligatureDots(m, dw, dh))
		if len(rows) == 0 {
			t.Fatalf("%dx%d: his picture drew no banner", w, h)
		}
		share := float64(len(rows)) / float64(h)
		if share < 0.35 || share > 0.45 {
			t.Fatalf("%dx%d: the picture takes %d of %d rows, %.0f%%, want about 40%%",
				w, h, len(rows), h, share*100)
		}
		if n := runeLen(rows[0]); n > w {
			t.Fatalf("%dx%d: the picture's banner is %d cells wide, wider than the gate", w, h, n)
		}
		if !strings.ContainsAny(strings.Join(rows, ""), "▀▄█") {
			t.Fatalf("%dx%d: the picture's banner is blank", w, h)
		}
	}
}

// The gate asks for the picture before it asks Windows for a glyph.
func TestTheGatePrefersThePicture(t *testing.T) {
	m, ok := pictureMask(testPicture(400, 120))
	if !ok {
		t.Fatalf("the test picture is not read")
	}
	old := pictureGlyph
	pictureGlyph = func() (ligatureMask, bool) { return m, true }
	t.Cleanup(func() { pictureGlyph = old })
	got, ok := bannerMark()
	if !ok || got.W != m.W || got.H != m.H {
		t.Fatalf("the gate's mark is %dx%d, want the picture's %dx%d", got.W, got.H, m.W, m.H)
	}
}
