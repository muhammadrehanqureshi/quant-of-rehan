package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-15: NET DELTA is withdrawn from the KSE100 tile. The
// bar takes the right edge of the percentage row in its place.
func TestKSE100LeadersCarryNoNetDelta(t *testing.T) {
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
		pkr := strings.Index(row, "PKR ")
		if pkr < 0 {
			continue
		}
		found++
		if strings.Contains(row[pkr:], "NET DELTA") {
			t.Errorf("the KSE100 leader still carries NET DELTA: %q", row)
		}
	}
	if found < 2 {
		t.Fatalf("only %d leader price lines were found:\n%s", found, plain(a))
	}
}
