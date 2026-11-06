package main

import (
	"context"
	"io"
	"strings"
	"time"
)

type screenID int

// The tabs, in the order the owner asked for on 2026-11-05: Home, Alerts, Order
// Flow, Scanner (which carries the search tile on top) and Settings.
const (
	scrHome screenID = iota
	scrAlerts
	scrOrderFlow
	scrScanner
	scrSettings
)

var screenNames = []string{"HOME", "ALERTS", "ORDER FLOW", "SCANNER", "SETTINGS"}

// Messages posted from fetch goroutines to the single UI goroutine.
type (
	msgMarket struct {
		m   *Market
		rtt time.Duration
		err error
	}
	msgHealth struct {
		h   *Head
		rtt time.Duration
		err error
	}
	msgSignals struct {
		text string
		ok   bool
	}
	msgQuotes struct {
		q   *Quotes
		err error
	}
	msgPrices struct {
		p   map[string]Quote
		err error
	}
	msgStock struct {
		sym  string
		info *StockInfo
		err  error
	}
	msgOrderFlow struct {
		f   *OrderFlow
		err error
	}
	msgSectors struct {
		s   *Sectors
		err error
	}
)

// App holds all state. Only the UI goroutine touches it.
type App struct {
	cfg     Settings
	cfgPath string
	// persist holds what the settings file said at start. Command line flags
	// change cfg for this run only; save writes persist plus the few things
	// the Settings screen changed.
	persist       Settings
	ephemeral     bool // a flag pointed this run at another relay
	themeTouched  bool
	notifyTouched bool
	flowTouched   bool // big buying, sound or size changed in Settings
	cellTouched   bool // the radar roundness changed with [ or ]
	relay         *Relay
	th            *Theme

	w, h   int
	screen screenID
	start  time.Time
	now    time.Time
	animT  float64 // when >= 0 the animation clock is pinned (snapshots)

	// relay data
	checking     bool
	link         bool // the relay answered the latest health or market call
	marketOpen   bool
	head         *Head
	market       *Market
	signals      string
	signalsOK    bool
	quotes       *Quotes
	prices       map[string]Quote
	symbols      []string
	lastMarketOK time.Time
	rtt          time.Duration
	relayErr     string

	// scheduling
	inflight map[string]bool
	next     map[string]time.Time
	sentAt   map[string]time.Time
	fails    map[string]int
	msgs     chan any

	// live tape: flashes, charts, feed health and the big buying detector
	flow        *Flow
	lastVal     map[string]float64
	flashes     map[string]flash
	idxHist     series
	symHist     map[string]*series
	feedMinAge  int // seconds since the freshest stock ticked, at the answer
	feed        feedStats
	answers     []time.Time
	quoteCount  int64
	flagCount   int
	of          *OrderFlow // the latest /orderflow answer
	ofErr       string     // why the last read failed, for the screen
	ofSort      int        // which order the ORDER FLOW list is in
	sectors      *Sectors   // the latest /sectors answer
	sectorsErr   string     // why the last sector read failed, for the screen
	sectorChoice int        // which sector group the scanner tile shows
	lvSector     listView   // the scanner's sector drop down
	sectorY      int        // the sector tile's top row, for the wheel
	sectorH      int        // and its height
	sectorOpen   bool       // a tapped sector is open with its KMIALLSHR scrips
	lvSectorStk  listView   // the open sector's scrip list
	lvOF        listView   // the ORDER FLOW list
	bannerSell  bool       // the banner on show is a big selling flag
	lvScan      listView   // the scanner's list
	lvBoard     listView   // the Alerts screen's big buying list
	lvSell      listView   // the Alerts screen's big selling list
	lvLog       listView   // the Alerts screen's log
	alertFocus  int        // 0 big buying list, 1 big selling list, 2 the log
	focusNext   bool       // the next panel drawn is the focused one
	alertSplitX int        // the column where the selling list starts, for the wheel
	alertSplit  int        // the row where the log panel starts, for the wheel

	// mouse
	hits           []hit
	hoverX, hoverY int
	bannerKind     string

	// request accounting (Cloudflare counts per UTC day)
	reqBase   int64
	reqOffset int64

	// ui state
	scanCursor   int
	scanChoice   int // 0 none, 1 rising fast, 2 buyers over sellers
	searchText   string
	searchCursor int
	selectedSym  string
	selectedInfo *StockInfo
	selectedSt   string // "", "loading", "failed", "ok"
	setCursor    int
	showRaw      bool
	bannerTitle  string
	bannerBody   string
	bannerUntil  time.Time

	demo     bool
	sim      *demoSim
	demoLast int64
	quit     bool
	dirty    bool
	lastSave time.Time
	bell     bool

	prevRows []string
	prevW    int
	prevH    int
}

