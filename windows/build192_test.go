package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-28 (build 192): "update the correct password
// banner/greeting to \"Welcome back, Mr. Rehan!\"". The gate greets him with that
// line exactly, the comma before his name and the mark at the end, in the gate's
// green and bold under the box.
func TestBuild192TheGateGreetsHimWithHisOwnLine(t *testing.T) {
	const greeting = "Welcome back, Mr. Rehan!"
	if unlockWelcome != greeting {
		t.Fatalf("the gate greets him with %q, want %q", unlockWelcome, greeting)
	}
	a := lockedApp(t, 100, 30)
	typeRunes(a, wantUnlockPassword)
	a.onKey(Key{Kind: KEnter})
	if !a.passOK {
		t.Fatal("the right password was not taken")
	}
	c := a.render()
	y, x := findCells(c, greeting)
	if y < 0 {
		t.Fatalf("the gate does not greet him with %q:\n%s", greeting, strings.Join(c.PlainRows(), "\n"))
	}
	cell := c.Cells[y*c.W+x]
	if cell.FG != a.th.Good {
		t.Fatalf("the greeting stands in %v, want the gate's green %v", cell.FG, a.th.Good)
	}
	if !cell.Bold {
		t.Fatal("the greeting stands in thin ink, want it bold")
	}
}

// The correction is the greeting's own wording, so a wrong password must still
// answer with the taunt and never with the greeting.
func TestBuild192AWrongPasswordStillGetsTheTaunt(t *testing.T) {
	a := lockedApp(t, 100, 30)
	typeRunes(a, "0000")
	a.onKey(Key{Kind: KEnter})
	if a.passOK {
		t.Fatal("a wrong password was taken")
	}
	rows := screenOf(a)
	if !strings.Contains(rows, unlockTaunt) {
		t.Fatalf("a wrong password does not get the taunt:\n%s", rows)
	}
	if strings.Contains(rows, unlockWelcome) {
		t.Fatalf("a wrong password is greeted as if it were the right one:\n%s", rows)
	}
}
