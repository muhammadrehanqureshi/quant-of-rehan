package main

import (
	"math"
	"math/rand"
	"strconv"
	"time"
)

// Demo mode feeds the screens with invented data so the layout can be seen
// and tested outside market hours. The tickers are made up on purpose and the
// header says DEMO DATA, so none of it can be mistaken for the real market.
// The demo market ticks once a second like the real feed, and every minute or
// so one stock is bought hard so the big buying flag can be seen and heard.

type demoRow struct {
	sym        string
	price, chg float64
	buy, sell  int64
}

var demoRows = []demoRow{
	{"ALFA", 42.10, 2.31, 3_410_000, 1_250_000},
	{"BRVO", 118.55, 1.12, 920_000, 410_000},
	{"CHRL", 7.84, -0.64, 5_200_000, 6_900_000},
	{"DLTA", 265.20, 3.77, 610_000, 150_000},
	{"ECHO", 15.02, 4.95, 2_100_000, 380_000},
	{"FXTR", 88.40, 0.35, 700_000, 640_000},
	{"GOLF", 31.77, -1.80, 1_050_000, 1_900_000},
	{"HTEL", 54.30, 0.92, 1_800_000, 1_100_000},
}

type demoSym struct {
	px, hi, lo, prev float64
	vol              int64
	lastTick         int64 // unix second of the last change
	rate             int64 // typical shares a second
}

// demoSim is the invented broker feed.
type demoSim struct {
	rng        *rand.Rand
	sec        int64 // last second simulated
	epoch      int64 // first second simulated
	burstStart int64 // seconds after epoch when the first burst begins
	burstLen   int64
	cycle      int64
	syms       map[string]*demoSym
	idx, idx0  float64
}

func newDemoSim(first int64, burstStart, cycle int64) *demoSim {
	d := &demoSim{rng: rand.New(rand.NewSource(7)), sec: first - 1, epoch: first,
		burstStart: burstStart, burstLen: 30, cycle: cycle,
		syms: map[string]*demoSym{}, idx: 166409.25, idx0: 167193.43}
	for _, r := range demoRows {
		prev := r.price / (1 + r.chg/100)
		d.syms[r.sym] = &demoSym{px: r.price, hi: r.price * 1.012, lo: r.price * 0.984, prev: prev,
			vol: r.buy + r.sell, rate: max(2000, (r.buy+r.sell)/700)}
	}
	return d
}

// advance simulates every whole second up to now and says whether it moved.
func (d *demoSim) advance(now int64) bool {
	moved := false
	for d.sec < now {
		d.sec++
		d.step(d.sec)
		moved = true
	}
	return moved
}

func (d *demoSim) bursting(s int64) bool {
	rel := s - d.epoch - d.burstStart
	return rel >= 0 && rel%d.cycle < d.burstLen
}

func (d *demoSim) step(s int64) {
	d.idx += (d.rng.Float64() - 0.48) * 6
	for _, r := range demoRows {
		y := d.syms[r.sym]
		tick := math.Max(0.01, math.Round(y.px*0.0004*100)/100)
		up := d.rng.Float64() < 0.5
		dv := y.rate/2 + d.rng.Int63n(y.rate+1)
		if r.sym == "ECHO" && d.bursting(s) {
			up = d.rng.Float64() < 0.9
			dv = 90_000 + d.rng.Int63n(110_000) // an institution working an order
		}
		if r.sym == "DLTA" && (s-d.epoch)%97 == 60 {
			up, dv = true, 160_000 // one big print
		}
		if d.rng.Float64() < 0.55 || dv > 50_000 {
			if up {
				y.px += tick
			} else {
				y.px -= tick
			}
			y.px = math.Round(y.px*100) / 100
			y.hi, y.lo = math.Max(y.hi, y.px), math.Min(y.lo, y.px)
			y.vol += dv
			y.lastTick = s
		}
	}
}

// quotes renders the simulated state as a /quotes answer.
func (d *demoSim) quotes(now time.Time) *Quotes {
	q := &Quotes{OK: true, Items: map[string]LiveQuote{}, FetchedAt: now}
	ch := d.idx - d.idx0
	q.Index = &IndexQuote{Value: d.idx, Change: ch, ChangePct: ch / d.idx0 * 100,
		AsOf: now.In(pkt).Format("2006-01-02 15:04:05"), Fresh: true}
	for sym, y := range d.syms {
		c := y.px - y.prev
		pct := c / y.prev * 100
		age := int(min(d.sec-y.lastTick, 9))
		q.Items[sym] = LiveQuote{Price: y.px, ChangePct: &pct, Change: &c, Fresh: true, Volume: y.vol,
			High: y.hi, Low: y.lo, AgeSeconds: age}
	}
	return q
}

// enableDemo switches to invented data. It plays the preceding stretch of the
// demo market first, so charts and the big buying board already have history.
func (a *App) enableDemo(now time.Time) {
	a.demo = true
	a.cfg.Notify = false
	a.checking = false
	a.link = true
	a.marketOpen = true
	a.now = now
	pre := int64(160)
	if a.animT < 0 {
		pre = 0 // a live demo starts clean and a burst arrives after 15 s
	}
	start := now.Unix() - pre
	burst, cycle := int64(100), int64(400)
	if pre == 0 {
		burst, cycle = 15, 90
	}
	a.sim = newDemoSim(start, burst, cycle)
	a.prices = map[string]Quote{}
	for _, r := range demoRows {
		c, b, s := r.chg, r.buy, r.sell
		a.prices[r.sym] = Quote{Price: r.price, ChangePct: &c, Buy: &b, Sell: &s}
	}
	for s := start; s <= now.Unix(); s++ {
		a.sim.advance(s)
		a.now = time.Unix(s, 0)
		a.ingestQuotes(a.sim.quotes(a.now))
		a.demoStatic(a.now)
	}
	a.now = now
	a.bannerUntil = time.Time{} // the pre-roll's own flags are history, not news
	a.scanChoice = 2
	a.demoLast = now.Unix()
}

