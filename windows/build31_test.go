package main

import (
	"strings"
	"testing"
	"time"
)

// Owner order 2026-11-16: both ALERTS boards name the current price with PKR
// and the share quantity is written without the old sh suffix.
func TestAlertBoardsPriceAndShareQuantity(t *testing.T) {
	a := demoApp(t, 160, 40)
	for _, side := range []int{sideBuy, sideSell} {
		c := NewCanvas(78, 20, a.th.Panel)
		a.drawBoardPanel(c, 0, 0, 78, 20, side)
		rows := c.PlainRows()
		found := false
		for _, row := range rows {
			if strings.Contains(row, " sh") {
				t.Errorf("side %d still writes sh: %q", side, row)
			}
			if strings.Contains(row, "PKR ") {
				found = true
			}
		}
		if !found {
			t.Errorf("side %d carries no PKR price:\n%s", side, strings.Join(rows, "\n"))
		}
	}
}

// The alert sentence is the owner's wording, with the current price and the
// day's direction and percentage.
func TestBigOrderSentenceNamesSharesPriceAndChange(t *testing.T) {
	f := NewFlow(defaultFlowCfg(100_000))
	pct := 5.08
	base := LiveQuote{Price: 114.60, Fresh: true, Volume: 1_000_000, ChangePct: &pct}
	f.Observe(flowT0, feedOf(map[string]LiveQuote{"PRL": base}), true)
	next := LiveQuote{Price: 114.65, Fresh: true, Volume: 1_100_000, ChangePct: &pct}
	got := f.Observe(flowT0.Add(time.Second), feedOf(map[string]LiveQuote{"PRL": next}), true)
	if len(got) != 1 {
		t.Fatalf("a 100k share order raised %d flags", len(got))
	}
	want := "100k shares of PRL were bought at PKR 114.65 ▲ 5.08%."
	if got[0].Text != want {
		t.Fatalf("alert reads %q, want %q", got[0].Text, want)
	}
}

// Owner order 2026-11-16: the SYMBOL order is gone from ORDER FLOW. The table
// still has a SYMBOL column, so this checks the order list, not the heading.
func TestOrderFlowHasNoSymbolOrder(t *testing.T) {
	for _, name := range flowSorts {
		if name == "SYMBOL" {
			t.Fatal("SYMBOL is still an ORDER FLOW order")
		}
	}
	a := orderFlowApp(t, 160, 45, sampleOrderFlow)
	for _, row := range rowsOf(a) {
		if strings.HasPrefix(strings.TrimSpace(row), "ORDER ") && strings.Contains(row, "SYMBOL") {
			t.Fatalf("the order row still offers SYMBOL: %q", row)
		}
	}
}

// Owner order 2026-11-16: NET DELTA % stays on screen when the table is
// narrower, by giving cells to the bar rather than dropping the column.
func TestOrderFlowNetDeltaPercentFitsNarrowTable(t *testing.T) {
	a := orderFlowApp(t, 150, 45, sampleOrderFlow)
	s := plain(a)
	if !strings.Contains(s, "NET DELTA %") {
		t.Fatalf("NET DELTA %% is missing at 150 columns:\n%s", s)
	}
	if !strings.Contains(s, "63.27%") {
		t.Fatalf("the NET DELTA %% value is missing at 150 columns:\n%s", s)
	}
}
