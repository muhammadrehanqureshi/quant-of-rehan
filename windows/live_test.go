package main

import (
	"fmt"
	"regexp"
	"strings"
	"testing"
	"time"
)

func rowsOf(a *App) []string { return a.render().PlainRows() }

// The name is centred on the top line with a diamond on either side, the
// index is on the next line and the rule is on the third line.
func TestTitleIsTheTopLine(t *testing.T) {
	for _, sz := range [][2]int{{80, 26}, {100, 30}, {120, 30}, {160, 45}} {
		for scr := range screenNames {
			a := demoApp(t, sz[0], sz[1])
			a.screen = screenID(scr)
			rows := rowsOf(a)
			if !strings.Contains(strings.Join(strings.Fields(rows[0]), ""), "QUANTOFREHAN") {
				t.Errorf("%dx%d screen %d: row 0 is %q", sz[0], sz[1], scr, rows[0])
			}
			if !strings.Contains(rows[1], headerTag) {
				t.Errorf("%dx%d screen %d: row 1 is %q", sz[0], sz[1], scr, rows[1])
			}
			if !strings.Contains(rows[0], headerTitle) {
				t.Errorf("%dx%d screen %d: row 0 is %q, want the tight diamonds", sz[0], sz[1], scr, rows[0])
			}
			if !strings.HasPrefix(rows[2], "━━━━") {
				t.Errorf("%dx%d screen %d: row 2 is %q, want the rule", sz[0], sz[1], scr, rows[2])
			}
		}
	}
}

// Every search box asks for a KMIALL scrip in the same words, and the empty
// CUSTOM SCRIPS tile no longer carries a sorting prompt.
func TestFooterActionsAreUppercase(t *testing.T) {
	a := demoApp(t, 122, 30)
	s := plain(a)
	for _, want := range []string{"D DETAILS", "TAB NEXT", "R REFRESH", "Q QUIT"} {
		if !strings.Contains(s, want) {
			t.Errorf("the footer is missing %q:\n%s", want, s)
		}
	}
}

func TestSearchBoxesAndEmptySortText(t *testing.T) {
	a := demoApp(t, 120, 30)
	a.screen = scrScanner
	if s := plain(a); !strings.Contains(s, scripSearchHint) {
		t.Errorf("scanner search box is missing %q", scripSearchHint)
	}
	a.scanChoice = 0
	if s := plain(a); strings.Contains(s, "Choose a sort") {
		t.Errorf("the empty CUSTOM SCRIPS tile still has its old prompt:\n%s", s)
	}
	a.screen = scrOrderFlow
	if s := plain(a); !strings.Contains(s, scripSearchHint) {
		t.Errorf("ORDER FLOW search box is missing %q", scripSearchHint)
	}
}

// The big buying heading is green and the big selling heading is red.
func TestAlertBoardHeadingsUseGreenAndRed(t *testing.T) {
	a := demoApp(t, 120, 30)
	a.screen = scrAlerts
	c := a.render()
	ink := func(title string) RGB {
		for y, row := range c.PlainRows() {
			i := strings.Index(row, title)
			if i < 0 {
				continue
			}
			return c.Cells[y*c.W+runeLen(row[:i])].FG
		}
		t.Fatalf("the alerts screen has no %q heading", title)
		return RGB{}
	}
	if got := ink("BIG BUYING NOW"); got != a.th.Good {
		t.Errorf("BIG BUYING NOW is %v, want green %v", got, a.th.Good)
	}
	if got := ink("BIG SELLING NOW"); got != a.th.Bad {
		t.Errorf("BIG SELLING NOW is %v, want red %v", got, a.th.Bad)
	}
}

// The one clock on the screen is at the top right, shows the date as well as
// the time, and its seconds move every second.
func TestHeaderClockTicksEverySecond(t *testing.T) {
	a := demoApp(t, 120, 30)
	a.animT = -1
	for i := 0; i < 3; i++ {
		a.now = time.Date(2026, 11, 2, 11, 0, i, 0, pkt)
		want := fmt.Sprintf("MON 02 NOV 2026 11:00:0%d UTC+5", i)
		if row := rowsOf(a)[1]; !strings.HasSuffix(strings.TrimRight(row, " "), want) {
			t.Errorf("second %d: top row is %q, want it to end with %q", i, row, want)
		}
	}
}

