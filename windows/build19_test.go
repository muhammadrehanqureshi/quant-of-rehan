package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-14: every search box is 20 percent shorter than its old
// 40 cells, and the empty hint sits on the box's own centre.
func TestSearchBoxIsTwentyPercentShorterAndCentred(t *testing.T) {
	a := demoApp(t, 120, 30)
	c := NewCanvas(120, 4, RGB{})
	bw := a.searchBox(c, 0, 0, 40, "", scripSearchHint, false)
	if bw != 32 {
		t.Fatalf("the search box is %d cells, want 32 (20 percent under 40)", bw)
	}
	row := c.PlainRows()[0]
	at := strings.Index(row, scripSearchHint)
	if at < 0 {
		t.Fatalf("the hint is missing:\n%s", row)
	}
	left := at
	right := bw - (at + len(scripSearchHint))
	if left-right > 1 || right-left > 1 {
		t.Fatalf("the hint is not centred: %d cells left, %d right", left, right)
	}
}

// Owner order 2026-11-14: C opens the calculator, and F6 no longer does.
func TestCalculatorOpensOnCNotF6(t *testing.T) {
	a := demoApp(t, 122, 36)
	a.screen = scrScanner
	if !strings.Contains(plain(a), `Press "C" to calculate`) {
		t.Fatal("the calculator tile does not name C")
	}
	a.onKey(Key{Kind: KF6})
	if a.calcOpen {
		t.Fatal("F6 still opens the calculator")
	}
	a.onKey(Key{Kind: KRune, R: 'c'})
	if !a.calcOpen {
		t.Fatal("C must open the calculator")
	}
	if !strings.Contains(plain(a), "TAB next, ESC leaves") {
		t.Fatal("the open calculator does not carry its TAB and ESC hint")
	}
}

// Owner order 2026-11-14: the PRICE ALERTS slots read EMPTY with no full stop,
// the tile names A and del, and A opens the alert form.
func TestPriceAlertsReadEmptyAndOpenOnA(t *testing.T) {
	a := demoApp(t, 120, 30)
	a.screen = scrAlerts
	s := plain(a)
	if n := strings.Count(s, "EMPTY"); n != priceAlertSlots {
		t.Fatalf("want %d EMPTY slots, got %d", priceAlertSlots, n)
	}
	if strings.Contains(s, "EMPTY.") {
		t.Fatal("an EMPTY slot still carries a full stop")
	}
	if !strings.Contains(s, `Press "A" to set alerts, "del clears them"`) {
		t.Fatal("the PRICE ALERTS tile does not carry the owner's sentence")
	}
	a.onKey(Key{Kind: KRune, R: 'a'})
	if a.priceEdit < 0 {
		t.Fatal("A must open the price-alert form")
	}
}

func TestWindowsBuildIs107(t *testing.T) {
	if hudBuild != "3.5.6" {
		t.Fatalf("hudBuild is %q, want 3.5.6", hudBuild)
	}
}
