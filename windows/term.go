package main

import (
	"io"
	"os"
	"strconv"
)

// KeyKind names a key press.
type KeyKind int

const (
	KRune KeyKind = iota
	KUp
	KDown
	KLeft
	KRight
	KEnter
	KEsc
	KTab
	KBackspace
	KF1
	KF2
	KF3
	KF4
	KF5
	KF6
	KCtrlC
	KHome
	KEnd
	KDel
	KMouse
	KPgUp
	KPgDn
)

// Key is one decoded key press.
type Key struct {
	Kind  KeyKind
	R     rune
	Shift bool
	// Mouse events carry the cell (0 based) and what happened.
	X, Y int
	Btn  MouseBtn
}

// MouseBtn says what a mouse event was.
type MouseBtn int

const (
	MouseNone  MouseBtn = iota
	MouseLeft           // left button went down
	MouseRight          // right button went down
	MouseMove           // pointer moved
	MouseWheelUp
	MouseWheelDown
)

// Term is the console. Each platform provides newTerm.
type Term interface {
	Init() error
	Restore()
	Size() (w, h int)
	Keys() <-chan Key
	io.Writer
}

const (
	escAltOn   = "\x1b[?1049h"
	escAltOff  = "\x1b[?1049l"
	escHide    = "\x1b[?25l"
	escShow    = "\x1b[?25h"
	escClear   = "\x1b[2J"
	escReset   = "\x1b[0m"
	escSyncOn  = "\x1b[?2026h"
	escSyncOff = "\x1b[?2026l"
)

func escMove(row, col int) string {
	return "\x1b[" + strconv.Itoa(row) + ";" + strconv.Itoa(col) + "H"
}

func escTitle(t string) string { return "\x1b]0;" + t + "\x07" }

func envSize() (int, int) {
	w, h := 120, 30
	if v, err := strconv.Atoi(os.Getenv("COLUMNS")); err == nil && v > 0 {
		w = v
	}
	if v, err := strconv.Atoi(os.Getenv("LINES")); err == nil && v > 0 {
		h = v
	}
	return w, h
}

// Console mouse record bits (MOUSE_EVENT_RECORD).
const (
	mouseMoved       = 0x0001
	mouseWheeled     = 0x0004
	mouseLeftButton  = 0x0001
	mouseRightButton = 0x0002
)

// decodeMouse turns the fields of a Windows console mouse record into a Key. A
// press is reported on the record where the button goes down, not while it
// stays down, so last carries the buttons held at the previous record. It
// reports false for records that mean nothing to the app, such as a button
// coming back up.
func decodeMouse(x, y int, buttons, flags uint32, last *uint32) (Key, bool) {
	k := Key{Kind: KMouse, X: x, Y: y}
	switch {
	case flags&mouseWheeled != 0:
		// The high word of the button state is the signed wheel delta.
		if int16(buttons>>16) > 0 {
			k.Btn = MouseWheelUp
		} else {
			k.Btn = MouseWheelDown
		}
	case flags&mouseMoved != 0:
		k.Btn = MouseMove
	default:
		down := buttons &^ *last
		switch {
		case down&mouseLeftButton != 0:
			k.Btn = MouseLeft
		case down&mouseRightButton != 0:
			k.Btn = MouseRight
		}
	}
	*last = buttons & (mouseLeftButton | mouseRightButton)
	return k, k.Btn != MouseNone
}
