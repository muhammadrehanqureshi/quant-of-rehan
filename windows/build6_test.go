package main

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"regexp"
	"strings"
	"sync/atomic"
	"testing"
)

func flowJSON(t *testing.T, s string) J {
	t.Helper()
	// The relay reader decodes numbers as json.Number, so the test does too.
	var o J
	d := json.NewDecoder(strings.NewReader(s))
	d.UseNumber()
	if err := d.Decode(&o); err != nil {
		t.Fatal(err)
	}
	return o
}

const sampleOrderFlow = `{"ok":true,"day":"2026-11-05","as_of":"2026-11-05T10:15:04.000Z",
"counts":{"universe":4,"included":4,"missing":0,"fresh":4},
"rows":[
 {"symbol":"AAA","price":10.5,"bid":10.49,"ask":10.51,"change_pct":1.2,"volume":1000,"buy_volume":600,"sell_volume":300,"classified_volume":900,"unclassified_volume":100,"split_method":"quote_rule","fresh":true},
 {"symbol":"BBB","price":20,"bid":19.9,"ask":20.1,"volume":5000,"buy_volume":4000,"sell_volume":900,"classified_volume":4900,"unclassified_volume":100,"split_method":"quote_rule","fresh":true},
 {"symbol":"CCC","price":30,"volume":2000,"buy_volume":1200,"sell_volume":800,"split_method":"range_position","fresh":true},
 {"symbol":"DDD","price":40,"volume":3000,"split_method":"unavailable","fresh":false},
 {"symbol":"","price":1,"volume":1},
 {"symbol":"EEE","price":0,"volume":1}
],
"large":{"threshold_pkr":1000000,"total":2,"prints":[{"symbol":"AAA","side":"BUY","shares":100000,"price":10.5,"value_pkr":1050000,"at":"2026-11-05T10:14:00.000Z"}]}}`

// Every number on the ORDER FLOW screen is the relay's own. Unclassified
// volume stays on its own and estimates never reach the measured totals.
func TestOrderFlowStrictTotals(t *testing.T) {
	of := ParseOrderFlow(flowJSON(t, sampleOrderFlow))
	if !of.OK || len(of.Rows) != 4 {
		t.Fatalf("rows: ok=%v n=%d (a row with no symbol or no price is dropped)", of.OK, len(of.Rows))
	}
	tot := of.Totals()
	if tot.Measured != 2 || tot.Estimated != 1 || tot.NoSplit != 1 {
		t.Fatalf("counts: %+v", tot)
	}
	if tot.Buy != 4600 || tot.Sell != 1200 || tot.Unclassified != 200 || tot.MeasuredTotal != 6000 {
		t.Fatalf("B, S, U and T must add up from the measured stocks only: %+v", tot)
	}
	if tot.Buy+tot.Sell+tot.Unclassified != tot.MeasuredTotal {
		t.Errorf("B+S+U must equal T")
	}
	if tot.OtherTotal != 5000 {
		t.Errorf("volume of the unmeasured stocks is kept apart: %d", tot.OtherTotal)
	}
	if tot.Unbalanced != 0 {
		t.Errorf("unbalanced: %d", tot.Unbalanced)
	}
	// A measured stock whose parts do not add up is called out, never smoothed.
	bad := ParseOrderFlow(flowJSON(t, strings.Replace(sampleOrderFlow, `"unclassified_volume":100,"split_method":"quote_rule","fresh":true},
 {"symbol":"BBB"`, `"unclassified_volume":99,"split_method":"quote_rule","fresh":true},
 {"symbol":"BBB"`, 1)))
	if got := bad.Totals().Unbalanced; got != 1 {
		t.Errorf("a stock where B+S+U is not T must be counted: %d", got)
	}
	if len(of.Prints) != 1 || of.Prints[0].Side != "BUY" || of.LargeTotal != 2 || of.LargeThreshold != 1_000_000 {
		t.Errorf("large prints: %+v", of)
	}
	if ParseOrderFlow(J{"ok": false}).OK {
		t.Errorf("a refusal is not an answer")
	}
}

func orderFlowApp(t *testing.T, w, h int, body string) *App {
	a := demoApp(t, w, h)
	a.of = ParseOrderFlow(flowJSON(t, body))
	a.of.AsOfTime = a.now
	a.screen = scrOrderFlow
	return a
}

