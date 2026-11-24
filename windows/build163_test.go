package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-24: every page's footer carries the three keys that move
// the whole build and nothing else. TAB goes to the next tab, R refreshes and Q
// quits; the per-page hints (ESC CLEAR, A PRICE ALERT, D DETAILS, CTRL+C QUIT)
// are gone.
func TestBuild163TheFooterCarriesThreeKeys(t *testing.T) {
	for _, scr := range []screenID{scrHome, scrAlerts, scrOrderFlow, scrScanner, scrWatch, scrSettings} {
		a := demoApp(t, 130, 40)
		a.screen = scr
		rows := a.render().PlainRows()
		row := rows[a.h-1]
		for _, want := range []string{"TAB NEXT", "R REFRESH", "Q QUIT"} {
			if !strings.Contains(row, want) {
				t.Errorf("screen %d: the footer lost %q: %q", scr, want, row)
			}
		}
		for _, gone := range []string{"ESC", "CTRL+C", "PRICE ALERT", "DETAILS", "D RAW"} {
			if strings.Contains(row, gone) {
				t.Errorf("screen %d: the footer still carries %q: %q", scr, gone, row)
			}
		}
	}
}

// Owner order 2026-11-24: a call is its own block, the CALL n/3 heading over the
// six labelled lines, and the values stand on one column after the longest
// label. The whole block fits the tile the home page gives it.
func TestBuild163ACallIsItsOwnLabelledBlock(t *testing.T) {
	a := demoApp(t, 160, 45)
	a.signals = "QUANT OF REHAN\nNO TRADE\nCALLS TODAY (1 of 3)\n" +
		"CALL 1 OF 3 | PRL | 10:20:05 | entry 89.1 | target 113.2 | stop 75.3 | score 90/100"
	rows := strings.Split(screenOf(a), "\n")
	order := []string{"CALL 1/3", "SCRIP:", "SCORE:", "ENTRY TIME:", "ENTRY PRICE:", "TARGET PRICE:", "STOP LOSS:"}
	at := -1
	for i, row := range rows {
		if strings.Contains(row, "CALL 1/3") {
			at = i
			break
		}
	}
	if at < 0 {
		t.Fatalf("the tile shows no call block:\n%s", strings.Join(rows, "\n"))
	}
	if at+len(order) > len(rows) {
		t.Fatalf("the call block is cut by the tile:\n%s", strings.Join(rows[at:], "\n"))
	}
	for i, want := range order {
		if !strings.Contains(rows[at+i], want) {
			t.Fatalf("line %d of the block is %q, want %q:\n%s", i+1, rows[at+i], want, strings.Join(rows[at:], "\n"))
		}
	}
	// Every value stands in the one column the longest label leaves.
	valueCol := strings.Index(rows[at+6], "75.3")
	for i, want := range []string{"PRL", "90/100", "10:20:05", "89.1", "113.2", "75.3"} {
		if got := strings.Index(rows[at+1+i], want); got != valueCol {
			t.Fatalf("the value of line %d starts on %d, want the one column %d:\n%s",
				i+1, got, valueCol, strings.Join(rows[at:], "\n"))
		}
	}
}
