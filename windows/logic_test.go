package main

import (
	"os"
	"regexp"
	"strings"
	"testing"
	"time"
)

func TestFormatHelpers(t *testing.T) {
	cases := []struct{ got, want string }{
		{commaInt(0), "0"},
		{commaInt(999), "999"},
		{commaInt(1000), "1,000"},
		{commaInt(1234567), "1,234,567"},
		{commaInt(-1234567), "-1,234,567"},
		{commaFloat(166409.25, 2), "166,409.25"},
		{commaFloat(-766.52, 2), "-766.52"},
		{commaFloat(0, 2), "0.00"},
		{commaFloat(-0.001, 2), "0.00"},
		{changeText(2.314), "▲ 2.31%"},
		{changeText(-0.456), "▼ 0.46%"},
		{indexLine(166426.91, -766.52, -0.4584), "KSE100  166,426.91 ▼ 766.52 (0.46%)"},
		{indexLine(100, 1.5, 1.5), "KSE100  100.00 ▲ 1.50 (1.50%)"},
	}
	for i, c := range cases {
		if c.got != c.want {
			t.Errorf("case %d: got %q want %q", i, c.got, c.want)
		}
	}
}

func TestFitAndWrap(t *testing.T) {
	if got := fit("abcdef", 4); got != "abc…" {
		t.Errorf("fit: %q", got)
	}
	if got := fit("abc", 4); got != "abc" {
		t.Errorf("fit short: %q", got)
	}
	if got := fit("abc", 0); got != "" {
		t.Errorf("fit zero: %q", got)
	}
	for _, w := range []int{4, 7, 20, 40} {
		for _, ln := range wrap("Scan blocked: WARMING UP. 299 of 317 symbols captured (94.3%). averyveryverylongwordthatmustbecut", w) {
			if runeLen(ln) > w {
				t.Errorf("wrap width %d produced %d runes: %q", w, runeLen(ln), ln)
			}
		}
	}
}

func TestGreetingBoundaries(t *testing.T) {
	night := "You have a wonderful night, Mr. Rehan!"
	cases := []struct {
		h, m int
		want string
	}{
		{0, 0, night}, {4, 59, night}, {5, 0, night}, {5, 1, "Good morning, Mr. Rehan!"},
		{11, 59, "Good morning, Mr. Rehan!"}, {12, 0, "Good morning, Mr. Rehan!"},
		{12, 1, "Good afternoon, sir!"}, {16, 59, "Good afternoon, sir!"}, {17, 0, "Good afternoon, sir!"},
		{17, 1, "Good evening, sir!"}, {18, 59, "Good evening, sir!"}, {19, 0, "Good evening, sir!"},
		{19, 1, night}, {23, 59, night},
	}
	for _, c := range cases {
		if got := greetingFor(c.h, c.m); got != c.want {
			t.Errorf("%02d:%02d got %q want %q", c.h, c.m, got, c.want)
		}
	}
}

func TestSignalParsing(t *testing.T) {
	labelled := "QUANT OF REHAN 10:00 PKT 2026-10-30\nSymbol: ALFA\nEntry price: 42.10\nTarget: 42.94 (+2%)\nStop Loss: 41.68"
	f := parseSignal(labelled)
	if f.State != "trade" || f.Symbol != "ALFA" || f.Entry != "42.10" || f.Exit != "42.94" || f.Stop != "41.68" {
		t.Errorf("labelled: %+v", f)
	}

	inline := "QUANT OF REHAN 10:00 PKT 2026-10-30\nENGRO entered at 285.50, target 291.21, stop loss 279.79"
	f = parseSignal(inline)
	if f.State != "trade" || f.Symbol != "ENGRO" || f.Entry != "285.50" || f.Exit != "291.21" || f.Stop != "279.79" {
		t.Errorf("inline: %+v", f)
	}

	partial := "Header\nEntry price: 10.5\nStop Loss: null"
	f = parseSignal(partial)
	if f.State != "trade" || f.Entry != "10.5" || f.Exit != notReported || f.Stop != notReported {
		t.Errorf("partial: %+v", f)
	}

	if f = parseSignal(""); f.State != "unavailable" {
		t.Errorf("empty: %+v", f)
	}
	if f = parseSignal("Signals could not load just now."); f.State != "unavailable" {
		t.Errorf("failure text: %+v", f)
	}
	if f = parseSignal("QUANT OF REHAN 2026-10-30\nNO TRADE today"); f.State != "none" {
		t.Errorf("no trade: %+v", f)
	}
	// Exit reference and Exit price variants, case insensitive labels.
	f = parseSignal("h\nentry price: 1\nexit reference: 2\nsl: 0.5")
	if f.Entry != "1" || f.Exit != "2" || f.Stop != "0.5" {
		t.Errorf("variants: %+v", f)
	}
	// A target that is not a number must not become the exit.
	f = parseSignal("h\nEntry price: 1\nTarget: soon")
	if f.Exit != notReported {
		t.Errorf("bad target: %+v", f)
	}
}

func TestLatestSignalDisplay(t *testing.T) {
	trade := "QUANT OF REHAN 10:00 PKT 2026-10-30\nSymbol: ALFA\nEntry price: 42.10\nTarget: 42.94\nStop Loss: 41.68"
	if got := latestSignalDisplay(trade, "2026-10-30"); !strings.Contains(got, "Entry Price: 42.10") || !strings.HasPrefix(got, "ALFA\n") {
		t.Errorf("same day: %q", got)
	}
	// The phone treats a card from another day as no signal.
	if got := latestSignalDisplay(trade, "2026-10-31"); got != signalNone {
		t.Errorf("other day: %q", got)
	}
	// No relay date known yet: show the card.
	if got := latestSignalDisplay(trade, ""); got == signalNone {
		t.Errorf("no relay date should still show the card")
	}
	// The real relay text of 2026-10-31 (market closed, scan warming up).
	warm := "QUANT OF REHAN 10:00 PKT 2026-10-30\nScan blocked: WARMING UP. 299 of 317 symbols captured (94.3%). None of them holds the 20 bars the strategy needs yet. No trade issued; the bar source is still filling, not broken. Scan resumes on its own in about 279 minutes."
	if got := latestSignalDisplay(warm, "2026-10-30"); got != signalNone {
		t.Errorf("warming up: %q", got)
	}
	if got := latestSignalDisplay("", "2026-10-30"); got != unavailable {
		t.Errorf("empty: %q", got)
	}
}

