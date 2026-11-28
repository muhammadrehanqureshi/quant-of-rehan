package main

import (
	"strings"
	"testing"
	"time"
)

// Build 188 shipped as 4.5.0; build 189 is 4.5.1, the owner's order of
// 2026-11-28. The version law stays here so the number the HUD prints is the
// number the build ships.
const build189Version = "4.5.1"

func TestBuild188TheHudCarriesTheBuildVersion(t *testing.T) {
	if hudBuild != build189Version {
		t.Fatalf("hudBuild is %q, want %q", hudBuild, build189Version)
	}
}

// Owner order 2026-11-28 (build 188): "the welcome banner image hangs up the
// build, I want you to make a dotted line render from that picture, don't double
// dot it, only keep one single dotted line for the render". The gate's banner is
// the picture's ink in dots, one dot in a cell, never a half block pair, and it
// keeps the size build 182 gave it.
func TestBuild188TheBannerIsOneDotACell(t *testing.T) {
	withLigatureGlyph(t, syntheticLigature(320, 160))
	for _, sz := range [][2]int{{80, 24}, {100, 30}, {120, 40}, {200, 50}} {
		w, h := sz[0], sz[1]
		rows := splashBanner(w, h)
		if len(rows) == 0 {
			t.Fatalf("%dx%d: the gate drew no mark", w, h)
		}
		if share := float64(len(rows)) / float64(h); share < 0.35 || share > 0.45 {
			t.Fatalf("%dx%d: the mark takes %d of %d rows, %.0f%%, want about 40%%",
				w, h, len(rows), h, share*100)
		}
		width := runeLen(rows[0])
		dots := 0
		for i, row := range rows {
			if n := runeLen(row); n != width {
				t.Fatalf("%dx%d: row %d is %d cells wide, row 0 is %d", w, h, i, n, width)
			}
			if width > w {
				t.Fatalf("%dx%d: the mark is %d cells wide, wider than the gate", w, h, width)
			}
			for _, r := range row {
				switch r {
				case ' ':
				case bannerDot:
					dots++
				default:
					t.Fatalf("%dx%d: row %d carries %q, which is not a dot: %q", w, h, i, r, row)
				}
			}
		}
		if dots == 0 {
			t.Fatalf("%dx%d: the mark is blank", w, h)
		}
	}
}

// Owner order 2026-11-28 (build 188): the dots come from his own picture, so the
// letters are the picture's joined calligraphy and never a shaping the console
// or a font had to guess at.
func TestBuild188HisPictureDrawsTheDots(t *testing.T) {
	m, ok := readBannerPicture()
	if !ok {
		t.Fatal("the artwork in assets/banner is not read")
	}
	for _, sz := range [][2]int{{100, 30}, {200, 50}} {
		w, h := sz[0], sz[1]
		dw, dh := ligatureFit(m, w, h)
		rows := ligatureRows(ligatureDots(m, dw, dh))
		if len(rows) == 0 {
			t.Fatalf("%dx%d: his picture drew no banner", w, h)
		}
		joined := strings.Join(rows, "")
		if !strings.Contains(joined, string(bannerDot)) {
			t.Fatalf("%dx%d: his picture's banner is blank", w, h)
		}
		if strings.ContainsAny(joined, "\u2580\u2584\u2588") {
			t.Fatalf("%dx%d: his picture still draws half blocks, want one dot a cell", w, h)
		}
	}
}

// A dotted stroke is the banner; the HUD's own single dot never is.
func TestBuild188ADottedStrokeIsTheBanner(t *testing.T) {
	if !basmalaOn("   " + strings.Repeat(string(bannerDot), 5) + "  ") {
		t.Fatal("a dotted stroke is not read as the banner")
	}
	if basmalaOn("SCAN  " + string(bannerDot) + "  DEMO DATA") {
		t.Fatal("one dot in a HUD sentence was read as the banner")
	}
	if basmalaOn("QUANT OF REHAN") {
		t.Fatal("a plain row was read as the banner")
	}
}

