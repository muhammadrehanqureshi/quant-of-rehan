package main

import (
	"regexp"
	"strings"
	"testing"
	"time"
)

// Owner order 2026-11-24 (later): the ALERTS boards name transactions, not a
// stock's running minute total. A 60k buy and a later 150k buy of the same scrip
// stand as two rows with their own quantities, and only the increment the ALERTS
// LOG announces wears the star.
func TestBuild165TheBoardsListEachIncrementItsOwnRow(t *testing.T) {
	f := NewFlow(defaultFlowCfg(alertFloorShares))
	f.Observe(flowT0, feedOf(map[string]LiveQuote{"GCIL": lq(20, 1_000_000)}), true)
	f.Observe(flowT0.Add(time.Second), feedOf(map[string]LiveQuote{"GCIL": lq(20.1, 1_060_000)}), true)
	now := flowT0.Add(2 * time.Second)
	f.Observe(now, feedOf(map[string]LiveQuote{"GCIL": lq(20.2, 1_210_000)}), true)

	rows := f.Increments(now, boardFloorShares, 0, sideBuy)
	if len(rows) != 2 {
		t.Fatalf("the board carries %d rows, want one per transaction: %+v", len(rows), rows)
	}
	if rows[0].BuyShares != 150_000 || rows[1].BuyShares != 60_000 {
		t.Fatalf("the rows carry %d and %d shares, want 150k and 60k, largest first",
			rows[0].BuyShares, rows[1].BuyShares)
	}
	for _, r := range rows {
		if r.Symbol != "GCIL" {
			t.Fatalf("row scrip is %q, want GCIL", r.Symbol)
		}
	}
	// The 150k increment is the one the ALERTS LOG announces; the 60k one is not.
	if !rows[0].Flagged || rows[1].Flagged {
		t.Fatalf("the star reads %v/%v, want the 150k row alone marked", rows[0].Flagged, rows[1].Flagged)
	}
	// A step below the board floor never reaches the board.
	small := NewFlow(defaultFlowCfg(alertFloorShares))
	small.Observe(flowT0, feedOf(map[string]LiveQuote{"PPL": lq(9, 500_000)}), true)
	small.Observe(flowT0.Add(time.Second), feedOf(map[string]LiveQuote{"PPL": lq(9.1, 540_000)}), true)
	if got := small.Increments(flowT0.Add(time.Second), boardFloorShares, 0, sideBuy); len(got) != 0 {
		t.Fatalf("a 40k step reached the board: %+v", got)
	}
}

// Owner order 2026-11-24 (later): one blank line stands between the WATCH LIST's
// search box and the ORDER line of chips.
func TestBuild165TheWatchBoxKeepsOneBlankLine(t *testing.T) {
	a := demoApp(t, 158, 41)
	a.screen = scrWatch
	rows := rowsOf(a)
	box := -1
	for i, row := range rows {
		if strings.Contains(row, watchPlaceholder) {
			box = i
			break
		}
	}
	if box < 0 {
		t.Fatalf("the box does not ask for a KMIALL scrip:\n%s", strings.Join(rows, "\n"))
	}
	chips := -1
	for i := box + 1; i < len(rows); i++ {
		if strings.Contains(rows[i], "TOTAL VOLUME") {
			chips = i
			break
		}
	}
	if chips < 0 {
		t.Fatalf("no ORDER line under the box:\n%s", strings.Join(rows, "\n"))
	}
	if chips-box != 2 {
		t.Fatalf("the chips stand %d rows under the box, want one blank line", chips-box)
	}
	if word := regexp.MustCompile(`[A-Za-z0-9]`); word.MatchString(rows[box+1]) {
		t.Fatalf("the row between the box and the chips carries words: %q", rows[box+1])
	}
}