func TestIsTradeSignalAndBody(t *testing.T) {
	yes := []string{"Symbol: ALFA\nEntry price: 1", "ENGRO entered at 285"}
	no := []string{"", "NO TRADE today", "No signal today", "no call", "Scan said NO SIGNAL AVAILABLE for now", "Scan blocked"}
	for _, s := range yes {
		if !isTradeSignal(s) {
			t.Errorf("should be a trade: %q", s)
		}
	}
	for _, s := range no {
		if isTradeSignal(s) {
			t.Errorf("should not be a trade: %q", s)
		}
	}
	if got := signalBody("header line\nbody one\nbody two "); got != "body one\nbody two" {
		t.Errorf("signalBody: %q", got)
	}
	if got := signalBody("only header"); got != "only header" {
		t.Errorf("signalBody single line: %q", got)
	}
}

func TestMarketEventMapping(t *testing.T) {
	cases := map[string]string{
		"OPEN": "online", "BREAK": "break", "CLOSED": "offline", "POST_CLOSE": "offline",
		"WARMUP": "", "PRE_OPEN": "", "": "",
	}
	for phase, want := range cases {
		m := NewMarket()
		m.Phase = phase
		if got := marketEvent(m); got != want {
			t.Errorf("phase %q: got %q want %q", phase, got, want)
		}
	}
	if marketEvent(nil) != "" {
		t.Error("nil market should raise nothing")
	}
}

func f64(v float64) *float64 { return &v }
func i64(v int64) *int64     { return &v }

func TestRanking(t *testing.T) {
	q := map[string]Quote{
		"AAA": {Price: 10, ChangePct: f64(1.5)},
		"BBB": {Price: 10, ChangePct: f64(3.2)},
		"CCC": {Price: 10, ChangePct: f64(4.9)},  // capped print, excluded
		"DDD": {Price: 10, ChangePct: f64(4.89)}, // just under the mark
		"EEE": {Price: 10, ChangePct: f64(-2)},
		"FFF": {Price: 10, ChangePct: f64(0)},
		"GGG": {Price: 10, ChangePct: f64(3.2)}, // ties with BBB, symbol order
		"HHH": {Price: 10},
	}
	got := rankedSpeedSymbols(q)
	want := []string{"DDD", "BBB", "GGG"}
	if strings.Join(got, ",") != strings.Join(want, ",") {
		t.Errorf("speed: got %v want %v", got, want)
	}

	s := map[string]Quote{
		"AAA": {Buy: i64(900), Sell: i64(100)},   // gap 800
		"BBB": {Buy: i64(5000), Sell: i64(4900)}, // gap 100
		"CCC": {Buy: i64(100), Sell: i64(900)},   // sellers win, excluded
		"DDD": {Buy: i64(300)},                   // one side missing, excluded
		"EEE": {Buy: i64(2000), Sell: i64(1200)}, // gap 800, ties with AAA
		"FFF": {Buy: i64(700), Sell: i64(700)},   // equal, excluded
		"GGG": {Buy: i64(1000), Sell: i64(10)},   // gap 990
	}
	got = rankedSplitSymbols(s)
	want = []string{"GGG", "AAA", "EEE"}
	if strings.Join(got, ",") != strings.Join(want, ",") {
		t.Errorf("split: got %v want %v", got, want)
	}
	if len(rankedSpeedSymbols(nil)) != 0 || len(rankedSplitSymbols(nil)) != 0 {
		t.Error("nil table should rank nothing")
	}

	// Owner order 2026-11-12: the four volume sorts CUSTOM SCRIPS OF VOLUME
	// adds. Each names three scrips, each is decided by volume, and a scrip is
	// at its lock when its move reaches the app's capped move mark.
	v := map[string]Quote{
		"AAA": {Price: 10, ChangePct: f64(-5.2), Buy: i64(100), Sell: i64(900)}, // lower lock, heaviest
		"BBB": {Price: 10, ChangePct: f64(5.4), Buy: i64(800), Sell: i64(200)},  // upper lock, heaviest
		"CCC": {Price: 10, ChangePct: f64(-4.9), Buy: i64(50), Sell: i64(50)},   // lower lock
		"DDD": {Price: 10, ChangePct: f64(4.9), Buy: i64(10), Sell: i64(10)},    // upper lock
		"EEE": {Price: 10, ChangePct: f64(1.0), Buy: i64(300), Sell: i64(700)},  // sellers ahead
		"FFF": {Price: 10, ChangePct: f64(2.0), Buy: i64(5), Sell: i64(5)},      // quietest
	}
	for _, c := range []struct {
		name string
		got  []string
		want []string
	}{
		{"more sellers", rankedSellerSymbols(v), []string{"AAA", "EEE"}},
		{"almost no volume", rankedQuietSymbols(v), []string{"FFF", "DDD", "CCC"}},
		{"lower lock", rankedLowerLockSymbols(v), []string{"AAA", "CCC"}},
		{"upper lock", rankedUpperLockSymbols(v), []string{"BBB", "DDD"}},
	} {
		if strings.Join(c.got, ",") != strings.Join(c.want, ",") {
			t.Errorf("%s: got %v want %v", c.name, c.got, c.want)
		}
	}
	if len(rankedSellerSymbols(nil)) != 0 || len(rankedQuietSymbols(nil)) != 0 ||
		len(rankedLowerLockSymbols(nil)) != 0 || len(rankedUpperLockSymbols(nil)) != 0 {
		t.Error("nil table should rank nothing")
	}
}

