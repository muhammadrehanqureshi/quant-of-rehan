package main

import (
	"strings"
	"testing"
	"time"
	"unicode/utf8"
)

// Owner order 2026-11-24 (later): both ALERTS boards wear the heading ink every
// other tile wears, so neither board reads as a warning because its words are
// green or red.
func TestBuild169TheBoardsWearThePageHeadingInk(t *testing.T) {
	a := demoApp(t, 158, 41)
	a.cfg.BigBuy, a.cfg.BigSell = true, true
	a.screen = scrAlerts
	c := a.render()
	find := func(word string) (int, int) {
		target := []rune(word)
		for y := 0; y < c.H; y++ {
			for x := 0; x+len(target) <= c.W; x++ {
				hit := true
				for i, r := range target {
					if c.Cells[y*c.W+x+i].Ch != r {
						hit = false
						break
					}
				}
				if hit {
					return y, x
				}
			}
		}
		return -1, -1
	}
	buyY, buyX := find("BIG BUYING NOW")
	sellY, sellX := find("BIG SELLING NOW")
	if buyY < 0 || sellY < 0 {
		t.Fatalf("a board heading is missing:\n%s", strings.Join(c.PlainRows(), "\n"))
	}
	buyInk := c.Cells[buyY*c.W+buyX].FG
	sellInk := c.Cells[sellY*c.W+sellX].FG
		for _, ink := range []interface{}{buyInk, sellInk} {
		if ink == a.th.Good || ink == a.th.Bad {
			t.Fatalf("a board heading wears the buy and sell ink, want the page heading ink")
		}
	}
	if buyInk != a.th.Accent && buyInk != a.th.Hot {
		t.Fatalf("BIG BUYING NOW stands in %v, want the heading ink %v", buyInk, a.th.Accent)
	}
	if buyInk != sellInk {
		t.Fatalf("the two board headings stand in %v and %v, want one ink", buyInk, sellInk)
	}
}

// Owner order 2026-11-24 (later): both boards keep every transaction as its own
// row, at 50k shares and above, so the same scrip can stand twice with two
// quantities and a step under the floor never stands at all.
func TestBuild169EachBoardRowIsItsOwnTransaction(t *testing.T) {
	f := NewFlow(defaultFlowCfg(alertFloorShares))
	f.Observe(flowT0, feedOf(map[string]LiveQuote{"GCIL": lq(20, 1_000_000)}), true)
	f.Observe(flowT0.Add(time.Second), feedOf(map[string]LiveQuote{"GCIL": lq(20.01, 1_060_000)}), true) // 60k buy
	f.Observe(flowT0.Add(2*time.Second), feedOf(map[string]LiveQuote{"GCIL": lq(20.02, 1_130_000)}), true) // 70k buy
	// A 45k step is under the board's floor and never stands.
	f.Observe(flowT0.Add(3*time.Second), feedOf(map[string]LiveQuote{"GCIL": lq(20.03, 1_175_000)}), true)
	now := flowT0.Add(4 * time.Second)
	a := demoApp(t, 158, 41)
	a.flow = f
	a.now = now
	buy := a.boardRows(200)
	if len(buy) != 2 {
		t.Fatalf("the buying board carries %d rows, want the two transactions of 60k and 70k: %+v", len(buy), buy)
	}
	if buy[0].BuyShares != 70_000 || buy[1].BuyShares != 60_000 {
		t.Fatalf("the buying board reads %d then %d, want 70000 then 60000", buy[0].BuyShares, buy[1].BuyShares)
	}
	for _, r := range buy {
		if r.Symbol != "GCIL" {
			t.Fatalf("a board row names %q, want GCIL twice", r.Symbol)
		}
		if r.BuyShares < boardFloorShares {
			t.Fatalf("a board row carries %d shares, under the %d floor", r.BuyShares, boardFloorShares)
		}
	}

	sell := NewFlow(defaultFlowCfg(alertFloorShares))
	sell.Observe(flowT0, feedOf(map[string]LiveQuote{"KEL": lq(6.10, 1_000_000)}), true)
	sell.Observe(flowT0.Add(time.Second), feedOf(map[string]LiveQuote{"KEL": lq(6.08, 1_055_000)}), true) // 55k sell
	sell.Observe(flowT0.Add(2*time.Second), feedOf(map[string]LiveQuote{"KEL": lq(6.06, 1_145_000)}), true) // 90k sell
	b := demoApp(t, 158, 41)
	b.flow = sell
	b.now = flowT0.Add(3 * time.Second)
	rows := b.sellRows(200)
	if len(rows) != 2 {
		t.Fatalf("the selling board carries %d rows, want the two transactions of 55k and 90k: %+v", len(rows), rows)
	}
	if rows[0].SellShares != 90_000 || rows[1].SellShares != 55_000 {
		t.Fatalf("the selling board reads %d then %d, want 90000 then 55000", rows[0].SellShares, rows[1].SellShares)
	}
}