// Owner order 2026-11-28 (build 188): "I am getting wrong average/mean change of
// the WATCH LIST scrips, according to me calculation I am getting 0.27 but the
// system showing me 0, also remove the commas around the result of the mean
// average and have only one single spacing after drop down/up icon." The figure
// keeps its decimals, carries no quotes, and stands two blank rows under the
// last scrip.
func TestBuild188TheWatchAverageReadsItsDecimals(t *testing.T) {
	a := demoApp(t, 210, 44)
	a.cfg.Watch = []string{"AAA", "BBB"}
	p1, p2 := 0.20, 0.34
	v := int64(10)
	row := func(sym string, pct *float64) FlowRow {
		return FlowRow{Symbol: sym, Price: 10, ChangePct: pct, Buy: &v, Sell: &v,
			Unclassified: &v, Volume: &v, Method: methodMeasured}
	}
	a.of = &OrderFlow{Rows: []FlowRow{row("AAA", &p1), row("BBB", &p2)}}
	a.screen = scrWatch
	if avg, ok := watchAverage(a.of.Rows); !ok || avg < 0.26 || avg > 0.28 {
		t.Fatalf("the average is %v, %v; want the 0.27 the two scrips make", avg, ok)
	}
	sorted := a.watchSorted()
	lastSym := sorted[len(sorted)-1].Symbol
	rows := a.render().PlainRows()
	last, avgRow := -1, -1
	for i, r := range rows {
		if strings.Contains(r, lastSym) {
			last = i
		}
		if strings.Contains(r, "The average change of the above scrips is") {
			avgRow = i
		}
	}
	if last < 0 || avgRow < 0 {
		t.Fatalf("the page has no average under %s:\n%s", lastSym, strings.Join(rows, "\n"))
	}
	if avgRow != last+3 {
		t.Fatalf("the average stands on row %d, %d rows under %s on row %d; want two blank rows",
			avgRow, avgRow-last, lastSym, last)
	}
	if want := "\u25b2 0.27%"; !strings.Contains(rows[avgRow], want) {
		t.Fatalf("the average does not read %q: %q", want, rows[avgRow])
	}
	if strings.Contains(rows[avgRow], "\"") {
		t.Fatalf("the average still wears quotes: %q", rows[avgRow])
	}
}

// Owner order 2026-11-28 (build 188): "on the ALERTS page, for BIG BUYING NOW,
// BIG SELLING NOW and ALERTS LOG, only have one single space after PKR then
// start all the PKR values from that alignment, of course the values that have
// more digits will take more space which is completely fine."
func TestBuild188PkrStandsOneSpaceBeforeItsFigure(t *testing.T) {
	a := demoApp(t, 158, 41)
	a.now = time.Date(2026, 10, 30, 11, 42, 18, 0, pkt)
	prices := map[string]float64{"AAA": 286.71, "BBB": 26.09, "CCC": 8.35}
	if a.quotes == nil || a.quotes.Items == nil {
		a.quotes = &Quotes{OK: true, Items: map[string]LiveQuote{}}
	}
	a.flow.sym = map[string]*symFlow{}
	shares := int64(700_000)
	for sym, px := range prices {
		p := px
		a.quotes.Items[sym] = LiveQuote{Price: p, Fresh: true, ChangePct: f64(2.51)}
		a.flow.sym[sym] = &symFlow{have: true, px: p, t: a.now,
			evts: []flowEvt{{t: a.now.Add(-5 * time.Second), dv: shares, px: p, side: 1}}}
		shares -= 100_000
	}
	a.flow.Log = []Flag{
		{Time: a.now.Add(-2 * time.Second), Symbol: "PRL", Kind: "flow", Side: "BUY", Value: 100_000,
			Price: 114.65, ChangePct: f64(5.08), Text: "100k shares of PRL were bought at PKR 114.65 \u25b2 5.08%."},
		{Time: a.now.Add(-time.Second), Symbol: "KEL", Kind: "flow", Side: "SELL", Value: 100_000,
			Price: 9.05, ChangePct: f64(-1.25), Text: "100k shares of KEL were sold at PKR 9.05 \u25bc 1.25%."},
	}
	a.screen = scrAlerts
	rows := a.render().PlainRows()
	// Every tile keeps its own column: the two boards share one, the log has
	// its own, and each row's figure must stand on its tile's cell.
	starts := map[int]int{}
	seen := 0
	for _, row := range rows {
		at := col(row, "PKR ")
		if at < 0 {
			continue
		}
		r := []rune(row)
		f := at + 4
		if f >= len(r) || r[f] < '0' || r[f] > '9' {
			t.Fatalf("PKR is not followed by one space and a figure: %q", row)
		}
		if want, ok := starts[at]; ok {
			if f != want {
				t.Errorf("a PKR figure starts on cell %d, want %d: %q", f, want, row)
			}
		} else {
			starts[at] = f
		}
		seen++
	}
	if seen < 5 {
		t.Fatalf("the page showed %d PKR figures, want the boards and the log:\n%s",
			seen, strings.Join(rows, "\n"))
	}
}
