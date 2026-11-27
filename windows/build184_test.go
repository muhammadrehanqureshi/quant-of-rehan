package main

import (
	"image"
	"image/color"
	"testing"
)

// Owner order 2026-11-27 (build 184): "only use this image as the welcome
// image, DO NOT RENDER IT, just have this exact image as the welcome banner."
// So the banner window carries the picture's own pixels, laid over the gate's
// background only where the picture is clear, and it is placed whole: its own
// size when the screen holds it, and shrunk evenly when it does not.

func TestBuild184TheBannerShowsThePicturesOwnPixels(t *testing.T) {
	img := image.NewNRGBA(image.Rect(0, 0, 3, 1))
	img.SetNRGBA(0, 0, color.NRGBA{R: 255, G: 255, B: 255, A: 255})
	img.SetNRGBA(1, 0, color.NRGBA{R: 255, G: 255, B: 255, A: 0})
	img.SetNRGBA(2, 0, color.NRGBA{R: 200, G: 10, B: 30, A: 255})
	bg := RGB{4, 8, 12}

	px, w, h := welcomePicturePixels(img, bg)
	if w != 3 || h != 1 || len(px) != 12 {
		t.Fatalf("pixels are %dx%d in %d bytes, want 3x1 in 12", w, h, len(px))
	}
	want := [][4]uint8{
		{255, 255, 255, 255}, // white ink stays white
		{12, 8, 4, 255},      // a clear pixel takes the gate's background
		{30, 10, 200, 255},   // B, G, R: the ink's own blue, green and red
	}
	for i, p := range want {
		got := [4]uint8{px[i*4], px[i*4+1], px[i*4+2], px[i*4+3]}
		if got != p {
			t.Fatalf("pixel %d is %v, want %v", i, got, p)
		}
	}
}

func TestBuild184TheBannerIsPlacedWholeAndNeverCut(t *testing.T) {
	console := image.Rect(100, 50, 1900, 850)
	work := image.Rect(0, 0, 1920, 1040)

	// A screen that holds the picture shows it at the file's own size with the
	// owner's 35% taken off (build 186), centred on the console and kept inside
	// the screen's edges.
	r := welcomePictureRect(console, work, 1447, 493)
	if r.Dx() != 940 || r.Dy() != 320 {
		t.Fatalf("a screen that holds the picture drew it %dx%d, want 940x320", r.Dx(), r.Dy())
	}
	if r.Min.X < work.Min.X || r.Min.Y < work.Min.Y || r.Max.X > work.Max.X || r.Max.Y > work.Max.Y {
		t.Fatalf("the picture %v left the work area %v", r, work)
	}
	if cy := r.Min.Y + r.Dy()/2; cy != 450 {
		t.Fatalf("the picture's centre row is %d, want the console's 450", cy)
	}

	// Owner order 2026-11-27 (build 186): "reduce the banner's image size by
	// 35% from it's current size." The picture is placed as 185 placed it, the
	// console's own width holding it first when that is narrower, and then it
	// stands at 65% of that size.
	r = welcomePictureRect(image.Rect(100, 50, 1300, 850), work, 1447, 493)
	if r.Dx() != 780 || r.Dy() != 265 {
		t.Fatalf("a 1200 wide console drew the picture %dx%d, want 780x265", r.Dx(), r.Dy())
	}

	// A screen too small for it shrinks it whole, keeping its shape, and the
	// same 35% comes off what is left.
	small := image.Rect(0, 0, 800, 600)
	r = welcomePictureRect(image.Rectangle{}, small, 1447, 493)
	if r.Dx() != 478 || r.Dy() != 162 {
		t.Fatalf("the picture drew %dx%d on an 800x600 screen, want 478x162", r.Dx(), r.Dy())
	}

	if r := welcomePictureRect(console, work, 4, 4); !r.Empty() {
		t.Fatalf("a 4x4 picture was placed at %v, want nowhere", r)
	}
	if r := welcomePictureRect(console, image.Rectangle{}, 1447, 493); !r.Empty() {
		t.Fatalf("a picture was placed with no work area at %v, want nowhere", r)
	}
}