// Owner order 2026-11-07: the clock itself is green; the date and the UTC+5 tag
// stay in the darker shade.
func TestHeaderClockIsGreenButUTCDoesNotFollow(t *testing.T) {
	a := demoApp(t, 122, 30)
	a.animT = -1
	a.now = time.Date(2026, 11, 2, 11, 0, 7, 0, pkt)
	c := a.render()
	row := c.PlainRows()[1]
	// The index line carries the rules' box glyphs, which are three bytes each,
	// so the cell is counted in runes from the row's own start, on row one.
	cellOf := func(sub string) int {
		i := strings.Index(row, sub)
		if i < 0 {
			t.Fatalf("the index line has no %q: %q", sub, row)
		}
		return c.W + len([]rune(row[:i]))
	}
	if got := c.Cells[cellOf("11:00:07")].FG; got != a.th.Good {
		t.Errorf("the clock is %v, want green %v", got, a.th.Good)
	}
	if got := c.Cells[cellOf("UTC+5")].FG; got == a.th.Good {
		t.Errorf("UTC+5 is green too; it must stay in the darker shade")
	}
}

// There is exactly one clock on the home screen: the time of day appears once.
func TestOnlyOneClockOnHome(t *testing.T) {
	a := demoApp(t, 122, 30)
	a.animT = -1
	a.now = time.Date(2026, 11, 2, 11, 0, 7, 0, pkt)
	clock := regexp.MustCompile(`\b\d{2}:\d{2}:\d{2}\b`)
	var hits []string
	for y, row := range rowsOf(a) {
		if strings.Contains(row, "ENTRY TIME") {
			continue // the signal's own entry time is not a clock
		}
		for _, m := range clock.FindAllString(row, -1) {
			hits = append(hits, fmt.Sprintf("row %d: %s", y, m))
		}
	}
	if len(hits) != 1 || !strings.HasPrefix(hits[0], "row 1:") {
		t.Errorf("want one clock on the index line, row 1, got %v", hits)
	}
}

func quotesAt(price float64, vol int64) *Quotes {
	chg := 1.5
	return &Quotes{OK: true, FetchedAt: flowT0, Items: map[string]LiveQuote{
		"ECHO": {Price: price, Fresh: true, Volume: vol, High: 16, Low: 14, ChangePct: &chg, AgeSeconds: 0},
	}, Index: &IndexQuote{Value: 166000 + price, Change: 100, ChangePct: 0.06, AsOf: "2026-11-02 11:00:00", Fresh: true}}
}

func TestNumbersFlashWhenTheyChangeAndFade(t *testing.T) {
	a := newTestApp(t)
	a.now = flowT0
	a.ingestQuotes(quotesAt(15.00, 1_000_000))
	if k, _ := a.flashAmount("px:ECHO"); k != 0 {
		t.Fatalf("the first reading is a baseline, not a change")
	}
	a.now = flowT0.Add(time.Second)
	a.ingestQuotes(quotesAt(15.00, 1_000_000)) // nothing moved
	if k, _ := a.flashAmount("px:ECHO"); k != 0 {
		t.Errorf("no change must not flash")
	}
	a.now = flowT0.Add(2 * time.Second)
	a.ingestQuotes(quotesAt(15.05, 1_020_000))
	k, dir := a.flashAmount("px:ECHO")
	if k < 0.99 || dir != 1 {
		t.Errorf("a rise flashes full and up: %v %d", k, dir)
	}
	if k, dir := a.flashAmount("vol:ECHO"); k < 0.99 || dir != 1 {
		t.Errorf("volume flashes too: %v %d", k, dir)
	}
	a.now = flowT0.Add(2*time.Second + flashFor/2)
	if mid, _ := a.flashAmount("px:ECHO"); mid <= 0 || mid >= k {
		t.Errorf("half way through the fade: %v", mid)
	}
	a.now = flowT0.Add(2*time.Second + flashFor + time.Millisecond)
	if end, _ := a.flashAmount("px:ECHO"); end != 0 {
		t.Errorf("after the fade: %v", end)
	}
	a.now = flowT0.Add(4 * time.Second)
	a.ingestQuotes(quotesAt(15.00, 1_030_000))
	if _, dir := a.flashAmount("px:ECHO"); dir != -1 {
		t.Errorf("a fall flashes down: %d", dir)
	}
	if len(a.symHist["ECHO"].v) != 4 || len(a.idxHist.v) != 4 {
		t.Errorf("the charts take one point per answer: %d %d", len(a.symHist["ECHO"].v), len(a.idxHist.v))
	}
}

