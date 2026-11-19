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

// Owner order 2026-11-18: the SCANNER SEARCH tile puts T after U, drops the
// BARS word, and puts the bar and both NET DELTA figures on the line below.
func TestScannerSearchLedgerPutsTAfterU(t *testing.T) {
	a := demoApp(t, 122, 36)
	a.screen = scrScanner
	a.searchText, a.searchCursor = "AL", 0
	a.selectedSym, a.selectedSt = "ALFA", "ok"
	a.selectedInfo = demoStock("ALFA")
	c := NewCanvas(116, 20, a.th.Panel)
	a.drawSearchTile(c, 0, 0, 116, 20)
	rows := c.PlainRows()
	volRow, barRow := "", ""
	for _, row := range rows {
		if strings.Contains(row, "B=") && strings.Contains(row, "S=") {
			volRow = row
		}
		if strings.ContainsRune(row, barBlock) && strings.Contains(row, "NET DELTA %") {
			barRow = row
		}
	}
	if volRow == "" || barRow == "" {
		t.Fatalf("the SCANNER search ledger is incomplete:\n%s", strings.Join(rows, "\n"))
	}
	if !strings.Contains(volRow, "U=") || !strings.Contains(volRow, "T=") {
		t.Fatalf("T is not after U on the volume line: %q", volRow)
	}
	if strings.Contains(volRow, "BARS") || strings.Contains(barRow, "BARS") {
		t.Fatalf("the SCANNER search tile still prints BARS:\n%s", strings.Join(rows, "\n"))
	}
	if !strings.Contains(barRow, "NET DELTA") {
		t.Fatalf("the bar line carries no NET DELTA: %q", barRow)
	}
}

// Owner order 2026-11-18: the ALERTS SEARCH tile keeps T on its own line, puts
// the bar four cells after T and prints no BARS word.
func TestAlertsSearchLedgerPutsBarAfterT(t *testing.T) {
	a := demoApp(t, 140, 36)
	a.screen = scrAlerts
	a.searchText, a.searchCursor = "AL", 0
	a.selectedSym, a.selectedSt = "ALFA", "ok"
	a.selectedInfo = demoStock("ALFA")
	c := NewCanvas(90, 20, a.th.Panel)
	a.drawSearchTile(c, 0, 0, 90, 20)
	rows := c.PlainRows()
	bRow, tRow := "", ""
	for _, row := range rows {
		if strings.Contains(row, "B=") && strings.Contains(row, "S=") {
			bRow = row
		}
		if strings.Contains(row, "T=") {
			tRow = row
		}
	}
	if bRow == "" || tRow == "" {
		t.Fatalf("the ALERTS search ledger is incomplete:\n%s", strings.Join(rows, "\n"))
	}
	if strings.Contains(bRow, "T=") {
		t.Fatalf("T is not on its own line on ALERTS: %q", bRow)
	}
	if strings.Contains(tRow, "BARS") {
		t.Fatalf("the ALERTS T line still prints BARS: %q", tRow)
	}
	tAt := col(tRow, "T=")
	barAt := col(tRow, string(barBlock))
	if tAt < 0 || barAt < 0 {
		t.Fatalf("the ALERTS T line carries no bar: %q", tRow)
	}
	if want := tAt + 2 + leaderVolDigits + 2 + 2; barAt != want {
		t.Fatalf("the bar starts on cell %d, want two cells after T on %d: %q", barAt, want, tRow)
	}
}

// Owner order 2026-11-18: S gives the ALERTS SEARCH tile the keys, and the
// tile names that key while its box is empty.
func TestAlertsSearchTileOpensOnS(t *testing.T) {
	a := demoApp(t, 120, 34)
	a.screen = scrAlerts
	a.alertFocus = 0
	a.onKey(Key{Kind: KRune, R: 's'})
	if a.alertFocus != 4 {
		t.Fatalf("S must focus the ALERTS SEARCH tile, focus %d", a.alertFocus)
	}
	if s := plain(a); !strings.Contains(s, alertSearchHint) {
		t.Fatalf("the ALERTS SEARCH tile does not name the S key:\n%s", s)
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
