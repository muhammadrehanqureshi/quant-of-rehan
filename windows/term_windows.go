//go:build windows

package main

import (
	"os"
	"syscall"
	"unicode/utf16"
	"unsafe"
)

var (
	kernel32                    = syscall.NewLazyDLL("kernel32.dll")
	pGetConsoleMode             = kernel32.NewProc("GetConsoleMode")
	pSetConsoleMode             = kernel32.NewProc("SetConsoleMode")
	pReadConsoleInputW          = kernel32.NewProc("ReadConsoleInputW")
	pGetConsoleScreenBufferInfo = kernel32.NewProc("GetConsoleScreenBufferInfo")
	pSetConsoleOutputCP         = kernel32.NewProc("SetConsoleOutputCP")
	pSetConsoleCP               = kernel32.NewProc("SetConsoleCP")
	pGetConsoleOutputCP         = kernel32.NewProc("GetConsoleOutputCP")
	pGetConsoleCP               = kernel32.NewProc("GetConsoleCP")
)

const (
	enableProcessedInput = 0x0001
	enableLineInput      = 0x0002
	enableEchoInput      = 0x0004
	enableWindowInput    = 0x0008
	enableMouseInput     = 0x0010
	enableQuickEdit      = 0x0040
	enableExtendedFlags  = 0x0080

	enableProcessedOutput = 0x0001
	enableWrapAtEOL       = 0x0002
	enableVTProcessing    = 0x0004

	keyEvent   = 0x0001
	mouseEvent = 0x0002

	vkBack   = 0x08
	vkTab    = 0x09
	vkReturn = 0x0D
	vkEscape = 0x1B
	vkPrior  = 0x21
	vkNext   = 0x22
	vkEnd    = 0x23
	vkHome   = 0x24
	vkLeft   = 0x25
	vkUp     = 0x26
	vkRight  = 0x27
	vkDown   = 0x28
	vkDelete = 0x2E
	vkF1     = 0x70

	shiftPressed = 0x0010
)

const (
	mouseOnSeq  = ""
	mouseOffSeq = ""
)

type coord struct{ X, Y int16 }
type smallRect struct{ Left, Top, Right, Bottom int16 }
type consoleScreenBufferInfo struct {
	Size              coord
	CursorPosition    coord
	Attributes        uint16
	Window            smallRect
	MaximumWindowSize coord
}

// inputRecord is the 20 byte INPUT_RECORD; only key events are decoded.
type inputRecord struct {
	EventType       uint16
	_               uint16
	KeyDown         int32
	RepeatCount     uint16
	VirtualKeyCode  uint16
	VirtualScanCode uint16
	UnicodeChar     uint16
	ControlKeyState uint32
}

// mouseRecord is the same 20 bytes seen as a MOUSE_EVENT_RECORD.
type mouseRecord struct {
	EventType       uint16
	_               uint16
	X, Y            int16
	ButtonState     uint32
	ControlKeyState uint32
	EventFlags      uint32
}

type winTerm struct {
	hIn, hOut       syscall.Handle
	inMode, outMode uint32
	inCP, outCP     uint32
	keys            chan Key
	haveIn, haveOut bool
	stdout          *os.File
}

func newTerm() Term {
	return &winTerm{stdout: os.Stdout, keys: make(chan Key, 64)}
}

func (t *winTerm) Write(p []byte) (int, error) { return t.stdout.Write(p) }

func (t *winTerm) Init() error {
	var err error
	if t.hIn, err = syscall.GetStdHandle(syscall.STD_INPUT_HANDLE); err != nil {
		return err
	}
	if t.hOut, err = syscall.GetStdHandle(syscall.STD_OUTPUT_HANDLE); err != nil {
		return err
	}
	if r, _, e := pGetConsoleMode.Call(uintptr(t.hIn), uintptr(unsafe.Pointer(&t.inMode))); r == 0 {
		return e
	}
	t.haveIn = true
	if r, _, e := pGetConsoleMode.Call(uintptr(t.hOut), uintptr(unsafe.Pointer(&t.outMode))); r == 0 {
		return e
	}
	t.haveOut = true
	cp, _, _ := pGetConsoleOutputCP.Call()
	t.outCP = uint32(cp)
	cpi, _, _ := pGetConsoleCP.Call()
	t.inCP = uint32(cpi)

	// Output: let the console understand colour and cursor sequences.
	om := t.outMode | enableProcessedOutput | enableWrapAtEOL | enableVTProcessing
	if r, _, e := pSetConsoleMode.Call(uintptr(t.hOut), uintptr(om)); r == 0 {
		return e
	}
	// Input: raw keys, no echo, no line editing, and no quick edit (a stray
	// click in quick edit mode would freeze the screen).
	im := (t.inMode &^ (enableProcessedInput | enableLineInput | enableEchoInput | enableQuickEdit)) |
		enableExtendedFlags | enableWindowInput | enableMouseInput
	if r, _, e := pSetConsoleMode.Call(uintptr(t.hIn), uintptr(im)); r == 0 {
		return e
	}
	pSetConsoleOutputCP.Call(65001)
	pSetConsoleCP.Call(65001)
	go t.readLoop()
	return nil
}

