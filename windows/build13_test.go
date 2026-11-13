package main

import (
	"fmt"
	"strings"
	"testing"
	"time"
)

// Owner order 2026-11-13: build 101 adds the three PRICE ALERT slots on the
// ALERTS page and the calculator on the SCANNER page. These pins hold the form,
// the trigger rule, the one ring, the calculator's sum and the saved slots.

func TestPriceAlertFormSetsASlot(t *testing.T) {
	a := demoApp(t, 120, 30)
	a.screen = scrAlerts
	a.onKey(Key{Kind: KRune, R: 'p'})
	if a.priceEdit != 0 || a.priceField != 0 {
		t.Fatalf("P must open slot 1's form: edit %d field %d", a.priceEdit, a.priceField)
	}
	for _, r := range "echo" {
		a.onKey(Key{Kind: KRune, R: r})
	}
	a.onKey(Key{Kind: KEnter})
	if a.priceField != 1 || a.priceSym != "ECHO" {
		t.Fatalf("the scrip did not move the form on: sym %q field %d", a.priceSym, a.priceField)
	}
	for _, r := range "26.50" {
		a.onKey(Key{Kind: KRune, R: r})
	}
	a.onKey(Key{Kind: KEnter})
	p := a.cfg.PriceAlerts[0]
	if p.Symbol != "ECHO" || p.Target != 26.5 || p.Fired {
		t.Fatalf("slot: %+v", p)
	}
	if a.priceEdit != -1 {
		t.Fatal("the form must close after the price is saved")
	}
	if !a.alertsTouched {
		t.Fatal("a set slot must be written to the settings file")
	}
	if a.screen != scrAlerts {
		t.Fatalf("a digit typed in the form must not switch pages: screen %d", a.screen)
	}
}

func TestPriceAlertFormRefusesABadPriceAndAnUnknownScrip(t *testing.T) {
	a := demoApp(t, 120, 30)
	a.screen = scrAlerts
	a.startPriceEdit(0)
	a.priceBuf = ""
	a.priceStep() // an empty scrip
	if a.priceField != 0 || a.priceMsg == "" {
		t.Fatal("an empty scrip must stay in the scrip field and say why")
	}
	a.priceBuf = "ECHO"
	a.priceStep()
	if a.priceField != 1 {
		t.Fatalf("ECHO must be accepted: %q", a.priceMsg)
	}
	a.priceBuf = "zero"
	a.priceStep()
	if a.priceEdit != 0 || a.cfg.PriceAlerts[0].Set() {
		t.Fatal("a price that is not a number must not be saved")
	}
	a.priceBuf = "0"
	a.priceStep()
	if a.priceEdit != 0 || a.cfg.PriceAlerts[0].Set() {
		t.Fatal("a zero price must not be saved")
	}
	a.onKey(Key{Kind: KEsc})
	if a.priceEdit != -1 || a.cfg.PriceAlerts[0].Set() {
		t.Fatal("ESC must close the form without saving")
	}
}

