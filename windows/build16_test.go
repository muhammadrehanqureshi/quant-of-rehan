package main

import (
	"fmt"
	"regexp"
	"strings"
	"testing"
)

// Owner order 2026-11-13: the ALERTS LOG is read only on the ALERTS page.
func TestAlertsLogCannotBeDeleted(t *testing.T) {
	a := demoApp(t, 120, 30)
	a.screen = scrAlerts
	before := len(a.flow.Log)
	a.onKey(Key{Kind: KDel})
	if len(a.flow.Log) != before {
		t.Fatalf("DEL deleted the log: %d alerts became %d", before, len(a.flow.Log))
	}
	if strings.Contains(plain(a), "DEL clears the log") {
		t.Fatal("the ALERTS LOG still advertises a delete key")
	}
}

// Owner order 2026-11-13: a sector's percentage stands at the far right of the
// tile, after its name, not in front of it.
func TestSectorPercentagesStandAtTheRightEdge(t *testing.T) {
	a := demoApp(t, 122, 36)
	a.screen = scrScanner
	for _, row := range rowsOf(a) {
		if !strings.Contains(row, "AUTOMOBILE") || !strings.Contains(row, "%") {
			continue
		}
		if strings.Index(row, "AUTOMOBILE") > strings.LastIndex(row, "%") {
			t.Fatalf("the sector percentage still leads the name: %q", row)
		}
		return
	}
	t.Fatal("the scanner did not draw a sector percentage")
}

// Owner order 2026-11-13: the six sorts carry the same sequence numbers the
// SECTORS tile uses.
func TestCustomScripsMenuCarriesSequenceNumbers(t *testing.T) {
	a := demoApp(t, 122, 36)
	a.screen = scrScanner
	a.scanChoice = 2
	rows := rowsOf(a)
	for i, name := range scanChoices {
		number := fmt.Sprintf("%d.", i+1)
		found := false
		for _, row := range rows {
			at, numAt := strings.Index(row, name), strings.Index(row, number)
			if at >= 0 && numAt >= 0 && numAt < at {
				found = true
				break
			}
		}
		if !found {
			t.Errorf("sort %q is not numbered %s", name, number)
		}
	}
}

func TestCalculatorTileWording(t *testing.T) {
	a := demoApp(t, 122, 36)
	a.screen = scrScanner
	s := plain(a)
	for _, want := range []string{"Enter price", "Enter qty", "Press \"C\" to calculate"} {
		if !strings.Contains(s, want) {
			t.Errorf("the calculator tile is missing %q", want)
		}
	}
	a.onKey(Key{Kind: KRune, R: 'C'})
	if !strings.Contains(plain(a), "TAB next, ESC leaves") {
		t.Error("the calculator hint does not carry the comma")
	}
}

// Owner order 2026-11-13: the unclassified column keeps its own width, so the
// total no longer follows a full-volume blank, and PKR, the change and the
// NET DELTA stand as one group at the right.
func TestKSE100ColumnsAreTight(t *testing.T) {
	a := busyApp(t, 158, 41, 3)
	uToT := regexp.MustCompile(`U=([\d,]+)( +)& T=`)
	inside := false
	totAt := -1
	priced := 0
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
		if m := uToT.FindStringSubmatch(row); m != nil {
			if len(m[2]) > 8 {
				t.Errorf("U=%s leaves %d cells before & T=: %q", m[1], len(m[2]), row)
			}
			at := strings.Index(row, "& T=")
			if totAt < 0 {
				totAt = at
			} else if at != totAt {
				t.Errorf("& T= starts at %d, the first at %d: %q", at, totAt, row)
			}
		}
		pkr := strings.Index(row, "PKR ")
		arrow := strings.IndexAny(row, "▲▼")
		if pkr >= 0 && arrow > pkr {
			priced++
			if arrow-pkr > 18 {
				t.Errorf("the change floats %d cells from PKR: %q", arrow-pkr, row)
			}
		}
	}
	if priced < 2 {
		t.Fatalf("only %d leader price lines carried a change", priced)
	}
}
