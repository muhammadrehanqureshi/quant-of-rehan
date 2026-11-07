package main

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// The relay's /history answer is read as written: minute stamps in Karachi
// time, OHLC, volume, and no invented bar when the relay sends none.
func TestParseHistoryReadsBars(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/history" || r.URL.Query().Get("symbol") != "OGDC" {
			t.Errorf("path %q symbol %q", r.URL.Path, r.URL.Query().Get("symbol"))
		}
		_, _ = w.Write([]byte(`{"ok":true,"day":"2026-11-10","forming":true,"bars":[
			{"t":"2026-11-10T09:31:00+05:00","o":241.5,"h":242,"l":241,"c":241.8,"v":1200},
			{"t":"2026-11-10T09:32:00+05:00","o":241.8,"h":242.4,"l":241.7,"c":242.1,"v":900}]}`))
	}))
	defer srv.Close()
	h, err := NewRelay(srv.URL).FetchHistory(context.Background(), "ogdc", "2026-11-10")
	if err != nil || h == nil || len(h.Bars) != 2 {
		t.Fatalf("fetch: %v %+v", err, h)
	}
	if h.Symbol != "OGDC" || h.Bars[1].Close != 242.1 || h.Bars[0].Minute != "09:31" || !h.Forming {
		t.Errorf("parsed: %+v", h)
	}
}

func TestChartCandlesAggregateTheWholeDay(t *testing.T) {
	bars := make([]ChartBar, 300)
	for i := range bars {
		px := 100 + float64(i%7)
		bars[i] = ChartBar{Open: px, High: px + 2, Low: px - 2, Close: px + 1, Volume: 10}
	}
	out, step := chartCandles(bars, 30)
	if len(out) != 30 || step != 10 {
		t.Fatalf("300 bars into 30 candles: %d candles of %d minutes", len(out), step)
	}
	if out[0].Open != bars[0].Open || out[0].Close != bars[9].Close {
		t.Errorf("a group must open at its first open and close at its last close: %+v", out[0])
	}
	if out[0].High != 108 || out[0].Low != 98 {
		t.Errorf("a group must carry its own high and low: %+v", out[0])
	}
}

func TestChartsTabShowsEveryKMIALLStockAndCandles(t *testing.T) {
	a := demoApp(t, 140, 36)
	a.screen = scrCharts
	s := plain(a)
	for _, want := range []string{"CHARTS", "ALFA", "BRVO", "DLTA", "HTEL", "INTRADAY", "LIVE PKR", "demo bars"} {
		if !strings.Contains(s, want) {
			t.Errorf("charts is missing %q:\n%s", want, s)
		}
	}
	if n := strings.Count(s, "█"); n < 10 {
		t.Errorf("charts has %d candle cells, want a drawn chart:\n%s", n, s)
	}
	if len(a.chartSymbols()) != len(demoRows)+2 {
		t.Errorf("the chart list has %d names, want the %d demo KMIALL stocks and both indices", len(a.chartSymbols()), len(demoRows))
	}
}

func TestChartsSearchOpensTheChosenStock(t *testing.T) {
	a := demoApp(t, 140, 36)
	a.screen = scrCharts
	_ = a.render()
	for _, r := range "DL" {
		a.onKey(Key{Kind: KRune, R: r})
	}
	if m := a.chartMatches(); len(m) != 1 || m[0] != "DLTA" {
		t.Fatalf("DL must filter to DLTA: %v", m)
	}
	a.onKey(Key{Kind: KEnter})
	if a.chartSym != "DLTA" {
		t.Fatalf("ENTER opened %q, want DLTA", a.chartSym)
	}
	if a.chart == nil || a.chart.Symbol != "DLTA" || len(a.chart.Bars) == 0 {
		t.Fatalf("DLTA has no demo bars: %+v", a.chart)
	}
	if s := plain(a); !strings.Contains(s, "DLTA INTRADAY") {
		t.Errorf("the chart panel is not labelled DLTA:\n%s", s)
	}
}

// /bars carries every frame the owner ordered, and the desktop reads its own
// frame labels from the stamps rather than inventing them.
func TestParseBarsReadsEveryFrame(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/bars" || r.URL.Query().Get("symbol") != "OGDC" ||
			r.URL.Query().Get("tf") != "5m" || r.URL.Query().Get("days") != "365" {
			t.Errorf("path %q query %q", r.URL.Path, r.URL.RawQuery)
		}
		_, _ = w.Write([]byte(`{"ok":true,"tf":"5m","days":365,"retention_days":180,
			"bars":[{"t":"2026-11-10T09:30:00+05:00","o":241.5,"h":242,"l":241,"c":241.8,"v":1200},
			{"t":"2026-11-10T09:35:00+05:00","o":241.8,"h":242.4,"l":241.7,"c":242.1,"v":900}]}`))
	}))
	defer srv.Close()
	h, err := NewRelay(srv.URL).FetchBars(context.Background(), "ogdc", "5m", 365, 400)
	if err != nil || h == nil || len(h.Bars) != 2 {
		t.Fatalf("fetch: %v %+v", err, h)
	}
	if h.TF != "5m" || h.Days != 365 || h.Retention != 180 || h.Bars[1].Close != 242.1 {
		t.Errorf("parsed: %+v", h)
	}
	if h.Bars[0].Minute != "09:30" || h.Bars[0].High != 242 {
		t.Errorf("first bar: %+v", h.Bars[0])
	}
}

func TestChartFramesFollowTheOwnerOrder(t *testing.T) {
	want := []string{"1s", "5s", "1m", "5m", "15m", "30m", "1h", "1D", "1W", "1M"}
	if strings.Join(chartFrames, ",") != strings.Join(want, ",") {
		t.Fatalf("frames: %v", chartFrames)
	}
	a := demoApp(t, 140, 36)
	a.screen = scrCharts
	_ = a.render()
	if a.chartFrame() != "1m" {
		t.Fatalf("the panel starts on %q, want 1m", a.chartFrame())
	}
	a.moveChartFrame(1)
	if a.chartTF != "5m" {
		t.Errorf("] took the frame to %q, want 5m", a.chartTF)
	}
	a.moveChartFrame(-2)
	if !a.liveFrame() || a.chartTF != "5s" {
		t.Errorf("[ took the frame to %q, want live 5s", a.chartTF)
	}
	if h := a.liveChart("ALFA", "5s"); h == nil || !h.LiveOnly {
		t.Errorf("a live frame must be labelled live-only: %+v", h)
	}
}

func TestOrbRedIsSaturated(t *testing.T) {
	if hudMid.R < 250 || hudMid.G > 20 || hudMid.B > 20 {
		t.Errorf("the ORB core is %v, want a saturated red", hudMid)
	}
	if hudPale.G > 90 || hudPale.B > 90 {
		t.Errorf("the ORB's light shade is %v, still washed out", hudPale)
	}
}

func TestIndexLineIsTenPercentShorter(t *testing.T) {
	if headerTitle != "◆ QUANT OF REHAN ◆" {
		t.Errorf("the diamonds must sit one space from the words: %q", headerTitle)
	}
	if runeLen(headerTag) > 16 {
		t.Errorf("the index line is %d cells, want 16", runeLen(headerTag))
	}
}
