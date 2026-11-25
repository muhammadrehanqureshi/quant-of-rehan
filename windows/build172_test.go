package main

import (
	"strings"
	"testing"
	"time"
)

// Owner order 2026-11-25: the yellow diamond the flagged rows carried on BIG
// BUYING NOW and BIG SELLING NOW is withdrawn. The two cells stay, so the
// symbol keeps its column and the boards still line up with the PRICE ALERTS
// tile under them.
func TestBuild172BoardsWearNoDiamondOnTheirRows(t *testing.T) {
	a := demoApp(t, 120, 30)
	flagged := 0
	for _, side := range []int{sideBuy, sideSell} {
		c := NewCanvas(79, 20, a.th.Panel)
		a.drawBoardPanel(c, 0, 0, 79, 20, side)
		for y, row := range c.PlainRows() {
			if y == 0 {
				continue // the heading keeps the panel's own diamond
			}
			if strings.ContainsRune(row, '◆') {
				t.Fatalf("side %d: row %d still wears the diamond: %q", side, y, row)
			}
			if strings.TrimSpace(row) != "" {
				flagged++
			}
		}
	}
	if flagged == 0 {
		t.Fatal("the boards drew no rows, so the mark law was never exercised")
	}
}

// Owner order 2026-11-25: NET DELTA is a receipt. The day's measured buying
// minus selling is copied onto the step when it prints, so a later frame that
// reverses the pair never restamps an older row.
func TestBuild172NetDeltaBelongsToThePrint(t *testing.T) {
	f := NewFlow(defaultFlowCfg(50_000))
	pair := func(vol, buy, sell int64) *Quotes {
		b, s := buy, sell
		return &Quotes{OK: true, Items: map[string]LiveQuote{"AAA": {
			Price: 10, Fresh: true, Volume: vol,
			MeasuredBuy: &b, MeasuredSell: &s, FlowMethod: methodMeasured,
		}}}
	}
	f.Observe(flowT0, pair(200_000, 100_000, 100_000), true)
	f.Observe(flowT0.Add(time.Second), pair(300_000, 200_000, 100_000), true)
	f.Observe(flowT0.Add(2*time.Second), pair(400_000, 200_000, 200_000), true)

	bought := f.Increments(flowT0.Add(3*time.Second), 50_000, 0, sideBuy)
	if len(bought) != 1 {
		t.Fatalf("the buying side holds %d step(s), want one", len(bought))
	}
	// The first print stood at +100,000; the pair has since fallen back to 0.
	if !bought[0].NetKnown || bought[0].Net != 100_000 {
		t.Fatalf("the buying row carries net %+d (known %v), want +100000",
			bought[0].Net, bought[0].NetKnown)
	}
	sold := f.Increments(flowT0.Add(3*time.Second), 50_000, 0, sideSell)
	if len(sold) != 1 {
		t.Fatalf("the selling side holds %d step(s), want one", len(sold))
	}
	if !sold[0].NetKnown || sold[0].Net != 0 {
		t.Fatalf("the selling row carries net %+d (known %v), want 0",
			sold[0].Net, sold[0].NetKnown)
	}
}

// The board prints the step's own reading, never the live pair.
func TestBuild172BoardPrintsTheFrozenNetDelta(t *testing.T) {
	a := demoApp(t, 120, 30)
	liveBuy, liveSell := int64(900_000), int64(100_000)
	a.quotes = &Quotes{OK: true, Items: map[string]LiveQuote{"AAA": {
		Price: 10, Fresh: true, Volume: 1_000_000,
		MeasuredBuy: &liveBuy, MeasuredSell: &liveSell, FlowMethod: methodMeasured,
	}}}
	a.flow = NewFlow(defaultFlowCfg(50_000))
	a.flow.sym["AAA"] = &symFlow{have: true, t: a.now, px: 10, vol: 1_000_000,
		buy: liveBuy, sell: liveSell, pair: true,
		evts: []flowEvt{{t: a.now, dv: 120_000, px: 10, side: 1,
			net: 250_000, netKnown: true}}}
	c := NewCanvas(79, 20, a.th.Panel)
	a.drawBoardPanel(c, 0, 0, 79, 20, sideBuy)
	want := signedCompact(250_000)
	live := signedCompact(800_000)
	for _, row := range c.PlainRows() {
		if !strings.Contains(row, "AAA") {
			continue
		}
		if !strings.Contains(row, want) {
			t.Fatalf("the row does not carry the print's own NET DELTA %q: %q", want, row)
		}
		if strings.Contains(row, live) {
			t.Fatalf("the row was restamped with the live pair %q: %q", live, row)
		}
		return
	}
	t.Fatal("the buying board drew no AAA row")
}

