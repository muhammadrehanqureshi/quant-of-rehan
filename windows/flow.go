package main

import (
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
	"time"
)

// The flow engine watches the broker feed (/quotes) once a second and flags a
// stock when large buying, or large selling, is going through the tape and that
// side dominates.
//
// What it can and cannot see. The feed gives each stock's last price and its
// running volume for the day, with bid and ask at zero, so there is no order
// book. A resting order that has not traded is invisible. What the engine
// measures is executed volume: every second it takes the volume added since
// the last look and classes it as buying when the price ticked up (or stayed
// up after an uptick) and as selling when the price ticked down, the usual
// tick rule. "Big buying orders" in an alert therefore means big executed
// buying, which is what an institution working an order leaves on the tape, and
// "big selling orders" means the same on the other side. The ORDER FLOW screen
// does not use this rule: it shows the relay's own quote-rule split.

// FlowCfg holds the thresholds. Value fields are in PKR.
type FlowCfg struct {
	Window     time.Duration // how far back the buying is added up
	MinValue   float64       // bought inside the window to count as big
	BlockValue float64       // one second's buying that counts as a block print
	RelMult    float64       // and at least this many times the stock's own average minute
	MinShare   float64       // buyers' share of classified volume, 0 to 1
	Cooldown   time.Duration // quiet time before the same stock can flag again
	MaxPerMin  int           // alerts that may ring in one minute, all stocks
}

func defaultFlowCfg(minValue int64) FlowCfg {
	if minValue <= 0 {
		minValue = 10_000_000
	}
	return FlowCfg{
		Window: 60 * time.Second, MinValue: float64(minValue), BlockValue: 2 * float64(minValue),
		RelMult: 4, MinShare: 0.70, Cooldown: 5 * time.Minute, MaxPerMin: 6,
	}
}

type flowEvt struct {
	t    time.Time
	dv   int64
	px   float64
	side int8 // +1 bought, -1 sold, 0 unclassified
}

// sideBuy and sideSell index the per side alert memory.
const (
	sideBuy  = 0
	sideSell = 1
)

type alertMem struct {
	at  time.Time
	val float64
}

type symFlow struct {
	have  bool
	t     time.Time
	px    float64
	vol   int64
	side  int8
	evts  []flowEvt
	alert [2]alertMem // the last flag on each side
}

// lastAlert is the most recent flag on either side.
func (s *symFlow) lastAlert() time.Time {
	if s.alert[sideBuy].at.After(s.alert[sideSell].at) {
		return s.alert[sideBuy].at
	}
	return s.alert[sideSell].at
}

// Flag is one raised alert.
type Flag struct {
	Time      time.Time
	Symbol    string
	Kind      string  // "flow" or "block"
	Side      string  // "BUY" or "SELL"
	Value     float64 // PKR on the flagged side
	Shares    int64   // shares on the flagged side
	Share     float64 // the flagged side's share of the classified volume
	Price     float64
	ChangePct *float64
	Text      string
	Detail    string
	Silent    bool // logged but not announced, because too many rang this minute
}

// FlowStat is one stock's buying over the window, for the live board.
type FlowStat struct {
	Side       string // "BUY" or "SELL", the side this row ranks
	Symbol     string
	Price      float64
	ChangePct  *float64
	BuyShares  int64
	SellShares int64
	BuyValue   float64
	SellValue  float64
	Share      float64
	Flagged    bool
}

// Flow is the detector. Only the UI goroutine uses it.
type Flow struct {
	cfg  FlowCfg
	sym  map[string]*symFlow
	Log  []Flag // newest last
	rang []time.Time

	// Allow, when set, says which symbols count. The app uses it to keep the
	// detector on the KMIALL names once the relay has sent that list.
	Allow func(sym string) bool

	// Buy and Sell say which sides may raise a flag. Both keep their baselines
	// up to date either way, so switching one on mid-session is safe.
	Buy, Sell bool
}

func NewFlow(cfg FlowCfg) *Flow {
	return &Flow{cfg: cfg, sym: map[string]*symFlow{}, Buy: true, Sell: true}
}

// addFlag appends one alert. Owner order 2026-11-13: the log is never trimmed
// during trading hours, so every alert raised while the market is open stays
// in it.
func (f *Flow) addFlag(flag Flag) {
	f.Log = append(f.Log, flag)
}

// SetValue changes the main threshold, for example from the settings file.
func (f *Flow) SetValue(minValue int64) { f.cfg = defaultFlowCfg(minValue) }