func TestFlashingNumbersAreDrawnOnATintedGround(t *testing.T) {
	a := demoApp(t, 120, 30)
	c := a.render()
	tinted := 0
	for _, cell := range c.Cells {
		if cell.BG != a.th.Panel && cell.BG != a.th.BG && cell.Ch >= '0' && cell.Ch <= '9' {
			tinted++
		}
	}
	if tinted == 0 {
		t.Errorf("a live number that just changed must stand out on the screen")
	}
}

func TestFeedAgeCountsUpEverySecond(t *testing.T) {
	a := newTestApp(t)
	a.link, a.checking = true, false
	a.now = flowT0
	a.ingestQuotes(quotesAt(15, 1_000_000))
	// Owner order 2026-11-12: the LIVE window is fifteen seconds, longer than
	// the eleven second broker burst, so one cycle no longer flips the light.
	for i, want := range []string{"LIVE", "LIVE", "LAGGING", "LAGGING"} {
		a.now = flowT0.Add([]time.Duration{0, 4 * time.Second, 16 * time.Second, 45 * time.Second}[i])
		if got, _, _ := a.feedState(); got != want {
			t.Errorf("after step %d: %s want %s", i, got, want)
		}
	}
	// The relay's own freshness boundary is ninety seconds; the HUD must not
	// paint a normal broker burst as STALE before that boundary.
	a.now = flowT0.Add(91 * time.Second)
	if got, _, _ := a.feedState(); got != "STALE" {
		t.Errorf("past the relay boundary: %s want STALE", got)
	}
	a.now = flowT0.Add(7 * time.Second)
	if _, age, _ := a.feedState(); age != 7 {
		t.Errorf("age: %d", age)
	}
	a.now = flowT0.Add(16 * time.Second)
	light := ""
	for _, sp := range a.feedLight() {
		light += sp.S
	}
	if !strings.Contains(light, "LAGGING 16s") {
		t.Errorf("feed light: %q", light)
	}
}

func TestUpdatesPerSecond(t *testing.T) {
	a := newTestApp(t)
	for i := 0; i <= 10; i++ {
		a.now = flowT0.Add(time.Duration(i) * time.Second)
		a.ingestQuotes(quotesAt(15, 1_000_000))
	}
	if got := a.updatesPerSecond(); got < 0.99 || got > 1.01 {
		t.Errorf("updates per second: %v", got)
	}
}

// Polling is timed from when a request left, so one second is one second.
func TestPollingIsTimedFromTheSend(t *testing.T) {
	a := newTestApp(t)
	a.sentAt["quotes"] = flowT0
	a.now = flowT0.Add(300 * time.Millisecond) // the round trip
	a.done("quotes", true)
	if got := a.next["quotes"]; !got.Equal(flowT0.Add(time.Second)) {
		t.Errorf("next quotes at +%v, want +1s", got.Sub(flowT0))
	}
	a.now = flowT0.Add(2500 * time.Millisecond) // a slow answer
	a.done("quotes", true)
	if got := a.next["quotes"]; !got.Equal(a.now) {
		t.Errorf("a slow answer must be followed at once: %v", got.Sub(flowT0))
	}
}

