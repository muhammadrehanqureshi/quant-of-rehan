package main

import (
	"path/filepath"
	"strconv"
	"strings"
	"testing"
)

// The owner's orders of 2026-11-24: no part of a version ever reads above ten
// on either build.

// rollVersion is the owner's numbering law: 3.10.10 is followed by 4.0.0, and a
// part never reads eleven.
func rollVersion(v string) string {
	parts := strings.Split(v, ".")
	n := make([]int, len(parts))
	for i, p := range parts {
		n[i], _ = strconv.Atoi(p)
	}
	i := len(n) - 1
	n[i]++
	for i > 0 && n[i] > 10 {
		n[i] = 0
		i--
		n[i]++
	}
	out := make([]string, len(n))
	for k, x := range n {
		out[k] = strconv.Itoa(x)
	}
	return strings.Join(out, ".")
}

func TestBuild162TheVersionNeverReadsAboveTen(t *testing.T) {
	// Owner order 2026-11-25: the HUD ships as 4.3.3, and the ten law stands.
	if hudBuild != "4.4.9" {
		t.Fatalf("hudBuild is %q, want 4.4.9", hudBuild)
	}
	for i, p := range strings.Split(hudBuild, ".") {
		n, err := strconv.Atoi(p)
		if err != nil {
			t.Fatalf("version part %d is %q", i+1, p)
		}
		if n > 10 {
			t.Fatalf("version part %d is %d, and no part may read above ten", i+1, n)
		}
	}
	for _, c := range []struct{ from, to string }{
		{"3.10.10", "4.0.0"},
		{"4.2.5", "4.2.6"},
		{"4.2.10", "4.3.0"},
		{"4.10.10", "5.0.0"},
	} {
		if got := rollVersion(c.from); got != c.to {
			t.Fatalf("%s steps to %q, want %q", c.from, got, c.to)
		}
	}
}

// Owner order 2026-11-24: the ORDER FLOW page names its first column SCRIP, and
// every value stands on the cell its heading starts on. The five price fields
// are one cell narrower than build 161, so each of the pairs the owner named
// stands one cell closer.
func TestBuild162OrderFlowSaysScripFromTheLeft(t *testing.T) {
	if flowSymHeading != "SCRIP" {
		t.Fatalf("the column is headed %q, want SCRIP", flowSymHeading)
	}
	if flowPriceW != 7 {
		t.Fatalf("the price field is %d cells, want 7", flowPriceW)
	}
	if got := flowPrice(1234.56); got != "1234.56" {
		t.Fatalf("a wide price reads %q, want the separator gone and no digit lost", got)
	}
	rows := []FlowRow{{
		Symbol: "AAA", Price: 1234.56, ChangePct: f64(1.2),
		High: f64(1234.56), Low: f64(1234.56), Bid: f64(1234.56), Ask: f64(1234.56),
		Buy: i64(600), Sell: i64(300), Volume: i64(1000), Method: methodMeasured,
	}}
	flowDropHL = false
	cols, barX := flowColumns(rows)
	if cols[0].x != flowSymX+flowSymW+flowGutter {
		t.Fatalf("PRICE starts on cell %d, want one gutter after the SCRIP field", cols[0].x)
	}
	for i := 1; i < len(cols); i++ {
		if got := cols[i].x - (cols[i-1].x + cols[i-1].w); got != flowGutter {
			t.Fatalf("column %d stands %d cells after column %d, want the one gutter",
				i, got, i-1)
		}
	}
	for i := 0; i <= 5; i++ {
		if cols[i].w > flowPriceW {
			t.Fatalf("price column %d is %d cells wide, want %d at most", i, cols[i].w, flowPriceW)
		}
	}
	if barX <= cols[9].x {
		t.Fatalf("the bar starts on %d, before the last column on %d", barX, cols[9].x)
	}
}

// Owner order 2026-11-24: the ALERTS LOG's own edge carries the floor it keeps
// and the key that gives its box the keys.
func TestBuild162TheAlertsLogNamesItsFloorAndTheSlash(t *testing.T) {
	a := demoApp(t, 240, 60)
	a.screen = scrAlerts
	rows := rowsOf(a)
	want := `QTY 100k and above. Press "/" to search`
	for _, row := range rows {
		if strings.Contains(row, "ALERTS LOG (") && strings.Contains(row, want) {
			return
		}
	}
	t.Fatalf("the ALERTS LOG tile does not carry %q:\n%s", want, strings.Join(rows, "\n"))
}