// Reset forgets every baseline, for example after the relay was unreachable.
func (f *Flow) Reset() {
	for _, s := range f.sym {
		s.have, s.evts = false, nil
	}
}

func (s *symFlow) set(now time.Time, q LiveQuote) {
	s.have, s.t, s.px, s.vol = true, now, q.Price, q.Volume
}

// Observe takes one /quotes answer. trading must be true only while the
// session is open; outside it the baselines are still kept up to date but no
// flow is counted.
func (f *Flow) Observe(now time.Time, q *Quotes, trading bool) []Flag {
	if q == nil {
		return nil
	}
	var out []Flag
	for sym, lq := range q.Items {
		if !lq.Fresh || lq.Price <= 0 || lq.Volume <= 0 {
			continue
		}
		if f.Allow != nil && !f.Allow(sym) {
			continue
		}
		sf := f.sym[sym]
		if sf == nil {
			sf = &symFlow{}
			f.sym[sym] = sf
		}
		if !sf.have {
			sf.set(now, lq)
			continue
		}
		if lq.Volume == sf.vol && lq.Price == sf.px {
			sf.t = now
			continue
		}
		// After a gap, or when the day's volume went backwards, what was added
		// in between is unknown, so start again from here.
		if now.Sub(sf.t) > 20*time.Second || lq.Volume < sf.vol || !trading {
			sf.evts = nil
			sf.set(now, lq)
			continue
		}
		dv := lq.Volume - sf.vol
		side := sf.side
		switch {
		case lq.Price > sf.px:
			side = 1
		case lq.Price < sf.px:
			side = -1
		}
		sf.side, sf.t, sf.px, sf.vol = side, now, lq.Price, lq.Volume
		if dv > 0 {
			sf.evts = append(sf.evts, flowEvt{now, dv, lq.Price, side})
		}
		cut := now.Add(-f.cfg.Window - 5*time.Second)
		i := 0
		for i < len(sf.evts) && sf.evts[i].t.Before(cut) {
			i++
		}
		sf.evts = sf.evts[i:]
		for _, side := range []int{sideBuy, sideSell} {
			if (side == sideBuy && !f.Buy) || (side == sideSell && !f.Sell) {
				continue
			}
			if fl := f.evaluate(now, sym, sf, lq, side); fl != nil {
				out = append(out, *fl)
			}
		}
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].Value != out[j].Value {
			return out[i].Value > out[j].Value
		}
		if out[i].Symbol != out[j].Symbol {
			return out[i].Symbol < out[j].Symbol
		}
		return out[i].Side < out[j].Side
	})
	for i := range out {
		f.rang = append(f.rang, now)
		cut := now.Add(-time.Minute)
		k := 0
		for k < len(f.rang) && f.rang[k].Before(cut) {
			k++
		}
		f.rang = f.rang[k:]
		if len(f.rang) > f.cfg.MaxPerMin {
			out[i].Silent = true
		}
		f.addFlag(out[i])
	}
	return out
}

// sums adds up the window.
func (f *Flow) sums(now time.Time, sf *symFlow) (buy, sell int64, buyV, sellV float64, nBuy, nSell int) {
	from := now.Add(-f.cfg.Window)
	for _, e := range sf.evts {
		if e.t.Before(from) {
			continue
		}
		switch {
		case e.side > 0:
			buy += e.dv
			buyV += float64(e.dv) * e.px
			nBuy++
		case e.side < 0:
			sell += e.dv
			sellV += float64(e.dv) * e.px
			nSell++
		}
	}
	return
}

// WindowSides totals one window across every stock: the shares that printed on
// each side and, kept apart, the shares that could not be sided. Owner order
// 2026-11-09: buying and selling are never added into one number, and the
// unclear remainder never joins either side.
func (f *Flow) WindowSides(now time.Time, window time.Duration) (buy, sell, unclear int64) {
	from := now.Add(-window)
	for _, sf := range f.sym {
		if sf == nil {
			continue
		}
		for _, e := range sf.evts {
			if e.t.Before(from) {
				continue
			}
			switch {
			case e.side > 0:
				buy += e.dv
			case e.side < 0:
				sell += e.dv
			default:
				unclear += e.dv
			}
		}
	}
	return
}