func TestPhaseLine(t *testing.T) {
	mk := func(phase, cond, text string) *Market {
		m := NewMarket()
		m.Phase, m.Condition, m.ConditionText = phase, cond, text
		return m
	}
	cases := []struct {
		m    *Market
		want string
	}{
		{nil, "Market status not reported by the relay yet."},
		{NewMarket(), "Market status not reported by the relay yet."},
		{mk("OPEN", "OPERATIONAL", ""), ""},
		{mk("OPEN", "", ""), ""},
		{mk("BREAK", "BREAK", ""), "Market is on a break right now. Quant is offline."},
		{mk("BREAK", "BREAK", "Back at 15:30"), "Back at 15:30"},
		{mk("CLOSED", "CLOSED", ""), "Market is closed right now."},
		{mk("CLOSED", "CLOSED", "Closed until Monday"), "Closed until Monday"},
		{mk("POST_CLOSE", "", ""), "Market is closed right now."},
	}
	for i, c := range cases {
		if got := phaseLine(c.m); got != c.want {
			t.Errorf("case %d: got %q want %q", i, got, c.want)
		}
	}
	h := mk("OPEN", "OPERATIONAL", "")
	h.FeedHalted, h.FeedStatusFresh = true, true
	if got := phaseLine(h); !strings.Contains(got, "halted") {
		t.Errorf("halted: %q", got)
	}
}

// Owner report 2026-11-10: the change arrow reached the Windows notification
// as "\u00d4\u00fb\u2593" because powershell.exe reads its input as the system code page.
// The toast text is plain ASCII now, and the arrow becomes a signed number.
func TestToastTextIsPlainASCII(t *testing.T) {
	s := toastScript("SAZEW is getting big buying orders",
		"Price 1,490.00, \u25b2 5.82% today. \u25c6")
	for _, r := range s {
		if r > 127 {
			t.Fatalf("the toast script carries %q (U+%04X), which powershell.exe cannot read", r, r)
		}
	}
	if !strings.Contains(s, "+5.82% today") {
		t.Fatalf("the rising change did not become a plus: %q", s)
	}
}

func TestToastScriptIsInjectionSafe(t *testing.T) {
	evil := `x'); Start-Process calc; ('` + "\n" + `"</text><script>` + "\x00"
	s := toastScript("title '", evil)
	// The only single quotes allowed are the ones the script itself writes.
	// LoadXml(' ... ') must contain none from the relay text.
	start := strings.Index(s, "LoadXml('")
	end := strings.Index(s[start:], "')\r\n")
	if start < 0 || end < 0 {
		t.Fatalf("script shape changed: %q", s)
	}
	xmlPart := s[start+len("LoadXml('") : start+end]
	if strings.Contains(xmlPart, "'") {
		t.Errorf("single quote survived in the XML text: %q", xmlPart)
	}
	if strings.Contains(xmlPart, "<script>") {
		t.Errorf("markup survived: %q", xmlPart)
	}
}

func TestSettingsRoundTripAndClamp(t *testing.T) {
	dir := t.TempDir()
	p := dir + "/sub/settings.json"
	s := defaultSettings()
	s.Theme, s.Notify, s.PollMS, s.LastSignal, s.LastMarketEvent = 3, false, 4000, "body", "online"
	if err := saveSettings(p, s); err != nil {
		t.Fatal(err)
	}
	got := loadSettings(p)
	if got.Theme != 3 || got.Notify || got.PollMS != 4000 || got.LastSignal != "body" || got.LastMarketEvent != "online" {
		t.Errorf("round trip: %+v", got)
	}
	bad := Settings{Theme: 99, PollMS: 10}
	_ = saveSettings(p, bad)
	got = loadSettings(p)
	if got.Theme != 0 || got.PollMS != 1000 {
		t.Errorf("clamp: %+v", got)
	}
	_ = saveSettings(p, Settings{Ver: settingsVer, Theme: 1, PollMS: 999999})
	if got = loadSettings(p); got.PollMS != 60000 {
		t.Errorf("clamp high: %+v", got)
	}
	if got = loadSettings(dir + "/missing.json"); got.PollMS != 1000 || !got.Notify || !got.BigBuy || !got.Sound || got.BigBuyValue != 10_000_000 {
		t.Errorf("defaults: %+v", got)
	}
}

// A settings file from build 1 holds the old two second poll and none of the
// big buying fields. It must come up at the new one second pace with the
// flag and the tone on, and keep what the user chose, such as the theme.
func TestSettingsFromBuildOneAreMigrated(t *testing.T) {
	p := t.TempDir() + "/settings.json"
	old := `{"theme": 3, "relay_url": "", "notify": false, "poll_ms": 2000, "last_signal": "x"}`
	if err := os.WriteFile(p, []byte(old), 0o600); err != nil {
		t.Fatal(err)
	}
	got := loadSettings(p)
	if got.PollMS != 1000 || !got.BigBuy || !got.Sound || got.BigBuyValue != 10_000_000 || got.Ver != settingsVer {
		t.Errorf("not migrated: %+v", got)
	}
	if got.Theme != 3 || got.Notify || got.LastSignal != "x" {
		t.Errorf("a choice was lost: %+v", got)
	}
}

// ---------- app logic ----------

func newTestApp(t *testing.T) *App {
	t.Helper()
	cfg := defaultSettings()
	cfg.Notify = false // never spawn PowerShell or notify-send from tests
	a := NewApp(cfg, t.TempDir()+"/settings.json", NewRelay("http://127.0.0.1:1"))
	a.now = time.Date(2026, 11, 2, 10, 0, 0, 0, pkt)
	return a
}

func marketIn(phase string) *Market {
	m := NewMarket()
	m.Answered, m.Phase, m.Open = true, phase, phase == "OPEN"
	return m
}