func NewApp(cfg Settings, cfgPath string, relay *Relay) *App {
	a := &App{
		cfg: cfg, cfgPath: cfgPath, relay: relay, persist: cfg,
		th: themeAt(cfg.Theme),
		w:  120, h: 30,
		start:    time.Now(),
		now:      time.Now(),
		animT:    -1,
		checking: true,
		inflight: map[string]bool{},
		next:     map[string]time.Time{},
		fails:    map[string]int{},
		sentAt:   map[string]time.Time{},
		msgs:     make(chan any, 64),
		lastVal:  map[string]float64{},
		flashes:  map[string]flash{},
		symHist:  map[string]*series{},
		hoverX:   -1, hoverY: -1,
		prices:     map[string]Quote{},
		scanCursor: 0,
	}
	a.flow = NewFlow(defaultFlowCfg(cfg.BigBuyValue))
	a.flow.Allow = a.inUniverse
	today := utcDay(a.now)
	if cfg.ReqDay == today {
		a.reqBase = cfg.ReqCount
	} else {
		a.cfg.ReqDay = today
	}
	return a
}

// ---------- derived state ----------

func (a *App) phase() string {
	if a.market != nil && a.market.PhaseKnown() {
		return a.market.Phase
	}
	if a.head != nil && a.head.Phase != nil && a.head.Phase.PhaseKnown() {
		return a.head.Phase.Phase
	}
	return ""
}

func (a *App) isLive() bool {
	p := a.phase()
	return p == "OPEN" || p == "WARMUP"
}

// karachiNow is the time everything on screen runs on. It is this PC's clock,
// unless the relay's own clock (read from the Date header of its answers)
// disagrees by more than two seconds, in which case the relay's clock wins, so
// a PC with a wrong clock still shows the real time in Karachi.
func (a *App) karachiNow() time.Time {
	if a.relay != nil {
		if sk := a.relay.ClockSkew(); sk > 2*time.Second || sk < -2*time.Second {
			return a.now.Add(sk)
		}
	}
	return a.now
}

// The parts of the quant's day, as the status tile words them.
const (
	qsOpen    = "OPEN"
	qsPre     = "PRE"
	qsPost    = "POST"
	qsBreak   = "BREAK"
	qsClosed  = "CLOSED"
	qsHalted  = "HALTED"
	qsUnknown = "UNKNOWN"
)

// quantPhase says which part of the PSX day it is. The relay decides whether
// the exchange is trading, on a break, halted, or off for the day. The
// pre-market and post-market, which the relay does not tell apart from the
// hours around them, come from the session law on Karachi's own clock.
func (a *App) quantPhase() string {
	switch {
	case a.demo:
		if a.marketOpen {
			return qsOpen
		}
		return qsClosed
	case a.market != nil && a.market.FeedHalted && a.market.FeedStatusFresh:
		return qsHalted
	case a.market != nil && a.market.PhaseKnown() && !a.market.TradingDay:
		return qsClosed
	case a.marketOpen:
		return qsOpen
	}
	switch a.phase() {
	case "OPEN", "WARMUP":
		return qsOpen
	case "BREAK":
		return qsBreak
	case "":
		return qsUnknown
	}
	return phaseAt(a.karachiNow())
}

// online is the quant's own state: online while the exchange is in its
// pre-market, trading or post-market, and offline otherwise, including when
// the relay cannot be reached.
func (a *App) online() bool {
	if !a.link {
		return false
	}
	switch a.quantPhase() {
	case qsOpen, qsPre, qsPost:
		return true
	}
	return false
}

func (a *App) reqToday() int64 { return a.reqBase + a.relay.Requests() - a.reqOffset }

func (a *App) relayDate() string {
	if a.market != nil {
		return a.market.Date
	}
	return ""
}

// statusNote is the sentence under the status pill. It changes with the part
// of the day, and the quant is offline whenever the market is not in its
// pre-market, trading or post-market.
func (a *App) statusNote() string {
	switch {
	case a.checking:
		return "Checking the system."
	case !a.link:
		if a.relayErr != "" {
			return a.relayErr
		}
		return "The relay did not answer in time. Will retry."
	}
	switch a.quantPhase() {
	case qsOpen:
		return "Market is open and the quant is online now."
	case qsPre:
		return "Pre-market is running and the quant is online now."
	case qsPost:
		return "Post-market is running and the quant is online now."
	case qsBreak:
		return "Market is on a break and the quant is offline now."
	case qsHalted:
		return "Market is halted and the quant is offline now."
	case qsUnknown:
		return "Market status not reported by the relay yet."
	}
	return "Market is closed and the quant is offline now."
}

// Where the index on screen came from.
const (
	idxLive = "live" // the broker feed, ticking now
	idxLast = "last" // the broker's own last tick, no longer ticking
	idxCard = "card" // the relay's market card, which can lag
)