func TestOrderFlowScreenShowsBSUTSeparately(t *testing.T) {
	for _, sz := range [][2]int{{122, 30}, {100, 30}, {80, 26}} {
		a := orderFlowApp(t, sz[0], sz[1], sampleOrderFlow)
		s := plain(a)
		for _, want := range []string{"ORDER FLOW", "AAA", "BBB", "CCC", "DDD", "U=", "B=", "T="} {
			if sz[0] >= 102 && (want == "U=" || want == "B=" || want == "T=") {
				continue // the wide table has these as column headings
			}
			if !strings.Contains(s, want) {
				t.Errorf("%dx%d: missing %q:\n%s", sz[0], sz[1], want, s)
			}
		}
		for _, want := range []string{"1,000", "600", "300", "100"} {
			if !strings.Contains(s, want) {
				t.Errorf("%dx%d: the numbers must be shown as sent, missing %q", sz[0], sz[1], want)
			}
		}
		if !strings.Contains(s, "~1,200") && !strings.Contains(s, "B~1,200") {
			t.Errorf("%dx%d: an estimate must be marked with a tilde:\n%s", sz[0], sz[1], s)
		}
		if strings.Contains(s, "B=1,200") || strings.Contains(s, "S=800") {
			t.Errorf("%dx%d: an estimate must not look like a measured number", sz[0], sz[1])
		}
	}
	a := orderFlowApp(t, 122, 30, sampleOrderFlow)
	s := plain(a)
	for _, want := range []string{"BUYING (B)", "SELLING (S)", "UNCL. (U)", "TOTAL (T)", "BID", "ASK", "10.49", "10.51", "no split", "MEASURED 2 stocks"} {
		if !strings.Contains(s, want) {
			t.Errorf("wide table is missing %q:\n%s", want, s)
		}
	}
	// The unclassified column for AAA is its own 100, and B stays 600.
	line := ""
	for _, r := range rowsOf(a) {
		if strings.Contains(r, "AAA") && strings.Contains(r, "10.49") {
			line = r
		}
	}
	f := strings.Fields(line)
	at := -1
	for i, w := range f {
		if w == "10.51" { // the ask, then B, S, U and T
			at = i
		}
	}
	if at < 0 || len(f) < at+5 || f[at+1] != "600" || f[at+2] != "300" || f[at+3] != "100" || f[at+4] != "1,000" {
		t.Errorf("AAA's row must read B 600, S 300, U 100, T 1,000, got %q", line)
	}
}

func TestTotalVolumeIsBlue(t *testing.T) {
	a := newTestApp(t)
	c := NewCanvas(80, 1, a.th.Panel)
	b, s, total := int64(1500), int64(750), int64(2250)
	a.putBST(c, 0, 0, &b, &s, &total)
	found := false
	for _, ce := range c.Cells {
		if ce.FG == totalBlue {
			found = true
			break
		}
	}
	if !found {
		t.Fatal("the T volume is not painted in the owner's blue")
	}
}

func TestOrderFlowSearchFieldHasNoLabel(t *testing.T) {
	a := orderFlowApp(t, 122, 30, sampleOrderFlow)
	for _, row := range a.render().PlainRows() {
		if strings.Contains(row, scripSearchHint) {
			if strings.Contains(row, "SEARCH") {
				t.Fatalf("the ORDER FLOW field still has a SEARCH label: %q", row)
			}
			return
		}
	}
	t.Fatal("the ORDER FLOW search field is not on screen")
}

func TestOrderFlowEmptyAndFailedStates(t *testing.T) {
	a := demoApp(t, 122, 30)
	a.of, a.ofErr = nil, ""
	a.screen = scrOrderFlow
	if !strings.Contains(plain(a), "Reading ORDER FLOW from the relay.") {
		t.Errorf("waiting state")
	}
	a.ofErr = "The relay did not answer in time."
	if !strings.Contains(plain(a), "ORDER FLOW is not available right now") {
		t.Errorf("failed state")
	}
}

func TestOrderFlowSortKeepsUnmeasuredAtTheBottom(t *testing.T) {
	a := orderFlowApp(t, 122, 30, sampleOrderFlow)
	a.ofSort = 1 // buying volume
	rows := a.sortedFlow()
	if rows[0].Symbol != "BBB" || rows[1].Symbol != "AAA" {
		t.Errorf("by buying volume: %s %s", rows[0].Symbol, rows[1].Symbol)
	}
	if last := rows[len(rows)-1].Symbol; last != "CCC" && last != "DDD" {
		t.Errorf("rows with no measured buying go last, not first as zeros: %s", last)
	}
	a.ofSort = 5
	if a.sortedFlow()[0].Symbol != "AAA" {
		t.Errorf("by symbol")
	}
	for i := 0; i < len(flowSorts)*2; i++ {
		a.onKey(Key{Kind: KRune, R: 'o'})
	}
	if a.ofSort != 5 {
		t.Errorf("o steps through the orders and wraps: %d", a.ofSort)
	}
}