func TestBeatMarketEventsDedupe(t *testing.T) {
	a := newTestApp(t)
	a.market = marketIn("CLOSED")
	a.beat()
	if a.cfg.LastMarketEvent != "offline" || a.bannerTitle != "" {
		t.Fatalf("first event is only a baseline: %q banner %q", a.cfg.LastMarketEvent, a.bannerTitle)
	}
	a.market = marketIn("WARMUP") // no event for warm up
	a.beat()
	if a.bannerTitle != "" || a.cfg.LastMarketEvent != "offline" {
		t.Fatalf("warm up must stay silent")
	}
	a.market = marketIn("OPEN")
	a.beat()
	if a.bannerTitle != textMarketOpen || a.cfg.LastMarketEvent != "online" || (!toneNative && !a.bell) {
		t.Fatalf("open should alert once: %q %q", a.bannerTitle, a.cfg.LastMarketEvent)
	}
	a.bannerTitle, a.bell = "", false
	a.beat() // same phase again
	if a.bannerTitle != "" || a.bell {
		t.Fatalf("repeat of the same phase must not alert")
	}
	a.market = marketIn("BREAK")
	a.beat()
	if a.bannerTitle != textMarketBreak {
		t.Fatalf("break: %q", a.bannerTitle)
	}
	a.market = marketIn("POST_CLOSE")
	a.beat()
	if a.bannerTitle != "" {
		t.Fatalf("the post-market must be silent: %q", a.bannerTitle)
	}
	if a.cfg.LastMarketEvent != "offline" {
		t.Fatalf("the post-market still updates the baseline: %q", a.cfg.LastMarketEvent)
	}
}

func TestBeatSignalDedupe(t *testing.T) {
	a := newTestApp(t)
	a.market = marketIn("OPEN")
	a.cfg.LastMarketEvent = "online"
	a.signals = "QUANT OF REHAN 10:00 PKT 2026-11-02\nSymbol: ALFA\nEntry price: 42.10\nTarget: 42.94\nStop Loss: 41.68"
	a.signalsOK = true
	a.beat()
	if a.bannerTitle != "Quant of Rehan signal" || !strings.Contains(a.bannerBody, "ALFA") {
		t.Fatalf("new signal should alert: %q %q", a.bannerTitle, a.bannerBody)
	}
	a.bannerTitle, a.bell = "", false
	a.beat()
	if a.bannerTitle != "" {
		t.Fatalf("same signal must not alert twice")
	}
	a.signals = "QUANT OF REHAN 10:05 PKT 2026-11-02\nSymbol: BRVO\nEntry price: 118.55\nTarget: 120.92\nStop Loss: 117.36"
	a.beat()
	if !strings.Contains(a.bannerBody, "BRVO") {
		t.Fatalf("a different signal should alert")
	}
	// A failed fetch (ok=false) never alerts, whatever the text says.
	a.bannerTitle = ""
	a.signals = "Symbol: ZZZZ\nEntry price: 1"
	a.signalsOK = false
	a.beat()
	if a.bannerTitle != "" {
		t.Fatalf("failed fetch must not alert")
	}
	// No-trade text never alerts.
	a.signalsOK = true
	a.signals = "QUANT OF REHAN 2026-11-02\nNO TRADE today"
	a.beat()
	if a.bannerTitle != "" {
		t.Fatalf("no trade must not alert")
	}
}

func TestBeatIsSilentInDemo(t *testing.T) {
	a := newTestApp(t)
	a.demo = true
	a.market = marketIn("OPEN")
	a.beat()
	if a.cfg.LastMarketEvent != "" || a.bannerTitle != "" {
		t.Fatal("demo data must never touch real notification state")
	}
}

func TestScanWindow(t *testing.T) {
	at := func(day, h, m, sec int) time.Time { return time.Date(2026, 11, day, h, m, sec, 0, pkt) }
	// 2026-11-02 is a Monday, 11-06 a Friday, 11-07 a Saturday, 11-08 a Sunday.
	cases := []struct {
		t    time.Time
		want bool
	}{
		// Owner order 2026-11-12: Monday to Thursday the window is 08:55 to 15:49,
		// and Friday's is 08:55 to 16:49.
		{at(2, 8, 54, 59), false}, {at(2, 8, 55, 0), true}, {at(2, 9, 0, 0), true}, {at(2, 9, 20, 0), true}, {at(2, 12, 0, 0), true},
		{at(2, 15, 31, 0), true}, {at(2, 15, 48, 59), true}, {at(2, 15, 49, 0), true},
		// The window closes at 15:49 and the grace period catches the final
		// print, so 15:49:29 still scans and 15:49:30 does not.
		{at(2, 15, 49, 29), true}, {at(2, 15, 49, 30), false}, {at(2, 16, 0, 0), false},
		{at(2, 23, 0, 0), false},
		// Friday: the same start, an hour later at the end.
		{at(6, 8, 54, 59), false}, {at(6, 8, 55, 0), true}, {at(6, 9, 0, 0), true}, {at(6, 13, 0, 0), true},
		{at(6, 16, 48, 59), true}, {at(6, 16, 49, 0), true}, {at(6, 16, 49, 29), true}, {at(6, 16, 49, 30), false},
		{at(6, 17, 0, 0), false},
		// The weekend is never scanned.
		{at(7, 11, 0, 0), false}, {at(8, 11, 0, 0), false},
	}
	for _, c := range cases {
		if got := inScanWindow(c.t); got != c.want {
			t.Errorf("%v: got %v want %v", c.t.Format("Mon 15:04:05"), got, c.want)
		}
	}
}

