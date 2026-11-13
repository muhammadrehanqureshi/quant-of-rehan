package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-13: the BUILD VERSION & RELAY tile puts its values on the
// very column SETTINGS and THEMES use, so the three tiles read down one line.
// SETTINGS writes its value three cells in after a key field of 22, which is
// column 26 from the frame; the facts tile must land on the same cell.
func TestFactsValuesStandOnTheSettingsColumn(t *testing.T) {
	a := busyApp(t, 158, 41, 3)
	a.screen = scrSettings
	rows := rowsOf(a)
	want := -1
	for _, r := range rows {
		if strings.Contains(r, "RELAY STATUS") {
			want = strings.Index(r, "Opens the relay's health page.")
		}
	}
	if want < 0 {
		t.Fatalf("the SETTINGS tile carries no value to measure:\n%s",
			strings.Join(rows, "\n"))
	}
	checked := 0
	for _, r := range rows {
		switch {
		case strings.Contains(r, "BUILD VERSION"):
			continue
		case strings.Contains(r, "VERSION "):
			if at := strings.Index(r, appVersionLabel); at >= 0 {
				checked++
				if at != want {
					t.Errorf("VERSION value starts at %d, SETTINGS at %d: %q",
						at, want, r)
				}
			}
		case strings.Contains(r, "REQUESTS TODAY"):
			if at := strings.Index(r, "of 100,000."); at > 0 {
				j := at - 1 // the space between the count and the word
				for j > 0 && (r[j-1] >= '0' && r[j-1] <= '9' || r[j-1] == ',') {
					j--
				}
				checked++
				if j != want {
					t.Errorf("REQUESTS value starts at %d, SETTINGS at %d: %q",
						j, want, r)
				}
			}
		}
	}
	if checked < 2 {
		t.Fatalf("only %d fact rows carried a value to measure", checked)
	}
}

// Owner order 2026-11-13: the column heading says UNCLEAR (U), so the foot of
// ORDER FLOW says UNCLEAR too and the tile carries one word for one thing.
func TestOrderFlowFootSaysUnclear(t *testing.T) {
	a := busyApp(t, 158, 41, 3)
	a.screen = scrOrderFlow
	s := plain(a)
	if strings.Contains(s, "U = unclassified") {
		t.Errorf("the foot still says unclassified:\n%s", s)
	}
	if !strings.Contains(s, "U = UNCLEAR") {
		t.Errorf("the foot does not say U = UNCLEAR:\n%s", s)
	}
}

// Owner order 2026-11-13: the three KSE100 leaders carry their bar and NET DELTA
// again, on the name line, and the label, the price and the change stand on one
// set of columns on every row whatever digits they carry.
func TestKSE100LeadersLineUpAndCarryTheirBar(t *testing.T) {
	a := busyApp(t, 158, 41, 3)
	rows := rowsOf(a)
	inside := false
	barAt, pkrAt := -1, -1
	nameRows, priceRows := 0, 0
	for _, r := range rows {
		switch {
		case strings.Contains(r, "KSE100 INDEX & THE TOP 3 SCRIPS OF VOLUME"):
			inside = true
			continue
		case strings.Contains(r, "BUYING NOW"):
			inside = false
		}
		if !inside {
			continue
		}
		if at := strings.IndexRune(r, barBlock); at >= 0 {
			nameRows++
			if barAt < 0 {
				barAt = at
			} else if at != barAt {
				t.Errorf("a leader bar starts at %d, the first at %d: %q", at, barAt, r)
			}
			if !strings.ContainsAny(r[at:], "0123456789") {
				t.Errorf("the bar carries no NET DELTA: %q", r)
			}
			continue
		}
		if at := strings.Index(r, "PKR "); at >= 0 {
			priceRows++
			if pkrAt < 0 {
				pkrAt = at
			} else if at != pkrAt {
				t.Errorf("a leader price starts at %d, the first at %d: %q", at, pkrAt, r)
			}
		}
	}
	if nameRows < 2 {
		t.Fatalf("only %d leader name lines carry a bar:\n%s", nameRows,
			strings.Join(rows, "\n"))
	}
	if priceRows < 2 {
		t.Fatalf("only %d leader price lines were found:\n%s", priceRows,
			strings.Join(rows, "\n"))
	}
	if pkrAt <= 0 {
		t.Fatalf("no leader price column was measured")
	}
}
