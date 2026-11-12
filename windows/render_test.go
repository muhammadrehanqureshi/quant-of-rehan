package main

import (
	"bytes"
	"fmt"
	"regexp"
	"strings"
	"testing"
	"time"
)

func demoApp(t *testing.T, w, h int) *App {
	t.Helper()
	a := newTestApp(t)
	a.w, a.h, a.animT = w, h, 3.2
	a.cfg.PollMS = 1000
	a.enableDemo(time.Date(2026, 10, 30, 11, 42, 18, 0, pkt))
	return a
}

var ansiRe = regexp.MustCompile("\x1b\\[[0-9;]*m")

// Every screen, in every state and theme and at many sizes, must draw inside
// its canvas without panicking and without stray control characters.
func TestRenderSweep(t *testing.T) {
	sizes := [][2]int{{1, 1}, {10, 3}, {79, 25}, {80, 25}, {80, 26}, {99, 30}, {100, 30}, {100, 26}, {120, 30}, {160, 45}, {240, 70}}
	states := []string{"", "closed", "checking", "fault", "alert"}
	for _, sz := range sizes {
		for _, st := range states {
			for scr := 0; scr < len(screenNames); scr++ {
				for th := range themes {
					a := demoApp(t, sz[0], sz[1])
					a.cfg.Theme = th
					a.th = themeAt(th)
					a.screen = screenID(scr)
					if scr == 2 {
						a.searchText = "A"
					}
					if scr == 1 {
						a.scanChoice = 1 + th%2
					}
					snapshotState(a, st)
					a.showRaw = th%3 == 2
					name := fmt.Sprintf("%dx%d state=%q screen=%d theme=%d", sz[0], sz[1], st, scr, th)
					func() {
						defer func() {
							if r := recover(); r != nil {
								t.Fatalf("%s panicked: %v", name, r)
							}
						}()
						c := a.render()
						if c.W != sz[0] || c.H != sz[1] || len(c.Cells) != sz[0]*sz[1] {
							t.Fatalf("%s: canvas %dx%d", name, c.W, c.H)
						}
						for y, row := range c.PlainRows() {
							for _, r := range row {
								if r < 0x20 || r == 0x7f {
									t.Fatalf("%s: control rune %U on row %d", name, r, y)
								}
							}
						}
					}()
				}
			}
		}
	}
}

func TestTooSmallMessage(t *testing.T) {
	a := demoApp(t, 70, 20)
	rows := strings.Join(a.render().PlainRows(), "\n")
	if !strings.Contains(rows, "TERMINAL TOO SMALL: need 80x26, have 70x20") {
		t.Errorf("missing size message:\n%s", rows)
	}
}

func plain(a *App) string { return strings.Join(a.render().PlainRows(), "\n") }