func TestSessionNamesFollowThePSXLaw(t *testing.T) {
	at := func(day, h, m int) time.Time { return time.Date(2026, 11, day, h, m, 0, 0, pkt) }
	cases := []struct {
		t    time.Time
		want string
	}{
		{at(2, 8, 30), sesClosed}, {at(2, 9, 5), sesPre}, {at(2, 9, 20), sesBetween}, {at(2, 9, 31), sesBetween},
		{at(2, 9, 32), sesTrading}, {at(2, 15, 29), sesTrading}, {at(2, 15, 30), sesBetween}, {at(2, 15, 32), sesPost},
		{at(2, 15, 48), sesPost}, {at(2, 15, 49), sesClosed}, {at(2, 16, 0), sesClosed},
		{at(6, 9, 10), sesPre}, {at(6, 9, 17), sesTrading}, {at(6, 11, 59), sesTrading}, {at(6, 12, 0), sesBreak},
		{at(6, 14, 31), sesBreak}, {at(6, 14, 32), sesTrading}, {at(6, 16, 29), sesTrading}, {at(6, 16, 32), sesPost},
		{at(6, 16, 48), sesPost}, {at(6, 16, 49), sesClosed}, {at(6, 17, 0), sesClosed}, {at(7, 11, 0), sesClosed},
	}
	for _, c := range cases {
		if got := sessionAt(c.t); got != c.want {
			t.Errorf("%v: got %q want %q", c.t.Format("Mon 15:04"), got, c.want)
		}
	}
	// Trades happen only inside the trading bands.
	for _, c := range []struct {
		t    time.Time
		want bool
	}{{at(2, 9, 31), false}, {at(2, 9, 32), true}, {at(2, 15, 30), false}, {at(6, 12, 30), false}, {at(6, 15, 0), true}, {at(7, 10, 0), false}} {
		if got := inTradingBand(c.t); got != c.want {
			t.Errorf("trading band %v: got %v", c.t.Format("Mon 15:04"), got)
		}
	}
}

func TestFirstScanOfTheDayIsOnTime(t *testing.T) {
	a := newTestApp(t)
	a.market = marketIn("CLOSED")
	// Ten seconds before 08:55 the slow check must not sleep past the start.
	a.now = time.Date(2026, 11, 2, 8, 54, 50, 0, pkt)
	for _, n := range []string{"quotes", "market", "signals", "health"} {
		if got := a.interval(n); got != 10*time.Second {
			t.Errorf("%s at 08:54:50: %v, want 10s", n, got)
		}
	}
	// Friday evening: the next start is Monday 08:55, so the check stays slow.
	a.now = time.Date(2026, 11, 6, 20, 0, 0, 0, pkt)
	if got := a.interval("quotes"); got != 30*time.Second {
		t.Errorf("Friday evening: %v", got)
	}
	if u := untilScanStart(a.now); u != 60*time.Hour+55*time.Minute {
		t.Errorf("until Monday 08:55 from Friday 20:00: %v", u)
	}
}

// The quotes are read every second whenever the market is in its scanning
// window, which covers the pre-market, the session, the Friday break and the
// post-market, and only slow down outside it.
func TestEverySecondInTheScanWindow(t *testing.T) {
	a := newTestApp(t) // Monday 10:00 PKT
	if a.cfg.PollMS != 1000 {
		t.Fatalf("default poll is %d ms, want 1000", a.cfg.PollMS)
	}
	for _, ph := range []string{"OPEN", "WARMUP", "BREAK", "CLOSED", ""} {
		a.market = marketIn(ph)
		if ph == "" {
			a.market = nil
		}
		if got := a.interval("quotes"); got != time.Second {
			t.Errorf("phase %q at 10:00: quotes every %v, want 1s", ph, got)
		}
	}
	for _, clock := range []time.Time{
		time.Date(2026, 11, 2, 9, 10, 0, 0, pkt),  // pre-market
		time.Date(2026, 11, 2, 15, 40, 0, 0, pkt), // post-market, Monday
		time.Date(2026, 11, 6, 16, 40, 0, 0, pkt), // post-market, Friday
		time.Date(2026, 11, 6, 13, 0, 0, 0, pkt),  // Friday midday break
	} {
		a.now = clock
		a.market = marketIn("CLOSED") // the relay's label for pre and post
		if got := a.interval("quotes"); got != time.Second {
			t.Errorf("%s: quotes every %v, want 1s", clock.Format("Mon 15:04"), got)
		}
	}
	// Outside the window, and at the weekend, the check is slow.
	for _, clock := range []time.Time{time.Date(2026, 11, 2, 22, 0, 0, 0, pkt), time.Date(2026, 11, 2, 16, 10, 0, 0, pkt), time.Date(2026, 11, 7, 11, 0, 0, 0, pkt)} {
		a.now = clock
		a.market = marketIn("CLOSED")
		for _, n := range []string{"quotes", "market", "signals", "health"} {
			if got := a.interval(n); got != 30*time.Second {
				t.Errorf("%s idle %s: %v, want 30s", clock.Format("Mon 15:04"), n, got)
			}
		}
	}
	// A holiday the relay knows about stays slow even inside the window.
	a.now = time.Date(2026, 11, 2, 11, 0, 0, 0, pkt)
	a.market = marketIn("CLOSED")
	a.market.TradingDay = false
	if got := a.interval("quotes"); got != 30*time.Second {
		t.Errorf("holiday: %v", got)
	}
}

func TestAdaptivePolling(t *testing.T) {
	a := newTestApp(t)
	a.market = marketIn("OPEN")
	want := map[string]time.Duration{
		"market": 5 * time.Second, "quotes": time.Second, "signals": 5 * time.Second,
		"health": 15 * time.Second, "prices": 2 * time.Second,
	}
	for k, v := range want {
		if got := a.interval(k); got != v {
			t.Errorf("open %s: got %v want %v", k, got, v)
		}
	}
	// Failures back off but never beyond a minute.
	a.fails["market"] = 1
	if got := a.interval("market"); got != 5*time.Second {
		t.Errorf("1 failure: %v", got)
	}
	a.fails["quotes"] = 1
	if got := a.interval("quotes"); got != 4*time.Second {
		t.Errorf("1 failure: %v", got)
	}
	a.fails["quotes"] = 40
	if got := a.interval("quotes"); got != 60*time.Second {
		t.Errorf("many failures: %v", got)
	}
	// A slower poll setting is respected, and the signals pace follows it.
	a.fails = map[string]int{}
	a.cfg.PollMS = 10000
	if got := a.interval("signals"); got != 50*time.Second {
		t.Errorf("slow signals: %v", got)
	}
}