// After the bar there is one space and then the percentage, however many
// digits it has.
func TestPercentFollowsTheBarWithOneSpace(t *testing.T) {
	// The bar's glyph is whatever barBlock is, so the pattern follows it.
	mark := regexp.QuoteMeta(string(barBlock))
	good := regexp.MustCompile(mark + ` +\d{1,3}%`)
	bad := regexp.MustCompile(mark + `\d`)
	for _, ch := range []int{2, 3} {
		a := busyApp(t, 122, 30, 6)
		a.screen, a.scanChoice = scrScanner, ch
		s := plain(a)
		if !good.MatchString(s) {
			t.Errorf("scanner choice %d: no bar followed by one space and a percentage:\n%s", ch, s)
		}
		if bad.MatchString(s) {
			t.Errorf("scanner choice %d: the gap after a bar is not one space: %q", ch, bad.FindString(s))
		}
	}
	// 100%, 98% and 7% all follow their bars, right aligned in four cells.
	for _, share := range []float64{1, 0.98, 0.07} {
		c := NewCanvas(40, 1, RGB{})
		a := demoApp(t, 100, 30)
		a.shareBar(c, 2, 0, shareBarWidth, share)
		row := c.PlainRows()[0]
		i := strings.LastIndex(row, string(barBlock))
		if i < 0 {
			t.Fatalf("share %.2f: no bar drawn: %q", share, row)
		}
		after := row[i+len(string(barBlock)):]
		if !regexp.MustCompile(`^ +\d{1,3}%`).MatchString(after) {
			t.Errorf("share %.2f: the percentage does not follow the bar: %q", share, row)
		}
	}
}

func TestHomeHasOneBlankLineBeforeTheFeedNote(t *testing.T) {
	for _, sz := range [][2]int{{158, 41}, {240, 70}} {
		a := busyApp(t, sz[0], sz[1], 6)
		rows := rowsOf(a)
		b, n := -1, -1
		for i, r := range rows {
			if strings.Contains(r, "BUYING NOW") {
				b = i
			}
			if strings.Contains(r, "Data from the broker's feed") || strings.Contains(r, "Demo mode: every number here") {
				n = i // the demo says its own sentence in the same place
			}
		}
		if b < 0 || n < 0 {
			t.Fatalf("%dx%d: BUYING NOW row %d, note row %d:\n%s", sz[0], sz[1], b, n, strings.Join(rows, "\n"))
		}
		if n != b+2 {
			t.Errorf("%dx%d: the note is %d rows below BUYING NOW, want 2 (one blank line between)", sz[0], sz[1], n-b)
			continue
		}
		mid := rows[b+1]
		if strings.TrimSpace(strings.Trim(strings.TrimSpace(mid), "│┃")) != "" {
			// the left column is also on this row, so only look right of it
			if i := strings.LastIndex(mid, "│ "); i >= 0 && strings.TrimSpace(mid[i:]) != "│" {
				t.Errorf("%dx%d: the line between is not blank: %q", sz[0], sz[1], mid)
			}
		}
	}
}

func TestLatestSignalTileWords(t *testing.T) {
	a := demoApp(t, 122, 30)
	s := plain(a)
	for _, want := range []string{"SYMBOL", "ENTRY TIME", "ENTRY PRICE", "TAKE PROFIT", "STOP LOSS", "11:30:02 PKT", "42.10", "42.94", "41.68"} {
		if !strings.Contains(s, want) {
			t.Errorf("latest signal is missing %q", want)
		}
	}
	for _, old := range []string{"EXIT", "ENTRY  ", "STOP   "} {
		if strings.Contains(s, old) {
			t.Errorf("the old word %q is still on screen", old)
		}
	}

}

// Owner order 2026-11-07: the ORDER FLOW page carries its own search box.
func TestOrderFlowSearchFiltersTheList(t *testing.T) {
	a := orderFlowApp(t, 122, 30, sampleOrderFlow)
	a.onKey(Key{Kind: KRune, R: '/'})
	if !a.ofSearch {
		t.Fatal("the slash must focus the ORDER FLOW search")
	}
	for _, r := range "BBB" {
		a.onKey(Key{Kind: KRune, R: r})
	}
	if a.ofQuery != "BBB" {
		t.Fatalf("the search box holds %q", a.ofQuery)
	}
	rows := a.sortedFlow()
	if len(rows) != 1 || rows[0].Symbol != "BBB" {
		t.Fatalf("BBB must be the only row left: %+v", rows)
	}
	if s := plain(a); !strings.Contains(s, "BBB") || strings.Contains(s, "AAA") {
		t.Errorf("the filtered screen still shows another stock:\n%s", s)
	}
	a.onKey(Key{Kind: KEsc})
	if a.ofQuery != "" || a.ofSearch || len(a.sortedFlow()) != 4 {
		t.Errorf("ESC must clear the search: %q %v %d", a.ofQuery, a.ofSearch, len(a.sortedFlow()))
	}
}