// effectiveIndex prefers the broker feed: a fresh tick first, then the last
// tick the broker sent, and only then the relay's market card.
func (a *App) effectiveIndex() (v, ch, pct float64, asOf, src string, ok bool) {
	if a.quotes != nil && a.quotes.Index != nil {
		i := a.quotes.Index
		if i.Fresh {
			return i.Value, i.Change, i.ChangePct, i.AsOf, idxLive, true
		}
		return i.Value, i.Change, i.ChangePct, i.AsOf, idxLast, true
	}
	if a.market != nil && a.market.HasIndex() {
		m := a.market
		return *m.IndexValue, *m.IndexChange, *m.IndexPct, m.IndexAsOf, idxCard, true
	}
	return 0, 0, 0, "", "", false
}

// effectiveLeaders overlays fresh broker quotes onto the volume leaders.
func (a *App) effectiveLeaders() []Leader {
	if a.market == nil {
		return nil
	}
	out := make([]Leader, len(a.market.Leaders))
	copy(out, a.market.Leaders)
	if a.quotes == nil {
		return out
	}
	for i := range out {
		if q, ok := a.quotes.Items[out[i].Symbol]; ok && q.Fresh && q.Price > 0 {
			p := q.Price
			out[i].Price = &p
			if q.ChangePct != nil {
				c := *q.ChangePct
				out[i].ChangePct = &c
			}
			// Volume and the buy and sell split come from the same live tick, so
			// they move with the price. The split is the relay's own range
			// estimate, worked out on the live numbers, not order flow.
			if q.Volume > 0 {
				v := q.Volume
				out[i].Volume = &v
				if b, sl, ok := q.RangeSplit(); ok {
					out[i].Buy, out[i].Sell = &b, &sl
				}
			}
		}
	}
	return out
}

func (a *App) rebuildSymbols() {
	set := map[string]bool{}
	for s := range a.prices {
		set[s] = true
	}
	if a.quotes != nil {
		for s := range a.quotes.Items {
			set[s] = true
		}
	}
	a.symbols = sortedKeys(set)
}

func (a *App) matches() []string {
	q := strings.ToUpper(strings.TrimSpace(a.searchText))
	if q == "" {
		return nil
	}
	var out []string
	for _, s := range a.symbols {
		if strings.HasPrefix(s, q) {
			out = append(out, s)
			if len(out) == 8 {
				break
			}
		}
	}
	return out
}

// ---------- polling ----------

// scanning says whether the app should be reading the feed every second now:
// from 09:00 until the post-market closes, on a trading day. The relay's own
// phase wins while it says the market is trading or on a break, and a day the
// relay calls a non-trading day (a holiday) is never scanned, so it cannot
// burn the daily request quota.
func (a *App) scanning() bool {
	if a.demo {
		return true
	}
	if a.market != nil && a.market.PhaseKnown() && !a.market.TradingDay {
		return false
	}
	switch a.phase() {
	case "OPEN", "WARMUP", "BREAK":
		return true
	}
	return inScanWindow(a.karachiNow())
}

// trading says whether trades can be happening, which is when the big buying
// detector counts volume. It follows the relay's phase when there is one, and
// the PSX trading bands otherwise.
func (a *App) trading() bool {
	if a.demo {
		return true
	}
	if ph := a.phase(); ph != "" {
		return ph == "OPEN" || ph == "WARMUP"
	}
	return inTradingBand(a.karachiNow())
}

// inUniverse limits the flow detector to the KMIALL names once the relay has
// sent that table. Until then every symbol in the broker feed counts.
func (a *App) inUniverse(sym string) bool {
	if len(a.prices) == 0 {
		return true
	}
	_, ok := a.prices[sym]
	return ok
}

// idleEvery is how often the app checks the relay outside the scanning
// window. Nothing moves then, so it is slow, but it is never later than the
// start of the next window, so the first scan of the day is on time.
func (a *App) idleEvery() time.Duration {
	d := 30 * time.Second
	if u := untilScanStart(a.karachiNow()); u > 0 && u < d {
		d = max(u, time.Second)
	}
	return d
}

// interval says how long to wait before asking again. While the PSX day is in
// its scanning window the broker feed is read every second, which is what the
// phone app does while it is on screen. Outside the window the app waits, so
// a console left open overnight does not spend the free Cloudflare quota
// (100,000 requests a day, reset at 05:00 Karachi).
func (a *App) interval(name string) time.Duration {
	base := time.Duration(a.cfg.PollMS) * time.Millisecond
	scan := a.scanning()
	idle := a.idleEvery()
	var d time.Duration
	switch name {
	case "quotes":
		d = idle
		if scan {
			d = base
		}
	case "market":
		d = idle
		if scan {
			d = max(5*time.Second, base)
		}
	case "signals":
		d = idle
		if scan {
			d = max(5*time.Second, 5*base)
		}
	case "health":
		d = idle
		if scan {
			d = 15 * time.Second
		}
	case "prices":
		d = min(15*time.Second, idle)
		if scan {
			d = max(2*time.Second, 2*base)
		}
	case "orderflow":
		// The relay's snapshot is refreshed in bursts about every 24 seconds, so
		// asking more often than every 3 seconds only repeats an answer.
		d = min(15*time.Second, idle)
		if scan {
			d = max(3*time.Second, 3*base)
		}
	case "sectors":
		// The relay rebuilds this from the same membership list all day, so a
		// slow refresh is enough even while the feed is polled every second.
		d = min(10*time.Minute, idle)
		if scan {
			d = 5 * time.Minute
		}
	}
	if f := a.fails[name]; f > 0 {
		b := 2 * time.Second << min(f, 5)
		if b > 60*time.Second {
			b = 60 * time.Second
		}
		if b > d {
			d = b
		}
	}
	return d
}