// TestDailyBudget adds up the requests a full day of the default pace would
// use against the free Cloudflare allowance of 100,000 a day. The scanning
// window runs from 08:55 to 30 seconds after the post-market closes: 15:49:30
// Monday to Thursday and 16:49:30 on Friday (owner order 2026-11-12). The
// console is assumed open for
// all 24 hours, with the Scanner or Search screen (the extra prices call) open
// for the whole of it.
func TestDailyBudget(t *testing.T) {
	a := newTestApp(t)
	total := func(scan bool, seconds float64, extra bool) float64 {
		if scan {
			a.now = time.Date(2026, 11, 2, 11, 0, 0, 0, pkt)
		} else {
			a.now = time.Date(2026, 11, 2, 22, 0, 0, 0, pkt)
		}
		a.market = marketIn("CLOSED")
		names := []string{"market", "health", "signals", "quotes"}
		if extra {
			names = append(names, "prices")
		}
		var n float64
		for _, k := range names {
			n += seconds / a.interval(k).Seconds()
		}
		return n
	}
	for _, day := range []struct {
		name   string
		window float64
		cap    float64
	}{
		{"Monday to Thursday", float64(6*3600 + 54*60 + 30), 65000},
		{"Friday", float64(7*3600 + 54*60 + 30), 70000},
	} {
		idle := 24*3600 - day.window
		home := total(true, day.window, false) + total(false, idle, false)
		worst := total(true, day.window, true) + total(false, idle, true)
		t.Logf("%s: requests per day: home screen %.0f, scanner open all day %.0f (free cap 100000)", day.name, home, worst)
		if worst > day.cap {
			t.Errorf("%s: the default pace is too close to the free cap: %.0f", day.name, worst)
		}
		if worst > reqHardCap {
			t.Errorf("%s: a measured day must stay under the hard stop of %d: %.0f",
				day.name, reqHardCap, worst)
		}
	}
	a.now = time.Date(2026, 11, 2, 11, 0, 0, 0, pkt)
	if got := 7.8 * 3600 / a.interval("quotes").Seconds(); got != 7.8*3600 {
		// one quotes call every second for the whole window
		t.Errorf("quotes are not every second: %.0f", got)
	}
}

// TestRequestBudgetIsAHardStop proves the console stops itself below the free
// Cloudflare allowance instead of discovering that limit as a relay outage.
// Owner order 2026-11-09: the day's allowance is never exhausted.
func TestRequestBudgetIsAHardStop(t *testing.T) {
	a := newTestApp(t)
	if reqHardCap >= 100000 {
		t.Fatalf("the hard stop must leave headroom under 100,000: %d", reqHardCap)
	}
	set := func(want int64) {
		a.reqBase = want + a.reqOffset - a.relay.Requests()
		if got := a.reqToday(); got != want {
			t.Fatalf("count is %d, want %d", got, want)
		}
	}
	set(reqHardCap - 1)
	if !a.budgetOpen() {
		t.Fatalf("one request left must still be allowed: %d", a.reqToday())
	}
	set(reqHardCap)
	if a.budgetOpen() {
		t.Fatalf("the cap must be closed: %d", a.reqToday())
	}
	a.inflight = map[string]bool{}
	a.fetch("quotes")
	if a.inflight["quotes"] {
		t.Fatal("a request left the console after the cap was reached")
	}
	a.fetchStock("PRL")
	if a.selectedSt != "" {
		t.Fatalf("the stock fetch must be refused at the cap too: %q", a.selectedSt)
	}
}

func TestKeyNavigation(t *testing.T) {
	a := newTestApp(t)
	press := func(k Key) { a.onKey(k) }
	r := func(c rune) Key { return Key{Kind: KRune, R: c} }

	// The five tabs, in the owner's order.
	want := []string{"HOME", "ALERTS", "ORDER FLOW", "SCANNER", "SETTINGS"}
	if len(screenNames) != len(want) {
		t.Fatalf("tabs: %v", screenNames)
	}
	for i, n := range want {
		if screenNames[i] != n {
			t.Fatalf("tab %d is %q, want %q", i+1, screenNames[i], n)
		}
	}
	press(Key{Kind: KTab})
	if a.screen != scrAlerts {
		t.Fatalf("tab: %v", a.screen)
	}
	press(Key{Kind: KTab, Shift: true})
	press(Key{Kind: KTab, Shift: true})
	if a.screen != scrSettings {
		t.Fatalf("shift tab wraps: %v", a.screen)
	}
	press(Key{Kind: KF3})
	if a.screen != scrOrderFlow {
		t.Fatalf("F3 is order flow: %v", a.screen)
	}
	press(Key{Kind: KF4})
	if a.screen != scrScanner {
		t.Fatalf("F4 is the scanner: %v", a.screen)
	}
	press(Key{Kind: KF5})
	if a.screen != scrSettings {
		t.Fatalf("F5 is settings: %v", a.screen)
	}
	press(Key{Kind: KF4})
	// In the scanner, q is search text, not quit.
	press(r('q'))
	press(r('a'))
	if a.quit || a.searchText != "QA" {
		t.Fatalf("search typing: quit=%v text=%q", a.quit, a.searchText)
	}
	press(Key{Kind: KBackspace})
	if a.searchText != "Q" {
		t.Fatalf("backspace: %q", a.searchText)
	}
	press(Key{Kind: KEsc})
	if a.searchText != "" || a.screen != scrScanner {
		t.Fatalf("first esc clears: %q %v", a.searchText, a.screen)
	}
	press(Key{Kind: KEsc})
	if a.screen != scrHome {
		t.Fatalf("second esc goes home: %v", a.screen)
	}
	// Long input is capped, odd characters are ignored.
	a.setScreen(scrScanner)
	for _, c := range "abcdefghijklmnopqrstuvwxyz" {
		press(r(c))
	}
	press(r('!'))
	press(r(' '))
	if runeLen(a.searchText) != 12 {
		t.Fatalf("cap: %q", a.searchText)
	}
	a.clearSearch()
	press(Key{Kind: KDown})
	press(Key{Kind: KEnter})
	if a.scanChoice != 2 {
		t.Fatalf("scanner choice: %d", a.scanChoice)
	}
	press(Key{Kind: KBackspace})
	if a.scanChoice != 0 {
		t.Fatalf("scanner clear: %d", a.scanChoice)
	}
	// With an empty box a digit still jumps to its tab.
	press(r('3'))
	if a.screen != scrOrderFlow {
		t.Fatalf("3 is order flow: %v", a.screen)
	}
	press(r('o'))
	if a.ofSort != 1 {
		t.Fatalf("o steps the order: %d", a.ofSort)
	}
	press(r('2'))
	if a.screen != scrAlerts {
		t.Fatalf("2 is alerts: %v", a.screen)
	}
	press(Key{Kind: KF5})
	if a.screen != scrSettings {
		t.Fatalf("F5 is settings: %v", a.screen)
	}
	for i := 0; i < settingsItems; i++ {
		press(Key{Kind: KDown})
	}
	press(Key{Kind: KEnter}) // the first theme row
	if a.cfg.Theme != 0 {
		t.Fatalf("theme: %d", a.cfg.Theme)
	}
	press(Key{Kind: KDown})
	press(Key{Kind: KEnter}) // the second theme
	if a.cfg.Theme != 1 || a.th != themeAt(1) {
		t.Fatalf("theme: %d", a.cfg.Theme)
	}
	for i := 0; i < settingsItems; i++ {
		press(Key{Kind: KUp})
	}
	press(Key{Kind: KEnter}) // row 1 toggles notifications
	if !a.cfg.Notify {
		t.Fatalf("notify toggle: %v", a.cfg.Notify)
	}
	for i := 0; i < 20; i++ {
		press(Key{Kind: KDown})
	}
	if a.setCursor != settingsRows-1 {
		t.Fatalf("cursor must stop on the last row: %d", a.setCursor)
	}
	press(r('d')) // not on home: ignored
	if a.showRaw {
		t.Fatalf("d only works on home")
	}
	press(r('1'))
	press(r('d'))
	if !a.showRaw {
		t.Fatalf("d on home")
	}
	press(r('q'))
	if !a.quit {
		t.Fatalf("q quits outside the scanner")
	}
	b := newTestApp(t)
	b.onKey(Key{Kind: KCtrlC})
	if !b.quit {
		t.Fatalf("ctrl+c")
	}
	c := newTestApp(t)
	c.setScreen(scrScanner)
	c.onKey(Key{Kind: KCtrlC})
	if !c.quit {
		t.Fatalf("ctrl+c in the scanner")
	}
}