func TestLiveLeadersOverlayVolumeAndSplit(t *testing.T) {
	a := newTestApp(t)
	m := marketIn("OPEN")
	b, s, v, p := int64(1), int64(2), int64(3), 9.0
	m.Leaders = []Leader{{Symbol: "ECHO", Buy: &b, Sell: &s, Volume: &v, Price: &p}}
	a.market = m
	a.now = flowT0
	a.ingestQuotes(quotesAt(15, 1_000_000))
	l := a.effectiveLeaders()[0]
	if *l.Price != 15 || *l.Volume != 3 || !l.HasSplit() {
		t.Fatalf("overlay: %+v", l)
	}
	// Owner order 2026-11-11: the tile keeps the relay's measured pair and
	// never re-splits the volume from the day's price range.
	if *l.Buy != 1 || *l.Sell != 2 {
		t.Errorf("split: %d %d", *l.Buy, *l.Sell)
	}
}

func TestBigBuyRaisesBannerToneAndToast(t *testing.T) {
	a := newTestApp(t)
	a.now = flowT0
	fl := Flag{Time: flowT0, Symbol: "ECHO", Kind: "flow", Text: "Stock ECHO is getting big buying orders", Detail: "Bought PKR 12.0M"}
	a.cfg.Sound = true
	a.raiseFlag(fl)
	if a.bannerTitle != fl.Text || a.bannerKind != "flow" || !a.now.Before(a.bannerUntil) {
		t.Errorf("banner: %q %q", a.bannerTitle, a.bannerKind)
	}
	if !toneNative && !a.bell {
		t.Errorf("sound on: the bell where there is no sound card must play")
	}
	// Sound off: banner yes, tone no.
	b := newTestApp(t)
	b.cfg.Sound = false
	b.raiseFlag(fl)
	if b.bell || b.bannerTitle == "" {
		t.Errorf("sound off: bell %v banner %q", b.bell, b.bannerTitle)
	}
	// A quiet flag shows nowhere but the log.
	c := newTestApp(t)
	fl.Silent = true
	c.raiseFlag(fl)
	if c.bannerTitle != "" || c.bell {
		t.Errorf("a quiet flag must not announce itself")
	}
}

func TestBannerShowsOnRowOneAndClickOpensAlerts(t *testing.T) {
	a := demoApp(t, 120, 30)
	a.raiseFlag(Flag{Time: a.now, Symbol: "ECHO", Kind: "flow", Text: "Stock ECHO is getting big buying orders", Detail: "Bought PKR 12.0M"})
	rows := rowsOf(a)
	if !strings.Contains(rows[1], "Stock ECHO is getting big buying orders") {
		t.Fatalf("banner: %q", rows[1])
	}
	a.onKey(Key{Kind: KMouse, X: 40, Y: 1, Btn: MouseLeft})
	if a.screen != scrAlerts || a.now.Before(a.bannerUntil) {
		t.Errorf("a click on the banner opens the alerts and clears it: %v", a.screen)
	}
}

// click finds the text on screen and clicks its first cell.
func clickText(t *testing.T, a *App, text string) {
	t.Helper()
	for y, row := range rowsOf(a) {
		if x := strings.Index(row, text); x >= 0 {
			a.onKey(Key{Kind: KMouse, X: len([]rune(row[:x])), Y: y, Btn: MouseLeft})
			return
		}
	}
	t.Fatalf("%q is not on screen", text)
}

func TestMouseOperatesTheTabs(t *testing.T) {
	a := demoApp(t, 120, 30)
	for i, name := range screenNames {
		clickText(t, a, string(rune('1'+i))+" "+name)
		if a.screen != screenID(i) {
			t.Errorf("click on %s: screen %v", name, a.screen)
		}
	}
	// The sound and alert switches are only on Settings.
	a.setScreen(scrHome)
	if strings.Contains(plain(a), "♪ SOUND") || strings.Contains(plain(a), "BIG BUY FLAG") || strings.Contains(plain(a), "BIG SELL FLAG") {
		t.Errorf("the footer still carries a switch")
	}
	// The raw/card switch of the signal panel.
	clickText(t, a, "[D] RAW")
	if !a.showRaw {
		t.Errorf("[D] RAW click")
	}
	// Right click goes home.
	a.setScreen(scrScanner)
	a.onKey(Key{Kind: KMouse, X: 50, Y: 10, Btn: MouseRight})
	if a.screen != scrHome {
		t.Errorf("right click: %v", a.screen)
	}
}