// Owner order 2026-11-24: the gate's tile is headed SIGN IN, never the brand.
func TestBuild162TheGateIsHeadedSignIn(t *testing.T) {
	a := lockedApp(t, 100, 30)
	rows := screenOf(a)
	if !strings.Contains(rows, "SIGN IN") {
		t.Fatalf("the gate carries no SIGN IN heading:\n%s", rows)
	}
	if strings.Contains(rows, "QUANT OF REHAN") {
		t.Fatalf("the gate still carries the brand as its heading:\n%s", rows)
	}
}

// Owner order 2026-11-24: the WATCH LIST is a page of its own and stands before
// SETTINGS.
func TestBuild162TheWatchListStandsBeforeSettings(t *testing.T) {
	if len(screenNames) != 6 {
		t.Fatalf("the build carries %d tabs, want 6", len(screenNames))
	}
	if screenNames[4] != "WATCH LIST" || screenNames[5] != "SETTINGS" {
		t.Fatalf("the tabs read %v, want WATCH LIST then SETTINGS", screenNames)
	}
	if scrWatch >= scrSettings {
		t.Fatalf("the WATCH LIST page stands at %d, SETTINGS at %d", scrWatch, scrSettings)
	}
}

// Owner order 2026-11-24: the owner adds a scrip to the WATCH LIST by typing it
// and pressing ENTER, and takes it out with DEL. The row carries the ORDER FLOW
// page's own figures for that scrip, never a number of its own.
func TestBuild162TheWatchListAddsAndTakesOutScrips(t *testing.T) {
	a := orderFlowApp(t, 200, 50, flowSample150)
	a.screen = scrWatch
	a.onKey(Key{Kind: KRune, R: '/'})
	for _, r := range "AAA" {
		a.onKey(Key{Kind: KRune, R: r})
	}
	a.onKey(Key{Kind: KEnter})
	if len(a.cfg.Watch) != 1 || a.cfg.Watch[0] != "AAA" {
		t.Fatalf("the watch list reads %v after the add, want AAA", a.cfg.Watch)
	}
	// The price the page must print for that scrip is the relay's own price,
	// the same figure ORDER FLOW prints.
	wantPrice := ""
	for _, r := range a.of.Rows {
		if r.Symbol == "AAA" {
			wantPrice = flowPrice(r.Price)
		}
	}
	rows := rowsOf(a)
	text := strings.Join(rows, "\n")
	if !strings.Contains(text, "WATCH LIST") || !strings.Contains(text, "SCRIP") {
		t.Fatalf("the page does not read as the watch list:\n%s", text)
	}
	// The scrip's own row carries its price and its measured B and S.
	row := ""
	for _, r := range rows {
		if strings.Contains(r, "AAA") {
			row = r
		}
	}
	if row == "" {
		t.Fatalf("the watched scrip has no row:\n%s", text)
	}
	if wantPrice == "" {
		t.Fatalf("the sample carries no price for AAA")
	}
	if !strings.Contains(row, wantPrice) {
		t.Fatalf("the watched row carries no price, want %q: %q", wantPrice, row)
	}
	a.onKey(Key{Kind: KDel})
	if len(a.cfg.Watch) != 0 {
		t.Fatalf("the watch list reads %v after DEL, want empty", a.cfg.Watch)
	}
}

// The watch list is the owner's own state, so it is written to the settings
// file and read back as upper case tickers, one of each, in his order.
func TestBuild162TheWatchListSurvivesARestart(t *testing.T) {
	path := filepath.Join(t.TempDir(), "settings.json")
	s := defaultSettings()
	s.Watch = []string{" tele ", "TELE", "aapl", ""}
	if err := saveSettings(path, s); err != nil {
		t.Fatal(err)
	}
	got := loadSettings(path)
	want := []string{"TELE", "AAPL"}
	if len(got.Watch) != len(want) {
		t.Fatalf("the list reads %v, want %v", got.Watch, want)
	}
	for i := range want {
		if got.Watch[i] != want[i] {
			t.Fatalf("the list reads %v, want %v", got.Watch, want)
		}
	}
}