func demoStock(sym string) *StockInfo {
	for _, r := range demoRows {
		if r.sym == sym {
			b, s := float64(r.buy), float64(r.sell)
			t := b + s
			return &StockInfo{Symbol: sym, Buy: &b, Sell: &s, Volume: &t}
		}
	}
	return nil
}

// demoStatic builds the parts of the demo relay answers that do not tick.
func (a *App) demoStatic(now time.Time) {
	pk := now.In(pkt)
	date := pk.Format("2006-01-02")
	stamp := pk.Format("2006-01-02 15:04") + " PKT"

	m := NewMarket()
	m.Answered, m.Open = true, true
	m.Phase, m.Condition, m.TradingDay = "OPEN", "OPERATIONAL", true
	m.Date, m.KarachiNow, m.Members = date, stamp, 313
	m.FeedStatus, m.FeedStatusFresh = "ACTIVE", true
	m.IndexAsOf, m.IndexSource = pk.Format("2006-01-02 15:04:05"), "demo"
	val, ch, pct := a.sim.idx, a.sim.idx-a.sim.idx0, (a.sim.idx-a.sim.idx0)/a.sim.idx0*100
	m.IndexValue, m.IndexChange, m.IndexPct = &val, &ch, &pct
	m.Basis = "current session volume, top 3 (demo)"
	m.SplitBasis = "B/S estimated from the day's range, not order flow"
	m.NextEvent = "CLOSE " + pk.Format("2006-01-02") + " " + demoSessionEnd(pk)
	for _, idx := range []int{4, 2, 0} {
		r := demoRows[idx]
		p, c := r.price, r.chg
		b, s := r.buy, r.sell
		vol := b + s
		m.Leaders = append(m.Leaders, Leader{Symbol: r.sym, Price: &p, ChangePct: &c, Volume: &vol, Buy: &b, Sell: &s})
	}
	closed, rate := 4, 75
	m.WinLoss = &WinLoss{Wins: 3, Losses: 1, Closed: &closed, RatePct: &rate}
	a.market = m
	a.head = &Head{Reachable: true, MarketOpen: true, KarachiNow: stamp, NextEvent: m.NextEvent, Phase: m}
	a.head.Detail = "Karachi: " + stamp
	a.lastMarketOK = now
	a.rtt = 118 * time.Millisecond
	a.signals = "QUANT OF REHAN DEMO " + date + "\nSymbol: ALFA\nEntry time: 11:30:02 PKT\nEntry price: 42.10\nTarget: 42.94 (+2%)\nStop Loss: 41.68"
	a.signalsOK = true
	a.rebuildSymbols()
	a.demoOrderFlow(now)
}

// demoOrderFlow builds an invented ORDER FLOW answer from the demo market. Most
// stocks are measured, with a little unclassified volume kept apart, one has
// only a range estimate and one has no split, so every state of the screen can
// be seen.
func (a *App) demoOrderFlow(now time.Time) {
	if a.sim == nil {
		return
	}
	pk := now.In(pkt)
	of := &OrderFlow{OK: true, Day: pk.Format("2006-01-02"), AsOf: now.UTC().Format(time.RFC3339Nano), AsOfTime: now,
		Universe: len(demoRows), Included: len(demoRows), Fresh: len(demoRows), FetchedAt: now, Path: "/orderflow",
		LargeThreshold: 1_000_000, LargeTotal: 14}
	for _, r := range demoRows {
		ds := a.sim.syms[r.sym]
		if ds == nil {
			continue
		}
		vol := ds.vol
		p, bidv, askv := ds.px, ds.px-0.02, ds.px+0.02
		chg := (ds.px - ds.prev) / ds.prev * 100
		hi, lo := ds.hi, ds.lo
		fr := FlowRow{Symbol: r.sym, Price: p, Bid: &bidv, Ask: &askv, ChangePct: &chg, High: &hi, Low: &lo,
			Volume: &vol, Fresh: true, Method: methodMeasured, Source: "demo"}
		share := float64(r.buy) / float64(r.buy+r.sell)
		switch r.sym {
		case "CHRL": // only an estimate from the day's range
			b := int64(float64(vol) * share)
			sl := vol - b
			fr.Buy, fr.Sell, fr.Method = &b, &sl, methodEstimated
		case "GOLF": // no split at all
			fr.Method = methodNone
		default:
			u := vol / 40
			b := int64(float64(vol-u) * share)
			sl := vol - u - b
			cl := b + sl
			fr.Buy, fr.Sell, fr.Unclassified, fr.Classified = &b, &sl, &u, &cl
		}
		of.Rows = append(of.Rows, fr)
	}
	a.of, a.ofErr = of, ""
}

// demoTick advances the invented market. It runs on the 50 ms tick, but the
// market moves once a second, like the real feed.
func (a *App) demoTick(now time.Time) {
	a.now = now
	if a.sim == nil {
		return
	}
	if a.sim.advance(now.Unix()) {
		a.demoLast = now.Unix()
		a.ingestQuotes(a.sim.quotes(now))
		a.demoStatic(now)
	}
	_ = strconv.Itoa
}

// demoSessionEnd is when the trading day that the demo clock sits in ends.
// Owner order 2026-11-12: 15:49 Monday to Thursday and 16:49 on Friday, with
// Friday morning's answer staying at the 12:00 midday break.
func demoSessionEnd(pk time.Time) string {
	if pk.Weekday() != time.Friday {
		return "15:49"
	}
	if pk.Hour() < 12 {
		return "12:00"
	}
	return "16:49"
}