func TestMouseOnListsAndSettings(t *testing.T) {
	a := demoApp(t, 120, 30)
	a.screen = scrScanner
	a.scanChoice = 0
	clickText(t, a, "MORE BUYERS & LESS SELLERS")
	if a.scanChoice != 2 {
		t.Errorf("scanner choice by click: %d", a.scanChoice)
	}
	if strings.Contains(plain(a), "BIG BUYING & SELLING NOW (LIVE FLOW)") {
		t.Errorf("the flow sort is still on the scanner")
	}

	a.screen = scrSettings
	a.cfg.Notify = false
	clickText(t, a, "NOTIFICATIONS")
	if !a.cfg.Notify || a.setCursor != 1 {
		t.Errorf("notifications row: %v cursor %d", a.cfg.Notify, a.setCursor)
	}
	clickText(t, a, "NAVY BLUE & WHITE")
	if a.cfg.Theme != 3 || a.th != themeAt(3) {
		t.Errorf("theme by click: %d", a.cfg.Theme)
	}
	before := a.cfg.BigBuyValue
	clickText(t, a, "BIG ORDER SIZE")
	if a.cfg.BigBuyValue == before || a.flow.cfg.MinValue != float64(a.cfg.BigBuyValue) {
		t.Errorf("size by click: %d", a.cfg.BigBuyValue)
	}
	// Enter walks the sizes and wraps from the top back to the bottom.
	a.setCursor = 5
	seen := map[int64]bool{}
	for i := 0; i < len(bigBuyChoices); i++ {
		a.onKey(Key{Kind: KEnter})
		seen[a.cfg.BigBuyValue] = true
	}
	if len(seen) != len(bigBuyChoices) {
		t.Errorf("enter must visit every size: %v", seen)
	}
	// LEFT and RIGHT step without wrapping.
	a.cfg.BigBuyValue = bigBuyChoices[0]
	a.onKey(Key{Kind: KLeft})
	if a.cfg.BigBuyValue != bigBuyChoices[0] {
		t.Errorf("left at the bottom: %d", a.cfg.BigBuyValue)
	}
	a.onKey(Key{Kind: KRight})
	if a.cfg.BigBuyValue != bigBuyChoices[1] {
		t.Errorf("right: %d", a.cfg.BigBuyValue)
	}

	// The test alert row raises a banner marked as a test.
	a.bannerUntil = time.Time{}
	clickText(t, a, "TEST BUYING ALERT")
	if !strings.Contains(a.bannerTitle, "TEST") || len(a.flow.Log) != 0 && a.flow.Log[len(a.flow.Log)-1].Symbol == "TEST" {
		t.Errorf("test alert: %q", a.bannerTitle)
	}
}

func TestWheelAndHover(t *testing.T) {
	a := demoApp(t, 120, 30)
	a.screen = scrSettings
	a.onKey(Key{Kind: KMouse, X: 50, Y: 10, Btn: MouseWheelDown})
	a.onKey(Key{Kind: KMouse, X: 50, Y: 10, Btn: MouseWheelDown})
	if a.setCursor != 2 {
		t.Errorf("wheel on settings: %d", a.setCursor)
	}
	a.onKey(Key{Kind: KMouse, X: 50, Y: 10, Btn: MouseWheelUp})
	if a.setCursor != 1 {
		t.Errorf("wheel up: %d", a.setCursor)
	}
	a.screen = scrAlerts
	a.lvBoard = listView{total: 10, view: 3}
	a.alertSplit, a.alertSplitX = 100, 100
	a.onKey(Key{Kind: KMouse, X: 50, Y: 10, Btn: MouseWheelDown})
	if a.lvBoard.off != 2 {
		t.Errorf("wheel on alerts: %d", a.lvBoard.off)
	}
	// Hover only moves the pointer; nothing is clicked.
	screen := a.screen
	a.onKey(Key{Kind: KMouse, X: 5, Y: 28, Btn: MouseMove})
	if a.screen != screen || a.hoverX != 5 || a.hoverY != 28 {
		t.Errorf("hover: %d %d %v", a.hoverX, a.hoverY, a.screen)
	}
	// A click on nothing does nothing.
	a.onKey(Key{Kind: KMouse, X: 0, Y: 29, Btn: MouseLeft})
}