func (a *App) refreshNow() {
	a.next = map[string]time.Time{}
	a.fails = map[string]int{}
}

func (a *App) fetch(name string) {
	a.inflight[name] = true
	a.sentAt[name] = a.now
	r := a.relay
	// The one second feed must not sit behind a stuck request: it gives up
	// after 4 seconds and the next ask goes out at once. Slower answers get
	// longer.
	limit := 25 * time.Second
	switch name {
	case "quotes":
		limit = 4 * time.Second
	case "health":
		limit = 8 * time.Second
	}
	go func() {
		ctx, cancel := context.WithTimeout(context.Background(), limit)
		defer cancel()
		switch name {
		case "market":
			m, rtt, err := r.FetchMarket(ctx)
			a.msgs <- msgMarket{m, rtt, err}
		case "health":
			h, rtt, err := r.FetchHead(ctx, phaseLine)
			a.msgs <- msgHealth{h, rtt, err}
		case "signals":
			t, ok := r.FetchSignals(ctx)
			a.msgs <- msgSignals{t, ok}
		case "quotes":
			q, err := r.FetchQuotes(ctx)
			a.msgs <- msgQuotes{q, err}
		case "prices":
			p, err := r.FetchPrices(ctx)
			a.msgs <- msgPrices{p, err}
		case "orderflow":
			f, err := r.FetchOrderFlow(ctx)
			a.msgs <- msgOrderFlow{f, err}
		case "sectors":
			s, err := r.FetchSectors(ctx)
			a.msgs <- msgSectors{s, err}
		}
	}()
}

func (a *App) fetchStock(sym string) {
	a.selectedSt = "loading"
	a.selectedInfo = nil
	r := a.relay
	go func() {
		ctx, cancel := context.WithTimeout(context.Background(), 25*time.Second)
		defer cancel()
		info, err := r.FetchStock(ctx, sym)
		a.msgs <- msgStock{sym, info, err}
	}()
}

func (a *App) done(name string, ok bool) {
	a.inflight[name] = false
	if ok {
		a.fails[name] = 0
	} else {
		a.fails[name]++
	}
	// The next ask is timed from when the last one left, so one second polling
	// is one second, not one second plus the round trip.
	at := a.sentAt[name].Add(a.interval(name))
	if at.Before(a.now) {
		at = a.now
	}
	a.next[name] = at
}

func (a *App) onMsg(m any) {
	switch v := m.(type) {
	case msgMarket:
		ok := v.err == nil
		a.done("market", ok)
		a.rtt = v.rtt
		if ok {
			a.checking = false
			a.link = true
			a.relayErr = ""
			a.market = v.m
			a.marketOpen = v.m.Open
			a.lastMarketOK = a.now
			if a.head != nil && !v.m.PhaseKnown() && a.head.Phase != nil {
				v.m.Phase, v.m.TradingDay = a.head.Phase.Phase, a.head.Phase.TradingDay
			}
			a.beat()
		} else {
			a.checking = false
			a.link = false
			a.relayErr = unreachableText(v.err)
			if a.market == nil {
				a.market = v.m // carries the explanatory note
			}
		}
	case msgHealth:
		ok := v.err == nil
		a.done("health", ok)
		if ok {
			a.checking = false
			a.head = v.h
			a.link = v.h.Reachable
			a.marketOpen = v.h.MarketOpen
			if v.rtt > 0 && a.market == nil {
				a.rtt = v.rtt
			}
			if a.link {
				a.relayErr = ""
			}
		} else {
			a.checking = false
			a.link = false
			a.relayErr = unreachableText(v.err)
		}
	case msgSignals:
		a.done("signals", v.ok)
		a.signals, a.signalsOK = v.text, v.ok
		a.beat()
	case msgQuotes:
		ok := v.err == nil
		a.done("quotes", ok)
		if ok {
			a.ingestQuotes(v.q)
		}
	case msgPrices:
		ok := v.err == nil
		a.done("prices", ok)
		if ok {
			if len(v.p) == 0 && len(a.prices) > 0 {
				break // keep the last table, like the phone app
			}
			a.prices = v.p
			a.rebuildSymbols()
		}
	case msgOrderFlow:
		ok := v.err == nil
		a.done("orderflow", ok)
		if ok {
			a.of, a.ofErr = v.f, ""
		} else {
			a.ofErr = unreachableText(v.err)
		}
	case msgSectors:
		ok := v.err == nil
		a.done("sectors", ok)
		if v.s != nil {
			a.sectors = v.s
			if a.sectorChoice >= len(v.s.Items) {
				a.sectorChoice = 0
			}
		}
		if ok {
			a.sectorsErr = ""
		} else {
			a.sectorsErr = unreachableText(v.err)
		}
	case msgStock:
		if v.sym != a.selectedSym {
			return
		}
		if v.err != nil || v.info == nil {
			a.selectedSt, a.selectedInfo = "failed", nil
		} else {
			a.selectedSt, a.selectedInfo = "ok", v.info
		}
	}
}