func (t *winTerm) Restore() {
	if t.haveIn {
		pSetConsoleMode.Call(uintptr(t.hIn), uintptr(t.inMode))
	}
	if t.haveOut {
		pSetConsoleMode.Call(uintptr(t.hOut), uintptr(t.outMode))
	}
	if t.outCP != 0 {
		pSetConsoleOutputCP.Call(uintptr(t.outCP))
	}
	if t.inCP != 0 {
		pSetConsoleCP.Call(uintptr(t.inCP))
	}
}

func (t *winTerm) Size() (int, int) {
	var info consoleScreenBufferInfo
	r, _, _ := pGetConsoleScreenBufferInfo.Call(uintptr(t.hOut), uintptr(unsafe.Pointer(&info)))
	if r == 0 {
		return envSize()
	}
	w := int(info.Window.Right-info.Window.Left) + 1
	h := int(info.Window.Bottom-info.Window.Top) + 1
	if w < 1 || h < 1 {
		return envSize()
	}
	return w, h
}

func (t *winTerm) Keys() <-chan Key { return t.keys }

// onMouse turns a console mouse record into a Key and queues it.
func (t *winTerm) onMouse(m *mouseRecord, last *uint32) {
	k, ok := decodeMouse(int(m.X), int(m.Y), m.ButtonState, m.EventFlags, last)
	if !ok {
		return
	}
	select {
	case t.keys <- k:
	default:
	}
}

func (t *winTerm) readLoop() {
	var rec inputRecord
	var n uint32
	var pendingHigh uint16
	var lastBtn uint32
	for {
		r, _, _ := pReadConsoleInputW.Call(uintptr(t.hIn), uintptr(unsafe.Pointer(&rec)), 1, uintptr(unsafe.Pointer(&n)))
		if r == 0 {
			close(t.keys)
			return
		}
		if n == 0 {
			continue
		}
		if rec.EventType == mouseEvent {
			t.onMouse((*mouseRecord)(unsafe.Pointer(&rec)), &lastBtn)
			continue
		}
		if rec.EventType != keyEvent || rec.KeyDown == 0 {
			continue
		}
		shift := rec.ControlKeyState&shiftPressed != 0
		var k Key
		switch vk := rec.VirtualKeyCode; {
		case vk == vkUp:
			k = Key{Kind: KUp}
		case vk == vkDown:
			k = Key{Kind: KDown}
		case vk == vkLeft:
			k = Key{Kind: KLeft}
		case vk == vkRight:
			k = Key{Kind: KRight}
		case vk == vkReturn:
			k = Key{Kind: KEnter}
		case vk == vkEscape:
			k = Key{Kind: KEsc}
		case vk == vkTab:
			k = Key{Kind: KTab, Shift: shift}
		case vk == vkBack:
			k = Key{Kind: KBackspace}
		case vk == vkPrior:
			k = Key{Kind: KPgUp}
		case vk == vkNext:
			k = Key{Kind: KPgDn}
		case vk == vkHome:
			k = Key{Kind: KHome}
		case vk == vkEnd:
			k = Key{Kind: KEnd}
		case vk == vkDelete:
			k = Key{Kind: KDel}
		case vk >= vkF1 && vk <= vkF1+5:
			k = Key{Kind: KF1 + KeyKind(vk-vkF1)}
		case rec.UnicodeChar == 3:
			k = Key{Kind: KCtrlC}
		case rec.UnicodeChar >= 32:
			u := rec.UnicodeChar
			if u >= 0xD800 && u < 0xDC00 {
				pendingHigh = u
				continue
			}
			ru := rune(u)
			if u >= 0xDC00 && u < 0xE000 && pendingHigh != 0 {
				ru = utf16.DecodeRune(rune(pendingHigh), rune(u))
			}
			pendingHigh = 0
			k = Key{Kind: KRune, R: ru}
		default:
			continue
		}
		select {
		case t.keys <- k:
		default: // never block the console reader
		}
	}
}
