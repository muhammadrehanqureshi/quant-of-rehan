package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-19: NET DELTA is back on the KSE100 tile, between the
// current price and the percentage, on the same quote group as every other
// tile.
func TestKSE100LeadersCarryNetDeltaBeforePercentage(t *testing.T) {
	a := busyApp(t, 158, 41, 3)
	inside := false
	found := 0
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
		if !strings.Contains(row, "PKR ") || !strings.Contains(row, "%") {
			continue
		}
		found++
		rest := row[col(row, "PKR "):]
		netAt, pctAt := col(rest, "NET DELTA"), col(rest, "%")
		if netAt < 0 {
			t.Errorf("the KSE100 leader carries no NET DELTA: %q", row)
			continue
		}
		if netAt > pctAt {
			t.Errorf("NET DELTA and the percentage are out of order: %q", row)
		}
	}
	if found < 2 {
		t.Fatalf("only %d leader price lines were found:\n%s", found, plain(a))
	}
}