func TestAlertsScreenListsTheLogAndBoard(t *testing.T) {
	a := demoApp(t, 120, 30)
	a.screen = scrAlerts
	s := plain(a)
	for _, want := range []string{"BIG BUYING NOW", "BIG SELLING NOW", "ALERTS LOG (", "ECHO is getting big buying orders", "From PKR 10.0M a minute", "BUY FLOW", "BUY BLOCK"} {
		if !strings.Contains(s, want) {
			t.Errorf("alerts screen is missing %q", want)
		}
	}
	a.onKey(Key{Kind: KDel})
	if len(a.flow.Log) != 0 || !strings.Contains(plain(a), "No flag yet.") {
		t.Errorf("delete clears the log")
	}
	a.cfg.BigBuy = false
	a.cfg.BigSell = false
	if s := plain(a); !strings.Contains(s, "Press B or use Settings") || !strings.Contains(s, "Press S or use Settings") {
		t.Errorf("off state, both boards say how to turn the flag on:\n%s", s)
	}
	a.cfg.BigBuy, a.cfg.BigSell = true, true
	a.flow.Log = append(a.flow.Log, Flag{Time: a.now, Symbol: "XYZ", Kind: "flow", Side: "SELL", Value: 12e6,
		Text: "XYZ is getting big selling orders", Detail: "Sold PKR 12M (900K shares) in 60 seconds. Sellers made up 90% of the volume."})
	if s := plain(a); !strings.Contains(s, "SELL FLOW") || !strings.Contains(s, "XYZ is getting big selling orders") {
		t.Errorf("a selling flag is in the log:\n%s", s)
	}
}

func TestBigBuyOffStopsFlagsButNotTheFeed(t *testing.T) {
	a := newTestApp(t)
	a.cfg.BigBuy = false
	px, vol := 15.0, int64(1_000_000)
	for i := 0; i < 30; i++ {
		px += 0.01
		vol += 100_000
		a.now = flowT0.Add(time.Duration(i) * time.Second)
		a.ingestQuotes(quotesAt(px, vol))
	}
	if a.flagCount != 0 || len(a.flow.Log) != 0 || a.bannerTitle != "" {
		t.Errorf("flag is off: %d %d %q", a.flagCount, len(a.flow.Log), a.bannerTitle)
	}
	if a.quotes == nil || len(a.symHist["ECHO"].v) != 30 {
		t.Errorf("the feed itself keeps flowing")
	}
}

func TestWinLossTile(t *testing.T) {
	a := demoApp(t, 120, 30)
	text := func() string { return plain(a) }
	if !strings.Contains(text(), "3/1 & 75%") {
		t.Fatalf("demo record: wins/losses & rate")
	}
	closed, rate := 2, 40
	a.market.WinLoss = &WinLoss{Wins: 1, Losses: 3, Closed: &closed, RatePct: &rate}
	if !strings.Contains(text(), "1/3 & 40%") {
		t.Errorf("record 1/3")
	}
	sp := a.winLossSpans()
	if sp[0].FG != a.th.Good || sp[2].FG != a.th.Bad || sp[len(sp)-1].FG != a.th.Bad {
		t.Errorf("colours: losses ahead means the rate is red: %+v", sp)
	}
	a.market.WinLoss = &WinLoss{Wins: 3, Losses: 1, Closed: &closed, RatePct: &rate}
	if sp = a.winLossSpans(); sp[len(sp)-1].FG != a.th.Good {
		t.Errorf("wins ahead means the rate is green")
	}
	a.market.WinLoss = nil
	if !strings.Contains(text(), "NO CLOSED SIGNAL RIGHT NOW") {
		t.Errorf("no record yet")
	}
	zero := 0
	a.market.WinLoss = &WinLoss{Wins: 0, Losses: 0, Closed: &zero}
	if !strings.Contains(text(), "NO CLOSED SIGNAL RIGHT NOW") {
		t.Errorf("zero closed")
	}
}

