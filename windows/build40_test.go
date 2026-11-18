package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-18: B and S values end with a comma, and that comma wears
// the same ink as the value it follows.
func TestBAndSCommasWearTheirValueInk(t *testing.T) {
	a := newTestApp(t)
	c := NewCanvas(80, 1, a.th.Panel)
	b, s, total := int64(600), int64(300), int64(1000)
	a.putBST(c, 0, 0, &b, &s, &total)
	row := c.PlainRows()[0]
	for _, label := range []string{"B=", "S="} {
		at := strings.Index(row, label)
		if at < 0 {
			t.Fatalf("%s is missing from the line: %q", label, row)
		}
		comma := at + 2 + strings.Index(row[at+2:], ",")
		if comma < at+3 || c.Cells[comma].Ch != ',' {
			t.Fatalf("%s has no comma after its value: %q", label, row)
		}
		if c.Cells[comma].FG != c.Cells[comma-1].FG {
			t.Fatalf("%s comma ink differs from its value ink: %q", label, row)
		}
	}
}

// The narrow leader form carries the same two commas, so the KSE100 tile keeps
// the rule below 96 columns as well.
func TestPackedLeadersEndBAndSWithAComma(t *testing.T) {
	a := newTestApp(t)
	c := NewCanvas(80, 1, a.th.Panel)
	b, s, total := int64(600), int64(300), int64(1000)
	a.putBSTPacked(c, 0, 0, &b, &s, &total)
	row := c.PlainRows()[0]
	if !strings.Contains(row, "B=600,  S=300,") {
		t.Fatalf("the packed line does not carry both commas: %q", row)
	}
}

// Owner order 2026-11-18: the ALERTS LOG search box loses the row above it. The
// row under the title now holds the box, and one blank row still follows it.
func TestAlertsLogSearchBoxHasNoRowAboveIt(t *testing.T) {
	a := demoApp(t, 120, 34)
	a.screen = scrAlerts
	rows := rowsOf(a)
	searchAt := -1
	for i, row := range rows {
		if strings.Contains(row, scripSearchHint) {
			searchAt = i
			break
		}
	}
	if searchAt < 1 {
		t.Fatalf("the ALERTS LOG search box is missing:\n%s", strings.Join(rows, "\n"))
	}
	if blankSearchRow(rows[searchAt-1]) {
		t.Fatalf("the row above the ALERTS LOG search box is still blank: %q", rows[searchAt-1])
	}
	if !blankSearchRow(rows[searchAt+1]) {
		t.Fatalf("the row under the ALERTS LOG search box is not blank: %q", rows[searchAt+1])
	}
}
