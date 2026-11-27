package main

import (
	"strings"
	"testing"
	"time"
)

// Owner order 2026-11-26 (later): the search reads in the box itself. Every
// match it finds stands in the box's own drop down, and the list under it is
// still his own list, which the search never filters or replaces.
func TestTheBoxSearchAnswersUnderTheBoxAndLeavesTheListAlone(t *testing.T) {
	a := demoApp(t, 160, 40)
	a.setScreen(scrWatch)
	a.prices = nil
	a.cfg.Watch = []string{"HCAR"}
	a.of = &OrderFlow{Rows: []FlowRow{
		{Symbol: "ENGRO"}, {Symbol: "EFUG"}, {Symbol: "HCAR"}, {Symbol: "E"},
	}}
	a.watchQuery, a.watchSearch = "E", true
	if got := a.watchSorted(); len(got) != 1 || got[0].Symbol != "HCAR" {
		t.Fatalf("the search rewrote his own list: %v", got)
	}
	rows := plain(a)
	for _, sym := range []string{"EFUG", "ENGRO"} {
		if !strings.Contains(rows, sym) {
			t.Fatalf("%s is not in the box's drop down:\n%s", sym, rows)
		}
	}
	if !strings.Contains(rows, "HCAR") {
		t.Fatalf("the search took his own list away:\n%s", rows)
	}
	// The drop down stands under the box and above the ORDER line of chips.
	orderY, matchY := -1, -1
	for y, row := range a.render().PlainRows() {
			if orderY < 0 && strings.Contains(row, "ORDER ") {
			orderY = y
		}
		if matchY < 0 && strings.Contains(row, "ENGRO") {
			matchY = y
		}
	}
	if matchY < 0 || orderY < 0 || matchY > orderY {
		t.Fatalf("the drop down is not above the ORDER line: match %d, ORDER %d\n%s", matchY, orderY, rows)
	}
	// ESC empties the box and the drop down goes with it.
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
// opens Synced with a capital. Owner order 2026-11-26 (later): one space stands
// between the full stop and the word, not two.
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
	if !strings.Contains(line, "42 ms. SYNCED 5 s ago") {
		t.Fatalf("the LINK line reads %q, want one space before SYNCED", line)
	}
	if strings.Contains(line, "ms.  SYNCED") {
		t.Fatalf("the LINK line keeps two spaces before SYNCED: %q", line)
	}
}

// Owner order 2026-11-26 (later): the right password shows the basmala and
// nothing after it, and only then does the HUD take the screen.
// hasBasmalaArt says whether the screen carries the dotted art of the words.
func hasBasmalaArt(rows string) bool {
	return strings.ContainsRune(rows, basmalaDot)
}

// The banner is a picture of the phrase, not text in cells. Owner order
// 2026-11-27: it is made of one single dot and nothing else, so a cell is a dot
// or a space, the dots stand continuous from cell to cell, every line is the
// same width, and no block mark appears anywhere in it.
func TestTheBannerIsThePhraseDrawnWhole(t *testing.T) {
	for _, cols := range []int{60, 100, 160} {
		lines := basmalaArt(cols, 40)
		if len(lines) < 4 {
			t.Fatalf("%d cells: the art is %d lines", cols, len(lines))
		}
		want := runeLen(lines[0])
		for i, line := range lines {
			if runeLen(line) != want {
				t.Fatalf("%d cells: line %d is %d cells wide, want %d", cols, i, runeLen(line), want)
			}
			if want > cols {
				t.Fatalf("%d cells: the art is %d cells wide", cols, want)
			}
			blank := true
			for _, r := range line {
				switch r {
				case basmalaDot:
					blank = false
				case ' ':
				default:
					t.Fatalf("%d cells: line %d carries %U, not the one dot", cols, i, r)
				}
			}
			if blank {
				t.Fatalf("%d cells: line %d is empty", cols, i)
			}
		}
	}
}

func TestThePasswordShowsTheBasmalaAloneThenTheHud(t *testing.T) {
	a := lockedApp(t, 100, 30)
	typeRunes(a, wantUnlockPassword)
	a.onKey(Key{Kind: KEnter})
	if !a.passOK || !a.locked {
		t.Fatalf("the gate after the right password: passOK=%v locked=%v", a.passOK, a.locked)
	}
	rows := screenOf(a)
	if !hasBasmalaArt(rows) {
		t.Fatalf("the basmala is not on the gate:\n%s", rows)
	}
	if strings.Contains(rows, "QUANT OF REHAN") {
		t.Fatalf("the banner carries a name after the basmala:\n%s", rows)
	}
	a.onTick(a.now.Add(unlockWelcomeFor))
	if a.locked {
		t.Fatal("the gate stayed shut after the banner")
	}
}

