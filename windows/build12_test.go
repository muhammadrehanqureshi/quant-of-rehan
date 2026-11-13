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
	if !strings.Contains(s, "U = UNCLEAR") {
		t.Errorf("the foot does not say U = UNCLEAR:\n%s", s)
	}
}

// Owner order 2026-11-13: the bar stands alone on each leader's name line and
// the NET DELTA sits at the right of the price line, so the bar, the percentage
// and the delta no longer crowd one row. The label, the price and the change
// still stand on one set of columns whatever digits they carry.
func TestKSE100LeadersLineUpAndCarryTheirBar(t *testing.T) {
	a := busyApp(t, 158, 41, 3)
	rows := rowsOf(a)
	inside := false
	barAt, pkrAt := -1, -1
	nameRows, priceRows, netRows := 0, 0, 0
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
		barByte := strings.IndexRune(r, barBlock)
		// A frame's own three cell accent is a run of the bar glyph; a leader
		// line is the one that carries its serial and symbol before it.
		if barByte >= 0 && strings.Contains(r[:barByte], ". ") {
			nameRows++
			if at := col(r, string(barBlock)); barAt < 0 {
				barAt = at
			} else if at != barAt {
				t.Errorf("a leader bar starts at %d, the first at %d: %q", at, barAt, r)
			}
			if strings.ContainsAny(r[barByte:], "0123456789") {
				t.Errorf("the name line still carries a figure after the bar: %q", r)
			}
			continue
		}
		if at := col(r, "PKR "); at >= 0 {
			priceRows++
			// Search after PKR, by byte, because the telemetry tile on the left
			// of the same console row carries its own "NET DELTA" label.
			if pkrByte := strings.Index(r, "PKR "); pkrByte >= 0 &&
				strings.Contains(r[pkrByte:], "NET ") {
				netRows++
			}
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
	if netRows < 2 {
		t.Fatalf("only %d leader price lines carry a NET DELTA:\n%s", netRows,
			strings.Join(rows, "\n"))
	}
	if pkrAt <= 0 {
		t.Fatalf("no leader price column was measured")
	}
}
