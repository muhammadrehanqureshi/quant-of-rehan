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

// Owner order 2026-11-18: the ALERTS LOG has its own search box again, while
// the scanner's SEARCH tile stays on the right.
func TestAlertsPageKeepsLogSearchAndRightSearchTile(t *testing.T) {
	a := demoApp(t, 120, 34)
	a.screen = scrAlerts
	a.flow.Log = []Flag{
		{Time: a.now, Symbol: "ECHO", Kind: "flow", Side: "BUY", Value: 12e6,
			Text: "ECHO is getting big buying orders", Detail: "Bought PKR 12M (900K shares) in 60 seconds."},
		{Time: a.now.Add(-time.Minute), Symbol: "XYZ", Kind: "flow", Side: "SELL", Value: 12e6,
			Text: "XYZ is getting big selling orders", Detail: "Sold PKR 12M (900K shares) in 60 seconds."},
	}
	frame := ""
	for _, row := range rowsOf(a) {
		if strings.Contains(row, "ALERTS LOG") && strings.Contains(row, "SEARCH") {
			frame = row
			break
		}
	}
	if frame == "" {
		t.Fatalf("the log and the SEARCH tile do not share a row:\n%s", strings.Join(rowsOf(a), "\n"))
	}
	logAt, searchAt := strings.Index(frame, "ALERTS LOG"), strings.Index(frame, "SEARCH")
	if logAt < 0 || searchAt < 0 || logAt >= searchAt {
		t.Fatalf("the log is not left of SEARCH: log %d search %d in %q", logAt, searchAt, frame)
	}
	a.onKey(Key{Kind: KRune, R: '/'})
	if !a.alertLogSearch || a.alertFocus != 2 {
		t.Fatalf("slash must focus the ALERTS LOG box: search %v focus %d", a.alertLogSearch, a.alertFocus)
	}
	for _, r := range "ECHO" {
		a.onKey(Key{Kind: KRune, R: r})
	}
	if a.alertQuery != "ECHO" || a.searchText != "" {
		t.Fatalf("the log box holds %q, the right tile holds %q", a.alertQuery, a.searchText)
	}
	s := plain(a)
	if !strings.Contains(s, "ECHO is getting big buying orders") {
		t.Fatalf("the log search lost the ECHO alert:\n%s", s)
	}
	if strings.Contains(s, "XYZ is getting big selling orders") {
		t.Fatalf("the log search did not filter out XYZ:\n%s", s)
	}
	a.onKey(Key{Kind: KEnter})
	if a.alertLogSearch {
		t.Fatal("ENTER must put the keys back on the log")
	}
	a.onKey(Key{Kind: KEsc})
	if a.alertQuery != "" || a.alertFocus != 2 {
		t.Fatalf("ESC left the log search %q at focus %d", a.alertQuery, a.alertFocus)
	}
}

// Owner order 2026-11-11 (eleventh pass): after the closing bell the live
// minute is empty, so TELEMETRY FLOW falls back to the relay's day sides
// instead of reading B=0, S=0 & U=0.
func TestTelemetryFlowShowsTheDaysSidesAfterTheClose(t *testing.T) {
	a := newTestApp(t)
	a.w, a.h = 120, 34
	a.link, a.checking = true, false
	a.cfg.BigBuy, a.cfg.BigSell = true, true
	a.now = time.Date(2026, 11, 2, 16, 45, 0, 0, pkt)
	if a.flow == nil {
		a.flow = NewFlow(defaultFlowCfg(100_000))
	}
	buy, sell, un := int64(600), int64(300), int64(100)
	vol := int64(1000)
	a.of = &OrderFlow{Rows: []FlowRow{{
		Symbol: "AAA", Buy: &buy, Sell: &sell, Unclassified: &un, Volume: &vol,
		Method: methodMeasured,
	}}}
	s := plain(a)
	for _, want := range []string{"B=600", "S=300", "& U=100"} {
		if !strings.Contains(s, want) {
			t.Errorf("post market FLOW is missing %q:\n%s", want, s)
		}
	}
}
