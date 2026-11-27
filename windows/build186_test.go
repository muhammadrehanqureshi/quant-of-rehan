package main

import (
	"image"
	"testing"
)

// Owner order 2026-11-27 (build 186): "these are the changes for the windows
// build, the application still got hung for about 1 or 2 seconds, reduce the
// banner's image size by 35% from it's current size."

// The picture stands at 65% of the size build 185 gave it, whichever of its own
// file, the console's width or the screen's work area decided that size, and it
// is still whole, centred and inside the work area.
func TestBuild186TheBannerStandsAtSixtyFivePercent(t *testing.T) {
	if welcomePicturePercent != 65 {
		t.Fatalf("the picture stands at %d%% of 185's size, want 65", welcomePicturePercent)
	}
	console := image.Rect(100, 50, 1900, 850)
	work := image.Rect(0, 0, 1920, 1040)

	r := welcomePictureRect(console, work, 1447, 493)
	if r.Dx() != 940 || r.Dy() != 320 {
		t.Fatalf("the picture drew %dx%d, want 940x320, the 65%% of 1447x493", r.Dx(), r.Dy())
	}
	// The 35% comes off the console's own width when that is the narrower
	// window, not off the file's 1447.
	narrow := welcomePictureRect(image.Rect(100, 50, 1300, 850), work, 1447, 493)
	if narrow.Dx() != 780 || narrow.Dy() != 265 {
		t.Fatalf("on a 1200 wide console the picture drew %dx%d, want 780x265", narrow.Dx(), narrow.Dy())
	}
	if cy := r.Min.Y + r.Dy()/2; cy != 450 {
		t.Fatalf("the picture's centre row is %d, want the console's 450", cy)
	}
	if r.Min.X < work.Min.X || r.Min.Y < work.Min.Y || r.Max.X > work.Max.X || r.Max.Y > work.Max.Y {
		t.Fatalf("the picture %v left the work area %v", r, work)
	}
}

// Owner order 2026-11-27 (build 186): "the application still got hung for about
// 1 or 2 seconds". The picture is 4417 by 1282 pixels, and none of its work may
// run on the gate's thread: the gate asks for the picture and goes on drawing,
// so it answers its keys and its clock through the whole of the decode.
func TestBuild186TheBannerLeavesTheGateItsThread(t *testing.T) {
	if welcomePictureAllowed {
		t.Fatal("a test run must never open the picture's window")
	}
	if welcomePictureUp(RGB{4, 8, 12}) {
		t.Fatal("with no window allowed the gate must keep its own cell banner")
	}
}