func TestPriceAlertRingsOnceWhenTheTargetIsReached(t *testing.T) {
	a := newTestApp(t)
	a.now = flowT0
	a.cfg.Sound = true
	a.cfg.BigBuy, a.cfg.BigSell = false, false
	a.ingestQuotes(quotesAt(15.00, 1_000_000))
	a.setPriceAlert(0, "ECHO", 15.50)
	if p := a.cfg.PriceAlerts[0]; !p.Rises || p.Wait {
		t.Fatalf("a target above the market must wait for a rise: %+v", p)
	}
	a.ingestQuotes(quotesAt(15.40, 1_100_000))
	if a.bannerTitle != "" {
		t.Fatalf("a price under the target must not ring: %q", a.bannerTitle)
	}
	a.now = flowT0.Add(time.Second)
	a.ingestQuotes(quotesAt(15.55, 1_200_000))
	p := a.cfg.PriceAlerts[0]
	if !p.Fired || p.Hit != 15.55 || p.HitAt != "11:00" {
		t.Fatalf("the hit was not written: %+v", p)
	}
	if a.bannerTitle != "PRICE ALERT: ECHO" || a.bannerKind != "price" {
		t.Fatalf("banner: %q %q", a.bannerTitle, a.bannerKind)
	}
	if !toneNative && !a.bell {
		t.Fatal("sound on: the price alert must play its tone")
	}
	if n := len(a.flow.Log); n != 1 || a.flow.Log[0].Kind != "price" || a.flow.Log[0].Side != "BUY" {
		t.Fatalf("the log must hold one price alert: %+v", a.flow.Log)
	}
	a.now = flowT0.Add(2 * time.Second)
	a.ingestQuotes(quotesAt(15.60, 1_300_000))
	if n := len(a.flow.Log); n != 1 {
		t.Fatalf("a hit rings once, not on every tick: %d entries", n)
	}
	if !strings.Contains(a.bannerBody, "PKR 15.50") {
		t.Fatalf("the banner must name the target: %q", a.bannerBody)
	}
	a.screen = scrAlerts
	s := plain(a)
	if !strings.Contains(s, "BUY PRICE") || !strings.Contains(s, "HIT 11:00") {
		t.Fatalf("the ALERTS page must show the hit:\n%s", s)
	}
}

func TestPriceAlertRingsOnTheWayDownToo(t *testing.T) {
	a := newTestApp(t)
	a.now = flowT0
	a.cfg.BigBuy, a.cfg.BigSell = false, false
	a.ingestQuotes(quotesAt(16.00, 1_000_000))
	a.setPriceAlert(1, "ECHO", 15.50)
	if p := a.cfg.PriceAlerts[1]; p.Rises {
		t.Fatalf("a target below the market must wait for a fall: %+v", p)
	}
	a.ingestQuotes(quotesAt(15.50, 1_000_000))
	p := a.cfg.PriceAlerts[1]
	if !p.Fired || p.Hit != 15.50 {
		t.Fatalf("a fall to the target must ring: %+v", p)
	}
	if len(a.flow.Log) != 1 || a.flow.Log[0].Side != "SELL" {
		t.Fatalf("a fall is the sell side in the log: %+v", a.flow.Log)
	}
}

func TestPriceAlertWaitsForItsFirstPrice(t *testing.T) {
	a := newTestApp(t)
	a.now = flowT0
	a.cfg.BigBuy, a.cfg.BigSell = false, false
	a.setPriceAlert(0, "ECHO", 15.50)
	if p := a.cfg.PriceAlerts[0]; !p.Wait || !p.Rises {
		t.Fatalf("with no price at all the slot must wait: %+v", p)
	}
	a.ingestQuotes(quotesAt(16.00, 1_000_000))
	p := a.cfg.PriceAlerts[0]
	if p.Wait || p.Rises || p.Fired {
		t.Fatalf("the first price picks the side and must not ring: %+v", p)
	}
	a.ingestQuotes(quotesAt(15.40, 1_000_000))
	if !a.cfg.PriceAlerts[0].Fired {
		t.Fatal("the second price, under the target, must ring")
	}
}

func TestPriceAlertHasItsOwnTone(t *testing.T) {
	seen := map[string]bool{}
	for _, tn := range [][]toneStep{toneBigBuy, toneBigSell, toneEvent, toneSignal} {
		seen[fmt.Sprint(tn)] = true
	}
	if seen[fmt.Sprint(tonePrice)] {
		t.Fatal("the price alert must not reuse another tone")
	}
	if len(tonePrice) < 3 {
		t.Fatalf("the price alert tone is %d steps, want a chime", len(tonePrice))
	}
}

func TestAlertsPageCarriesThreePriceSlots(t *testing.T) {
	a := demoApp(t, 120, 30)
	a.screen = scrAlerts
	s := plain(a)
	if !strings.Contains(s, "PRICE ALERTS") {
		t.Fatalf("the ALERTS page has no PRICE ALERTS tile:\n%s", s)
	}
	if n := strings.Count(s, "EMPTY. Press P"); n != priceAlertSlots {
		t.Fatalf("want %d empty slots, got %d", priceAlertSlots, n)
	}
	a.startPriceEdit(2)
	if !strings.Contains(plain(a), "PRICE ALERT 3 OF 3") {
		t.Fatal("the form must name the slot it is setting")
	}
}