// beat ports Watcher.beat: raise a notification when the market phase flips
// or a new trade signal appears. The first phase seen only sets the baseline.
func (a *App) beat() {
	if a.demo || a.market == nil {
		return
	}
	// During the pre-market and the post-market there are no alerts. The quant
	// is online in both windows, and the session law owns the waiting; nothing
	// in the window may turn a phase change into a notification. The clock is
	// consulted as well as the relay's phase, because the relay can call the
	// whole stretch around the session CLOSED.
	silentPhase := false
	switch a.phase() {
	case "PRE_OPEN", "POST_CLOSE":
		silentPhase = true
	}
	switch phaseAt(a.karachiNow()) {
	case qsPre, qsPost:
		silentPhase = true
	}
	if silentPhase {
		// Keep the phase baseline current without a banner, tone or toast. Any
		// banner from the session that just ended is cleared too: the pre and
		// post markets must not mention sleep or a closed market.
		a.bannerTitle, a.bannerBody, a.bannerKind = "", "", ""
		a.bannerUntil = time.Time{}
		if ev := marketEvent(a.market); ev != "" {
			a.cfg.LastMarketEvent, a.dirty = ev, true
		}
		return
	}
	if ev := marketEvent(a.market); ev != "" {
		switch {
		case a.cfg.LastMarketEvent == "":
			a.cfg.LastMarketEvent, a.dirty = ev, true
		case ev != a.cfg.LastMarketEvent:
			detail := ""
			if a.head != nil {
				detail = strings.TrimSpace(a.head.Detail)
			}
			a.alert(marketEventTitle(ev), detail)
			a.cfg.LastMarketEvent, a.dirty = ev, true
		}
	}
	body := signalBody(a.signals)
	if a.signalsOK && isTradeSignal(body) && body != a.cfg.LastSignal {
		a.alert("Quant of Rehan signal", body)
		a.cfg.LastSignal, a.dirty = body, true
	}
}

// alert shows the in-app banner, rings the terminal bell and, when allowed,
// raises a Windows toast.
func (a *App) alert(title, body string) {
	a.bannerTitle, a.bannerBody = title, body
	a.bannerUntil = a.now.Add(20 * time.Second)
	a.bannerKind = "event"
	if strings.HasPrefix(title, "Quant of Rehan signal") {
		a.tone(toneSignal)
	} else {
		a.tone(toneEvent)
	}
	if a.cfg.Notify {
		sendToast(title, body)
	}
}

func (a *App) syncReqCount() {
	today := utcDay(a.now)
	if a.cfg.ReqDay != today {
		a.cfg.ReqDay = today
		a.reqBase = 0
		a.reqOffset = a.relay.Requests()
		a.dirty = true
	}
	a.cfg.ReqCount = a.reqToday()
}

func (a *App) save() {
	a.syncReqCount()
	out := a.persist
	if !a.ephemeral {
		// Request counts and notification memory belong to the real relay.
		out.LastMarketEvent, out.LastSignal = a.cfg.LastMarketEvent, a.cfg.LastSignal
		out.ReqDay, out.ReqCount = a.cfg.ReqDay, a.cfg.ReqCount
	}
	if a.themeTouched {
		out.Theme = a.cfg.Theme
	}
	if a.notifyTouched {
		out.Notify = a.cfg.Notify
	}
	if a.flowTouched {
		out.BigBuy, out.BigSell, out.Sound, out.BigBuyValue = a.cfg.BigBuy, a.cfg.BigSell, a.cfg.Sound, a.cfg.BigBuyValue
	}
	if a.cellTouched {
		out.CellShape = a.cfg.CellShape
	}
	_ = saveSettings(a.cfgPath, out)
	a.persist = out
	a.dirty = false
	a.lastSave = a.now
}

func (a *App) onTick(now time.Time) {
	a.now = now
	a.syncReqCount()
	for k, f := range a.flashes {
		if !now.Before(f.until) {
			delete(a.flashes, k)
		}
	}
	if a.demo {
		a.demoTick(now)
		return
	}
	names := []string{"market", "health", "signals", "quotes"}
	if a.screen == scrScanner {
		names = append(names, "prices", "sectors")
	}
	if a.screen == scrOrderFlow {
		names = append(names, "orderflow")
	}
	for _, n := range names {
		if !a.inflight[n] && !now.Before(a.next[n]) {
			a.fetch(n)
		}
	}
	if a.dirty && now.Sub(a.lastSave) > 10*time.Second {
		a.save()
	}
}