// Owner order 2026-11-26 (later still): the banner stands at half the width it
// took before, so the words read as a mark in the middle of the gate.
func TestTheBannerIsHalfTheWidthOfTheWindow(t *testing.T) {
	a := lockedApp(t, 200, 40)
	typeRunes(a, wantUnlockPassword)
	a.onKey(Key{Kind: KEnter})
	widest := 0
	for _, row := range a.render().PlainRows() {
		n := 0
		for _, r := range row {
			if r == basmalaDot {
				n++
			}
		}
		if n > widest {
			widest = n
		}
	}
	if widest == 0 {
		t.Fatal("the banner drew no art")
	}
	if widest > 100 {
		t.Fatalf("the banner is %d cells wide, want at most 100 in a 200 cell window", widest)
	}
}

// Owner order 2026-11-26 (later): one space stands between PKR and its price on
// CUSTOM SCRIPS OF VOLUME, two digits or three, and the group's later columns
// are still placed from the price field's own end.
func TestPKRKeepsOneSpaceBeforeItsPrice(t *testing.T) {
	a := demoApp(t, 80, 24)
	for _, px := range []string{"99.50", "102.75"} {
		c := NewCanvas(40, 1, a.th.Panel)
		a.drawQuoteLeft(c, 0, 0, 9, px, nil, "")
		row := c.PlainRows()[0]
		if !strings.HasPrefix(row, "PKR "+px) {
			t.Fatalf("%s: the day line reads %q, want one space after PKR", px, row)
		}
	}
}

// Owner order 2026-11-26 (later): every sub menu carries the same PKR field and
// the same NET DELTA field, because both are measured on the whole scan table
// and not on the three scrips the chosen sort happens to carry.
func TestEverySubMenuKeepsTheSameQuoteFields(t *testing.T) {
	b, s, tot := int64(40), int64(5), int64(45)
	b2, s2, tot2 := int64(9000), int64(10), int64(9010)
	tbl := map[string]Quote{
		"QUIET": {Price: 12.5, Buy: &b, Sell: &s, Volume: &tot},
		"LOUD":  {Price: 1234.5, Buy: &b2, Sell: &s2, Volume: &tot2},
	}
	if w, want := scanPriceW(tbl), runeLen("1,234.50"); w != want {
		t.Fatalf("the PKR field is %d cells, want the table's widest price, %d", w, want)
	}
	if w, want := scanNetWidth(tbl), runeLen(signedCompact(8990)); w != want {
		t.Fatalf("the NET DELTA field is %d cells, want the table's widest figure, %d", w, want)
	}
}

// Owner order 2026-11-26 (later): the FEED row carries the freshest tick and no
// "typical" age at all. Owner order 2026-11-27: the answers per second figure
// is withdrawn from the tile as well.
func TestTheTelemetryRowCarriesNoTypicalAge(t *testing.T) {
	a := demoApp(t, 122, 40)
	rows := plain(a)
	if strings.Contains(rows, "typical") {
		t.Fatalf("the TELEMETRY tile still counts a typical stock:\n%s", rows)
	}
	if strings.Contains(rows, "/s") {
		t.Fatalf("the FEED row still prints answers per second:\n%s", rows)
	}
	if !strings.Contains(rows, " s old") {
		t.Fatalf("the FEED row lost the freshest tick's age:\n%s", rows)
	}
}

// Owner order 2026-11-26 (later): the slash between the advancers and the
// decliners is the theme's white.
func TestTheAdvDecSlashIsWhite(t *testing.T) {
	a := demoApp(t, 122, 40)
	c := a.render()
	for y, row := range c.PlainRows() {
		if !strings.Contains(row, "ADV/DEC") {
			continue
		}
		at := strings.LastIndex(row, "/")
		if at < 0 || at == strings.Index(row, "/") {
			t.Fatalf("the ADV/DEC row carries no dividing slash: %q", row)
		}
		x := runeLen(row[:at])
		if fg := c.Cells[y*c.W+x].FG; fg != a.th.Text {
			t.Fatalf("the ADV/DEC slash is %v, want the theme's white %v", fg, a.th.Text)
		}
		return
	}
	t.Fatal("no ADV/DEC row on the page")
}
