package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-20 (latest): at the owner's 122x36 window the KSE100 leader
// writes its price, its percentage and NET DELTA on the line that carries T, and
// the bar stands on the line above the price, starting on the price's own cell.
func TestBuild147KSE100QuoteSharesTheTLine(t *testing.T) {
	a := busyApp(t, 122, 36, 3)
	rows := rowsOf(a)
	inside := false
	priced, barred := 0, 0
	for i, row := range rows {
		switch {
		case strings.Contains(row, "KSE100 INDEX & THE TOP 3 SCRIPS OF VOLUME"):
			inside = true
			continue
		case strings.Contains(row, "BUYING NOW"):
			inside = false
		}
		if !inside || !strings.Contains(row, "T=") {
			continue
		}
		if !strings.Contains(row, "PKR ") {
			t.Errorf("the T line carries no price: %q", row)
			continue
		}
		priced++
		if !strings.Contains(row, "NET DELTA=") {
			t.Errorf("the price's line carries no NET DELTA=: %q", row)
		}
		if !strings.Contains(row, "%") {
			t.Errorf("the price's line carries no percentage: %q", row)
		}
		if i == 0 {
			continue
		}
		above := rows[i-1]
		at := col(row, "PKR ")
		barAt := col(above, string(barBlock))
		if barAt < 0 || barAt != at {
			t.Errorf("the bar above the price starts on %d, the price on %d: %q", barAt, at, above)
			continue
		}
		barred++
	}
	if priced == 0 {
		t.Fatalf("no KSE100 T line carried its price:\n%s", strings.Join(rows, "\n"))
	}
	if barred == 0 {
		t.Fatalf("no KSE100 bar stood above a price:\n%s", strings.Join(rows, "\n"))
	}
}

// Owner order 2026-11-20 (latest): ORDER FLOW keeps the bar, NET DELTA and
// NET DELTA % columns on the owner's window, with one cell between the columns
// and HIGH and LOW standing down there rather than either NET DELTA figure.
func TestBuild147OrderFlowKeepsTheNetDeltaColumns(t *testing.T) {
	a := orderFlowApp(t, 122, 36, sampleOrderFlow)
	a.screen = scrOrderFlow
	rows := rowsOf(a)
	head := -1
	for i, row := range rows {
		if strings.Contains(row, "SCRIP") && strings.Contains(row, "NET DELTA %") {
			head = i
			break
		}
	}
	if head < 0 {
		t.Fatalf("the ORDER FLOW heading carries no NET DELTA %% column:\n%s", strings.Join(rows, "\n"))
	}
	// HIGH and LOW step out at this width so the bar and both NET DELTA columns
	// stay; they are back on a wider window.
	for _, want := range []string{"TOTAL (T)", "BAR", "NET DELTA"} {
		if !strings.Contains(rows[head], want) {
			t.Errorf("the ORDER FLOW heading lost %q: %q", want, rows[head])
		}
	}
	bars := 0
	for _, row := range rows[head+1:] {
		if strings.Contains(row, string(barBlock)) {
			bars++
		}
	}
	if bars == 0 {
		t.Fatalf("no ORDER FLOW row carried a bar:\n%s", strings.Join(rows, "\n"))
	}
}
