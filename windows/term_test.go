package main

import "testing"

func TestDecodeMouse(t *testing.T) {
	var last uint32
	// Pointer moves.
	if k, ok := decodeMouse(10, 4, 0, mouseMoved, &last); !ok || k.Btn != MouseMove || k.X != 10 || k.Y != 4 {
		t.Errorf("move: %+v %v", k, ok)
	}
	// A left press reports once, however many records follow while held.
	if k, ok := decodeMouse(10, 4, mouseLeftButton, 0, &last); !ok || k.Btn != MouseLeft {
		t.Errorf("press: %+v %v", k, ok)
	}
	if _, ok := decodeMouse(10, 4, mouseLeftButton, 0, &last); ok {
		t.Errorf("a held button must not repeat")
	}
	if _, ok := decodeMouse(10, 4, mouseLeftButton, 0x0002, &last); ok {
		t.Errorf("the double click record after a press must not repeat it")
	}
	// Release says nothing, and the next press reports again.
	if _, ok := decodeMouse(10, 4, 0, 0, &last); ok {
		t.Errorf("release")
	}
	if k, ok := decodeMouse(3, 3, mouseRightButton, 0, &last); !ok || k.Btn != MouseRight {
		t.Errorf("right press: %+v %v", k, ok)
	}
	decodeMouse(3, 3, 0, 0, &last)
	if k, ok := decodeMouse(3, 3, mouseLeftButton, 0, &last); !ok || k.Btn != MouseLeft {
		t.Errorf("second press: %+v %v", k, ok)
	}
	// Wheel: positive delta in the high word is up, negative is down.
	up := uint32(120) << 16
	down := uint32(0xFF88) << 16 // -120
	if k, ok := decodeMouse(0, 0, up, mouseWheeled, &last); !ok || k.Btn != MouseWheelUp {
		t.Errorf("wheel up: %+v", k)
	}
	if k, ok := decodeMouse(0, 0, down, mouseWheeled, &last); !ok || k.Btn != MouseWheelDown {
		t.Errorf("wheel down: %+v", k)
	}
}