// The dot matrix mark is on the home screen only. The scanner gives its width
// to the search, the sectors and the list. No other screen carries the mark.
func TestNoRingOnSettingsAndAlerts(t *testing.T) {
	for _, scr := range []screenID{scrSettings, scrAlerts, scrOrderFlow, scrScanner} {
		a := demoApp(t, 158, 41)
		a.screen = scr
		s := strings.ToUpper(plain(a))
		if strings.Contains(s, "QUANT CORE") {
			t.Errorf("screen %d carries the quant mark", scr)
		}
		if strings.Contains(s, "RADAR") || strings.Contains(strings.ReplaceAll(s, "JARVIS CYAN", ""), "JARVIS") {
			t.Errorf("screen %d still mentions the ring or the radar", scr)
		}
	}
	a := demoApp(t, 158, 41)
	a.screen = scrHome
	c := a.render()
	// The left column holds the mark and nothing else, so its Braille dots are
	// the dial's own.
	dots := 0
	for y := 0; y < c.H; y++ {
		for x := 0; x < 41 && x < c.W; x++ {
			ce := c.Cells[y*c.W+x]
			if ce.Ch < 0x2800 || ce.Ch > 0x28ff {
				continue
			}
			for m := ce.Ch - 0x2800; m != 0; m &= m - 1 {
				dots++
			}
		}
	}
	if dots < 200 {
		t.Errorf("home must have the dot matrix dial, it has %d dots in the left column", dots)
	}
}

// The scanner and the search are one tab: the search tile is on top and the
// scanner continues below it. There is no tab called SEARCH.
func TestScannerHasTheSearchTileOnTop(t *testing.T) {
	a := demoApp(t, 122, 30)
	a.screen = scrScanner
	rows := rowsOf(a)
	ts, tc := -1, -1
	for i, r := range rows {
		if strings.Contains(r, "SEARCH") && ts < 0 {
			ts = i
		}
		if strings.Contains(r, "CUSTOM SCRIPS BY VOLUME") {
			tc = i
		}
	}
	if ts < 0 || tc < 0 || ts >= tc {
		t.Fatalf("search tile row %d, scanner row %d", ts, tc)
	}
	for _, n := range screenNames {
		if n == "SEARCH" {
			t.Errorf("there is no SEARCH tab any more")
		}
	}
	// Typing fills the tile and opening a symbol keeps the screen.
	for _, r := range "alf" {
		a.onKey(Key{Kind: KRune, R: r})
	}
	a.onKey(Key{Kind: KEnter})
	if a.screen != scrScanner || a.selectedSym != "ALFA" {
		t.Fatalf("enter opens the symbol in the tile: %v %q", a.screen, a.selectedSym)
	}
	s := plain(a)
	for _, want := range []string{"ALFA", "3,410,000", "1,250,000", "4,660,000", "CUSTOM SCRIPS BY VOLUME"} {
		if !strings.Contains(s, want) {
			t.Errorf("scanner with a symbol open is missing %q", want)
		}
	}
	// Clicking a row of the list opens that symbol in the tile, on the scanner.
	a.clearSearch()
	a.scanChoice = 2
	a.render()
	clickText(t, a, ". ECHO")
	if a.screen != scrScanner || a.selectedSym != "ECHO" || a.searchText != "ECHO" {
		t.Errorf("a click opens the symbol in the search tile: %v %q %q", a.screen, a.selectedSym, a.searchText)
	}
}

func TestSellFlagSettingAndMigration(t *testing.T) {
	if !defaultSettings().BigSell {
		t.Errorf("the selling flag is on by default")
	}
	dir := t.TempDir()
	path := dir + "/settings.json"
	old := defaultSettings()
	old.Ver, old.BigSell = 2, false // a file written before the selling flag existed
	_ = saveSettings(path, old)
	got := loadSettings(path)
	if !got.BigSell {
		t.Errorf("an older file gets the selling flag on")
	}
	got.BigSell = false
	_ = saveSettings(path, got)
	if loadSettings(path).BigSell {
		t.Errorf("a chosen OFF must stay off once the file is current")
	}
}