// ---------- input ----------

func (a *App) setScreen(s screenID) {
	if s == a.screen {
		return
	}
	a.screen = s
	switch s {
	case scrScanner:
		a.next["prices"] = time.Time{}  // ask for fresh prices at once
		a.next["sectors"] = time.Time{} // and the sector groups
	case scrOrderFlow:
		a.next["orderflow"] = time.Time{}
	}
}

func (a *App) cycle(d int) {
	n := len(screenNames)
	a.setScreen(screenID((int(a.screen) + d + n) % n))
}

func (a *App) onKey(k Key) {
	switch k.Kind {
	case KCtrlC:
		a.quit = true
		return
	case KF1:
		a.setScreen(scrHome)
		return
	case KF2:
		a.setScreen(scrAlerts)
		return
	case KF3:
		a.setScreen(scrOrderFlow)
		return
	case KF4:
		a.setScreen(scrScanner)
		return
	case KF5:
		a.setScreen(scrSettings)
		return
	case KMouse:
		a.onMouse(k)
		return
	case KTab:
		if k.Shift {
			a.cycle(-1)
		} else {
			a.cycle(1)
		}
		return
	}
	// The scanner has the search tile on top, and letters typed there go into
	// it, so the one letter keys (Q, R, M, B, S) are not hot keys on that screen.
	// The sound and alert flags are changed only on Settings now. CTRL+C quits
	// from anywhere.
	if a.screen == scrScanner {
		a.keyScanner(k)
		return
	}
	switch k.Kind {
	case KEsc:
		a.setScreen(scrHome)
	case KRune:
		switch k.R {
		case '1':
			a.setScreen(scrHome)
		case '2':
			a.setScreen(scrAlerts)
		case '3':
			a.setScreen(scrOrderFlow)
		case '4':
			a.setScreen(scrScanner)
		case '5':
			a.setScreen(scrSettings)
		case 'q', 'Q':
			a.quit = true
		case 'r', 'R':
			a.refreshNow()
		case 'd', 'D':
			if a.screen == scrHome {
				a.showRaw = !a.showRaw
			}
		case 'o', 'O':
			if a.screen == scrOrderFlow {
				a.stepFlowSort(1)
			}
		case '[':
			a.stepCell(-1, false)
		case ']':
			a.stepCell(1, false)
		}
	default:
		switch a.screen {
		case scrAlerts:
			a.keyAlerts(k)
		case scrOrderFlow:
			a.keyOrderFlow(k)
		case scrSettings:
			a.keySettings(k)
		}
	}
}

// keyScanner handles the scanner screen with its search tile. Letters and
// digits typed here go to the search box. UP and DOWN move through the matches
// while there is a search, and scroll the list otherwise. LEFT and RIGHT change
// the sort. ENTER picks the highlighted match, or the highlighted sort when
// nothing is typed. BACKSPACE edits the search, and clears the sort when the box
// is empty. ESC clears the search, and goes Home when there is none.
func (a *App) keyScanner(k Key) {
	searching := a.searchText != ""
	switch k.Kind {
	case KEsc:
		if a.sectorOpen {
			a.sectorOpen = false
		} else if searching || a.selectedSym != "" {
			a.clearSearch()
		} else {
			a.setScreen(scrHome)
		}
	case KLeft:
		a.pickScan(max(1, a.scanChoice-1))
	case KRight:
		a.pickScan(min(len(scanChoices), a.scanChoice+1))
	case KUp:
		switch {
		case searching:
			if a.searchCursor > 0 {
				a.searchCursor--
			}
		case a.scanChoice > 0:
			a.lvScan.scroll(-1)
		case a.scanCursor > 0:
			a.scanCursor--
		}
	case KDown:
		switch {
		case searching:
			if a.searchCursor < len(a.matches())-1 {
				a.searchCursor++
			}
		case a.scanChoice > 0:
			a.lvScan.scroll(1)
		case a.scanCursor < len(scanChoices)-1:
			a.scanCursor++
		}
	case KPgUp:
		a.lvScan.page(-1)
	case KPgDn:
		a.lvScan.page(1)
	case KHome:
		a.lvScan.top()
	case KEnd:
		a.lvScan.bottom()
	case KEnter:
		if searching {
			a.pickMatch()
		} else {
			a.pickScan(a.scanCursor + 1)
		}
	case KBackspace:
		if r := []rune(a.searchText); len(r) > 0 {
			a.searchText = string(r[:len(r)-1])
			a.searchCursor = 0
			a.selectedSym, a.selectedSt, a.selectedInfo = "", "", nil
		} else {
			a.pickScan(0)
		}
	case KDel:
		a.pickScan(0)
	case KRune:
		r := k.R
		if r >= 'a' && r <= 'z' {
			r -= 'a' - 'A'
		}
		// With an empty box a digit still jumps to that tab, as on every screen.
		if !searching && r >= '1' && r <= '5' {
			a.setScreen(screenID(r - '1'))
			return
		}
		if (r >= 'A' && r <= 'Z') || (r >= '0' && r <= '9') || r == '.' || r == '-' || r == '_' {
			if runeLen(a.searchText) < 12 {
				a.searchText += string(r)
			}
			a.searchCursor = 0
			a.selectedSym, a.selectedSt, a.selectedInfo = "", "", nil
		}
		if (r == '[' || r == ']') && !searching {
			if r == '[' {
				a.stepCell(-1, false)
			} else {
				a.stepCell(1, false)
			}
		}
	}
}

