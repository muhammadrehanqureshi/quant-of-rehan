package main

import (
	"fmt"
	"strings"
	"testing"
)

// sectorFixture is a scanner with three real groups, each carrying its own
// scrips, so opening one can prove which group the tile read.
func sectorFixture(t *testing.T) *App {
	t.Helper()
	a := demoApp(t, 122, 36)
	a.demo = false
	a.quotes = nil
	a.screen = scrScanner
	a.sectors = &Sectors{OK: true, Items: []Sector{
		{Name: "CEMENT", Symbols: []string{"AAA", "EEE"}},
		{Name: "AUTOMOBILE", Symbols: []string{"BBB"}},
		{Name: "BANKS", Symbols: []string{"CCC"}},
	}}
	a.symbols = nil
	a.prices = map[string]Quote{
		"AAA": {Price: 10, ChangePct: f64(-1.5)},
		"BBB": {Price: 10, ChangePct: f64(2.5)},
		"CCC": {Price: 10, ChangePct: f64(0.5)},
	}
	a.sectorChoice = a.visibleSectorIndices()[0]
	return a
}

// Owner order 2026-11-20 (latest): ENTER opens the sector the arrows marked.
// A pointer left resting over another row could open that row instead, which
// read as every sector opening the same group.
func TestBuild148SectorEnterOpensTheMarkedGroup(t *testing.T) {
	a := sectorFixture(t)
	// Highest percentage first, so the rows read AUTOMOBILE, BANKS, CEMENT.
	a.onKey(Key{Kind: KDown})
	before := a.sectorGroups()[a.sectorChoice].Name
	if before != "BANKS" {
		t.Fatalf("the selection reads %q after one DOWN, want BANKS", before)
	}
	a.onKey(Key{Kind: KEnter})
	if !a.sectorOpen {
		t.Fatalf("ENTER left the tile closed")
	}
	if got := a.sectorGroups()[a.sectorChoice].Name; got != before {
		t.Fatalf("ENTER opened %q, the marked row is %q", got, before)
	}
	if got := strings.Join(a.visibleSectorMembers(), ","); got != "CCC" {
		t.Fatalf("the opened tile lists %q, want BANKS' own CCC", got)
	}
	if !strings.Contains(plain(a), "CCC") {
		t.Errorf("the opened tile does not draw its scrip:\n%s", plain(a))
	}
}

// Owner order 2026-11-20 (latest): the SECTORS list wraps, so DOWN on the last
// sector lands on the first and UP on the first lands on the last.
func TestBuild148SectorListWraps(t *testing.T) {
	a := sectorFixture(t)
	vis := a.visibleSectorIndices()
	for i := 1; i < len(vis); i++ {
		a.moveSectorChoice(1)
	}
	if a.sectorChoice != vis[len(vis)-1] {
		t.Fatalf("the selection stopped on %d, want the last %d", a.sectorChoice, vis[len(vis)-1])
	}
	a.moveSectorChoice(1)
	if a.sectorChoice != vis[0] {
		t.Errorf("DOWN on the last sector reads %d, want the first %d", a.sectorChoice, vis[0])
	}
	a.moveSectorChoice(-1)
	if a.sectorChoice != vis[len(vis)-1] {
		t.Errorf("UP on the first sector reads %d, want the last %d", a.sectorChoice, vis[len(vis)-1])
	}
}

// Owner order 2026-11-20 (latest): the PRICE ALERTS slots carry their number
// and their EMPTY word on the same cells the BIG BUYING NOW board writes its
// number and its symbol, so the two tiles read as one column.
func TestBuild148PriceAlertsLineUpWithTheBoards(t *testing.T) {
	a := demoApp(t, 120, 30)
	a.screen = scrAlerts
	slot := 0
	for _, row := range rowsOf(a) {
		if !strings.Contains(row, "EMPTY") {
			continue
		}
		slot++
		// The board writes fmt.Sprintf("%2d.", n) on the tile's first cell, then
		// the two cell mark, then the symbol on the sixth: " 1.   SYMBOL".
		want := fmt.Sprintf(" %d.   EMPTY", slot)
		if !strings.Contains(row, want) {
			t.Errorf("slot %d does not stand on the board's cells, want %q in: %q", slot, want, row)
		}
	}
	if slot != priceAlertSlots {
		t.Fatalf("the tile carries %d EMPTY slots, want %d", slot, priceAlertSlots)
	}
}
