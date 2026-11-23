package main

import (
	"time"
	"unicode"
)

// The password gate.
//
// Owner order 2026-11-23: "i will click the windows build open and the window
// will open and then it will ask me for a password". The window opens on the
// box, the box says "Enter password" until he types, and the hint under it
// claims the password is thirteen characters long. That hint is a decoy, on his
// own order: the password is the four digits below and the hint never changes
// to match them. The right one opens the HUD after the welcome line; a wrong
// one gets the taunt, the box is cleared and the gate stays shut.
const (
	unlockPassword    = "7861"
	unlockPlaceholder = "Enter password"
	unlockHint        = "HINT: Password contains 13 characters."
	unlockWelcome     = "Welcome back, Mr. Rehan!"
	unlockTaunt       = "Nice try, buddy. Get your punk ahh out of here."
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
	case KBackspace:
		if a.passOK || a.passText == "" {
			return
		}
		r := []rune(a.passText)
		a.passText = string(r[:len(r)-1])
		a.passMsg = ""
	case KRune:
		if a.passOK || !unicode.IsPrint(k.R) || k.R == ' ' {
			return
		}
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

// drawLogin paints the gate: the mark's name, the password box with its
// placeholder or its masked digits, the decoy hint and the last verdict.
func (a *App) drawLogin(c *Canvas) {
	th := a.th
	w, h := c.W, c.H
	if w < 12 || h < 8 {
		return
	}
	// The panel is as wide as the window when the window is narrow, so the
	// hint's 37 characters are never cut: thirteen is the number it must show.
	bw := min(58, w)
	bh := min(11, h)
	bx := (w - bw) / 2
	by := (h - bh) / 2

	c.Fill(bx, by, bw, bh, th.Panel)
	c.Put(bx, by, '┏', th.Line, false)
	c.Put(bx+bw-1, by, '┓', th.Line, false)
	c.Put(bx, by+bh-1, '┗', th.Line, false)
	c.Put(bx+bw-1, by+bh-1, '┛', th.Line, false)
	c.HLine(bx+1, by, bw-2, '─', th.Line)
	c.HLine(bx+1, by+bh-1, bw-2, '─', th.Line)
	if bw >= 6 {
		c.HLine(bx+bw-4, by+bh-1, 3, '━', th.Accent)
	}

	inside := bw - 2
	centred := func(y int, s string, fg RGB, bold bool) {
		x := bx + 1 + max(0, (inside-runeLen(s))/2)
		c.Text(x, y, inside, s, fg, bold)
	}

	centred(by+1, "QUANT OF REHAN", th.Hot, true)

	// The password box, the same field the HUD's own forms use.
	fw := min(inside-2, 34)
	fx := bx + 1 + (inside-fw)/2
	fy := by + 3
	c.Fill(fx, fy, fw, 3, th.Field)
	c.Put(fx, fy, '┏', th.Line, false)
	c.Put(fx+fw-1, fy, '┓', th.Line, false)
	c.Put(fx, fy+2, '┗', th.Line, false)
	c.Put(fx+fw-1, fy+2, '┛', th.Line, false)
	c.HLine(fx+1, fy, fw-2, '─', th.Line)
	c.HLine(fx+1, fy+2, fw-2, '─', th.Line)
	shown := unlockPlaceholder
	ink := th.Soft
	if a.passText != "" {
		shown, ink = "", th.Accent
		for range a.passText {
			shown += "*"
		}
	}
	tx := fx + 2
	room := fw - 4
	n := c.Text(tx, fy+1, room, shown, ink, a.passText != "")
	if !a.passOK && n < room {
		c.Put(tx+n, fy+1, '█', th.Hot, false)
	}

	if bh > 7 {
		centred(fy+4, unlockHint, th.Soft, false)
	}
	if bh > 9 && a.passMsg != "" {
		msgInk := th.Bad
		if a.passOK {
			msgInk = th.Good
		}
		centred(by+bh-2, a.passMsg, msgInk, true)
	}
}
