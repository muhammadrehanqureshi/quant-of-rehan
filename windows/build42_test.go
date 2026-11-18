package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-18: ALERTS LOG has its own search box again. It filters
// the log by scrip, ENTER puts the keys back on the log, and ESC clears it.
func TestAlertsLogOwnSearchFiltersAndClears(t *testing.T) {
	a := demoApp(t, 120, 34)
	a.screen = scrAlerts
	a.flow.Log = []Flag{
		{Time: a.now, Symbol: "ECHO", Kind: "flow", Side: "BUY", Value: 12e6,
			Text: "ECHO is getting big buying orders"},
		{Time: a.now.Add(-1), Symbol: "XYZ", Kind: "flow", Side: "SELL", Value: 12e6,
			Text: "XYZ is getting big selling orders"},
	}
	a.onKey(Key{Kind: KRune, R: '/'})
	if !a.alertLogSearch || a.alertFocus != 2 {
		t.Fatalf("slash must focus the log box: search %v focus %d", a.alertLogSearch, a.alertFocus)
	}
	for _, r := range "ECHO" {
		a.onKey(Key{Kind: KRune, R: r})
	}
	if a.alertQuery != "ECHO" || a.searchText != "" {
		t.Fatalf("log box %q, right tile %q", a.alertQuery, a.searchText)
	}
	s := plain(a)
	if !strings.Contains(s, "ECHO is getting big buying orders") {
		t.Fatalf("the log search lost ECHO:\n%s", s)
	}
	if strings.Contains(s, "XYZ is getting big selling orders") {
		t.Fatalf("the log search did not filter XYZ:\n%s", s)
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

// Owner order 2026-11-18: the SEARCH tile puts T below B, S and U and adds
// BARS, NET DELTA and NET DELTA % in their own cells.
func TestSearchTileLedgerPutsTBelowBSU(t *testing.T) {
	a := demoApp(t, 122, 36)
	a.screen = scrScanner
	a.searchText, a.searchCursor = "AL", 0
	a.selectedSym, a.selectedSt = "ALFA", "ok"
	a.selectedInfo = demoStock("ALFA")
	c := NewCanvas(90, 20, a.th.Panel)
	a.drawSearchTile(c, 0, 0, 90, 20)
	rows := c.PlainRows()
	bRow, tRow, netRow := "", "", ""
	for _, row := range rows {
		if strings.Contains(row, "B=") && strings.Contains(row, "S=") {
			bRow = row
		}
		if strings.Contains(row, "T=") {
			tRow = row
		}
		if strings.Contains(row, "NET DELTA %") {
			netRow = row
		}
	}
	if bRow == "" || tRow == "" || netRow == "" {
		t.Fatalf("the search ledger is incomplete:\n%s", strings.Join(rows, "\n"))
	}
	if strings.Contains(bRow, "T=") {
		t.Fatalf("T is still on the B, S and U line: %q", bRow)
	}
	if !strings.Contains(tRow, "BARS") {
		t.Fatalf("the T line has no BARS: %q", tRow)
	}
	if !strings.Contains(netRow, "NET DELTA") || !strings.Contains(netRow, "NET DELTA %") {
		t.Fatalf("the NET DELTA line is incomplete: %q", netRow)
	}
}

// Owner order 2026-11-18: a changed REQ total marks the settings dirty, so the
// ten second save writes it down and the next build starts where this one
// stopped.
func TestReqCountMarksDirtyForPeriodicSave(t *testing.T) {
	a := newTestApp(t)
	today := utcDay(a.now)
	a.cfg.ReqDay, a.cfg.ReqCount = today, 0
	a.reqBase, a.reqOffset, a.dirty = 42, 0, false
	a.syncReqCount()
	if a.cfg.ReqCount != 42 || !a.dirty {
		t.Fatalf("REQ count %d, dirty %v, want 42 and dirty", a.cfg.ReqCount, a.dirty)
	}
	a.save()
	got := loadSettings(a.cfgPath)
	if got.ReqDay != today || got.ReqCount != 42 {
		t.Fatalf("stored REQ %s %d, want %s 42", got.ReqDay, got.ReqCount, today)
	}
}
