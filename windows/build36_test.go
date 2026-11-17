package main

import (
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// Owner order 2026-11-17: the big-order flash leaves the top of the window
// after two seconds.
func TestBigOrderFlashLastsTwoSeconds(t *testing.T) {
	a := demoApp(t, 120, 36)
	a.raiseFlag(Flag{Time: a.now, Symbol: "PRL", Kind: "flow", Text: "BIG ORDER"})
	if got := a.bannerUntil.Sub(a.now); got != 2*time.Second {
		t.Fatalf("the banner stays for %v, want two seconds", got)
	}
}

// Owner order 2026-11-17: D opens PRICE DIFFERENCE from the SCANNER.
func TestDOpensPriceDifference(t *testing.T) {
	a := demoApp(t, 122, 36)
	a.screen = scrScanner
	if !strings.Contains(plain(a), `Press "D" to calculate`) {
		t.Fatal("the tile does not name D")
	}
	a.onKey(Key{Kind: KRune, R: 'D'})
	if !a.pctOpen || a.calcOpen {
		t.Fatalf("D must open PRICE DIFFERENCE alone: pct %v calc %v", a.pctOpen, a.calcOpen)
	}
	a.onKey(Key{Kind: KEsc})
	a.onKey(Key{Kind: KRune, R: 'C'})
	if !a.calcOpen {
		t.Fatal("C must still open POSITION CALCULATOR")
	}
}

// Owner order 2026-11-17: FIRST PRICE and SECOND PRICE, both boxes reading
// Enter price with one blank cell on each side.
func TestPriceDifferenceFieldWords(t *testing.T) {
	a := demoApp(t, 120, 36)
	c := NewCanvas(59, 4, a.th.Panel)
	a.drawPercentTile(c, 0, 0, 59, 4)
	row := c.PlainRows()[1]
	for _, want := range []string{"FIRST PRICE", "SECOND PRICE"} {
		if !strings.Contains(row, want) {
			t.Fatalf("the tile is missing %q: %q", want, row)
		}
	}
	if got := strings.Count(row, " Enter price "); got != 2 {
		t.Fatalf("the two boxes have %d padded Enter price hints, want two: %q", got, row)
	}
	firstBox := strings.Index(row, "Enter price")
	secondLabel := strings.Index(row, "SECOND PRICE")
	if firstBox < 0 || secondLabel != firstBox-1+13+5 {
		t.Fatalf("SECOND PRICE starts on cell %d, want five cells after the first box at %d: %q", secondLabel, firstBox-1+13, row)
	}
}

// Owner order 2026-11-17: an empty total reads PKR -, with the dash after PKR
// in the same soft ink as TOTAL.
func TestEmptyCalculatorDashIsSoftAfterPKR(t *testing.T) {
	a := newTestApp(t)
	c := NewCanvas(80, 4, a.th.Panel)
	a.drawCalculatorTile(c, 0, 0, 80, 4)
	row := c.PlainRows()[2]
	dash := strings.Index(row, "-")
	pkr := strings.Index(row, "PKR")
	if dash < 0 || pkr < 0 || dash != pkr+4 {
		t.Fatalf("the empty total is not PKR -: %q", row)
	}
	// strings.Index counts bytes, while Cells is a flat row-major array. Find
	// the dash on the total row itself, not on the title row above it.
	dashCell := -1
	for i, r := range []rune(row) {
		if r == '-' {
			dashCell = i
			break
		}
	}
	if dashCell < 0 {
		t.Fatalf("the empty total has no dash: %q", row)
	}
	if got := c.Cells[2*c.W+dashCell].FG; got != a.th.Soft {
		t.Fatalf("the dash is %v, want the TOTAL soft ink %v: %q", got, a.th.Soft, row)
	}
}

// Owner order 2026-11-17: the difference tile keeps one dash when there is no
// percentage to calculate, not the old pair of placeholder dashes.
func TestEmptyDifferenceKeepsOneDash(t *testing.T) {
	a := demoApp(t, 120, 36)
	c := NewCanvas(59, 4, a.th.Panel)
	a.drawPercentTile(c, 0, 0, 59, 4)
	row := c.PlainRows()[2]
	if !strings.Contains(row, "DIFFERENCE  -") {
		t.Fatalf("the empty difference does not carry a dash: %q", row)
	}
	if strings.Contains(row, "--") {
		t.Fatalf("the empty difference carries two dashes: %q", row)
	}
}

// Owner order 2026-11-17: every market day's stored session is cleared at
// 08:00, and a weekend keeps the last stored day.
func TestStoredSessionClearsAtEightOnMarketDays(t *testing.T) {
	dir := t.TempDir()
	cfgPath := filepath.Join(dir, "settings.json")
	snap := &sessionSnapshot{
		Ver:     sessionVer,
		SavedAt: time.Date(2026, 11, 16, 15, 30, 0, 0, pkt),
		Session: "2026-11-16",
		Market:  &Market{Date: "2026-11-16"},
		Prices:  map[string]Quote{"KEL": {Price: 5.79}},
	}
	cfg := defaultSettings()
	cfg.Notify = false
	a := NewApp(cfg, cfgPath, NewRelay(defaultRelay))
	if err := saveSession(sessionPath(cfgPath), snap); err != nil {
		t.Fatalf("save: %v", err)
	}
	a.restoreSession(snap)
	a.now = time.Date(2026, 11, 17, 7, 59, 0, 0, pkt)
	a.maybeClearSession(a.now)
	if loadSession(sessionPath(cfgPath)) == nil {
		t.Fatal("the stored session was cleared before 08:00")
	}
	a.now = time.Date(2026, 11, 17, 8, 0, 0, 0, pkt)
	a.maybeClearSession(a.now)
	if got := loadSession(sessionPath(cfgPath)); got != nil {
		t.Fatalf("the stored session survived 08:00: %+v", got)
	}
	if a.market != nil || a.sessionDate != "" || len(a.prices) != 0 {
		t.Fatalf("the day is still in memory: market %v date %q prices %d", a.market, a.sessionDate, len(a.prices))
	}

	// Saturday keeps the last stored day.
	weekend := NewApp(cfg, cfgPath, NewRelay(defaultRelay))
	if err := saveSession(sessionPath(cfgPath), snap); err != nil {
		t.Fatalf("save weekend: %v", err)
	}
	weekend.now = time.Date(2026, 11, 14, 8, 0, 0, 0, pkt)
	weekend.maybeClearSession(weekend.now)
	if loadSession(sessionPath(cfgPath)) == nil {
		t.Fatal("a weekend cleared the stored session")
	}
}
