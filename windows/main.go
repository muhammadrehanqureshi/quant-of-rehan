package main

import (
	"flag"
	"fmt"
	"io"
	"os"
	"strconv"
	"strings"
	"time"
)

const usage = `Quant of Rehan for Windows, the console edition of the Android app (version ` + appVersion + `).

Keys:  1-6 or F1-F6 or TAB switch screens   R refresh   D signal details (Home)
       Q quit (Ctrl+C anywhere)
       Search: type, UP/DOWN, ENTER, ESC clears
Mouse: click tabs, rows and switches, wheel scrolls, right click goes Home
Sound and the two alert flags are changed only on SETTINGS.

Flags:
`

func main() {
	var (
		relayURL  = flag.String("relay", "", "relay address for this run only (the default is the relay built into the app)")
		theme     = flag.Int("theme", -1, "theme number, 0 to 5, for this run only (choose one in Settings to keep it)")
		pollMS    = flag.Int("poll", 0, "scan interval in milliseconds for this run, at least 1000 (the default is 1000)")
		noNotify  = flag.Bool("no-notify", false, "no Windows notifications for this run (Settings keeps your choice)")
		noSound   = flag.Bool("no-sound", false, "no alert tones for this run (Settings keeps your choice)")
		demo      = flag.Bool("demo", false, "run on invented demo data, clearly labelled as such")
		selftest  = flag.Bool("selftest", false, "check that every relay endpoint answers, then exit")
		feedwatch = flag.Int("feedwatch", 0, "watch the live feed for this many seconds (10 to 900), write qor-feedwatch.txt and say whether any lag is the broker's wire, a stall upstream, or the network")
		version   = flag.Bool("version", false, "print the version and exit")
		snapshot  = flag.String("snapshot", "", "render one frame as WxH to stdout and exit (implies --demo)")
		screen    = flag.Int("screen", 1, "with --snapshot: screen 1 home, 2 alerts, 3 order flow, 4 scanner, 5 charts, 6 settings")
		ansi      = flag.Bool("ansi", false, "with --snapshot: keep colour codes")
		at        = flag.Float64("t", 3.0, "with --snapshot: animation time in seconds")
		query     = flag.String("query", "", "with --snapshot: search text for the search screen")
		ticks     = flag.Int("ticks", 0, "with --snapshot: let the demo market run this many more seconds first")
		state     = flag.String("state", "", "with --snapshot: open (default), closed, checking, fault or alert")
		halfblock = flag.Bool("halfblock", false, "draw the ring with half blocks instead of quadrant blocks (only if the ring looks broken in your font)")
		cell      = flag.String("cell", "", "size of one terminal cell in pixels as WxH, for example 9x20 (the default shape is 2.22); only the dial's roundness uses it")
	)
	flag.Usage = func() {
		fmt.Fprint(os.Stderr, usage)
		flag.PrintDefaults()
	}
	flag.Parse()

	if *version {
		fmt.Printf("Quant of Rehan for Windows %s (build %s)\n", appVersion, hudBuild)
		return
	}

	ringHalfBlocks = *halfblock

	cellFromFlag := false
	if *cell != "" {
		cellFromFlag = true
		var cw, ch float64
		if n, err := fmt.Sscanf(*cell, "%fx%f", &cw, &ch); n != 2 || err != nil || cw < 4 || ch < 8 || ch/cw < 1.2 || ch/cw > 3.5 {
			fmt.Fprintln(os.Stderr, "-cell wants the size of one terminal cell in pixels, for example 9x20")
			os.Exit(2)
		}
		cellAspect = ch / cw
	}

	path := settingsPath()
	cfg := loadSettings(path)
	if !cellFromFlag {
		cellAspect = float64(cfg.CellShape) / 100
	}
	base := cfg // what the file holds; flags below change this run only
	if *relayURL != "" {
		if !validRelayURL(strings.TrimSpace(*relayURL)) {
			fmt.Fprintln(os.Stderr, "-relay must be an http:// or https:// address")
			os.Exit(2)
		}
		cfg.RelayURL = *relayURL
	}
	if *theme >= 0 && *theme < len(themes) {
		cfg.Theme = *theme
	}
	if *pollMS > 0 {
		cfg.PollMS = max(1000, min(*pollMS, 60000))
	}
	if *noNotify {
		cfg.Notify = false
	}
	if *noSound {
		cfg.Sound = false
	}
	if *selftest {
		os.Exit(selfTest(cfg.RelayURL))
	}
	if *feedwatch > 0 {
		os.Exit(feedWatch(cfg.RelayURL, *feedwatch, os.Stdout))
	}

	app := NewApp(cfg, path, NewRelay(cfg.RelayURL))
	app.persist = base
	app.ephemeral = NewRelay(cfg.RelayURL).Base != NewRelay(base.RelayURL).Base

	if *snapshot != "" {
		os.Exit(runSnapshot(app, *snapshot, *screen, *ansi, *at, *query, *state, *ticks, os.Stdout))
	}
	if *demo {
		app.enableDemo(time.Now())
	}

	t := newTerm()
	if err := app.run(t); err != nil {
		fmt.Fprintln(os.Stderr, "could not start the console UI:", err)
		os.Exit(1)
	}
}