func TestSellingToneDiffersFromBuyingTone(t *testing.T) {
	if len(toneBigSell) == 0 || len(toneBigBuy) == 0 {
		t.Fatal("tones missing")
	}
	same := len(toneBigSell) == len(toneBigBuy)
	for i := range toneBigSell {
		if same && toneBigSell[i] != toneBigBuy[i] {
			same = false
		}
	}
	if same {
		t.Errorf("selling must sound different from buying")
	}
}

func TestFetchOrderFlowFallsBackToFlowAndAcceptsALargeBody(t *testing.T) {
	var hits atomic.Int32
	// A realistic big answer: 400 stocks plus the large print board is well over
	// the 256 KB the other endpoints are limited to.
	var big strings.Builder
	big.WriteString(`{"ok":true,"day":"2026-11-05","as_of":"2026-11-05T10:15:04.000Z","counts":{"universe":2500,"included":2500,"missing":0,"fresh":2500},"rows":[`)
	for i := 0; i < 2500; i++ {
		if i > 0 {
			big.WriteString(",")
		}
		big.WriteString(`{"symbol":"S` + strings.Repeat("A", 4) + string(rune('A'+i%26)) + string(rune('A'+(i/26)%26)) + string(rune('A'+(i/676)%26)) +
			`","price":10.5,"bid":10.49,"ask":10.51,"volume":1000,"buy_volume":600,"sell_volume":300,"classified_volume":900,"unclassified_volume":100,"split_method":"quote_rule","fresh":true,` +
			`"observed_at":"2026-11-05T10:15:00.000Z","split_source":"quote_rule over the wire's own bid and ask, padding padding padding padding padding"}`)
	}
	big.WriteString(`]}`)
	if big.Len() < 300_000 || big.Len() > 4<<20 {
		t.Fatalf("test body is %d bytes", big.Len())
	}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		switch r.URL.Path {
		case "/orderflow":
			w.WriteHeader(404)
			_, _ = w.Write([]byte(`{"ok":false,"error":"not found"}`))
		case "/flow":
			_, _ = w.Write([]byte(big.String()))
		default:
			w.WriteHeader(404)
		}
	}))
	defer srv.Close()
	rl := NewRelay(srv.URL)
	of, err := rl.FetchOrderFlow(context.Background())
	if err != nil || of == nil {
		t.Fatalf("fetch: %v", err)
	}
	if of.Path != "/flow" || len(of.Rows) != 2500 || hits.Load() != 2 {
		t.Errorf("path %q rows %d hits %d: /orderflow failed, so /flow must be tried", of.Path, len(of.Rows), hits.Load())
	}
	if tot := of.Totals(); tot.Buy != 1_500_000 || tot.Sell != 750_000 || tot.Unclassified != 250_000 || tot.MeasuredTotal != 2_500_000 {
		t.Errorf("totals: %+v", tot)
	}
	// When both answers are refusals the error is returned, not an empty screen.
	bad := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = w.Write([]byte(`{"ok":false}`)) }))
	defer bad.Close()
	if _, err := NewRelay(bad.URL).FetchOrderFlow(context.Background()); err == nil {
		t.Errorf("two refusals must be an error")
	}
}

// Owner order 2026-11-10 (later): every bar is ten solid boxes, one per ten
// percent, with a line between them and no lighter or darker shade inside a
// colour. A long span carries two cells per box and nine lines.
// Owner order 2026-11-10 (latest): build 21's bar is back, so the bar is its
// 17 cells split into ten tabs, and the widths are build 21's own.
// Owner order 2026-11-10 (latest): the bar is ten boxes, two cells each, so
// it is twenty cells long and the box count is still ten.
func TestShareBarHasTenBoxesOfTwoCells(t *testing.T) {
	a := demoApp(t, 100, 30)
	c := NewCanvas(40, 1, RGB{})
	a.shareBar(c, 2, 0, shareBarWidth, 0.5)
	row := c.PlainRows()[0]
	if n := strings.Count(row, string(barBlock)); n != shareBarBoxes*shareBarBoxW {
		t.Fatalf("the bar is %d cells, want %d boxes of %d: %q", n, shareBarBoxes, shareBarBoxW, row)
	}
	if strings.ContainsAny(row, "│▄▀█") {
		t.Fatalf("a separator or full cell is in the bar: %q", row)
	}
}

func TestOrderFlowBarColumnIsCalledBars(t *testing.T) {
	a := demoApp(t, 160, 45)
	a.screen = scrOrderFlow
	s := plain(a)
	if !strings.Contains(s, "BARS") {
		t.Errorf("the order flow bar column is not called BARS:\n%s", s)
	}
	if strings.Contains(s, "BUY SHARE") {
		t.Errorf("the old BUY SHARE heading is still there")
	}
}
