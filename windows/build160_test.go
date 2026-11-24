package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-24: every call is the owner's own block, its CALL n/3
// heading and the six labelled lines under it, SCRIP, SCORE, ENTRY TIME, ENTRY
// PRICE, TARGET PRICE and STOP LOSS, with the values on one column after the
// longest label. The next call starts five blank cells after the longest line
// of the block before it.
func TestTheLatestSignalShowsEachCallInItsOwnBlock(t *testing.T) {
	a := demoApp(t, 160, 45)
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
	// The block is the longest label (TARGET PRICE:, 13), one blank cell, then
	// the widest value it carries. Call 1's widest figure is eight cells, so
	// its block is 22 wide and the next call starts 27 cells later; call 2's
	// figures are nine cells, so its block is 23 and call 3 starts 28 later.
	if two-one != 27 || three-two != 28 {
		t.Fatalf("the call blocks start at %d, %d, %d, want pitches of 27 and 28: %q",
			one, two, three, head)
	}

	screen := screenOf(a)
	for _, want := range []string{"SCRIP:", "SCORE:", "ENTRY TIME:", "ENTRY PRICE:",
		"TARGET PRICE:", "STOP LOSS:", "HCAR", "TREET", "ENGROH",
		"09:41:07", "148.6200", "151.5924", "147.1338", "89/100", "84/100", "81/100"} {
		if !strings.Contains(screen, want) {
			t.Fatalf("the tile lost %q:\n%s", want, screen)
		}
	}
	// The gutter is five blank cells, measured from the longest line of the
	// block: the TARGET PRICE line, whose value is that block's widest.
	found := false
	for _, row := range rows {
		if strings.Count(row, "TARGET PRICE:") < 3 {
			continue
		}
		i1 := strings.Index(row, "TARGET PRICE:")
		i2 := i1 + 1 + strings.Index(row[i1+1:], "TARGET PRICE:")
		i3 := i2 + 1 + strings.Index(row[i2+1:], "TARGET PRICE:")
		if got := i2 - (i1 + 14 + 8); got != 5 {
			t.Errorf("call 1 to call 2 keeps %d cells after its longest line, want 5: %q", got, row)
		}
		if got := i3 - (i2 + 14 + 9); got != 5 {
			t.Errorf("call 2 to call 3 keeps %d cells after its longest line, want 5: %q", got, row)
		}
		found = true
	}
	if !found {
		t.Fatalf("no row carried the three TARGET PRICE lines side by side:\n%s", screen)
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
