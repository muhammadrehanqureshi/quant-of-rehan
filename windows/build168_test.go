package main

import (
	"testing"
	"time"
)

// Owner order 2026-11-24 (later): a row on BIG BUYING NOW or BIG SELLING NOW
// keeps the price and the percentage the scrip held when that transaction
// printed. The row is a record of a transaction that already happened, so it
// must not follow the live quote while it stands on the board.
func TestBuild168TheBoardsKeepTheTransactionsOwnPrice(t *testing.T) {
	f := NewFlow(defaultFlowCfg(alertFloorShares))
	f.Observe(flowT0, feedOf(map[string]LiveQuote{"GCIL": lq(20, 1_000_000)}), true)

	first := lq(20.1, 1_060_000)
	firstPct := 1.25
	first.ChangePct = &firstPct
	f.Observe(flowT0.Add(time.Second), feedOf(map[string]LiveQuote{"GCIL": first}), true)

	second := lq(20.9, 1_210_000)
	secondPct := 3.5
	second.ChangePct = &secondPct
	f.Observe(flowT0.Add(2*time.Second), feedOf(map[string]LiveQuote{"GCIL": second}), true)

	// The quote moves on twice after both transactions printed.
	now := flowT0.Add(3 * time.Second)
	later := lq(21.4, 1_220_000)
	laterPct := 6.75
	later.ChangePct = &laterPct
	f.Observe(now, feedOf(map[string]LiveQuote{"GCIL": later}), true)

	rows := f.Increments(now, boardFloorShares, 0, sideBuy)
	if len(rows) != 2 {
		t.Fatalf("the board carries %d rows, want two transactions: %+v", len(rows), rows)
	}
	// Largest first: the 150k step printed at 20.9 and 3.5 percent.
	if rows[0].BuyShares != 150_000 || rows[0].Price != 20.9 {
		t.Fatalf("the 150k row reads %d shares at %v, want 150000 at 20.9", rows[0].BuyShares, rows[0].Price)
	}
	if rows[0].ChangePct == nil || *rows[0].ChangePct != 3.5 {
		t.Fatalf("the 150k row carries %v percent, want the 3.5 it printed at", rows[0].ChangePct)
	}
	if rows[1].BuyShares != 60_000 || rows[1].Price != 20.1 {
		t.Fatalf("the 60k row reads %d shares at %v, want 60000 at 20.1", rows[1].BuyShares, rows[1].Price)
	}
	if rows[1].ChangePct == nil || *rows[1].ChangePct != 1.25 {
		t.Fatalf("the 60k row carries %v percent, want the 1.25 it printed at", rows[1].ChangePct)
	}
	for _, r := range rows {
		if r.Price == 21.4 {
			t.Fatalf("a row followed the live quote to 21.4: %+v", r)
		}
	}
}