// Owner order 2026-11-09: buying, selling and unclear stay three separate
// numbers on the telemetry row. A side is never printed as a combined figure
// and U never joins either of them.
func TestTelemetryKeepsBuyingSellingAndUnclearApart(t *testing.T) {
	a := newTestApp(t)
	a.w, a.h = 120, 30
	a.link, a.checking = true, false
	a.market = marketIn("OPEN")
	a.cfg.BigBuy, a.cfg.BigSell = true, true
	a.now = time.Date(2026, 11, 2, 10, 0, 0, 0, pkt)
	if a.flow == nil {
		a.flow = NewFlow(defaultFlowCfg(10_000_000))
	}
	a.flow.sym["AAA"] = &symFlow{evts: []flowEvt{
		{t: a.now.Add(-10 * time.Second), dv: 600, px: 10, side: 1},
		{t: a.now.Add(-9 * time.Second), dv: 300, px: 10, side: -1},
		{t: a.now.Add(-8 * time.Second), dv: 100, px: 10, side: 0},
	}}
	flowRow := ""
	for _, row := range rowsOf(a) {
		// The navigation line says `3 ORDER FLOW`; the telemetry label is the
		// bare `FLOW`, so the two are never confused.
		if strings.Contains(row, "FLOW") && !strings.Contains(row, "ORDER FLOW") {
			flowRow = row
		}
	}
	if flowRow == "" {
		t.Fatal("the telemetry FLOW row is missing")
	}
	// Owner order 2026-11-11 (tenth pass): the row reads B=..., S=... & U=...,
	// three separate figures with the sum never written. The ampersand joins U
	// to the list, it does not add the sides together.
	for _, want := range []string{"B=600", "S=300", "& U=100"} {
		if !strings.Contains(flowRow, want) {
			t.Errorf("the FLOW row is missing %q: %q", want, flowRow)
		}
	}
}

func TestTelemetryTellsTheTruthAboutScanning(t *testing.T) {
	a := newTestApp(t)
	a.w, a.h = 120, 30
	a.link, a.checking = true, false
	a.market = marketIn("CLOSED")
	if w, _ := a.scanStatus(); w != "EVERY SECOND" {
		t.Errorf("10:00 on a Monday: %q", w)
	}
	a.now = time.Date(2026, 11, 7, 11, 0, 0, 0, pkt) // Saturday
	if w, _ := a.scanStatus(); w != "OFF AT THE WEEKEND" {
		t.Errorf("Saturday: %q", w)
	}
	// The weekend names itself even when the relay also reports the day closed.
	a.market.TradingDay = false
	if w, _ := a.scanStatus(); w != "OFF AT THE WEEKEND" {
		t.Errorf("Saturday, closed day: %q", w)
	}
	// Owner order 2026-11-09: a weekday the exchange has closed says so.
	a.market = marketIn("CLOSED")
	a.market.TradingDay = false
	a.now = time.Date(2026, 11, 9, 11, 0, 0, 0, pkt) // Iqbal Day, a Monday holiday
	if w, _ := a.scanStatus(); w != "MARKET IS CLOSED TODAY" {
		t.Errorf("closed trading day: %q", w)
	}
	a.market = marketIn("CLOSED")
	// The row above the foot is the navigation, and says nothing about polling.
	// The last row is the first build's scrolling ticker.
	a.now = time.Date(2026, 11, 2, 10, 0, 0, 0, pkt)
	last := rowsOf(a)[a.h-1]
	for _, bad := range []string{"30S", "IDLE", "EVERY 1S", "16:45"} {
		if strings.Contains(last, bad) {
			t.Errorf("footer still says %q: %q", bad, last)
		}
	}
	if !strings.Contains(last, "HOME") {
		t.Errorf("last row is not the navigation: %q", last)
	}
}

func TestSnapshotAlertStateShowsBanner(t *testing.T) {
	a := demoApp(t, 120, 30)
	snapshotState(a, "alert")
	if !strings.Contains(rowsOf(a)[1], "is getting big buying orders") {
		t.Errorf("alert snapshot: %q", rowsOf(a)[1])
	}
}
