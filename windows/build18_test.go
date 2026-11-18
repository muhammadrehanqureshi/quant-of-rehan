package main

import (
	"strings"
	"testing"
	"time"
)

// Owner order 2026-11-14: the PRICE ALERTS form leaves its boxes to say
// "Type here", carries no ESC line and no words along its bottom.
func TestPriceAlertFormIsQuiet(t *testing.T) {
	a := demoApp(t, 120, 30)
	a.screen = scrAlerts
	a.startPriceEdit(0)
	s := plain(a)
	if n := strings.Count(s, "Type here"); n != 2 {
		t.Fatalf("want Type here in both boxes, got %d:\n%s", n, s)
	}
	if strings.Contains(s, "type here") {
		t.Fatal("the form still carries the lower case placeholder")
	}
	for _, gone := range []string{
		"ESC cancels",
		"Type a KMIALL scrip, then ENTER.",
		"Type the price. A target below the market rings on the way down.",
	} {
		if strings.Contains(s, gone) {
			t.Errorf("the form still carries %q:\n%s", gone, s)
		}
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

// Owner order 2026-11-18: the log has its own search box again. Its first
// alert starts after the box and the one blank row under it.
func TestAlertsLogStartsUnderItsTitle(t *testing.T) {
	a := demoApp(t, 120, 34)
	a.screen = scrAlerts
	rows := rowsOf(a)
	titleAt := -1
	for i, row := range rows {
		if strings.Contains(row, "ALERTS LOG") {
			titleAt = i
			break
		}
	}
	if titleAt < 0 || titleAt+3 >= len(rows) {
		t.Fatalf("the ALERTS LOG title is missing:\n%s", strings.Join(rows, "\n"))
	}
	if !strings.Contains(rows[titleAt+1], scripSearchHint) {
		t.Fatalf("the log search box is not under the title: %q", rows[titleAt+1])
	}
	blank := strings.TrimSpace(strings.ReplaceAll(rows[titleAt+2], "│", ""))
	if blank != "" {
		t.Fatalf("no blank row stands under the log search box: %q", rows[titleAt+2])
	}
	log := a.flagLog()
	if len(log) == 0 {
		t.Fatal("the demo log is empty")
	}
	stamp := log[0].Time.In(pkt).Format("15:04:05")
	if !strings.Contains(rows[titleAt+3], stamp) {
		t.Fatalf("the first alert does not start under the search box: %q", rows[titleAt+3])
	}
}

// Owner order 2026-11-13: the ALERTS LOG keeps every alert. The old 300 entry
// cut deleted the oldest entries while the market was still open.
func TestAlertsLogKeepsEveryEntry(t *testing.T) {
	f := NewFlow(defaultFlowCfg(100_000))
	at := time.Date(2026, 11, 13, 10, 0, 0, 0, pkt)
	for i := 0; i < 350; i++ {
		f.addFlag(Flag{Time: at, Symbol: "ECHO", Kind: "flow", Side: "BUY"})
	}
	if len(f.Log) != 350 {
		t.Fatalf("the log holds %d alerts, want all 350", len(f.Log))
	}
}