func (a *App) clearSearch() {
	a.searchText, a.selectedSym, a.selectedSt, a.selectedInfo = "", "", "", nil
	a.searchCursor = 0
}

// pickMatch opens the highlighted search match.
func (a *App) pickMatch() {
	m := a.matches()
	if len(m) == 0 {
		return
	}
	if a.searchCursor >= len(m) {
		a.searchCursor = 0
	}
	a.pickSymbol(m[a.searchCursor])
}

func (a *App) pickScan(c int) {
	a.scanChoice = c
	a.lvScan = listView{}
	if c > 0 {
		a.scanCursor = c - 1
	}
}

// alertList is the list the keys scroll on the Alerts screen.
func (a *App) alertList() *listView {
	switch a.alertFocus {
	case 1:
		return &a.lvSell
	case 2:
		return &a.lvLog
	}
	return &a.lvBoard
}

func (a *App) keyAlerts(k Key) {
	switch k.Kind {
	case KLeft:
		a.alertFocus = max(0, a.alertFocus-1)
	case KRight:
		a.alertFocus = min(2, a.alertFocus+1)
	case KUp:
		a.alertList().scroll(-1)
	case KDown:
		a.alertList().scroll(1)
	case KPgUp:
		a.alertList().page(-1)
	case KPgDn:
		a.alertList().page(1)
	case KHome:
		a.alertList().top()
	case KEnd:
		a.alertList().bottom()
	case KDel, KBackspace:
		a.flow.Log, a.lvLog = nil, listView{}
	case KEnter:
		a.testFlag(false)
	}
}

func (a *App) keyOrderFlow(k Key) {
	switch k.Kind {
	case KLeft:
		a.stepFlowSort(-1)
	case KRight:
		a.stepFlowSort(1)
	case KUp:
		a.lvOF.scroll(-1)
	case KDown:
		a.lvOF.scroll(1)
	case KPgUp:
		a.lvOF.page(-1)
	case KPgDn:
		a.lvOF.page(1)
	case KHome:
		a.lvOF.top()
	case KEnd:
		a.lvOF.bottom()
	}
}

// stepFlowSort moves the ORDER FLOW list to the next or previous order.
func (a *App) stepFlowSort(d int) {
	n := len(flowSorts)
	a.ofSort = ((a.ofSort+d)%n + n) % n
	a.lvOF.top()
}

func (a *App) toggleSound() {
	a.cfg.Sound = !a.cfg.Sound
	a.flowTouched, a.dirty = true, true
	if a.cfg.Sound {
		a.tone(toneEvent)
	}
}

func (a *App) toggleBigBuy() {
	a.cfg.BigBuy = !a.cfg.BigBuy
	a.flowTouched, a.dirty = true, true
}

func (a *App) toggleBigSell() {
	a.cfg.BigSell = !a.cfg.BigSell
	a.flowTouched, a.dirty = true, true
}

// stepBigBuy moves the size threshold through bigBuyChoices. The one size
// applies to buying and to selling.
func (a *App) stepBigBuy(d int) {
	i := 0
	for k, v := range bigBuyChoices {
		if v <= a.cfg.BigBuyValue {
			i = k
		}
	}
	i = min(max(0, i+d), len(bigBuyChoices)-1)
	a.cfg.BigBuyValue = bigBuyChoices[i]
	a.flow.SetValue(a.cfg.BigBuyValue)
	a.flowTouched, a.dirty = true, true
}

// testFlag raises a sample flag so the tone, the banner and the Windows toast
// can be checked on this PC. It is marked TEST and never enters the log.
func (a *App) testFlag(sell bool) {
	fl := Flag{Time: a.now, Symbol: "TEST", Kind: "flow", Side: "BUY",
		Text:   "TEST is getting big buying orders",
		Detail: "This is a test of the big buying alert, no real stock is involved."}
	if sell {
		fl.Side = "SELL"
		fl.Text = "TEST is getting big selling orders"
		fl.Detail = "This is a test of the big selling alert, no real stock is involved."
	}
	a.raiseFlag(fl)
}

// settingsRows: relay, notifications, big buying, big selling, sound, size,
// test buying, test selling, then the six themes.
const (
	settingsItems = 8
	settingsRows  = settingsItems + 6
)