func TestCalculatorShowsTheMoneyTheSharesNeed(t *testing.T) {
	a := demoApp(t, 122, 36)
	a.screen = scrScanner
	a.onKey(Key{Kind: KF6})
	if !a.calcOpen {
		t.Fatal("F6 must open the calculator on the SCANNER page")
	}
	for _, r := range "12.5" {
		a.onKey(Key{Kind: KRune, R: r})
	}
	a.onKey(Key{Kind: KTab})
	for _, r := range "400" {
		a.onKey(Key{Kind: KRune, R: r})
	}
	s := plain(a)
	if !strings.Contains(s, "POSITION CALCULATOR") || !strings.Contains(s, "PRICE") || !strings.Contains(s, "QUANTITY") {
		t.Fatalf("the calculator's two boxes are missing:\n%s", s)
	}
	if !strings.Contains(s, "PKR 5,000.00") {
		t.Fatalf("12.5 at 400 shares must read PKR 5,000.00:\n%s", s)
	}
	if a.screen != scrScanner {
		t.Fatalf("the calculator's digits must not switch pages: screen %d", a.screen)
	}
	a.onKey(Key{Kind: KEsc})
	if a.calcOpen {
		t.Fatal("ESC must take the keys out of the calculator")
	}
	if !strings.Contains(plain(a), "POSITION CALCULATOR") {
		t.Fatal("the calculator tile must stay under CUSTOM SCRIPS when it has no keys")
	}
	// The boxes keep what was typed, so F6 reopens the same sum.
	a.onKey(Key{Kind: KF6})
	if !strings.Contains(plain(a), "PKR 5,000.00") {
		t.Fatal("reopening the calculator must keep the two boxes")
	}
}

func TestCalculatorNeedsBothBoxes(t *testing.T) {
	if _, ok := calcAmount("", "400"); ok {
		t.Fatal("a quantity with no price has no total")
	}
	if _, ok := calcAmount("12.5", ""); ok {
		t.Fatal("a price with no quantity has no total")
	}
	if _, ok := calcAmount("0", "400"); ok {
		t.Fatal("a zero price has no total")
	}
	if v, ok := calcAmount("10.50", "100"); !ok || v != 1050 {
		t.Fatalf("10.50 at 100 shares: %v %v", v, ok)
	}
	a := demoApp(t, 122, 36)
	a.screen = scrScanner
	a.openCalc()
	for _, r := range "abc" {
		a.onKey(Key{Kind: KRune, R: r})
	}
	if a.calcPrice != "" {
		t.Fatalf("letters must not reach the price box: %q", a.calcPrice)
	}
	if !strings.Contains(plain(a), "PKR -") {
		t.Fatal("an empty calculator must show no total")
	}
}

func TestPriceAlertsSurviveARestart(t *testing.T) {
	a := newTestApp(t)
	a.setPriceAlert(1, "ECHO", 21.25)
	a.save()
	b := NewApp(loadSettings(a.cfgPath), a.cfgPath, NewRelay("http://127.0.0.1:1"))
	p := b.cfg.PriceAlerts[1]
	if p.Symbol != "ECHO" || p.Target != 21.25 {
		t.Fatalf("the saved slot came back as %+v", p)
	}
	if b.cfg.PriceAlerts[0].Set() || b.cfg.PriceAlerts[2].Set() {
		t.Fatal("the slots that were never set must stay empty")
	}
}

func TestPriceAlertTileAndFormsDrawAtEverySize(t *testing.T) {
	for _, sz := range [][2]int{{80, 26}, {100, 30}, {120, 30}, {160, 45}, {240, 70}} {
		a := demoApp(t, sz[0], sz[1])
		a.screen = scrAlerts
		a.startPriceEdit(0)
		rowsOf(a)
		a.priceEdit = -1
		a.screen = scrScanner
		a.openCalc()
		rowsOf(a)
	}
}
