package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-14: ORDER FLOW puts its NET DELTA in percentage beside
// the absolute figure, as the gap over the classified volume.
func TestOrderFlowNetDeltaPercent(t *testing.T) {
	buy, sell := int64(26_100_000), int64(17_000_000)
	r := FlowRow{Buy: &buy, Sell: &sell, Method: methodMeasured}
	pct, ok := netDeltaPct(r)
	if !ok {
		t.Fatal("a measured pair must have a NET DELTA percentage")
	}
	if got := pct; got < 21.11 || got > 21.12 {
		t.Fatalf("26.1M against 17M is %.4f percent, want 21.11", got)
	}
	if _, ok := netDeltaPct(FlowRow{Buy: &buy, Method: methodEstimated}); ok {
		t.Fatal("an estimated split must not carry a NET DELTA percentage")
	}
	zero := int64(0)
	if _, ok := netDeltaPct(FlowRow{Buy: &zero, Sell: &zero, Method: methodMeasured}); ok {
		t.Fatal("a measured row with no classified volume has no percentage")
	}
}

// The column stands after NET DELTA, under its own heading, on the ORDER FLOW
// table only.
func TestOrderFlowNetDeltaPercentColumn(t *testing.T) {
	a := orderFlowApp(t, 160, 45, sampleOrderFlow)
	rows := rowsOf(a)
	head, bbb := -1, -1
	for i, row := range rows {
		if strings.Contains(row, "NET DELTA %") {
			head = i
		}
		if strings.Contains(row, "BBB") && strings.Contains(row, "63.27%") {
			bbb = i
		}
	}
	if head < 0 {
		t.Fatalf("the NET DELTA %% heading is missing:\n%s", strings.Join(rows, "\n"))
	}
	if bbb < 0 {
		t.Fatalf("BBB's NET DELTA %% value is missing:\n%s", strings.Join(rows, "\n"))
	}
	hx := strings.Index(rows[head], "NET DELTA %")
	vx := strings.Index(rows[bbb], "63.27%")
	if hx != vx {
		t.Fatalf("the heading starts on %d and its value on %d, so the column is not aligned", hx, vx)
	}
	if ds := plain(a); !strings.Contains(ds, "33.33%") {
		t.Errorf("AAA's 300 over 900 must read 33.33%%:\n%s", ds)
	}

	a.screen = scrHome
	if strings.Contains(plain(a), "NET DELTA %") {
		t.Fatal("the NET DELTA % column must not appear outside ORDER FLOW")
	}
}

// NET DELTA % is in the ORDER FLOW sort list, highest percentage first, with
// unmeasured rows last.
func TestOrderFlowSortsByNetDeltaPercent(t *testing.T) {
	a := orderFlowApp(t, 160, 45, sampleOrderFlow)
	a.ofSort = flowSortNetDeltaPct
	rows := a.sortedFlow()
	if len(rows) < 4 {
		t.Fatalf("only %d flow rows", len(rows))
	}
	if rows[0].Symbol != "BBB" || rows[1].Symbol != "AAA" {
		t.Fatalf("by NET DELTA %%: %s %s", rows[0].Symbol, rows[1].Symbol)
	}
	if last := rows[len(rows)-1].Symbol; last != "DDD" {
		t.Fatalf("a row with no measured percentage must go last, not %s", last)
	}
	found := false
	for _, name := range flowSorts {
		if name == "NET DELTA %" {
			found = true
		}
	}
	if !found {
		t.Fatal("NET DELTA % is not in the ORDER FLOW sort list")
	}
}