func TestScreensShowTheAppsText(t *testing.T) {
	a := demoApp(t, 120, 30)
	home := plain(a)
	for _, want := range []string{
		"GREETING", "Good morning, Mr. Rehan!", "QUANT STATUS", "ONLINE", "LATEST SIGNAL", "ALFA", "42.94",
		"KSE100 INDEX & THE TOP 3 SCRIPS OF VOLUME", "KSE100  166,4", "B=", "S=", "T=",
		"QUANT CORE", "TELEMETRY", "DEMO DATA", "FRI 30 OCT 2026 11:42:18 UTC+5",
		"1 HOME", "2 ALERTS", "3 ORDER FLOW", "4 SCANNER", "5 SETTINGS",
		"SYMBOL", "ENTRY TIME", "ENTRY PRICE", "TAKE PROFIT", "STOP LOSS",
		"W/L & W/L RATE", "3/1 & 75%", "BUYING NOW",
	} {
		if !strings.Contains(home, want) {
			t.Errorf("home is missing %q", want)
		}
	}
	a.screen = scrScanner
	a.scanChoice = 2
	scan := plain(a)
	for _, want := range []string{"CUSTOM SCRIPS OF VOLUME", "PRICES RISING FAST", "MORE BUYERS & LESS SELLERS", "MORE SELLERS & LESS BUYERS", "ALMOST NO VOLUME AT ALL",       "SCRIPS WITH LOWER LOCK", "SCRIPS WITH UPPER LOCK", "SECTORS"} {
		if !strings.Contains(scan, want) {
			t.Errorf("scanner is missing %q", want)
		}
	}
	// The list is the live table ranked by the app's own rule, in that order.
	checkOrder := func(name string, ranked []string, text string) {
		if len(ranked) < 3 {
			t.Fatalf("%s: only %d ranked", name, len(ranked))
		}
		pos := func(sym string) int { return strings.Index(text, ". "+sym) }
		if !(pos(ranked[0]) >= 0 && pos(ranked[0]) < pos(ranked[1]) && pos(ranked[1]) < pos(ranked[2])) {
			t.Errorf("%s: %v not shown in that order: %d %d %d", name, ranked[:3], pos(ranked[0]), pos(ranked[1]), pos(ranked[2]))
		}
	}
	checkOrder("buyers over sellers", rankedSplitSymbols(a.scanTable()), scan)
	a.scanChoice = 1
	scan = plain(a)
	checkOrder("rising fast", rankedSpeedSymbols(a.scanTable()), scan)
	if strings.Contains(scan, "BIG BUYING & SELLING NOW (LIVE FLOW)") {
		t.Errorf("the flow sort is still on the scanner:\n%s", scan)
	}
	a.screen = scrSettings
	set := plain(a)
	for _, want := range []string{"RELAY STATUS", "NOTIFICATIONS", "JARVIS CYAN", "PURPLE & YELLOW", "BLACK & WHITE",
		"NAVY BLUE & WHITE", "VERSION", appVersionLabel, "REQUESTS TODAY",
		"The requests reset at 05:00 PKT.",
		"Every second from 09:00 until the post-market closes.",
		"That is at 15:49 from Monday to Thursday and at 16:49 on Friday.",
		"BIG BUYING FLAG", "BIG SELLING FLAG", "SOUND", "BIG ORDER SIZE", "TEST BUYING ALERT", "TEST SELLING ALERT"} {
		if !strings.Contains(set, want) {
			t.Errorf("settings is missing %q", want)
		}
	}
	factsAt := strings.Index(set, "BUILD VERSION & RELAY")
	if factsAt < 0 {
		t.Errorf("the settings page has no facts tile")
	} else {
		rest := set[factsAt+len("BUILD VERSION & RELAY"):]
		v, r := strings.Index(rest, "VERSION"), strings.Index(rest, "RELAY")
		if v < 0 || r < 0 || v > r {
			t.Errorf("VERSION must come before RELAY in the facts tile:\n%s", set)
		}
	}
}

func TestClosedAndFaultWording(t *testing.T) {
	a := demoApp(t, 120, 30)
	snapshotState(a, "closed")
	s := plain(a)
	for _, want := range []string{"OFFLINE", "NO SIGNAL AVAILABLE RIGHT NOW", "Scan blocked: WARMING UP", "Volume leaders unavailable right now.", "Market is closed and the quant is sleeping now."} {
		if !strings.Contains(s, want) {
			t.Errorf("closed is missing %q", want)
		}
	}
	a = demoApp(t, 120, 30)
	snapshotState(a, "fault")
	s = plain(a)
	for _, want := range []string{"No route to the relay from this PC", "(UnknownHost)", "STALE 47s", "Signal unavailable", "UNREACHABLE"} {
		if !strings.Contains(s, want) {
			t.Errorf("fault is missing %q", want)
		}
	}
	a = demoApp(t, 120, 30)
	snapshotState(a, "checking")
	s = plain(a)
	for _, want := range []string{"CHECKING", "Checking the system.", "KSE100: waiting for the broker feed."} {
		if !strings.Contains(s, want) {
			t.Errorf("checking is missing %q", want)
		}
	}
	if strings.Contains(s, "STALE") {
		t.Errorf("nothing is stale before the first answer")
	}
}

func TestDifferentDaySignalIsHidden(t *testing.T) {
	a := demoApp(t, 120, 30)
	a.signals = "QUANT OF REHAN 10:00 PKT 2026-10-29\nSymbol: OLDX\nEntry price: 9.99\nTarget: 10.19\nStop Loss: 9.89"
	s := plain(a)
	if strings.Contains(s, "OLDX") || strings.Contains(s, "9.99") || !strings.Contains(s, "NO SIGNAL AVAILABLE RIGHT NOW") {
		t.Errorf("yesterday's card must show as no signal, with none of its prices:\n%s", s)
	}
	if !strings.Contains(s, "dated 2026-10-29, not 2026-10-30") {
		t.Errorf("the screen should say why:\n%s", s)
	}
	a.showRaw = true
	if s := plain(a); !strings.Contains(s, "OLDX") {
		t.Errorf("raw view shows the relay text as sent")
	}
}

