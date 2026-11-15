package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-15: the W/L & W/L RATE record moved from QUANT STATUS to
// the foot of the LATEST SIGNAL tile.
func TestWinLossRecordLivesOnLatestSignal(t *testing.T) {
	a := busyApp(t, 158, 41, 3)
	rows := rowsOf(a)
	signalRow, statusRow, wlRow, kseRow := -1, -1, -1, -1
	for i, row := range rows {
		switch {
		case strings.Contains(row, "LATEST SIGNAL"):
			signalRow = i
		case strings.Contains(row, "QUANT STATUS"):
			statusRow = i
		case strings.Contains(row, "W/L & W/L RATE"):
			wlRow = i
		case strings.Contains(row, "KSE100 INDEX"):
			kseRow = i
		}
	}
	if signalRow < 0 || wlRow < 0 {
		t.Fatalf("the LATEST SIGNAL tile has no W/L record:\n%s", strings.Join(rows, "\n"))
	}
	if statusRow >= 0 && wlRow == statusRow {
		t.Fatalf("the W/L record is still on QUANT STATUS:\n%s", strings.Join(rows, "\n"))
	}
	if wlRow <= signalRow || (kseRow >= 0 && wlRow >= kseRow) {
		t.Fatalf("the W/L record stands on row %d, outside LATEST SIGNAL (row %d):\n%s",
			wlRow, signalRow, strings.Join(rows, "\n"))
	}
	if !strings.Contains(rows[wlRow], "3/1 & 75%") {
		t.Fatalf("the W/L row carries no record: %q", rows[wlRow])
	}
}

// Owner order 2026-11-15: clicking a tile on ALERTS no longer highlights its
// frame. The panel's line ink is the theme line, not the focused hot frame.
func TestAlertsTilesDoNotHighlightOnFocus(t *testing.T) {
	a := demoApp(t, 120, 32)
	a.screen = scrAlerts
	check := func(name string, focus int, draw func(*Canvas)) {
		t.Helper()
		a.alertFocus = focus
		c := NewCanvas(100, 24, a.th.BG)
		draw(c)
		if c.Cells[0].FG != a.th.Line {
			t.Errorf("%s draws a focused frame on a click: corner ink %v, want line %v",
				name, c.Cells[0].FG, a.th.Line)
		}
	}
	check("BIG BUYING NOW", 0, func(c *Canvas) { a.drawBoardPanel(c, 0, 0, 40, 12, sideBuy) })
	check("ALERTS LOG", 2, func(c *Canvas) { a.drawAlertLog(c, 0, 0, 80, 20) })
	check("PRICE ALERTS", 3, func(c *Canvas) { a.drawPriceTile(c, 0, 0, 80, 5) })
}

// Owner order 2026-11-15: opening the POSITION CALCULATOR no longer highlights
// its tile frame either.
func TestCalculatorTileDoesNotHighlightOnFocus(t *testing.T) {
	a := demoApp(t, 122, 36)
	a.screen = scrScanner
	a.openCalc()
	c := NewCanvas(80, 6, a.th.BG)
	a.drawCalculatorTile(c, 0, 0, 80, 6)
	if c.Cells[0].FG != a.th.Line {
		t.Fatalf("the calculator draws a focused frame: corner ink %v, want line %v",
			c.Cells[0].FG, a.th.Line)
	}
}