// stepCell moves the radar roundness by dir steps of 0.05. It is changed with [
// and ] on the home and scanner screens, where the ring is, so it can be judged
// by eye. It stops at the ends.
func (a *App) stepCell(dir int, wrap bool) {
	if a.screen != scrHome {
		return
	}
	v := a.cfg.CellShape + dir*cellShapeStep
	switch {
	case v > cellShapeMax && wrap:
		v = cellShapeMin
	case v > cellShapeMax:
		v = cellShapeMax
	case v < cellShapeMin:
		v = cellShapeMin
	}
	a.cfg.CellShape = v
	cellAspect = float64(v) / 100
	a.cellTouched, a.dirty = true, true
}

func (a *App) keySettings(k Key) {
	switch k.Kind {
	case KUp:
		if a.setCursor > 0 {
			a.setCursor--
		}
	case KDown:
		if a.setCursor < settingsRows-1 {
			a.setCursor++
		}
	case KLeft:
		if a.setCursor == 5 {
			a.stepBigBuy(-1)
		}
	case KRight:
		if a.setCursor == 5 {
			a.stepBigBuy(1)
		}
	case KEnter:
		a.activateSetting(a.setCursor)
	}
}

func (a *App) activateSetting(i int) {
	a.setCursor = i
	switch {
	case i == 0:
		openURL(a.relay.Base + "/health")
	case i == 1:
		a.cfg.Notify = !a.cfg.Notify
		a.notifyTouched, a.dirty = true, true
	case i == 2:
		a.toggleBigBuy()
	case i == 3:
		a.toggleBigSell()
	case i == 4:
		a.toggleSound()
	case i == 5:
		// Enter walks the sizes and wraps from the largest back to the smallest.
		idx := 0
		for k, v := range bigBuyChoices {
			if v <= a.cfg.BigBuyValue {
				idx = k
			}
		}
		a.cfg.BigBuyValue = bigBuyChoices[(idx+1)%len(bigBuyChoices)]
		a.flow.SetValue(a.cfg.BigBuyValue)
		a.flowTouched, a.dirty = true, true
	case i == 6:
		a.testFlag(false)
	case i == 7:
		a.testFlag(true)
	default:
		a.cfg.Theme = i - settingsItems
		a.th = themeAt(a.cfg.Theme)
		a.themeTouched, a.dirty = true, true
	}
}

// ---------- drawing ----------

// draw serialises the canvas and writes only the rows that changed.
func (a *App) draw(w io.Writer) {
	c := a.render()
	var b strings.Builder
	b.WriteString(escSyncOn)
	if c.W != a.prevW || c.H != a.prevH || a.prevRows == nil {
		b.WriteString(escReset + escClear)
		a.prevRows = make([]string, c.H)
		a.prevW, a.prevH = c.W, c.H
	}
	for y := 0; y < c.H; y++ {
		if row := c.Row(y); row != a.prevRows[y] {
			b.WriteString(escMove(y+1, 1))
			b.WriteString(row)
			a.prevRows[y] = row
		}
	}
	b.WriteString(escSyncOff)
	if a.bell {
		b.WriteString("\a")
		a.bell = false
	}
	_, _ = io.WriteString(w, b.String())
}

// frameEvery is the time between animation frames. A console has to parse
// every colour code it is sent, so the orb runs at ten frames a second while
// the quant is online and at four when it is parked or the relay is down.
func (a *App) frameEvery() time.Duration {
	switch a.orbMode() {
	case OrbBurning, OrbChecking:
		return 100 * time.Millisecond
	}
	return 250 * time.Millisecond
}

// run is the main loop on a real terminal.
func (a *App) run(t Term) error {
	if err := t.Init(); err != nil {
		return err
	}
	defer t.Restore()
	_, _ = io.WriteString(t, escAltOn+escHide+mouseOnSeq+escTitle("Quant of Rehan"))
	defer func() { _, _ = io.WriteString(t, mouseOffSeq+escReset+escShow+escAltOff) }()

	keys := t.Keys()
	tick := time.NewTicker(50 * time.Millisecond)
	defer tick.Stop()
	var lastDraw time.Time
	for !a.quit {
		select {
		case k, ok := <-keys:
			if !ok {
				a.quit = true
				break
			}
			a.onKey(k)
			// Keys answer at once, whatever the frame rate. Pointer moves are
			// drawn at most every 30 ms, since a mouse can send hundreds a second.
			if !a.quit && (k.Kind != KMouse || k.Btn != MouseMove || time.Since(lastDraw) > 30*time.Millisecond) {
				a.draw(t)
				lastDraw = time.Now()
			}
		case m := <-a.msgs:
			a.onMsg(m)
		case now := <-tick.C:
			a.w, a.h = t.Size()
			a.onTick(now)
			if now.Sub(lastDraw) >= a.frameEvery() {
				a.draw(t)
				lastDraw = now
			}
		}
	}
	a.save()
	return nil
}