// evaluate decides whether one side of one stock earns a flag now.
func (f *Flow) evaluate(now time.Time, sym string, sf *symFlow, q LiveQuote, side int) *Flag {
	buy, sell, buyV, sellV, nBuy, nSell := f.sums(now, sf)
	own, opp, ownV, n := buy, sell, buyV, nBuy
	want, word, past, noun := int8(1), "BUY", "Bought", "Buyers"
	if side == sideSell {
		own, opp, ownV, n = sell, buy, sellV, nSell
		want, word, past, noun = -1, "SELL", "Sold", "Sellers"
	}
	share := 0.0
	if own+opp > 0 {
		share = float64(own) / float64(own+opp)
	}
	mins := math.Max(10, sessionMinutes(now))
	avgPerMin := float64(q.Volume) * q.Price / mins
	thr := math.Max(f.cfg.MinValue, f.cfg.RelMult*avgPerMin)

	kind := ""
	// A block print: one second of pure one sided trading that is itself large.
	if last := lastEvt(sf); last != nil && now.Sub(last.t) < 2*time.Second &&
		float64(last.dv)*last.px >= math.Max(f.cfg.BlockValue, f.cfg.RelMult*avgPerMin) && last.side == want {
		kind = "block"
	}
	// Sustained trading: large, dominant, at least two seconds on that side, and
	// the price has not been running against it through the window.
	if kind == "" && ownV >= thr && share >= f.cfg.MinShare && n >= 2 && !movedAgainst(sf, now, f.cfg.Window, want) {
		kind = "flow"
	}
	if kind == "" {
		return nil
	}
	val := ownV
	shares := own
	if kind == "block" {
		l := lastEvt(sf)
		val, shares = float64(l.dv)*l.px, l.dv
		share = math.Max(share, 1)
	}
	// Inside the cooldown the same stock flags again on the same side only when
	// its trading has tripled since the last flag and a minute has passed.
	mem := &sf.alert[side]
	if !mem.at.IsZero() && now.Sub(mem.at) < f.cfg.Cooldown &&
		(val < 3*mem.val || now.Sub(mem.at) < time.Minute) {
		return nil
	}
	mem.at, mem.val = now, val
	fl := &Flag{Time: now, Symbol: sym, Kind: kind, Side: word, Value: val, Shares: shares, Share: share, Price: q.Price, ChangePct: q.ChangePct}
	// Just the stock's name, then what it is getting.
	fl.Text = sym + " is getting big " + map[int]string{sideBuy: "buying", sideSell: "selling"}[side] + " orders"
	price := commaFloat(q.Price, 2)
	if q.ChangePct != nil {
		price += ", " + changeText(*q.ChangePct) + " today"
	}
	if kind == "block" {
		fl.Detail = fmt.Sprintf("A block %s of PKR %s (%s shares) in one trade. Price %s.", map[int]string{sideBuy: "buy", sideSell: "sell"}[side],
			compactNum(val), compactNum(float64(shares)), price)
	} else {
		fl.Detail = fmt.Sprintf("%s PKR %s (%s shares) in %d seconds. %s made up %.0f%% of the volume. Price %s.",
			past, compactNum(val), compactNum(float64(shares)), int(f.cfg.Window.Seconds()), noun, share*100, price)
	}
	return fl
}

func lastEvt(sf *symFlow) *flowEvt {
	if len(sf.evts) == 0 {
		return nil
	}
	return &sf.evts[len(sf.evts)-1]
}

// movedAgainst is true when the price at the end of the window is on the wrong
// side of where the window began for this trade: below it for buying (want 1),
// above it for selling (want -1).
func movedAgainst(sf *symFlow, now time.Time, w time.Duration, want int8) bool {
	from := now.Add(-w)
	first := math.NaN()
	for _, e := range sf.evts {
		if e.t.Before(from) {
			continue
		}
		first = e.px
		break
	}
	if math.IsNaN(first) {
		return false
	}
	if want > 0 {
		return sf.px < first
	}
	return sf.px > first
}

// sessionMinutes is the time since the 09:32 PKT open, never negative.
func sessionMinutes(now time.Time) float64 {
	n := now.In(pkt)
	open := time.Date(n.Year(), n.Month(), n.Day(), 9, 32, 0, 0, pkt)
	if m := n.Sub(open).Minutes(); m > 0 {
		return m
	}
	return 0
}

// Board lists the stocks with the most buying inside the window, strongest
// first, for the live board and the scanner sort.
func (f *Flow) Board(now time.Time, q *Quotes, limit int) []FlowStat {
	return f.BoardSide(now, q, limit, sideBuy)
}

