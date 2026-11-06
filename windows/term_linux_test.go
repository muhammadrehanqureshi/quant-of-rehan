//go:build linux

package main

import "testing"

func TestSGRMouseReports(t *testing.T) {
	u := &unixTerm{keys: make(chan Key, 8)}
	get := func() Key {
		select {
		case k := <-u.keys:
			return k
		default:
			return Key{}
		}
	}
	u.csi([]byte("<0;12;5"), 'M') // left press at column 12, row 5 (1 based)
	if k := get(); k.Kind != KMouse || k.Btn != MouseLeft || k.X != 11 || k.Y != 4 {
		t.Errorf("press: %+v", k)
	}
	u.csi([]byte("<0;12;5"), 'm') // release is ignored
	if k := get(); k.Kind == KMouse {
		t.Errorf("release must be ignored: %+v", k)
	}
	u.csi([]byte("<35;20;7"), 'M') // motion with no button
	if k := get(); k.Btn != MouseMove || k.X != 19 || k.Y != 6 {
		t.Errorf("motion: %+v", k)
	}
	u.csi([]byte("<64;1;1"), 'M')
	if k := get(); k.Btn != MouseWheelUp {
		t.Errorf("wheel up: %+v", k)
	}
	u.csi([]byte("<65;1;1"), 'M')
	if k := get(); k.Btn != MouseWheelDown {
		t.Errorf("wheel down: %+v", k)
	}
	u.csi([]byte("<2;3;3"), 'M')
	if k := get(); k.Btn != MouseRight {
		t.Errorf("right: %+v", k)
	}
	u.csi([]byte("15"), '~')
	if k := get(); k.Kind != KF5 {
		t.Errorf("F5: %+v", k)
	}
	u.csi([]byte("5"), '~')
	if k := get(); k.Kind != KPgUp {
		t.Errorf("Page Up: %+v", k)
	}
	u.csi([]byte("6"), '~')
	if k := get(); k.Kind != KPgDn {
		t.Errorf("Page Down: %+v", k)
	}
}
