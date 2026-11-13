package main

import (
	"strings"
	"testing"
	"time"
)

// Owner order 2026-11-13: the PRICE ALERTS form asks for a scrip, not the one
// scrip it might have been thinking of.
func TestPriceAlertFormAsksForAScrip(t *testing.T) {
	a := demoApp(t, 120, 30)
	a.screen = scrAlerts
	a.startPriceEdit(0)
	s := plain(a)
	if !strings.Contains(s, "Type a KMIALL scrip, then ENTER.") {
		t.Fatalf("the form does not ask for a scrip:\n%s", s)
	}
	if strings.Contains(s, "Type the KMIALL scrip") {
		t.Fatal("the form still says the KMIALL scrip")
	}
}

// Owner order 2026-11-13: the ALERTS LOG carries no sentence under its search
// box. The box alone stands above the list.
func TestAlertsLogHasNoWordsUnderTheSearchBox(t *testing.T) {
	a := demoApp(t, 120, 32)
	a.screen = scrAlerts
	a.flow.Log = nil
	s := plain(a)
	for _, bad := range []string{"No flag yet", "No alert matches", "Press ENTER to hear a test"} {
		if strings.Contains(s, bad) {
			t.Errorf("the empty log still says %q:\n%s", bad, s)
		}
	}
}

// Owner order 2026-11-13: one blank row stands between the search box and the
// first alert.
func TestAlertsLogLeavesOneBlankRowAfterTheSearchBox(t *testing.T) {
	a := demoApp(t, 120, 34)
	a.screen = scrAlerts
	rows := rowsOf(a)
	searchAt := -1
	for i, row := range rows {
		if strings.Contains(row, scripSearchHint) {
			searchAt = i
			break
		}
	}
	if searchAt < 0 {
		t.Fatal("the ALERTS LOG search box is missing")
	}
	log := a.flagLog()
	if len(log) == 0 {
		t.Fatal("the demo log is empty")
	}
	first := log[0].Text
	entryAt := -1
	for i := searchAt + 1; i < len(rows); i++ {
		if strings.Contains(rows[i], first) {
			entryAt = i
			break
		}
	}
	if entryAt != searchAt+2 {
		t.Fatalf("the first alert starts %d rows under the search box, want one blank row", entryAt-searchAt)
	}
}

// Owner order 2026-11-13: the ALERTS LOG keeps every alert. The old 300 entry
// cut deleted the oldest entries while the market was still open.
func TestAlertsLogKeepsEveryEntry(t *testing.T) {
	f := NewFlow(defaultFlowCfg(10_000_000))
	at := time.Date(2026, 11, 13, 10, 0, 0, 0, pkt)
	for i := 0; i < 350; i++ {
		f.addFlag(Flag{Time: at, Symbol: "ECHO", Kind: "flow", Side: "BUY"})
	}
	if len(f.Log) != 350 {
		t.Fatalf("the log holds %d alerts, want all 350", len(f.Log))
	}
}
