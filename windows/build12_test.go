package main

import (
	"strings"
	"testing"
	"unicode/utf8"
)

// col is the cell a substring starts on. PlainRows builds a string, so a byte
// index would count the frame's three byte glyphs three times and make two
// aligned tiles look two cells apart.
func col(row, sub string) int {
	at := strings.Index(row, sub)
	if at < 0 {
		return -1
	}
	return utf8.RuneCountInString(row[:at])
}

// Owner order 2026-11-13: the BUILD VERSION & RELAY tile puts its values on the
// very column SETTINGS and THEMES use, so the three tiles read down one line.
// SETTINGS writes its value three cells in after a key field of 22, which is
// column 26 from the frame; the facts tile must land on the same cell.
func TestFactsValuesStandOnTheSettingsColumn(t *testing.T) {
	a := busyApp(t, 158, 41, 3)
	a.screen = scrSettings
	rows := rowsOf(a)
	want := -1
	status, _ := a.relayStatus()
	for _, r := range rows {
		if strings.Contains(r, "RELAY STATUS") {
			want = col(r, status)
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
		case strings.Contains(r, "VERSION ") || strings.Contains(r, "VERSION\t"):
			if at := col(r, appVersionLabel); at >= 0 {
				checked++
				if at != want {
					t.Errorf("VERSION value starts at %d, SETTINGS at %d: %q",
						at, want, r)
				}
			}
		case strings.Contains(r, "REQUESTS TODAY"):
			at := strings.Index(r, "of 100,000.")
			if at < 0 {
				continue
			}
			j := at - 1 // the space between the count and the word
			for j > 0 && (r[j-1] >= '0' && r[j-1] <= '9' || r[j-1] == ',') {
				j--
			}
			checked++
			if got := utf8.RuneCountInString(r[:j]); got != want {
				t.Errorf("REQUESTS value starts at %d, SETTINGS at %d: %q",
					got, want, r)
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
	if !strings.Contains(s, "U = UNCLEAR: The volume that the feed could not capture, U is never added to either B or S.") {
		t.Errorf("the foot does not carry the full U = UNCLEAR sentence:\n%s", s)
	}
}

// Owner order 2026-11-18: each KSE100 bar stands above the price line and
// starts on the current price's own cell. The price, the percentage and the
// bar no longer compete for one row.
func TestKSE100LeadersLineUpAndCarryTheirBar(t *testing.T) {
	a := busyApp(t, 158, 41, 3)
	rows := rowsOf(a)
	inside := false
	pkrAt := -1
	priceRows, barRows := 0, 0
	for i, r := range rows {
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
		pkrByte := strings.Index(r, "PKR ")
		if pkrByte < 0 {
			continue
		}
		priceRows++
		at := col(r, "PKR ")
		if pkrAt < 0 {
			pkrAt = at
		} else if at != pkrAt {
			t.Errorf("a leader price starts at %d, the first at %d: %q", at, pkrAt, r)
		}
		rest := r[pkrByte:]
		if strings.Contains(rest, "NET DELTA") {
			t.Errorf("the KSE100 leader still carries NET DELTA: %q", r)
		}
		if !strings.Contains(rest, "%") {
			continue
		}
		if i == 0 {
			t.Errorf("the first leader price line has no name line above it: %q", r)
			continue
		}
		barAt := col(rows[i-1], string(barBlock))
		if barAt < 0 {
			t.Errorf("the line above the price carries no bar: %q", rows[i-1])
			continue
		}
		if barAt != at {
			t.Errorf("the bar starts on cell %d, the current price on %d: %q", barAt, at, rows[i-1])
		}
		barRows++
	}
	if priceRows < 2 {
		t.Fatalf("only %d leader price lines were found:\n%s", priceRows,
			strings.Join(rows, "\n"))
	}
	if barRows < 2 {
		t.Fatalf("only %d leader name lines carry a bar:\n%s", barRows,
			strings.Join(rows, "\n"))
	}
	if pkrAt <= 0 {
		t.Fatalf("no leader price column was measured")
	}
}
