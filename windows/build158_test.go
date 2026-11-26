package main

import (
	"fmt"
	"strings"
	"testing"
	"time"
)

// Owner order 2026-11-23: the window opens on the password box, the box says
// "Enter password", and the hint under it claims thirteen characters. The
// password is four digits and the hint is never corrected to match them.
const (
	wantUnlockPlaceholder = "Enter password"
	wantUnlockHint        = "HINT: Password contains 13 characters."
	wantUnlockTaunt       = "Nice try, buddy. Get your punk ahh out of here. HAHAHA!"
	wantUnlockPassword    = "7861"
)

func lockedApp(t *testing.T, w, h int) *App {
	t.Helper()
	a := demoApp(t, w, h)
	a.locked = true
	a.now = time.Date(2026, 10, 30, 11, 42, 18, 0, pkt)
	return a
}

func screenOf(a *App) string {
	return strings.Join(a.render().PlainRows(), "\n")
}

func typeRunes(a *App, s string) {
	for _, r := range s {
		a.onKey(Key{Kind: KRune, R: r})
	}
}

func TestTheBuildOpensOnThePasswordBox(t *testing.T) {
	a := lockedApp(t, 100, 30)
	rows := screenOf(a)
	if !strings.Contains(rows, wantUnlockPlaceholder) {
		t.Fatalf("the box does not say %q:\n%s", wantUnlockPlaceholder, rows)
	}
	if !strings.Contains(rows, wantUnlockHint) {
		t.Fatalf("the hint is missing:\n%s", rows)
	}
	if strings.Contains(rows, wantUnlockPassword) {
		t.Fatalf("the gate prints the password itself:\n%s", rows)
	}
	// Nothing of the HUD is drawn behind the gate.
	for _, tile := range []string{"ORDER FLOW", "CUSTOM SCRIPS", "ALERTS LOG"} {
		if strings.Contains(rows, tile) {
			t.Fatalf("the gate drew the HUD's %s tile behind it:\n%s", tile, rows)
		}
	}
}

func TestTheRightPasswordWelcomesHimThenOpensTheHud(t *testing.T) {
	a := lockedApp(t, 100, 30)
	typeRunes(a, wantUnlockPassword)
	a.onKey(Key{Kind: KEnter})
	if !a.locked {
		t.Fatal("the HUD took the screen before the splash was read")
	}
	if rows := screenOf(a); !strings.Contains(rows, unlockBasmala) {
		t.Fatalf("the basmala is not on the gate:\n%s", rows)
	}
	if a.passText != wantUnlockPassword {
		t.Fatalf("the box lost the password: %q", a.passText)
	}
	a.onTick(a.now.Add(unlockWelcomeFor))
	if a.locked {
		t.Fatal("the gate stayed shut after the right password")
	}
	if a.passText != "" || a.passMsg != "" {
		t.Fatalf("the gate kept its state after opening: %q %q", a.passText, a.passMsg)
	}
	if rows := screenOf(a); strings.Contains(rows, wantUnlockHint) {
		t.Fatalf("the gate is still drawn after opening:\n%s", rows)
	}
}

func TestTheWrongPasswordGetsTheTauntAndStaysShut(t *testing.T) {
	a := lockedApp(t, 100, 30)
	typeRunes(a, "786")
	a.onKey(Key{Kind: KEnter})
	if a.passMsg != wantUnlockTaunt {
		t.Fatalf("a wrong password says %q, want %q", a.passMsg, wantUnlockTaunt)
	}
	if !a.locked {
		t.Fatal("a wrong password opened the HUD")
	}
	if a.passText != "" {
		t.Fatalf("the wrong password is still in the box: %q", a.passText)
	}
	if rows := screenOf(a); !strings.Contains(rows, wantUnlockTaunt) {
		t.Fatalf("the taunt is not on the gate:\n%s", rows)
	}
	// A wrong attempt never opens the gate, however long he waits.
	a.onTick(a.now.Add(time.Hour))
	if !a.locked {
		t.Fatal("waiting opened the gate without the password")
	}
	// Typing after a refusal clears the taunt instead of leaving it under the box.
	a.onKey(Key{Kind: KRune, R: '7'})
	if a.passMsg != "" {
		t.Fatalf("the taunt survived the first new digit: %q", a.passMsg)
	}
	// And the password is right after the refusal.
	typeRunes(a, wantUnlockPassword[1:])
	a.onKey(Key{Kind: KEnter})
	if !a.passOK {
		t.Fatal("the second try did not take the password")
	}
}

