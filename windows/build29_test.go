package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-16: an empty BIG BUYING NOW or BIG SELLING NOW board says
// nothing under its heading. The old empty sentence is withdrawn entirely.
func TestAlertBoardsStayEmpty(t *testing.T) {
	a := newTestApp(t)
	c := NewCanvas(80, 14, a.th.Panel)
	a.drawBoardPanel(c, 0, 0, 80, 14, sideBuy)
	s := strings.Join(c.PlainRows(), "\n")
	if strings.Contains(s, "Nothing is being traded in size right now.") ||
		strings.Contains(s, "Watching every broker tick") {
		t.Fatalf("an empty board still carries a sentence:\n%s", s)
	}
}

// Owner order 2026-11-17: every KSE100 volume keeps nine digit positions, so a
// short U is padded with spaces and S, U and T stay on their own columns.
func TestKSE100UValuesUseTheNineDigitField(t *testing.T) {
	a := busyApp(t, 158, 41, 3)
	inside, found := false, 0
	for _, row := range rowsOf(a) {
		switch {
		case strings.Contains(row, "KSE100 INDEX & THE TOP 3 SCRIPS OF VOLUME"):
			inside = true
			continue
		case strings.Contains(row, "BUYING NOW"):
			inside = false
		}
		if !inside {
			continue
		}
		i := strings.Index(row, "U=")
		if i < 0 {
			continue
		}
		rest := row[i+2:]
		if len(rest) < 11 {
			t.Errorf("the U field is shorter than nine digits: %q", row)
			continue
		}
		if last := rest[10]; last < '0' || last > '9' {
			t.Errorf("the U field is not right aligned in its nine digit width: %q", row)
		}
		found++
	}
	if found < 2 {
		t.Fatalf("only %d leader U columns were found:\n%s", found, plain(a))
	}
}