func TestSearchDetailShowsBuySellTotal(t *testing.T) {
	a := demoApp(t, 120, 30)
	a.screen = scrScanner
	for _, c := range "alf" {
		a.onKey(Key{Kind: KRune, R: c})
	}
	a.onKey(Key{Kind: KEnter})
	s := plain(a)
	for _, want := range []string{"ALFA", "PKR", "3,410,000", "1,250,000", "4,660,000"} {
		if !strings.Contains(s, want) {
			t.Errorf("stock detail is missing %q:\n%s", want, s)
		}
	}
}

func TestRowDiffOutput(t *testing.T) {
	a := demoApp(t, 100, 30)
	var first, second bytes.Buffer
	a.draw(&first)
	a.draw(&second)
	if !strings.Contains(first.String(), escAltOn[:0]+escClear) {
		t.Errorf("first frame must clear the screen")
	}
	moves := regexp.MustCompile("\x1b\\[[0-9]+;[0-9]+H").FindAllString(second.String(), -1)
	if len(moves) != 0 {
		t.Errorf("an unchanged frame must send no rows, sent %d", len(moves))
	}
	a.animT = 3.6
	var third bytes.Buffer
	a.draw(&third)
	moves = regexp.MustCompile("\x1b\\[[0-9]+;[0-9]+H").FindAllString(third.String(), -1)
	if len(moves) == 0 || len(moves) >= 30 {
		t.Errorf("an animated frame should resend some rows but not all: %d", len(moves))
	}
	if !strings.HasPrefix(third.String(), escSyncOn) || !strings.HasSuffix(third.String(), escSyncOff) {
		t.Errorf("frames are wrapped in synchronized output")
	}
	a.w, a.h = 120, 30
	var resized bytes.Buffer
	a.draw(&resized)
	if !strings.Contains(resized.String(), escClear) {
		t.Errorf("a resize must clear the screen")
	}
	// Plain text of a drawn row must match the canvas, colours aside.
	if got := ansiRe.ReplaceAllString(a.render().Row(0), ""); runeLen(got) != 120 {
		t.Errorf("row width %d", runeLen(got))
	}
}

func TestOrbStaysInsideItsBox(t *testing.T) {
	th := themeAt(0)
	for _, mode := range []OrbMode{OrbBurning, OrbParked, OrbChecking, OrbFault} {
		c := NewCanvas(40, 20, th.BG)
		drawOrb(c, 5, 3, 20, 10, 1.7, mode, true, th)
		lit := 0
		for y := 0; y < c.H; y++ {
			for x := 0; x < c.W; x++ {
				inside := x >= 5 && x < 25 && y >= 3 && y < 13
				ce := c.Cells[y*c.W+x]
				if ce.Ch != ' ' {
					lit++
					if !inside {
						t.Fatalf("mode %d drew outside its box at %d,%d", mode, x, y)
					}
				}
			}
		}
		if lit < 25 {
			t.Errorf("mode %d drew almost nothing: %d cells", mode, lit)
		}
	}
	drawOrb(NewCanvas(4, 3, th.BG), 0, 0, 4, 3, 0, OrbBurning, true, th) // too small: must not panic
}

func TestSourceHasNoEmOrEnDashes(t *testing.T) {
	// The owner's style rule: no long dashes anywhere in what this program says.
	for _, s := range []string{usage, textMarketOpen, textMarketBreak, textMarketClosed, signalNone, unavailable} {
		if strings.ContainsAny(s, "\u2014\u2013") {
			t.Errorf("long dash in %q", s)
		}
	}
	for scr := 0; scr < len(screenNames); scr++ {
		a := demoApp(t, 120, 30)
		a.screen = screenID(scr)
		if strings.ContainsAny(plain(a), "\u2014\u2013") {
			t.Errorf("long dash on screen %d", scr)
		}
	}
}