// Owner order 2026-11-24 (later): the ALERTS LOG reads in columns from the
// quantity onwards, so shares, of, the scrip, were bought and were sold start on
// one cell down the log, and the current price and the percentage hold their
// columns at the right.
func TestBuild169TheAlertLogHoldsItsColumns(t *testing.T) {
	a := demoApp(t, 158, 41)
	a.screen = scrAlerts
	up, down := 10.01, 5.56
	flags := []Flag{
		{Time: flowT0.Add(4 * time.Second), Symbol: "FPRM", Kind: "order", Side: "BUY", Shares: 149_660, Value: 149_660, Price: 16.59, ChangePct: &up},
		{Time: flowT0.Add(3 * time.Second), Symbol: "TPLREF1", Kind: "order", Side: "BUY", Shares: 100_000, Value: 100_000, Price: 8.85, ChangePct: &down},
		{Time: flowT0.Add(2 * time.Second), Symbol: "KEL", Kind: "order", Side: "SELL", Shares: 211_680, Value: 211_680, Price: 6.08, ChangePct: &down},
		{Time: flowT0.Add(time.Second), Symbol: "PRL", Kind: "order", Side: "SELL", Shares: 275_000, Value: 275_000, Price: 80.50, ChangePct: &up},
	}
	for _, fl := range flags {
		a.flow.addFlag(fl)
	}
	c := a.render()
	rows := c.PlainRows()
	at := func(row, word string) int {
		i := strings.Index(row, word)
		if i < 0 {
			return -1
		}
		return utf8.RuneCountInString(row[:i])
	}
	var sharesAt, wereAt, pkrAt, pctAt int
	seen := 0
	for _, sym := range []string{"FPRM", "TPLREF1", "KEL", "PRL"} {
		row := ""
		for _, r := range rows {
			if strings.Contains(r, "shares of "+sym+" ") {
				row = r
				break
			}
		}
		if row == "" {
			t.Fatalf("%s carries no order row:\n%s", sym, strings.Join(rows, "\n"))
		}
		sh, were := at(row, "shares of"), at(row, "were ")
		pkr := at(row, "PKR")
		// Owner order 2026-11-25 (build 173): the move starts on one cell for
		// every row, so the arrow is the column's cell and the figure follows
		// it. A two digit move ends one cell later than a one digit move, which
		// is the point of the alignment.
		pct := at(row, "▲")
		if pct < 0 {
			pct = at(row, "▼")
		}
		if sh < 0 || were < 0 || pkr < 0 || pct < 0 {
			t.Fatalf("%s's row is missing a column: %q", sym, row)
		}
		if seen == 0 {
			sharesAt, wereAt, pkrAt, pctAt = sh, were, pkr, pct
		} else {
			if sh != sharesAt {
				t.Errorf("%s starts shares on cell %d, want %d: %q", sym, sh, sharesAt, row)
			}
			if were != wereAt {
				t.Errorf("%s starts were on cell %d, want %d: %q", sym, were, wereAt, row)
			}
			if pkr != pkrAt {
				t.Errorf("%s starts PKR on cell %d, want %d: %q", sym, pkr, pkrAt, row)
			}
			if pct != pctAt {
				t.Errorf("%s starts its percentage on cell %d, want %d: %q", sym, pct, pctAt, row)
			}
		}
		seen++
	}
	if seen != len(flags) {
		t.Fatalf("the log carried %d of the %d order rows", seen, len(flags))
	}
}