// Owner order 2026-11-25: a price alert reads "<scrip> hit its price alert of
// PKR <price>", the price being the print that rang it.
func TestBuild172PriceAlertNamesItsOwnPrice(t *testing.T) {
	a := newTestApp(t)
	a.now = flowT0
	a.cfg.BigBuy, a.cfg.BigSell = false, false
	a.ingestQuotes(quotesAt(15.00, 1_000_000))
	a.setPriceAlert(0, "ECHO", 15.50)
	a.now = flowT0.Add(time.Second)
	a.ingestQuotes(quotesAt(15.55, 1_200_000))
	if len(a.flow.Log) != 1 {
		t.Fatalf("the log holds %d rows, want one price alert", len(a.flow.Log))
	}
	row := a.flow.Log[0]
	want := "ECHO hit its price alert of PKR 15.55"
	if row.Text != want {
		t.Fatalf("the log sentence is %q, want %q", row.Text, want)
	}
	if strings.Contains(row.Text, "hit the PKR") {
		t.Fatalf("the old wording survives: %q", row.Text)
	}
	if p := a.cfg.PriceAlerts[0]; p.Hit != 15.55 {
		t.Fatalf("the slot holds hit %v, want 15.55", p.Hit)
	}
	a.screen = scrAlerts
	if s := plain(a); !strings.Contains(s, "hit its price alert of") {
		t.Fatalf("the ALERTS page does not carry the new sentence:\n%s", s)
	}
}

// Owner order 2026-11-25: the PRICE ALERTS tile wears the BIG BUYING NOW
// tile's own alternating shades.
func TestBuild172PriceAlertsWearTheBoardShades(t *testing.T) {
	a := demoApp(t, 120, 24)
	c := NewCanvas(120, 24, a.th.Panel)
	a.drawPriceTile(c, 0, 0, 90, 9)
	rows := c.PlainRows()
	var slots []int
	for y, row := range rows {
		body := row
		if at := strings.IndexRune(body, '│'); at >= 0 {
			body = body[at+1:]
		}
		body = strings.TrimSpace(body)
		if strings.HasPrefix(body, "1.") || strings.HasPrefix(body, "2.") ||
			strings.HasPrefix(body, "3.") {
			slots = append(slots, y)
		}
	}
	if len(slots) < 3 {
		t.Fatalf("the PRICE ALERTS tile drew %d slots, want three:\n%s",
			len(slots), strings.Join(rows, "\n"))
	}
	bg := func(y int) RGB { return c.Cells[y*c.W+20].BG }
	if bg(slots[0]) == bg(slots[1]) {
		t.Fatalf("slots 1 and 2 wear one shade")
	}
	if bg(slots[0]) == bg(slots[2]) {
		t.Fatalf("slots 1 and 3 do not share the alternating shade")
	}
}

// Owner order 2026-11-25: an opened sector keeps one blank line under its
// search box, and its scrips stand one cell further right.
func TestBuild172OpenedSectorHasABlankLineAndIndentedScrips(t *testing.T) {
	a := demoApp(t, 158, 41)
	a.screen = scrScanner
	a.sectorOpen, a.sectorChoice = true, 1
	a.lvSectorStk.top()
	c := NewCanvas(120, 12, a.th.Panel)
	a.drawSectorOpen(c, 0, 0, 120, 12)
	rows := c.PlainRows()
	box := -1
	for y, row := range rows {
		if strings.Contains(row, "Search for a scrip") {
			box = y
			break
		}
	}
	if box < 0 {
		t.Fatalf("the opened sector carries no search box:\n%s", strings.Join(rows, "\n"))
	}
	if box+2 >= len(rows) {
		t.Fatalf("the opened sector lists nothing under the box:\n%s", strings.Join(rows, "\n"))
	}
	if rest := strings.Trim(strings.TrimSpace(rows[box+1]), "│┃ "); rest != "" {
		t.Fatalf("the row under the box is not a blank line: %q", rows[box+1])
	}
	first := rows[box+2]
	frame := strings.IndexRune(first, '│')
	if frame < 0 {
		t.Fatalf("the scrip row carries no frame: %q", first)
	}
	digit := -1
	for i, r := range []rune(first) {
		if r >= '0' && r <= '9' {
			digit = i
			break
		}
	}
	if digit < 0 {
		t.Fatalf("the scrip row carries no number: %q", first)
	}
	// The number stood five cells after the frame before this build and stands
	// six now, the one cell the scrips moved right.
	if digit != frame+6 {
		t.Fatalf("the scrip number starts on cell %d, want %d (frame %d plus "+
			"the one cell the scrips moved right): %q", digit, frame+6, frame, first)
	}
}

// Owner order 2026-11-25: T's figure is bold like B's and S's.
func TestBuild172TotalVolumeIsBoldLikeBuyAndSell(t *testing.T) {
	a := busyApp(t, 158, 41, 3)
	c := NewCanvas(158, 41, a.th.Panel)
	a.drawMarket(c, 0, 0, 158, 41)
	rows := c.PlainRows()
	for y, row := range rows {
		at := strings.Index(row, "T=")
		if at < 0 || strings.Index(row, "B=") < 0 {
			continue
		}
		runes := []rune(row)
		for _, label := range []string{"B=", "T="} {
			col := strings.Index(row, label)
			if col < 0 {
				continue
			}
			ch := col + len(label)
			for ch < len(runes) && (runes[ch] == ' ') {
				ch++
			}
			if ch >= len(runes) {
				continue
			}
			cell := c.Cells[y*c.W+ch]
			if !cell.Bold {
				t.Fatalf("%s's first figure cell (%q) is not bold in row %d: %q",
					label, cell.Ch, y, row)
			}
		}
		return
	}
	t.Fatalf("the KSE100 tile drew no leader volume line:\n%s", strings.Join(rows, "\n"))
}
