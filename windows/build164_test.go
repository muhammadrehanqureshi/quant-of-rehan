package main

import (
	"regexp"
	"strings"
	"testing"
)

// Owner order 2026-11-24 (later): the WATCH LIST's box asks for a KMIALL scrip,
// no words stand under it, and the page's one instruction is its footer line.
func TestBuild164TheWatchBoxAsksForAKMIALLScrip(t *testing.T) {
	a := demoApp(t, 158, 41)
	a.screen = scrWatch
	text := screenOf(a)
	if !strings.Contains(text, watchPlaceholder) {
		t.Fatalf("the box does not ask for a KMIALL scrip:\n%s", text)
	}
	for _, gone := range []string{"Add a scrip", "Type a scrip", "The list is empty", "Pick a row and press DEL"} {
		if strings.Contains(text, gone) {
			t.Errorf("the page still writes %q under the box:\n%s", gone, text)
		}
	}
	// Owner order 2026-11-24 (later): the sentence stands inside the page, and
	// the tab bar carries TAB, R and Q again.
	rows := rowsOf(a)
	page := false
	for _, row := range rows[:len(rows)-1] {
		if strings.Contains(row, watchFooter) {
			page = true
		}
	}
	if !page {
		t.Fatalf("the page does not carry %q on a row of its own:\n%s", watchFooter, strings.Join(rows, "\n"))
	}
	foot := rows[len(rows)-1]
	if strings.Contains(foot, watchFooter) {
		t.Fatalf("the sentence still stands in the tab bar: %q", foot)
	}
	for _, want := range []string{"TAB NEXT", "R REFRESH", "Q QUIT"} {
		if !strings.Contains(foot, want) {
			t.Errorf("the tab bar lost %q on the WATCH LIST: %q", want, foot)
		}
	}
}

// Owner order 2026-11-24 (later): the rows carry ORDER FLOW's own numbers, a
// full stop after them, and no diamond under the #.
func TestBuild164TheWatchRowsAreNumberedNotDiamond(t *testing.T) {
	a := demoApp(t, 158, 41)
	a.screen = scrWatch
	a.cfg.Watch = []string{"PRL", "OGDC", "PPL"}
	a.watchPick = 1
	rows := rowsOf(a)
	head, at := -1, -1
	for i, row := range rows {
		if strings.Contains(row, "#") && strings.Contains(row, "SCRIP") && strings.Contains(row, "PRICE") {
			head, at = i, runeAt(row, "#")
			break
		}
	}
	if head < 0 {
		t.Fatalf("the WATCH LIST draws no table heading:\n%s", strings.Join(rows, "\n"))
	}
	cell := regexp.MustCompile(`^\d+\.$`)
	seen := 0
	for _, row := range rows[head+1:] {
		if strings.Contains(row, "┗") || strings.Contains(row, watchFooter) {
			break // the page's own footer line and the panel's rule close the table
		}
		r := []rune(row)
		if at < 0 || at+flowNumW > len(r) {
			continue
		}
		num := strings.TrimSpace(string(r[at : at+flowNumW]))
		if num == "" {
			continue
		}
		if strings.Contains(num, "◆") {
			t.Fatalf("a row still wears the diamond under the #: %q", row)
		}
		if !cell.MatchString(num) {
			t.Fatalf("a row's number reads %q, want the ORDER FLOW form 1.: %q", num, row)
		}
		seen++
	}
	if seen < 3 {
		t.Fatalf("only %d rows carried a number, want three:\n%s", seen, strings.Join(rows, "\n"))
	}
}

// Owner order 2026-11-24 (later): the WATCH LIST carries the ORDER FLOW page's
// ORDER line of chips, and a chip orders the watch list without touching the
// order the ORDER FLOW page is in.
func TestBuild164TheWatchPageCarriesTheOrderLine(t *testing.T) {
	a := demoApp(t, 158, 41)
	a.screen = scrWatch
	if a.watchSort != 0 {
		t.Fatalf("the page opens in order %d, want the owner's own at 0", a.watchSort)
	}
	text := screenOf(a)
	if !strings.Contains(text, "ORDER") || !strings.Contains(text, "◆ MY ORDER") {
		t.Fatalf("the ORDER line carries no chip for the owner's own order:\n%s", text)
	}
	if !strings.Contains(text, "TOTAL VOLUME") {
		t.Fatalf("the ORDER line lost the ORDER FLOW page's chips:\n%s", text)
	}
	of := a.ofSort
	a.keyWatch(Key{Kind: KRight})
	if a.watchSort != 1 {
		t.Fatalf("RIGHT left the watch order at %d, want 1", a.watchSort)
	}
	if a.ofSort != of {
		t.Fatalf("the watch page moved ORDER FLOW's order from %d to %d", of, a.ofSort)
	}
	// Owner order 2026-11-24 (later): the second chip is CHANGE.
	if next := screenOf(a); !strings.Contains(next, "◆ CHANGE") {
		t.Fatalf("the chosen chip wears no diamond:\n%s", next)
	}
}

// Owner order 2026-11-24 (later): the bar column is headed BAR across the whole
// build, and SCRIP keeps one blank cell before PRICE on ORDER FLOW and on the
// WATCH LIST alike.
func TestBuild164TheBarIsBARAndScripKeepsItsBlank(t *testing.T) {
	for _, scr := range []screenID{scrOrderFlow, scrWatch} {
		a := demoApp(t, 160, 45)
		a.screen = scr
		a.cfg.Watch = []string{"PRL", "OGDC"}
		head := ""
		for _, row := range rowsOf(a) {
			if strings.Contains(row, "SCRIP") && strings.Contains(row, "PRICE") {
				head = row
				break
			}
		}
		if head == "" {
			t.Fatalf("screen %d draws no SCRIP and PRICE heading", scr)
		}
		if strings.Contains(head, "BARS") {
			t.Errorf("screen %d still heads the column BARS: %q", scr, head)
		}
		if !strings.Contains(head, "BAR") {
			t.Errorf("screen %d has no BAR heading: %q", scr, head)
		}
		if got := runeAt(head, "PRICE") - runeAt(head, "SCRIP"); got != 8 {
			t.Errorf("screen %d puts PRICE %d cells after SCRIP, want 8 (SCRIP, one blank, one gutter): %q",
				scr, got, head)
		}
	}
}