func TestSearchMatching(t *testing.T) {
	a := newTestApp(t)
	a.prices = map[string]Quote{"ENGRO": {Price: 1}, "EFERT": {Price: 1}, "ENGROH": {Price: 1}, "LUCK": {Price: 1}}
	a.quotes = &Quotes{Items: map[string]LiveQuote{"EPCL": {}, "ENGRO": {}}}
	a.rebuildSymbols()
	a.searchText = "e"
	got := strings.Join(a.matches(), ",")
	if got != "EFERT,ENGRO,ENGROH,EPCL" {
		t.Errorf("prefix matches (sorted, union of both sources): %s", got)
	}
	a.searchText = "  "
	if len(a.matches()) != 0 {
		t.Errorf("blank text matches nothing")
	}
	for i := 0; i < 20; i++ {
		a.prices["X"+string(rune('A'+i))] = Quote{Price: 1}
	}
	a.rebuildSymbols()
	a.searchText = "X"
	if len(a.matches()) != 8 {
		t.Errorf("at most 8 matches, got %d", len(a.matches()))
	}
}

func TestEffectiveFeedPrefersFreshQuotes(t *testing.T) {
	a := newTestApp(t)
	m := marketIn("OPEN")
	v, ch, pct := 100.0, 1.0, 1.0
	m.IndexValue, m.IndexChange, m.IndexPct, m.IndexSource = &v, &ch, &pct, "relay"
	p, c := 10.0, 1.0
	m.Leaders = []Leader{{Symbol: "AAA", Price: &p, ChangePct: &c}, {Symbol: "BBB", Price: &p, ChangePct: &c}}
	a.market = m
	if val, _, _, _, src, ok := a.effectiveIndex(); !ok || val != 100 || src != idxCard {
		t.Fatalf("relay index: %v %q %v", val, src, ok)
	}
	nc := 2.5
	a.quotes = &Quotes{
		Index: &IndexQuote{Value: 200, Change: 5, ChangePct: 2.5, AsOf: "t", Fresh: true},
		Items: map[string]LiveQuote{"AAA": {Price: 11, ChangePct: &nc, Fresh: true}, "BBB": {Price: 12, Fresh: false}},
	}
	if val, _, _, _, src, _ := a.effectiveIndex(); val != 200 || src != idxLive {
		t.Fatalf("fresh broker index should win: %v %q", val, src)
	}
	l := a.effectiveLeaders()
	if *l[0].Price != 11 || *l[0].ChangePct != 2.5 {
		t.Errorf("fresh quote overlays: %v %v", *l[0].Price, *l[0].ChangePct)
	}
	if *l[1].Price != 10 {
		t.Errorf("stale quote must not overlay: %v", *l[1].Price)
	}
	if *a.market.Leaders[0].Price != 10 {
		t.Errorf("overlay must not mutate the relay data")
	}
}

func TestRequestCounterRollsOverAtUTCMidnight(t *testing.T) {
	a := newTestApp(t)
	a.now = time.Date(2026, 11, 2, 23, 59, 0, 0, time.UTC)
	a.cfg.ReqDay = "2026-11-02"
	a.reqBase = 500
	a.relay.reqs.Add(30)
	a.syncReqCount()
	if a.reqToday() != 530 {
		t.Fatalf("same day: %d", a.reqToday())
	}
	a.now = time.Date(2026, 11, 3, 0, 0, 5, 0, time.UTC)
	a.syncReqCount()
	if a.cfg.ReqDay != "2026-11-03" || a.reqToday() != 0 {
		t.Fatalf("new day starts at zero: day=%s count=%d", a.cfg.ReqDay, a.reqToday())
	}
	a.relay.reqs.Add(7)
	a.syncReqCount()
	if a.reqToday() != 7 || a.cfg.ReqCount != 7 {
		t.Fatalf("new day counts from the rollover: %d / %d", a.reqToday(), a.cfg.ReqCount)
	}
}

