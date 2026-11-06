//go:build linux

package main

import (
	"os"
	"syscall"
	"time"
	"unsafe"
)

// Mouse reporting is switched on with escape codes here; the Windows console
// takes mouse records instead.
const (
	mouseOnSeq  = "\x1b[?1003h\x1b[?1006h"
	mouseOffSeq = "\x1b[?1003l\x1b[?1006l"
)

// The Linux terminal exists so the program can be run and tested here. The
// product is the Windows build.
type unixTerm struct {
	old  syscall.Termios
	have bool
	keys chan Key
	raw  chan byte
}

func newTerm() Term {
	return &unixTerm{keys: make(chan Key, 64), raw: make(chan byte, 256)}
}

func (t *unixTerm) Write(p []byte) (int, error) { return os.Stdout.Write(p) }

func ioctl(fd, req uintptr, arg unsafe.Pointer) error {
	if _, _, e := syscall.Syscall(syscall.SYS_IOCTL, fd, req, uintptr(arg)); e != 0 {
		return e
	}
	return nil
}

func (t *unixTerm) Init() error {
	fd := os.Stdin.Fd()
	if err := ioctl(fd, syscall.TCGETS, unsafe.Pointer(&t.old)); err == nil {
		t.have = true
		raw := t.old
		raw.Iflag &^= syscall.ICRNL | syscall.IXON | syscall.INLCR | syscall.ISTRIP | syscall.BRKINT
		raw.Lflag &^= syscall.ICANON | syscall.ECHO | syscall.ISIG | syscall.IEXTEN
		raw.Cc[syscall.VMIN] = 1
		raw.Cc[syscall.VTIME] = 0
		if err := ioctl(fd, syscall.TCSETS, unsafe.Pointer(&raw)); err != nil {
			return err
		}
	}
	go func() {
		buf := make([]byte, 64)
		for {
			n, err := os.Stdin.Read(buf)
			if err != nil || n == 0 {
				close(t.raw)
				return
			}
			for _, b := range buf[:n] {
				t.raw <- b
			}
		}
	}()
	go t.parse()
	return nil
}

func (t *unixTerm) Restore() {
	if t.have {
		_ = ioctl(os.Stdin.Fd(), syscall.TCSETS, unsafe.Pointer(&t.old))
	}
}

func (t *unixTerm) Size() (int, int) {
	var ws struct{ Row, Col, X, Y uint16 }
	if err := ioctl(os.Stdout.Fd(), syscall.TIOCGWINSZ, unsafe.Pointer(&ws)); err == nil && ws.Col > 0 && ws.Row > 0 {
		return int(ws.Col), int(ws.Row)
	}
	return envSize()
}

func (t *unixTerm) Keys() <-chan Key { return t.keys }

func (t *unixTerm) next(timeout time.Duration) (byte, bool) {
	select {
	case b, ok := <-t.raw:
		return b, ok
	case <-time.After(timeout):
		return 0, false
	}
}

func (t *unixTerm) emit(k Key) {
	select {
	case t.keys <- k:
	default:
	}
}

func (t *unixTerm) parse() {
	for {
		b, ok := <-t.raw
		if !ok {
			close(t.keys)
			return
		}
		switch {
		case b == 0x03:
			t.emit(Key{Kind: KCtrlC})
		case b == '\r' || b == '\n':
			t.emit(Key{Kind: KEnter})
		case b == '\t':
			t.emit(Key{Kind: KTab})
		case b == 0x7f || b == 0x08:
			t.emit(Key{Kind: KBackspace})
		case b == 0x1b:
			t.parseEsc()
		case b >= 32 && b < 127:
			t.emit(Key{Kind: KRune, R: rune(b)})
		}
	}
}

func (t *unixTerm) parseEsc() {
	b, ok := t.next(30 * time.Millisecond)
	if !ok {
		t.emit(Key{Kind: KEsc})
		return
	}
	switch b {
	case 'O':
		c, _ := t.next(30 * time.Millisecond)
		if c >= 'P' && c <= 'S' {
			t.emit(Key{Kind: KF1 + KeyKind(c-'P')})
		}
	case '[':
		var params []byte
		for {
			c, ok := t.next(30 * time.Millisecond)
			if !ok {
				return
			}
			if c >= 0x40 && c <= 0x7e {
				t.csi(params, c)
				return
			}
			params = append(params, c)
		}
	}
}

func (t *unixTerm) csi(params []byte, final byte) {
	// SGR mouse report: ESC [ < b ; x ; y M (press or motion) or m (release).
	if len(params) > 0 && params[0] == '<' && (final == 'M' || final == 'm') {
		var v [3]int
		i := 0
		for _, c := range params[1:] {
			if c == ';' {
				i++
				if i > 2 {
					return
				}
				continue
			}
			if c >= '0' && c <= '9' {
				v[i] = v[i]*10 + int(c-'0')
			}
		}
		k := Key{Kind: KMouse, X: v[1] - 1, Y: v[2] - 1}
		switch {
		case final == 'm':
			return
		case v[0]&64 != 0 && v[0]&3 == 0:
			k.Btn = MouseWheelUp
		case v[0]&64 != 0:
			k.Btn = MouseWheelDown
		case v[0]&32 != 0:
			k.Btn = MouseMove
		case v[0]&3 == 0:
			k.Btn = MouseLeft
		case v[0]&3 == 2:
			k.Btn = MouseRight
		default:
			return
		}
		t.emit(k)
		return
	}
	switch final {
	case 'A':
		t.emit(Key{Kind: KUp})
	case 'B':
		t.emit(Key{Kind: KDown})
	case 'C':
		t.emit(Key{Kind: KRight})
	case 'D':
		t.emit(Key{Kind: KLeft})
	case 'H':
		t.emit(Key{Kind: KHome})
	case 'F':
		t.emit(Key{Kind: KEnd})
	case 'Z':
		t.emit(Key{Kind: KTab, Shift: true})
	case '~':
		switch string(params) {
		case "1":
			t.emit(Key{Kind: KHome})
		case "3":
			t.emit(Key{Kind: KDel})
		case "4":
			t.emit(Key{Kind: KEnd})
		case "5":
			t.emit(Key{Kind: KPgUp})
		case "6":
			t.emit(Key{Kind: KPgDn})
		case "15":
			t.emit(Key{Kind: KF5})
		}
	}
}
