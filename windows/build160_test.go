package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-23: the LATEST SIGNAL tile puts each call in a column,
// the first on the very left with all of its details, and six blank cells
// between one call and the next.
func TestTheLatestSignalShowsEachCallInItsOwnColumn(t *testing.T) {
	a := demoApp(t, 120, 40)
	a.signals = "QUANT OF REHAN\nNO TRADE\nCALLS TODAY (3 of 3)\n" +
		"CALL 1 OF 3 | HCAR | 09:41:07 | entry 148.6200 | target 151.5924 | stop 147.1338 | score 89/100\n" +
		"CALL 2 OF 3 | TREET | 10:02:13 | entry 2786.9860 | target 2842.7257 | stop 2759.1161 | score 84/100\n" +
		"CALL 3 OF 3 | ENGROH | 11:03:51 | entry 315.4000 | target 321.7080 | stop 312.2460 | score 81/100"

	rows := strings.Split(screenOf(a), "\n")
	head := ""
	for _, row := range rows {
		if strings.Contains(row, "CALL 1/3") {
			head = row
		}
	}
	if head == "" {
		t.Fatalf("the tile shows no call column:\n%s", strings.Join(rows, "\n"))
	}
	one := strings.Index(head, "CALL 1/3")
	two := strings.Index(head, "CALL 2/3")
	three := strings.Index(head, "CALL 3/3")
	if one < 0 || two < 0 || three < 0 {
		t.Fatalf("the three calls are not side by side: %q", head)
	}
	// A column is 21 cells and the gutter is exactly 6, so each call starts
	// 27 cells after the one before it.
	if two-one != 27 || three-two != 27 {
		t.Fatalf("the call columns start at %d, %d, %d, not one 27 cell pitch: %q",
			one, two, three, head)
	}

	screen := screenOf(a)
	for _, want := range []string{"HCAR", "TREET", "ENGROH",
		"09:41:07  148.6200", "TP 151.5924", "SL 147.1338", "89/100",
		"84/100", "81/100"} {
		if !strings.Contains(screen, want) {
			t.Fatalf("the tile lost %q:\n%s", want, screen)
		}
	}
}

// A card with no ledger still draws the one latest signal, so a day before its
// first call reads exactly as it did.
func TestACardWithoutCallsDrawsTheOneSignal(t *testing.T) {
	a := demoApp(t, 120, 40)
	a.signals = "QUANT OF REHAN\nSymbol: HCAR\nEntry time: 09:41:07 PKT\nEntry price: 148.6200\nTarget: 151.59\nStop Loss: 147.13\nScore: 89/100"
	screen := screenOf(a)
	if !strings.Contains(screen, "SYMBOL") || !strings.Contains(screen, "HCAR") {
		t.Fatalf("the single card no longer draws:\n%s", screen)
	}
	if strings.Contains(screen, "CALL 1/3") {
		t.Fatalf("a card without calls grew call columns:\n%s", screen)
	}
}
