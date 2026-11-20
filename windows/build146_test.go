package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-20: the BUILD VERSION & RELAY tile carries the version,
// the relay, the request count, the scanning window and the settings file, and
// the broker refresh line is gone from it.
func TestBuild146BuildTileDropsTheBrokerRefreshLine(t *testing.T) {
	a := demoApp(t, 140, 40)
	a.screen = scrSettings
	s := plain(a)
	if strings.Contains(s, "Broker refresh") {
		t.Fatalf("the BUILD VERSION & RELAY tile still names the broker refresh:\n%s", s)
	}
	for _, want := range []string{"BUILD VERSION & RELAY", "VERSION", "RELAY", "REQUESTS TODAY"} {
		if !strings.Contains(s, want) {
			t.Errorf("the BUILD VERSION & RELAY tile lost %q", want)
		}
	}
}

// Owner order 2026-11-20: both SEARCH tiles write each figure on the cell after
// its own equals sign, so neither label leaves a gap before its number.
func TestBuild146SearchTilesHugTheirEqualsSigns(t *testing.T) {
	a := demoApp(t, 140, 34)
	c := NewCanvas(120, 6, a.th.Panel)
	a.drawNetRow(c, 0, 0, 1_200_000, 400_000)
	row := string([]rune(c.PlainRows()[0]))
	netAt := col(row, "NET DELTA=")
	pctAt := col(row, "NET DELTA %=")
	if netAt < 0 || pctAt < 0 {
		t.Fatalf("the line carries no NET DELTA and NET DELTA %%: %q", row)
	}
	r := []rune(row)
	if netAt+10 >= len(r) || r[netAt+10] == ' ' {
		t.Errorf("NET DELTA= leaves a gap before its figure: %q", row)
	}
	if pctAt+12 >= len(r) || r[pctAt+12] == ' ' {
		t.Errorf("NET DELTA %%= leaves a gap before its figure: %q", row)
	}
	if !strings.Contains(row[netAt:pctAt], "  &  ") {
		t.Errorf("the two figures are not joined by an ampersand with two cells each side: %q", row)
	}
}

// Owner order 2026-11-20: HIGH and LOW join ORDER FLOW after CHANGE, before BID,
// and the columns keep their left to right order under the headings.
func TestBuild146OrderFlowCarriesHighAndLow(t *testing.T) {
	want := []string{"PRICE", "CHANGE", "HIGH", "LOW", "BID", "ASK",
		"BUYING (B)", "SELLING (S)", "UNCLEAR (U)", "TOTAL (T)"}
	if len(want) != len(flowHeads) {
		t.Fatalf("the table carries %d headings, want %d", len(flowHeads), len(want))
	}
	for i, hd := range want {
		if flowHeads[i] != hd {
			t.Fatalf("heading %d reads %q, want %q", i, flowHeads[i], hd)
		}
	}
	rows := []FlowRow{{
		Symbol: "AAA", Price: 10, ChangePct: f64(1.5),
		High: f64(11), Low: f64(9), Bid: f64(9.9), Ask: f64(10.1),
		Buy: i64(100), Sell: i64(50), Volume: i64(200), Method: methodMeasured,
	}}
	flowDropHL = false
	cols, barX := flowColumns(rows)
	for i := 1; i < len(cols); i++ {
		if cols[i].x <= cols[i-1].x {
			t.Fatalf("column %d starts on cell %d, not right of column %d on %d",
				i, cols[i].x, i-1, cols[i-1].x)
		}
	}
	if barX <= cols[len(cols)-1].x+cols[len(cols)-1].w {
		t.Fatalf("the bar starts on cell %d, over the TOTAL column", barX)
	}
}

