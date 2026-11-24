package main

import (
	"strings"
	"time"
	"unicode"
)

// The password gate.
//
// Owner order 2026-11-23: "i will click the windows build open and the window
// will open and then it will ask me for a password". The window opens on the
// box, the box says "Enter password" until it has the keys, and the hint under
// it claims the password is thirteen characters long. That hint is a decoy, on
// his own order: the password is the four digits below and the hint never
// changes to match them. The right one opens the HUD after the welcome line; a
// wrong one gets the taunt, the box is cleared and the gate stays shut.
//
// Owner order 2026-11-23 (later): the gate is one of the build's own tiles, with
// the same frame, diamond title and bright bars as every other panel, the same
// filled input box the forms use, and the same blinking block at the end of the
// box, so the cursor moves exactly as it does on the screens behind it. A click
// on the box takes it: the placeholder goes and the block keeps blinking.
const (
	unlockPassword    = "7861"
	unlockPlaceholder = "Enter password"
	unlockHint        = "HINT: Password contains 13 characters."
	unlockWelcome     = "Welcome back, Mr. Rehan!"
	unlockTaunt       = "Nice try, buddy. Get your punk ahh out of here. HAHAHA!"
	unlockMaxChars    = 16
	unlockWelcomeFor  = 1500 * time.Millisecond
)

// keyLogin owns every key while the gate is up, so nothing he types reaches a
// tile behind it and no shortcut can open the HUD without the password.
func (a *App) keyLogin(k Key) {
	switch k.Kind {
	case KCtrlC, KEsc:
		a.quit = true
	case KEnter:
		a.submitPassword()
	case KMouse:
		if k.Btn == MouseLeft && a.passW > 0 &&
			k.X >= a.passX && k.X < a.passX+a.passW &&
			k.Y >= a.passY && k.Y < a.passY+a.passH {
			a.passFocus = true
			a.passMsg = ""
		}
	case KBackspace:
		if a.passOK {
			return
		}
		a.passFocus = true
		if a.passText == "" {
			return
		}
		r := []rune(a.passText)
		a.passText = string(r[:len(r)-1])
		a.passMsg = ""
	case KRune:
		if a.passOK || !unicode.IsPrint(k.R) || k.R == ' ' {
			return
		}
		a.passFocus = true
		if runeLen(a.passText) >= unlockMaxChars {
			return
		}
		a.passText += string(k.R)
		a.passMsg = ""
	}
}

// submitPassword judges the box. The welcome is shown on the gate for a moment
// before the HUD takes the screen, so he reads the line he asked for.
func (a *App) submitPassword() {
	if a.passOK {
		return
	}
	if a.passText == unlockPassword {
		a.passOK = true
		a.passMsg = unlockWelcome
		a.unlockAt = a.now.Add(unlockWelcomeFor)
		return
	}
	a.passMsg = unlockTaunt
	a.passText = ""
}

// loginOpens says whether the welcome has been read and the HUD may take over.
func (a *App) loginOpens(now time.Time) bool {
	return a.locked && a.passOK && !now.Before(a.unlockAt)
}

// drawLogin paints the gate as one of the build's own tiles: the panel frame
// with its diamond and bright bars, the password field built like the forms'
// input boxes, the decoy hint and the last verdict, and the blinking block at
// the end of the field while it has the keys. The field's cells are kept on the
// app so a mouse click can take it.
func (a *App) drawLogin(c *Canvas) {
	th := a.th
	w, h := c.W, c.H
	if w < 12 || h < 8 {
		return
	}
	// Owner order 2026-11-23 (latest): the taunt ends HAHAHA!, which is 55
	// cells, so the tile is two cells wider than it was and the whole sentence
	// lands on the gate instead of losing its last letter.
	pw := min(60, w)
	ph := min(9, h)
	px, py := (w-pw)/2, (h-ph)/2
	// Owner order 2026-11-24: the gate's tile is headed SIGN IN, not the brand.
	ix, iy, iw, _ := a.panel(c, px, py, pw, ph, "SIGN IN", "")

	// The input box, exactly as inputRow draws one: the same fill, the same
	// placeholder ink and the same block cursor.
	const labelW = 10
	c.Text(ix, iy+1, labelW, "PASSWORD", th.Soft, false)
	bx := ix + labelW
	bw := max(6, min(iw-labelW, 34))
	field := mix(th.Panel, th.Accent, 0.3)
	for k := 0; k < bw; k++ {
		c.Set(bx+k, iy+1, ' ', th.Text, field, false)
	}
	masked := strings.Repeat("*", runeLen(a.passText))
	switch {
	case a.passText != "":
		c.Text(bx+1, iy+1, bw-2, fit(masked, bw-2), th.Hot, true)
	case !a.passFocus:
		// The placeholder stands until the box is clicked or typed in.
		c.Text(bx+1, iy+1, bw-2, unlockPlaceholder, mix(th.Soft, th.Panel, 0.25), false)
	}
	// The same blink the calculator's and the forms' boxes use: half a second
	// on, half a second off, from the frame clock.
	if a.passFocus && !a.passOK && int(a.animSeconds()*2)%2 == 0 {
		at := bx + 1 + min(runeLen(masked), bw-3)
		c.Set(at, iy+1, '█', th.Accent, field, false)
	}

	if iw >= runeLen(unlockHint)+2 {
		c.Text(ix+max(0, (iw-runeLen(unlockHint))/2), iy+3, iw, unlockHint, th.Soft, false)
	}
	if a.passMsg != "" && ph >= 8 {
		ink := th.Bad
		if a.passOK {
			ink = th.Good
		}
		c.Text(ix+max(0, (iw-runeLen(a.passMsg))/2), iy+5, iw, a.passMsg, ink, true)
	}

	a.passX, a.passY, a.passW, a.passH = bx, iy+1, bw, 1
}
