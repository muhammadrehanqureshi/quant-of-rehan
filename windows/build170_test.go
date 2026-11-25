package main

import (
	"strings"
	"testing"
	"time"
)

// Owner order 2026-11-25: the percentage steps one cell left on BIG BUYING NOW
// and BIG SELLING NOW, so one blank cell stands between it and the quantity
// after it, and only the PKR label steps one cell left, so the label and its
// value stand one blank apart while the value keeps the field it holds.
func TestBuild170TheBoardsStepThePercentageAndThePkrLabelLeft(t *testing.T) {
	a := demoApp(t, 170, 40)
	// One priced transaction with its own move on each side, so both boards
	// carry the label, the value and the percentage this order is about.
	up, down := 2.35, 1.25
	a.flow.sym["TESTB"] = &symFlow{have: true, t: a.now, px: 12.5, vol: 250_000,
		evts: []flowEvt{{t: a.now, dv: 250_000, px: 12.5, side: 1, chg: &up}}}
	a.flow.sym["TESTS"] = &symFlow{have: true, t: a.now, px: 9.05, vol: 250_000,
		evts: []flowEvt{{t: a.now, dv: 250_000, px: 9.05, side: -1, chg: &down}}}
	for _, side := range []int{sideBuy, sideSell} {
		c := NewCanvas(100, 24, a.th.Panel)
		a.drawBoardPanel(c, 0, 0, 100, 24, side)
		seen := 0
		for _, row := range c.PlainRows() {
			if !strings.Contains(row, "PKR") || !strings.Contains(row, "%") {
				continue
			}
			r := []rune(row)
			pkr := runeAt(row, "PKR")
			if pkr < 0 || pkr+4 >= len(r) {
				t.Fatalf("side %d: the row ends before its price: %q", side, row)
			}
			// The label ends on pkr+2; the two cells after it are the blanks
			// the shift opened before the value's own field.
			if r[pkr+3] != ' ' || r[pkr+4] != ' ' {
				t.Fatalf("side %d: the label and its value are not one blank apart: %q", side, row)
			}
			pct := runeAt(row, "%")
			if pct < 0 || pct+1 >= len(r) {
				t.Fatalf("side %d: the row carries no percentage: %q", side, row)
			}
			if r[pct+1] != ' ' {
				t.Fatalf("side %d: the percentage touches the quantity after it: %q", side, row)
			}
			seen++
		}
		if seen == 0 {
			t.Fatalf("side %d drew no priced row with a percentage", side)
		}
	}
}

// Owner order 2026-11-25: the ALERTS LOG opens one more space between the scrip
// and were bought or were sold, and the verb holds one width, so at starts on
// one cell for a buy and a sell alike.
func TestBuild170TheLogSpacesTheScripFromWereAndAlignsAt(t *testing.T) {
	// The log gives its sentence the cells it needs at this width, the size
	// the ALERTS page's own column laws are read at.
	a := demoApp(t, 158, 41)
	a.screen = scrAlerts
	up := 10.01
	flags := []Flag{
		{Time: flowT0.Add(2 * time.Second), Symbol: "TPLREF1", Kind: "order", Side: "BUY",
			Shares: 149_660, Value: 149_660, Price: 16.59, ChangePct: &up},
		{Time: flowT0.Add(time.Second), Symbol: "KEL", Kind: "order", Side: "SELL",
			Shares: 211_680, Value: 211_680, Price: 6.08, ChangePct: &up},
	}
	for _, fl := range flags {
		a.flow.addFlag(fl)
	}
	rows := a.render().PlainRows()
	wereAt, atAt := -1, -1
	for i, sym := range []string{"TPLREF1", "KEL"} {
		row := ""
		for _, r := range rows {
			if strings.Contains(r, "shares of") && strings.Contains(r, sym) {
				row = r
				break
			}
		}
		if row == "" {
			t.Fatalf("%s carries no order row: %s", sym, strings.Join(rows, "\n"))
		}
		r := []rune(row)
		were, at := runeAt(row, "were "), runeAt(row, " at")
		if were < 2 || at < 0 {
			t.Fatalf("%s's row is missing a word: %q", sym, row)
		}
		if r[were-1] != ' ' || r[were-2] != ' ' {
			t.Fatalf("%s: the scrip and were are not two blanks apart: %q", sym, row)
		}
		if i == 0 {
			wereAt, atAt = were, at
			continue
		}
		if were != wereAt || at != atAt {
			t.Fatalf("%s starts were on cell %d and at on cell %d, want %d and %d: %q",
				sym, were, at, wereAt, atAt, row)
		}
	}
}

// Owner order 2026-11-25: a value the relay never sent reads N/A, never n/a.
func TestBuild170ThePlaceholderIsCapitalised(t *testing.T) {
	if got := watchNum(nil); got != "N/A" {
		t.Fatalf("a missing price reads %q, want N/A", got)
	}
	if got := watchVol(nil); got != "N/A" {
		t.Fatalf("a missing volume reads %q, want N/A", got)
	}
	if got := netDeltaText(FlowRow{}); got != "N/A" {
		t.Fatalf("an unmeasured split reads %q, want N/A", got)
	}
}
