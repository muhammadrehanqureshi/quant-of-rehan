package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-14 (latest): the KSE100 leader price line carries the
// full NET DELTA label, and every leader puts it on the same cell.
func TestKSE100LeadersCarryFullNetDelta(t *testing.T) {
	a := busyApp(t, 158, 41, 3)
	at := -1
	found := 0
	for _, row := range rowsOf(a) {
		pkr := strings.Index(row, "PKR ")
		if pkr < 0 {
			continue
		}
		rest := row[pkr:]
		j := strings.Index(rest, "NET DELTA ")
		if j < 0 {
			continue
		}
		cell := runeLen(row[:pkr+j])
		if at < 0 {
			at = cell
		} else if cell != at {
			t.Errorf("NET DELTA starts on cell %d, the first on %d: %q", cell, at, row)
		}
		found++
	}
	if found < 2 {
		t.Fatalf("only %d leader price lines carry NET DELTA:\n%s", found, plain(a))
	}
}