// runSnapshot renders one frame of demo data without touching the terminal.
func runSnapshot(a *App, size string, screen int, withColour bool, t float64, query, state string, ticks int, out io.Writer) int {
	ws, hs, ok := strings.Cut(strings.ToLower(size), "x")
	w, e1 := strconv.Atoi(ws)
	h, e2 := strconv.Atoi(hs)
	if !ok || e1 != nil || e2 != nil || w < 1 || h < 1 {
		fmt.Fprintln(os.Stderr, "--snapshot wants WxH, for example 120x30")
		return 2
	}
	a.w, a.h = w, h
	a.animT = t
	a.cfg.PollMS = 1000
	a.enableDemo(time.Date(2026, 10, 30, 11, 42, 18, 0, pkt))
	for i := 1; i <= ticks; i++ {
		a.demoTick(a.now.Add(time.Second))
	}
	if screen >= 1 && screen <= len(screenNames) {
		a.screen = screenID(screen - 1)
	}
	if a.screen == scrCharts && query != "" {
		a.chartQuery = strings.ToUpper(strings.TrimSpace(query))
		if m := a.chartMatches(); len(m) > 0 {
			a.selectChart(m[0])
		}
	}
	if a.screen == scrScanner && query != "" {
		a.searchText = strings.ToUpper(query)
		// A symbol that is typed in full is also opened, as ENTER would.
		for _, m := range a.matches() {
			if m == a.searchText {
				a.pickSymbol(m)
			}
		}
	}
	snapshotState(a, state)
	c := a.render()
	if withColour {
		for y := 0; y < c.H; y++ {
			fmt.Fprint(out, c.Row(y), "\n")
		}
		return 0
	}
	for _, r := range c.PlainRows() {
		fmt.Fprintln(out, strings.TrimRight(r, " "))
	}
	return 0
}

// snapshotState bends the demo data into the other conditions the UI must
// show. The closed state uses the shape of the text the real relay sent on
// the night of 2026-10-31.
func snapshotState(a *App, state string) {
	switch state {
	case "closed":
		m := a.market
		m.Open, m.Phase, m.Condition = false, "CLOSED", "CLOSED"
		m.ConditionText, m.TradingDay = "Market is closed right now.", false
		m.Leaders = nil
		a.marketOpen = false
		a.head.MarketOpen = false
		a.head.Phase = m
		a.head.Detail = "Karachi: " + m.KarachiNow + "\nMarket is closed right now."
		a.signals = "QUANT OF REHAN 10:00 PKT 2026-10-30\nScan blocked: WARMING UP. 299 of 317 symbols captured (94.3%). None of them holds the 20 bars the strategy needs yet. No trade issued; the bar source is still filling, not broken. Scan resumes on its own in about 279 minutes."
		a.prices = map[string]Quote{}
		a.quotes = nil
		a.symbols = nil
	case "alert":
		if len(a.flow.Log) > 0 {
			a.flow.Log[len(a.flow.Log)-1].Time = a.now
			a.raiseFlag(a.flow.Log[len(a.flow.Log)-1])
		}
	case "checking":
		a.checking, a.link, a.market, a.head, a.signals = true, false, nil, nil, ""
		a.quotes = nil
		a.lastMarketOK = time.Time{}
	case "fault":
		a.checking, a.link, a.marketOpen = false, false, false
		a.lastMarketOK = a.now.Add(-47 * time.Second)
		a.relayErr = "No route to the relay from this PC. Check internet or VPN. (UnknownHost)"
		a.signals = ""
	}
}