func TestTheGateMasksWhatHeTypes(t *testing.T) {
	a := lockedApp(t, 100, 30)
	typeRunes(a, "78")
	rows := screenOf(a)
	if strings.Contains(rows, "78") {
		t.Fatalf("the gate shows the digits he typed:\n%s", rows)
	}
	if !strings.Contains(rows, "**") {
		t.Fatalf("the box does not mask the digits:\n%s", rows)
	}
	a.onKey(Key{Kind: KBackspace})
	if a.passText != "7" {
		t.Fatalf("BACKSPACE left %q, want one digit", a.passText)
	}
}

func TestEscapeClosesTheGate(t *testing.T) {
	a := lockedApp(t, 100, 30)
	a.onKey(Key{Kind: KEsc})
	if !a.quit {
		t.Fatal("ESC did not close the window")
	}
}

// The gate is drawn at every window size the HUD itself must survive, so a
// small console shows what fits instead of nothing at all.
func TestTheGateDrawsAtEverySize(t *testing.T) {
	for _, sz := range [][2]int{{1, 1}, {12, 8}, {40, 12}, {80, 24}, {100, 30}, {160, 45}, {240, 70}} {
		t.Run(fmt.Sprintf("%dx%d", sz[0], sz[1]), func(t *testing.T) {
			a := lockedApp(t, sz[0], sz[1])
			c := a.render()
			if c.W != sz[0] || c.H != sz[1] {
				t.Fatalf("the gate drew %dx%d, want %dx%d", c.W, c.H, sz[0], sz[1])
			}
			// Thirty seven characters of hint need a panel wide enough to hold
			// them; below that the window is too small for the gate's full line.
			if c.W >= 44 && c.H >= 12 {
				if rows := strings.Join(c.PlainRows(), "\n"); !strings.Contains(rows, wantUnlockHint) {
					t.Fatalf("the hint is missing at %dx%d:\n%s", sz[0], sz[1], rows)
				}
			}
		})
	}
}

// Owner order 2026-11-23: every dot of the green orb is one shade of green at
// the near edge as in the middle. The globe's own tests (build10_test.go and
// sphere_test.go) pin that too; this one pins the shade the HUD draws with, so
// a theme's green cannot slip back to a mixed one.
func TestTheGreenGlobeIsTheThemeSOneGreen(t *testing.T) {
	a := demoApp(t, 122, 36)
	c := NewCanvas(38, 14, a.th.Panel)
	drawSphere(c, 0, 0, 38, 14, 3.0, true, a.th)
	want := a.th.Good
	lit := 0
	for _, ce := range c.Cells {
		if ce.Ch < 0x2800 || ce.Ch > 0x28ff {
			continue
		}
		lit++
		if ce.FG != want {
			t.Fatalf("a green dot is %v, want the one green %v", ce.FG, want)
		}
	}
	if lit == 0 {
		t.Fatal("the green globe painted no dots")
	}
}

// The green window the owner named: before the open, the session and after the
// close are all green; the break in the middle is not, as build 3.8.30 already
// ruled.
func TestTheGlobeIsGreenBeforeDuringAndAfterTheSession(t *testing.T) {
	a := newTestApp(t)
	at := func(month time.Month, day, hour, minute int) bool {
		a.now = time.Date(2026, month, day, hour, minute, 0, 0, pkt)
		return a.orbGreen()
	}
	if !at(time.November, 23, 9, 20) {
		t.Fatal("the mark is not green before the open")
	}
	if !at(time.November, 23, 11, 0) {
		t.Fatal("the mark is not green during the session")
	}
	if !at(time.November, 23, 15, 40) {
		t.Fatal("the mark is not green after the close")
	}
}
