package main

import (
	"strings"
	"testing"
	"time"
)

// Owner order 2026-11-11 (tenth pass): every TELEMETRY value ends on the tile's
// right edge, FLOW stands directly before NET DELTA, and the FLOW value starts
// with B=..., S=... & U=....
func TestTelemetryValuesEndOnTheRightEdge(t *testing.T) {
	a := demoApp(t, 140, 40)
	c := NewCanvas(70, 40, a.th.Panel)
	a.drawLeft(c, 0, 0, 70, 40)
	coreH, _ := leftTileHeights(40)
	// The panel's inner content is inset two cells from the left and two from
	// the right, so the value column ends at 67 on this 70 cell tile.
	rows := c.PlainRows()
	for row := 0; row < 12; row++ {
		line := []rune(rows[coreH+2+row])
		if len(line) <= 67 || line[67] <= ' ' {
			t.Fatalf("telemetry row %d does not reach the tile's right edge: %q", row, string(line))
		}
	}
	flow, net := -1, -1
	for i, row := range rows {
		switch {
		case strings.Contains(row, "NET DELTA"):
			net = i
		case strings.Contains(row, "FLOW") && !strings.Contains(row, "ORDER FLOW"):
			flow = i
		}
	}
	if flow < 0 || net < 0 || flow+1 != net {
		t.Fatalf("FLOW does not stand directly before NET DELTA: FLOW %d, NET DELTA %d", flow, net)
	}
	for _, want := range []string{"B=", "S=", "& U="} {
		if !strings.Contains(rows[flow], want) {
			t.Fatalf("the FLOW row is missing %q: %q", want, rows[flow])
		}
	}
}

// Owner order 2026-11-11 (tenth pass): the ALERTS LOG carries its own SEARCH
// box; typing a scrip keeps only that scrip's alerts, and ESC restores the log.
func TestAlertsLogSearchesAScrip(t *testing.T) {
	a := demoApp(t, 120, 32)
	a.screen = scrAlerts
	a.alertFocus = 2
	a.flow.Log = []Flag{
		{Time: a.now, Symbol: "ECHO", Kind: "flow", Side: "BUY", Value: 12e6,
			Text: "ECHO is getting big buying orders", Detail: "Bought PKR 12M (900K shares) in 60 seconds."},
		{Time: a.now.Add(-time.Minute), Symbol: "XYZ", Kind: "flow", Side: "SELL", Value: 12e6,
			Text: "XYZ is getting big selling orders", Detail: "Sold PKR 12M (900K shares) in 60 seconds."},
	}
	a.onKey(Key{Kind: KRune, R: '/'})
	for _, r := range "ECHO" {
		a.onKey(Key{Kind: KRune, R: r})
	}
	if a.alertQuery != "ECHO" || !a.alertSearch {
		t.Fatalf("the search box holds %q, focused %v", a.alertQuery, a.alertSearch)
	}
	s := plain(a)
	if !strings.Contains(s, "ECHO is getting big buying orders") {
		t.Fatalf("the matching alert is missing:\n%s", s)
	}
	if strings.Contains(s, "XYZ is getting big selling orders") {
		t.Fatalf("an alert of another scrip is still in the log:\n%s", s)
	}
	if !strings.Contains(s, "ALERTS LOG (1 of 2)") {
		t.Fatalf("the title does not count the match:\n%s", s)
	}
	a.onKey(Key{Kind: KEsc})
	if a.alertQuery != "" || a.alertSearch {
		t.Fatalf("ESC left %q, focused %v", a.alertQuery, a.alertSearch)
	}
	if !strings.Contains(plain(a), "XYZ is getting big selling orders") {
		t.Fatal("ESC did not restore the whole log")
	}
}
