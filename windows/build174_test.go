package main

import (
	"strings"
	"testing"
	"time"
)

// Owner order 2026-11-26: the WATCH LIST page's box searches as he types. One
// letter puts every scrip that starts with it on the page, so E lists every E
// scrip and none of the others.
func TestTypingALetterListsEveryScripThatStartsWithIt(t *testing.T) {
	a := demoApp(t, 160, 40)
	a.setScreen(scrWatch)
	a.prices = nil
	a.of = &OrderFlow{Rows: []FlowRow{
		{Symbol: "ENGRO"}, {Symbol: "EFUG"}, {Symbol: "HCAR"}, {Symbol: "E"},
	}}
	a.watchQuery = "E"
	got := []string{}
	for _, r := range a.watchSorted() {
		if !strings.HasPrefix(r.Symbol, "E") {
			t.Fatalf("the search listed %s, which does not start with E", r.Symbol)
		}
		got = append(got, r.Symbol)
	}
	want := "E EFUG ENGRO"
	if strings.Join(got, " ") != want {
		t.Fatalf("typing E lists %v, want %s", got, want)
	}
	rows := plain(a)
	for _, sym := range []string{"EFUG", "ENGRO"} {
		if !strings.Contains(rows, sym) {
			t.Fatalf("%s is not on the page while the box holds E:\n%s", sym, rows)
		}
	}
	if strings.Contains(rows, "HCAR") {
		t.Fatalf("a scrip the search did not find is on the page:\n%s", rows)
	}
	// ESC empties the box and the page is his own list again.
	a.watchQuery, a.watchSearch = "", false
	if rows := plain(a); strings.Contains(rows, "EFUG") {
		t.Fatalf("the search's rows stayed on the page after the box emptied:\n%s", rows)
	}
}

// Owner order 2026-11-26: ENTER takes the one scrip the search found. Several
// matches are left to the tap that picks one, so the box never adds a letter.
func TestTheSearchTakesOneMatchAndLeavesManyToTheTap(t *testing.T) {
	a := demoApp(t, 160, 40)
	a.prices = nil
	a.of = &OrderFlow{Rows: []FlowRow{{Symbol: "ENGRO"}, {Symbol: "EFUG"}}}
	a.watchQuery = "ENG"
	a.addWatch()
	if !a.isWatched("ENGRO") {
		t.Fatalf("the one scrip the search found was not added: %v", a.cfg.Watch)
	}
	if a.watchQuery != "" || a.watchSearch {
		t.Fatalf("the box kept %q after the add", a.watchQuery)
	}
	a.watchQuery, a.watchSearch = "E", true
	a.addWatch()
	if len(a.cfg.Watch) != 1 || a.isWatched("E") {
		t.Fatalf("two matches added a scrip anyway: %v", a.cfg.Watch)
	}
	if !strings.Contains(a.watchMsg, "2 scrips start with E") {
		t.Fatalf("the page says %q, want the count of the matches", a.watchMsg)
	}
	// A tap on one of the search's own rows adds that scrip and closes the box.
	a.addWatchSymbol("EFUG")
	if !a.isWatched("EFUG") {
		t.Fatalf("the tap did not add the scrip: %v", a.cfg.Watch)
	}
	if a.watchQuery != "" || a.watchSearch {
		t.Fatalf("the search stayed open after the tap: %q", a.watchQuery)
	}
}

// The page's own last row says what the search found, so he can see the count
// before he picks one.
func TestTheFooterCountsWhatTheSearchFound(t *testing.T) {
	a := demoApp(t, 160, 40)
	a.setScreen(scrWatch)
	a.prices = nil
	a.of = &OrderFlow{Rows: []FlowRow{{Symbol: "ENGRO"}, {Symbol: "EFUG"}, {Symbol: "HCAR"}}}
	a.watchQuery = "E"
	if rows := plain(a); !strings.Contains(rows, `2 scrips start with "E". Tap one to add it.`) {
		t.Fatalf("the footer does not count the search:\n%s", rows)
	}
	a.watchQuery = "ZZ"
	if rows := plain(a); !strings.Contains(rows, `No KMIALL scrip starts with "ZZ".`) {
		t.Fatalf("an empty search has no line of its own:\n%s", rows)
	}
	a.watchQuery, a.watchSearch = "", false
	if rows := plain(a); !strings.Contains(rows, watchFooter) {
		t.Fatalf("the page's own instruction is gone when the box is empty:\n%s", rows)
	}
}

// Owner order 2026-11-26: the LINK line closes its latency with a full stop and
// opens Synced with a capital.
func TestTheLinkLineClosesWithAFullStopAndOpensSyncedWithACapital(t *testing.T) {
	a := demoApp(t, 122, 40)
	a.link, a.checking = true, false
	a.rtt = 42 * time.Millisecond
	a.now = time.Date(2026, 11, 26, 11, 0, 0, 0, pkt)
	a.lastMarketOK = a.now.Add(-5 * time.Second)
	line := ""
	for _, row := range a.render().PlainRows() {
		if strings.Contains(row, "LINK") && strings.Contains(row, " ms") {
			line = row
			break
		}
	}
	if !strings.Contains(line, "42 ms.  Synced 5 s ago") {
		t.Fatalf("the LINK line reads %q, want the full stop and the capital", line)
	}
}

// Owner order 2026-11-26: the right password shows the basmala in Arabic, then
// QUANT OF REHAN, and only then does the HUD take the screen.
func TestThePasswordShowsTheBasmalaThenTheNameThenTheHud(t *testing.T) {
	a := lockedApp(t, 100, 30)
	typeRunes(a, wantUnlockPassword)
	a.onKey(Key{Kind: KEnter})
	if !a.passOK || !a.locked {
		t.Fatalf("the gate after the right password: passOK=%v locked=%v", a.passOK, a.locked)
	}
	rows := screenOf(a)
	if !strings.Contains(rows, unlockBasmala) {
		t.Fatalf("the basmala is not on the gate:\n%s", rows)
	}
	if strings.Contains(rows, unlockBrand) {
		t.Fatalf("the name came before the basmala:\n%s", rows)
	}
	a.onTick(a.now.Add(unlockBasmalaFor))
	if !a.locked {
		t.Fatal("the HUD took the screen before the name was read")
	}
	if rows := screenOf(a); !strings.Contains(rows, unlockBrand) {
		t.Fatalf("the name is not on the gate:\n%s", rows)
	}
	a.onTick(a.now.Add(unlockWelcomeFor))
	if a.locked {
		t.Fatal("the gate stayed shut after the splash")
	}
}