// BoardBoth lists the stocks moving most on either side inside the window, so
// one scanner table can show buying and selling together. A stock is ranked by
// the money on its larger side, which keeps a huge sell from hiding a huge buy.
func (f *Flow) BoardBoth(now time.Time, q *Quotes, limit int) []FlowStat {
	var out []FlowStat
	for sym, sf := range f.sym {
		if !sf.have {
			continue
		}
		buy, sell, buyV, sellV, _, _ := f.sums(now, sf)
		if buy <= 0 && sell <= 0 {
			continue
		}
		buyFirst := buyV >= sellV
		word := "BUY"
		if !buyFirst {
			word = "SELL"
		}
		st := FlowStat{Side: word, Symbol: sym, Price: sf.px, BuyShares: buy, SellShares: sell, BuyValue: buyV, SellValue: sellV,
			Share: float64(buy) / float64(buy+sell), Flagged: f.Flagged(now, sym)}
		if q != nil {
			if lq, ok := q.Items[sym]; ok {
				st.ChangePct = lq.ChangePct
				if lq.Price > 0 {
					st.Price = lq.Price
				}
			}
		}
		out = append(out, st)
	}
	sort.Slice(out, func(i, j int) bool {
		iMax := math.Max(out[i].BuyValue, out[i].SellValue)
		jMax := math.Max(out[j].BuyValue, out[j].SellValue)
		if iMax != jMax {
			return iMax > jMax
		}
		return out[i].Symbol < out[j].Symbol
	})
	if limit > 0 && len(out) > limit {
		out = out[:limit]
	}
	return out
}

// BoardSide is Board for either side: the stocks with the most selling when
// side is sideSell.
func (f *Flow) BoardSide(now time.Time, q *Quotes, limit int, side int) []FlowStat {
	var out []FlowStat
	for sym, sf := range f.sym {
		if !sf.have {
			continue
		}
		buy, sell, buyV, sellV, _, _ := f.sums(now, sf)
		own, opp := buy, sell
		word := "BUY"
		if side == sideSell {
			own, opp = sell, buy
			word = "SELL"
		}
		if own <= 0 || own < opp {
			continue
		}
		st := FlowStat{Side: word, Symbol: sym, Price: sf.px, BuyShares: buy, SellShares: sell, BuyValue: buyV, SellValue: sellV,
			Share: float64(own) / float64(own+opp), Flagged: !sf.alert[side].at.IsZero() && now.Sub(sf.alert[side].at) < 10*time.Minute}
		if q != nil {
			if lq, ok := q.Items[sym]; ok {
				st.ChangePct = lq.ChangePct
				if lq.Price > 0 {
					st.Price = lq.Price
				}
			}
		}
		out = append(out, st)
	}
	val := func(s FlowStat) float64 {
		if side == sideSell {
			return s.SellValue
		}
		return s.BuyValue
	}
	sort.Slice(out, func(i, j int) bool {
		if val(out[i]) != val(out[j]) {
			return val(out[i]) > val(out[j])
		}
		return out[i].Symbol < out[j].Symbol
	})
	if limit > 0 && len(out) > limit {
		out = out[:limit]
	}
	return out
}

// Flagged reports whether a stock raised an alert, on either side, in the last
// ten minutes.
func (f *Flow) Flagged(now time.Time, sym string) bool {
	sf := f.sym[sym]
	return sf != nil && !sf.lastAlert().IsZero() && now.Sub(sf.lastAlert()) < 10*time.Minute
}

// compactNum writes 18400000 as 18.4M, 1250 as 1.25k and 3.1e9 as 3.10B. A
// whole million drops its decimal, so a million reads 1M and ten million 10M.
// Owner order 2026-11-12 (latest): the thousand mark is a lower case k.
func compactNum(v float64) string {
	a := math.Abs(v)
	switch {
	case a >= 1e9:
		return strconv.FormatFloat(v/1e9, 'f', 2, 64) + "B"
	case a >= 1e6:
		return strings.TrimRight(strings.TrimRight(strconv.FormatFloat(v/1e6, 'f', 1, 64), "0"), ".") + "M"
	case a >= 1e3:
		return strings.TrimRight(strings.TrimRight(strconv.FormatFloat(v/1e3, 'f', 2, 64), "0"), ".") + "k"
	}
	return strconv.FormatFloat(v, 'f', 0, 64)
}
