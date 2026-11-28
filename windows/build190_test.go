package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-28 (build 190): "on the footer of ORDER FLOW page, remove
// the centered dot before large prints of QTY, have it written just one space
// after the full stop of '... either B or S.', write like this 'qty prints of
// QTY 50k and above.'. on the SECTORS tile, move the alignment of PKR and its
// values one space to the left, make this change for the entire SECTORS tile.
// on the TELEMETRY tile, in front of PHASE, write 'CLOSED' in red and 'OPEN' in
// green. the results for the SCRIPS WITH LOWER LOCK and SCRPS WITH UPPER LOCK
// are not accurate. I am seeing scrips with ~5% change as well. UPPER
// LOCK/LOWER LOCKS on PSX contains ~20% and ~10%."

// The ORDER FLOW foot keeps the dot away and closes on "and above.".
func TestBuild190OrderFlowFootDropsTheDotAndSaysAndAbove(t *testing.T) {
	a := orderFlowApp(t, 160, 45, sampleOrderFlow)
	s := plain(a)
	if strings.Contains(s, "and more.") {
		t.Fatalf("the ORDER FLOW foot still says and more:\n%s", s)
	}
	const lead = "either B or S."
	i := strings.Index(s, lead)
	if i < 0 {
		t.Fatalf("the ORDER FLOW foot carries no U = UNCLEAR line:\n%s", s)
	}
	rest := []rune(s[i+len(lead):])
	if len(rest) < 3 || rest[0] != ' ' || rest[1] == ' ' {
		t.Fatalf("the foot holds %q after B or S., want one space before the count", string(rest))
	}
	// Owner order 2026-11-28 (build 191): the word "large" is withdrawn, so
	// the foot names the board's prints and their quantity alone.
	if !strings.Contains(string(rest), " prints of QTY 50k and above.") {
		t.Fatalf("the foot does not close on prints of QTY 50k and above: %q", string(rest))
	}
	if strings.Contains(string(rest), "large") {
		t.Fatalf("the foot still says large: %q", string(rest))
	}
	if strings.Contains(string(rest), "·") {
		t.Fatalf("the foot still carries the centred dot: %q", string(rest))
	}
}

// The phase word carries the law of its side: CLOSED red, OPEN green.
func TestBuild190PhaseClosedIsRedAndOpenIsGreen(t *testing.T) {
	a := demoApp(t, 140, 34)
	a.screen = scrHome
	check := func(open bool, word string, ink RGB) {
		t.Helper()
		a.marketOpen = open
		c := a.render()
		y, x := findCells(c, "PHASE")
		if y < 0 {
			t.Fatalf("TELEMETRY carries no PHASE row:\n%s", strings.Join(c.PlainRows(), "\n"))
		}
		row := []rune(c.PlainRows()[y])
		want := []rune(word)
		i := -1
		for k := 0; k+len(want) <= len(row); k++ {
			if string(row[k:k+len(want)]) == word {
				i = k
				break
			}
		}
		if i < x {
			t.Fatalf("the PHASE row carries no %s: %q", word, string(row))
		}
		for k, r := range want {
			cell := c.Cells[y*c.W+i+k]
			if cell.Ch != r {
				t.Fatalf("the PHASE row holds %q where %q belongs: %q", cell.Ch, r, string(row))
			}
			if cell.FG != ink {
				t.Fatalf("%s stands in %v, want %v: %q", word, cell.FG, ink, string(row))
			}
		}
	}
	check(false, "CLOSED", a.th.Bad)
	check(true, "OPEN", a.th.Good)
}

	// The opened SECTORS list keeps PKR and its figures left of where build 185
// placed them, on every row of the tile. Owner order 2026-11-28 (build 191):
// build 190's one cell read as unmoved on his screen, so the column takes one
// more cell and stands two cells off the frame's right edge.
func TestBuild190SectorPricesStepOneCellLeft(t *testing.T) {
	a := demoApp(t, 158, 41)
	a.demo = false
	a.quotes = nil
	a.screen = scrScanner
	a.sectors = &Sectors{OK: true, Items: []Sector{{Name: "TEST", Symbols: []string{"AAA", "BBB"}}}}
	a.prices = map[string]Quote{
		"AAA": {Price: 71.44, ChangePct: f64(2.03)},
		"BBB": {Price: 127.49, ChangePct: f64(-2.01)},
	}
	a.symbols = nil
	a.sectorOpen, a.sectorChoice = true, 0
	a.lvSectorStk.top()
	const w, h = 120, 12
	scratch := NewCanvas(w, h, a.th.Panel)
	ix, _, iw, _ := a.panel(scratch, 0, 0, w, h, "SECTORS", sectorMoveHint)
	want := ix + iw - quoteWidth(8) - 2
	c := NewCanvas(w, h, a.th.Panel)
	a.drawSectorOpen(c, 0, 0, w, h)
	found := 0
	for _, row := range c.PlainRows() {
		i := col(row, "PKR")
		if i < 0 {
			continue
		}
		found++
		if i != want {
			t.Fatalf("PKR stands on cell %d, want %d: %q", i, want, row)
		}
		r := []rune(row)
		if r[ix+iw-4] != '%' {
			t.Fatalf("the percentage does not close three cells inside the frame: %q", row)
		}
		if r[ix+iw-3] != ' ' || r[ix+iw-2] != ' ' {
			t.Fatalf("the quote group does not leave the frame's edge clear: %q", row)
		}
	}
	if found == 0 {
		t.Fatalf("the opened sector lists no PKR row:\n%s", strings.Join(c.PlainRows(), "\n"))
	}
}

// A lock is the exchange's own circuit, about ten percent either way, so a five
// percent mover is never named by either lock sort.
func TestBuild190LocksHoldTheExchangeCircuit(t *testing.T) {
	if lockMoveMark < 9.9 || lockMoveMark >= 10 {
		t.Fatalf("the lock mark is %v, want the exchange's ten percent circuit", lockMoveMark)
	}
	q := map[string]Quote{
		"AAA": {ChangePct: f64(-5.2), Volume: i64(900)},  // five percent, no lock
		"BBB": {ChangePct: f64(5.4), Volume: i64(800)},   // five percent, no lock
		"CCC": {ChangePct: f64(-10.4), Volume: i64(100)}, // lower lock, heaviest
		"DDD": {ChangePct: f64(20.2), Volume: i64(50)},   // upper lock, widened band
		"EEE": {ChangePct: f64(-9.9), Volume: i64(10)},   // lower lock, on the mark
	}
	if got := strings.Join(rankedLowerLockSymbols(q), ","); got != "CCC,EEE" {
		t.Fatalf("the lower lock names %q, want CCC,EEE", got)
	}
	if got := strings.Join(rankedUpperLockSymbols(q), ","); got != "DDD" {
		t.Fatalf("the upper lock names %q, want DDD", got)
	}
	// PRICES RISING FAST keeps the app's own capped move mark, so a five
	// percent print is still capped there and no row rises fast.
	if got := rankedSpeedSymbols(q); len(got) != 0 {
		t.Fatalf("the rising fast sort names %v, want none", got)
	}
}
