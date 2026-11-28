package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-28 (build 189): "the build's screen/interface is still not
// in the center of the console". The window is put in the middle of the space
// the taskbar leaves, on whatever monitor it stands on, whichever shell started
// the build.

// The middle of the work area is the window's middle: the air on its left is
// the air on its right and the air above it is the air below it, to within the
// odd pixel a size and a screen cannot split in two.
func TestTheWindowLandsOnTheMiddleOfItsWorkArea(t *testing.T) {
	cases := []struct {
		name string
		work consoleRect
		w, h int
		x, y int
	}{
		{"one screen, a window with an even gap", consoleRect{0, 0, 1920, 1040}, 1140, 680, 390, 180},
		{"a gap of an odd number of pixels", consoleRect{0, 0, 1920, 1040}, 1000, 501, 460, 269},
		{"the second screen's own corner", consoleRect{1920, 0, 3840, 1040}, 1000, 500, 2380, 270},
		{"a screen with the taskbar on top", consoleRect{0, 40, 1280, 1024}, 800, 600, 240, 232},
	}
	for _, c := range cases {
		x, y := consoleCentreTarget(c.work, c.w, c.h)
		if x != c.x || y != c.y {
			t.Errorf("%s: the window lands on %d,%d, want %d,%d", c.name, x, y, c.x, c.y)
		}
		left := x - int(c.work.left)
		right := int(c.work.right) - (x + c.w)
		if diff := left - right; diff > 1 || diff < -1 {
			t.Errorf("%s: %d pixels of screen before the window, %d after it", c.name, left, right)
		}
		above := y - int(c.work.top)
		below := int(c.work.bottom) - (y + c.h)
		if diff := above - below; diff > 1 || diff < -1 {
			t.Errorf("%s: %d pixels of screen above the window, %d below it", c.name, above, below)
		}
	}
}

// Owner order 2026-11-28 (build 189): "remove the welcome banner from the
// build, because it looks nothing like how I want it." The picture and its
// dots stay withdrawn. Owner order 2026-11-28 (build 191): the gate answers the
// right password with "Welcome back! Mr. Rehan." and the HUD takes the screen
// when that answer has been read, so this frame carries the gate and no banner.
func TestTheFrameAfterThePasswordCarriesNoBanner(t *testing.T) {
	a := lockedApp(t, 100, 30)
	typeRunes(a, wantUnlockPassword)
	a.onKey(Key{Kind: KEnter})
	if !a.passOK {
		t.Fatal("the right password was not taken")
	}
	joined := strings.Join(a.render().PlainRows(), "\n")
	if hasBasmala(joined) {
		t.Fatalf("the welcome banner is drawn after the password:\n%s", joined)
	}
	if strings.Contains(joined, strings.Repeat(string(bannerDot), 2)) {
		t.Fatalf("the dotted banner is drawn after the password:\n%s", joined)
	}
	if !strings.Contains(joined, unlockWelcome) {
		t.Fatalf("the gate does not answer the password with the welcome:\n%s", joined)
	}
	a.onTick(a.now.Add(unlockWelcomeFor))
	if a.locked {
		t.Fatal("the gate stayed shut instead of handing the screen to the HUD")
	}
}