// Owner order 2026-11-20: an opened sector shows four of its scrips in the
// height the scanner gives the tile, so the fourth is not a scroll away.
func TestBuild146OpenSectorShowsFourScrips(t *testing.T) {
	a := demoApp(t, 158, 41)
	a.demo = false
	a.quotes = nil
	a.screen = scrScanner
	a.sectors = &Sectors{OK: true, Items: []Sector{{Name: "REFINERY",
		Symbols: []string{"AAA", "BBB", "CCC", "DDD"}}}}
	a.symbols = nil
	a.sectorOpen, a.sectorChoice = true, 0
	a.lvSectorStk.top()
	c := NewCanvas(120, 8, a.th.Panel)
	a.drawSectorOpen(c, 0, 0, 120, 8)
	if a.lvSectorStk.total != 4 {
		t.Fatalf("the open sector lists %d scrips, want four", a.lvSectorStk.total)
	}
	if a.lvSectorStk.view != 4 {
		t.Fatalf("the open sector shows %d scrips, want four", a.lvSectorStk.view)
	}
}

// Owner order 2026-11-20: the KSE100 leader writes its price, its percentage and
// NET DELTA last, with the equals sign hard against the label, on the volume
// line where its B, S, U and T stand.
func TestBuild146KSE100NetDeltaClosesTheQuote(t *testing.T) {
	a := busyApp(t, 158, 41, 3)
	inside, found := false, 0
	for _, row := range rowsOf(a) {
		switch {
		case strings.Contains(row, "KSE100 INDEX & THE TOP 3 SCRIPS OF VOLUME"):
			inside = true
			continue
		case strings.Contains(row, "BUYING NOW"):
			inside = false
		}
		if !inside || !strings.Contains(row, "PKR ") {
			continue
		}
		found++
		netAt, pctAt := col(row, "NET DELTA="), col(row, "%")
		if netAt < 0 {
			t.Errorf("the leader carries no NET DELTA: %q", row)
			continue
		}
		if pctAt < 0 || netAt < pctAt {
			t.Errorf("NET DELTA= does not stand after the percentage: %q", row)
		}
	}
	if found == 0 {
		t.Fatalf("no KSE100 leader carried its quote:\n%s", plain(a))
	}
}

// Owner order 2026-11-20: the PRICE ALERTS form names what to type in each box
// and lists the KMIALL scrips that carry the letters typed so far.
func TestBuild146PriceEditorHintsAndMatches(t *testing.T) {
	a := demoApp(t, 122, 36)
	a.screen = scrAlerts
	a.symbols = []string{"PRIVATE", "APRIL", "CHRL"}
	a.startPriceEdit(0)
	// An empty box says what to type in it.
	c := NewCanvas(122, 36, a.th.Panel)
	a.drawPriceEditor(c)
	hints := strings.Join(c.PlainRows(), "\n")
	for _, want := range []string{"Enter scrip", "Enter price"} {
		if !strings.Contains(hints, want) {
			t.Errorf("the price form is missing %q:\n%s", want, hints)
		}
	}
	// The scrip box lists every scrip that carries the letters typed.
	a.priceBuf, a.priceField = "PR", 0
	c = NewCanvas(122, 36, a.th.Panel)
	a.drawPriceEditor(c)
	s := strings.Join(c.PlainRows(), "\n")
	for _, want := range []string{"PRIVATE", "APRIL", "Enter price"} {
		if !strings.Contains(s, want) {
			t.Errorf("the price form is missing %q:\n%s", want, s)
		}
	}
	if strings.Contains(s, "CHRL") {
		t.Errorf("the price form lists a scrip that does not carry PR:\n%s", s)
	}
}

// Owner order 2026-11-20: the ALERTS LOG keeps the price and the percentage the
// alert was raised at, and never follows the live quote afterwards.
func TestBuild146AlertLogKeepsTheRaisedPercentage(t *testing.T) {
	a := newTestApp(t)
	raised := 1.5
	f := Flag{Symbol: "AAA", Price: 10, ChangePct: &raised}
	if got := a.alertPct(f); got == nil || *got != raised {
		t.Fatalf("the log reads %v, want the raised 1.5", got)
	}
	live := 4.25
	a.quotes = &Quotes{Items: map[string]LiveQuote{
		"AAA": {Price: 12, Fresh: true, ChangePct: &live},
	}}
	if got := a.alertPct(f); got == nil || *got != raised {
		t.Fatalf("the log followed the live quote to %v, want the raised 1.5", got)
	}
}