func TestSentenceAddsFullStops(t *testing.T) {
	for in, want := range map[string]string{
		"Stock ABC is getting big buying orders": "Stock ABC is getting big buying orders.",
		"Already a sentence.":                    "Already a sentence.",
		"Really?":                                "Really?",
		"  spaced  ":                             "spaced.",
		"":                                       "",
	} {
		if got := sentence(in); got != want {
			t.Errorf("sentence(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestAlertBannerReadsAsSentences(t *testing.T) {
	a := demoApp(t, 140, 34)
	snapshotState(a, "alert")
	row := a.render().PlainRows()[1]
	if !strings.Contains(row, "big buying orders. A block buy") {
		t.Errorf("banner should read as two sentences: %q", row)
	}
}

func TestDemoNextEventFollowsTheSessionLaw(t *testing.T) {
	a := demoApp(t, 120, 30) // Friday 11:42
	if got := friendlyNext(a.head.NextEvent); got != "Closes Fri 30 Oct, 12:00" {
		t.Errorf("friday morning demo: %q", got)
	}
	for _, c := range []struct {
		at   time.Time
		want string
	}{
		{time.Date(2026, 10, 30, 14, 40, 0, 0, pkt), "16:49"},
		{time.Date(2026, 11, 2, 10, 0, 0, 0, pkt), "15:49"},
	} {
		if got := demoSessionEnd(c.at); got != c.want {
			t.Errorf("%v: %s, want %s", c.at, got, c.want)
		}
	}
}

// Owner order 2026-11-07: the next event is the scanner going live at 09:00,
// not the exchange's 09:32 opening bell. The relay's date is kept, so a holiday
// is still the relay's holiday.
func TestFriendlyNextShowsTheScanStart(t *testing.T) {
	if got := friendlyNext("OPEN 2026-11-10 09:32"); got != "Tue 10 Nov, 09:00" {
		t.Errorf("next open: %q", got)
	}
	if got := friendlyNext("CLOSE 2026-11-10 15:30"); got != "Closes Tue 10 Nov, 15:49" {
		t.Errorf("next close: %q", got)
	}
}

// Owner order 2026-11-07: the tab numbers and TAB are green, D and R are green,
// ESC is yellow, Q and CTRL+C are red, and every coloured key is bold.
func TestFooterKeysAreColoured(t *testing.T) {
	a := demoApp(t, 122, 30)
	a.screen = scrScanner
	c := a.render()
	check := func(c *Canvas, text string, want RGB, last bool) {
		t.Helper()
		row := c.PlainRows()[c.H-1]
		i := strings.Index(row, text)
		if last {
			i = strings.LastIndex(row, text)
		}
		if i < 0 {
			t.Fatalf("%q is not in the footer: %q", text, row)
		}
		ce := c.Cells[(c.H-1)*c.W+i]
		if ce.FG != want || !ce.Bold {
			t.Errorf("%s is %v (bold %v), want %v and bold", text, ce.FG, ce.Bold, want)
		}
	}
	check(c, "1 HOME", a.th.Good, false)
	check(c, "TAB", a.th.Good, false)
	check(c, "ESC", a.th.Warn, false)
	check(c, "CTRL+C", a.th.Bad, false)
	a.screen = scrHome
	c = a.render()
	check(c, "1 HOME", a.th.Good, false)
	check(c, "D DETAILS", a.th.Good, false)
	check(c, "R REFRESH", a.th.Good, false)
	check(c, "Q QUIT", a.th.Bad, false)
}

func TestAlertLogDetailIsWrappedNotCut(t *testing.T) {
	a := demoApp(t, 130, 34)
	a.screen = scrAlerts
	snapshotState(a, "alert")
	s := plain(a)
	if strings.Contains(s, "…") {
		t.Errorf("nothing on the alerts screen should be cut with an ellipsis:\n%s", s)
	}
	if !strings.Contains(s, "today.") {
		t.Errorf("the end of the first detail should show:\n%s", s)
	}
}

func TestSettingsDescriptionsAreNotCut(t *testing.T) {
	a := demoApp(t, 130, 34)
	a.screen = scrSettings
	s := plain(a)
	for _, want := range []string{"Windows pop-ups and the banner.", "Alerts you when buyers dominate.", "a minute.", "Plays the buying tone and a test pop-up.", "Alerts you when sellers dominate."} {
		if !strings.Contains(s, want) {
			t.Errorf("settings text is cut: missing %q", want)
		}
	}
}
