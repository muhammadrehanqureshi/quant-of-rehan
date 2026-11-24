package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-24 (later): the ORDER line reads CHANGE, NET DELTA, NET
// DELTA %, BUYING VOLUME, SELLING VOLUME, TOTAL VOLUME, UNCLEAR on ORDER FLOW
// and on the WATCH LIST alike, and both pages still open in the order they
// opened in before (TOTAL VOLUME on ORDER FLOW, the owner's own on the watch
// list).
func TestBuild166TheOrderChipsStandInTheOwnersOrder(t *testing.T) {
	want := []string{"CHANGE", "NET DELTA", "NET DELTA %", "BUYING VOLUME",
		"SELLING VOLUME", "TOTAL VOLUME", "UNCLEAR"}
	if len(flowSorts) != len(want) {
		t.Fatalf("flowSorts carries %d chips, want %d: %v", len(flowSorts), len(want), flowSorts)
	}
	for i, w := range want {
		if flowSorts[i] != w {
			t.Fatalf("chip %d is %q, want %q: %v", i+1, flowSorts[i], w, flowSorts)
		}
	}
	for _, scr := range []screenID{scrOrderFlow, scrWatch} {
		a := demoApp(t, 170, 45)
		a.screen = scr
		a.cfg.Watch = []string{"PRL"}
		line := ""
		for _, row := range rowsOf(a) {
			if strings.Contains(row, "ORDER ") && strings.Contains(row, "CHANGE") {
				line = row
				break
			}
		}
		if line == "" {
			t.Fatalf("screen %d draws no ORDER line of chips", scr)
		}
		pos := 0
		for i, name := range want {
			at := strings.Index(line[pos:], name)
			if at < 0 {
				t.Fatalf("screen %d: the ORDER line lost chip %d %q: %q", scr, i+1, name, line)
			}
			pos += at + len(name)
			if i > 0 && pos == 0 {
				t.Fatalf("screen %d: chip %q does not follow the one before it", scr, name)
			}
		}
	}
	a := demoApp(t, 170, 45)
	if a.ofSort != flowSortTotalVolume {
		t.Fatalf("ORDER FLOW opens in order %d, want TOTAL VOLUME at %d", a.ofSort, flowSortTotalVolume)
	}
	if a.watchSort != 0 {
		t.Fatalf("the WATCH LIST opens in order %d, want the owner's own at 0", a.watchSort)
	}
}

// Owner order 2026-11-24 (later): the WATCH LIST tile says how to open its box.
func TestBuild166TheWatchTileNamesTheKeyThatAdds(t *testing.T) {
	a := demoApp(t, 158, 41)
	a.screen = scrWatch
	text := screenOf(a)
	if !strings.Contains(text, watchAddHint) {
		t.Fatalf("the WATCH LIST tile does not say %q:\n%s", watchAddHint, text)
	}
}