func TestHostileTextCannotReachTheTerminal(t *testing.T) {
	c := NewCanvas(60, 3, RGB{})
	hostile := "ok\x1b]0;pwned\x07\x1b[2J\x1b]52;c;ZXZpbA==\x07\u202eevil\u200b\u009b31m"
	c.Text(0, 0, 60, hostile, RGB{255, 255, 255}, false)
	c.Put(0, 1, '\x1b', RGB{}, false)
	c.Set(1, 1, '\a', RGB{}, RGB{}, false)
	for y := 0; y < c.H; y++ {
		// Strip the colour codes this program writes itself, then look for any
		// control character that is left.
		line := c.Row(y)
		line = regexp.MustCompile("\x1b\\[[0-9;]*m").ReplaceAllString(line, "")
		for _, r := range line {
			if r < 0x20 || r == 0x7f || (r >= 0x80 && r <= 0x9f) || r == 0x202e || r == 0x200b {
				t.Fatalf("row %d still holds control rune %U: %q", y, r, line)
			}
		}
	}
	if !strings.HasPrefix(c.PlainRows()[0], "ok·]0;pwned·") {
		t.Errorf("hostile text should show as dots: %q", c.PlainRows()[0])
	}
}

func TestRelayURLValidation(t *testing.T) {
	good := []string{"https://quant-of-rehan-relay.mrmrehanqureshi.workers.dev", "http://127.0.0.1:8787", "https://x.test/path"}
	bad := []string{"", "file:///c:/windows/system32/calc.exe", "calc.exe", "javascript:alert(1)", "ftp://x.test", "https://user:pw@x.test", "https://", "//x.test"}
	for _, g := range good {
		if !validRelayURL(g) {
			t.Errorf("should accept %q", g)
		}
	}
	for _, b := range bad {
		if validRelayURL(b) {
			t.Errorf("should reject %q", b)
		}
	}
	if got := NewRelay("file:///etc/passwd").Base; got != defaultRelay {
		t.Errorf("bad address must fall back to the built in relay, got %q", got)
	}
	if got := NewRelay(" https://x.test/// ").Base; got != "https://x.test" {
		t.Errorf("trim: %q", got)
	}
}

func TestFlagsDoNotLeakIntoTheSettingsFile(t *testing.T) {
	dir := t.TempDir()
	path := dir + "/settings.json"
	file := defaultSettings()
	file.Theme, file.PollMS, file.Notify = 2, 3000, true
	_ = saveSettings(path, file)

	run := loadSettings(path)
	base := run
	run.RelayURL, run.PollMS, run.Notify, run.Theme = "http://127.0.0.1:9", 1000, false, 4 // as flags would
	a := NewApp(run, path, NewRelay(run.RelayURL))
	a.persist = base
	a.ephemeral = true
	a.cfg.LastSignal = "from the mock relay"
	a.save()
	got := loadSettings(path)
	if got.RelayURL != "" || got.PollMS != 3000 || !got.Notify || got.Theme != 2 || got.LastSignal != "" {
		t.Fatalf("flags leaked into the file: %+v", got)
	}
	// What the Settings screen changes does persist.
	a.screen = scrSettings
	a.setCursor = settingsItems + 1 // the second theme
	a.onKey(Key{Kind: KEnter})
	a.setCursor = 1
	a.onKey(Key{Kind: KEnter})
	a.setCursor = 4 // sound off
	a.onKey(Key{Kind: KEnter})
	a.setCursor = 3 // big selling flag off
	a.onKey(Key{Kind: KEnter})
	a.save()
	got = loadSettings(path)
	if got.Theme != 1 || got.Notify != true || got.Sound || !got.BigBuy || got.BigSell || got.RelayURL != "" || got.PollMS != 3000 {
		t.Fatalf("settings screen choices: %+v", got)
	}
}

func TestRadarRoundnessSetting(t *testing.T) {
	old := cellAspect
	defer func() { cellAspect = old }()
	dir := t.TempDir()
	path := dir + "/settings.json"
	cfg := loadSettings(path)
	if cfg.CellShape != 222 {
		t.Fatalf("default roundness: %d", cfg.CellShape)
	}
	a := NewApp(cfg, path, NewRelay(""))
	a.ephemeral = true
	// The ring is adjusted with ] and [ on the home screen, where it is drawn.
	a.screen = scrHome
	a.onKey(Key{Kind: KRune, R: ']'})
	if a.cfg.CellShape != 227 || cellAspect != 2.27 {
		t.Fatalf("] steps up: %d %v", a.cfg.CellShape, cellAspect)
	}
	for i := 0; i < 40; i++ {
		a.onKey(Key{Kind: KRune, R: ']'})
	}
	if a.cfg.CellShape != cellShapeMax {
		t.Fatalf("] stops at the tallest: %d", a.cfg.CellShape)
	}
	for i := 0; i < 60; i++ {
		a.onKey(Key{Kind: KRune, R: '['})
	}
	if a.cfg.CellShape != cellShapeMin {
		t.Fatalf("[ stops at the shortest: %d", a.cfg.CellShape)
	}
	// Where there is no ring the keys do nothing.
	a.screen = scrAlerts
	a.onKey(Key{Kind: KRune, R: ']'})
	if a.cfg.CellShape != cellShapeMin {
		t.Fatalf("] must do nothing on the alerts screen: %d", a.cfg.CellShape)
	}
	a.cfg.CellShape = 205
	a.cellTouched = true
	a.save()
	if got := loadSettings(path); got.CellShape != 205 {
		t.Fatalf("roundness must persist: %d", got.CellShape)
	}
	// A hand edited file cannot make the ring absurd.
	bad := defaultSettings()
	bad.CellShape = 9000
	_ = saveSettings(path, bad)
	if got := loadSettings(path); got.CellShape != cellShapeMax {
		t.Fatalf("clamped: %d", got.CellShape)
	}
}
