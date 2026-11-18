package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-18: B and S values end with a comma in the same soft ink
// as their '=' label, while U carries no comma because the ampersand already
// separates it from T.
func TestBSCommasWearTheEqualsInkAndUHasNone(t *testing.T) {
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
		if c.Cells[comma].FG != c.Cells[at+1].FG {
			t.Fatalf("%s comma ink differs from its '=' ink: %q", label, row)
		}
	}
	at := strings.Index(row, "U=")
	if at < 0 {
		t.Fatalf("U= is missing from the line: %q", row)
	}
	amp := strings.Index(row[at+2:], "&")
	if amp < 0 {
		t.Fatalf("the ampersand is missing after U: %q", row)
	}
	if strings.Contains(row[at+2:at+2+amp], ",") {
		t.Fatalf("U still ends with a comma: %q", row)
	}
}

// The narrow leader form carries the same two soft commas, so the KSE100 tile
// keeps the rule below 96 columns as well.
func TestPackedLeadersEndBAndSWithASoftComma(t *testing.T) {
	a := newTestApp(t)
	c := NewCanvas(80, 1, a.th.Panel)
	b, s, total := int64(600), int64(300), int64(1000)
	a.putBSTPacked(c, 0, 0, &b, &s, &total)
	row := c.PlainRows()[0]
	if !strings.Contains(row, "B=600,  S=300,") {
		t.Fatalf("the packed line does not carry both commas: %q", row)
	}
	for _, label := range []string{"B=", "S="} {
		at := strings.Index(row, label)
		comma := at + 2 + strings.Index(row[at+2:], ",")
		if at < 0 || comma < at+3 || c.Cells[comma].FG != c.Cells[at+1].FG {
			t.Fatalf("%s packed comma does not wear the '=' ink: %q", label, row)
		}
	}
}

// The measured totals use the same split, so a coloured B, S or U value never
// colours the comma after it.
func TestMeasuredTotalsCommasWearTheEqualsInk(t *testing.T) {
	a := newTestApp(t)
	sp := volumeCommaSpans(1234, a.th.Good, true, a.th.Soft)
	if len(sp) < 2 || sp[0].S != "1,234" || sp[0].FG != a.th.Good {
		t.Fatalf("the value span changed: %+v", sp)
	}
	if sp[1].S != "," || sp[1].FG != a.th.Soft {
		t.Fatalf("the trailing comma is not in the soft equals ink: %+v", sp[1])
	}
}

// Owner order 2026-11-18: the ALERTS page puts the SEARCH box in the right
// hand tile, not inside the log on the left.
func TestAlertsSearchBoxIsOnTheRight(t *testing.T) {
	a := demoApp(t, 120, 34)
	a.screen = scrAlerts
	rows := rowsOf(a)
	for _, row := range rows {
		if at := strings.Index(row, scripSearchHint); at >= 0 {
			if at < 60 {
				t.Fatalf("the ALERTS SEARCH box starts on cell %d, want the right half: %q", at, row)
			}
			return
		}
	}
	t.Fatalf("the ALERTS SEARCH box is missing:\n%s", strings.Join(rows, "\n"))
}
