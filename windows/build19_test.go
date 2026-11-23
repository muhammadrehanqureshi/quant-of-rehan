package main

import (
	"os"
	"strings"
	"testing"
)

// Owner order 2026-11-14 (latest): one cell of padding stands on each side
// of the empty hint.
func TestSearchHintHasOneCellOnEachSide(t *testing.T) {
	a := demoApp(t, 120, 30)
	c := NewCanvas(120, 4, RGB{})
	bw := a.searchBox(c, 0, 0, 40, "", scripSearchHint, false)
	if bw != runeLen(scripSearchHint)+2 {
		t.Fatalf("the empty box is %d cells, want the hint's %d plus two", bw, runeLen(scripSearchHint))
	}
	row := []rune(c.PlainRows()[0])
	if got, want := string(row[:bw]), " "+scripSearchHint+" "; got != want {
		t.Fatalf("the hint's padding is %q, want %q", got, want)
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
	if !strings.Contains(s, `Press "A" to set alerts, "del" clears them`) {
		t.Fatal("the PRICE ALERTS tile does not carry the owner's sentence")
	}
	if strings.Contains(s, `("del" clears them)`) {
		t.Fatal("the PRICE ALERTS tile still carries the brackets")
	}
	a.onKey(Key{Kind: KRune, R: 'a'})
	if a.priceEdit < 0 {
		t.Fatal("A must open the price-alert form")
	}
}

func TestWindowsBuildIsCurrent(t *testing.T) {
	if hudBuild != "3.8.33" {
		t.Fatalf("hudBuild is %q, want 3.8.33", hudBuild)
	}
}

// Owner report 2026-11-21: every build shipped as Windows file version
// 3.8.20.0, because the workflow called mksyso with that fixed number instead
// of the HUD build, so the desktop could not tell one build from another. The
// stamp is the HUD build now, and this test keeps the two from drifting apart.
func TestTheWorkflowStampsTheHudBuild(t *testing.T) {
	body, err := os.ReadFile("../.github/workflows/windows-desktop.yml")
	if err != nil {
		t.Fatalf("the Windows workflow is unreadable: %v", err)
	}
	want := "mksyso.py assets/QuantOfRehan.ico rsrc_windows_amd64.syso " + hudBuild + ".0"
	if !strings.Contains(string(body), want) {
		t.Fatalf("the workflow does not stamp %s.0; want %q", hudBuild, want)
	}
}
