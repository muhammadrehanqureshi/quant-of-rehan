package main

import (
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
	"time"
)

// The flow engine watches the broker feed (/quotes) at the live pace and flags
// a stock when a poll's volume step at or above the share threshold goes
// through the tape, on the side the relay measured.
//
// What it can and cannot see. The live feed carries each stock's last price,
// its running volume for the day and the relay capture's own cumulative
// quote-rule pair. A resting order that has not traded is invisible. What the
// engine measures is executed volume: on every live poll it differences that
// pair, so a heavy sell at the bid moves S even when the last price held. A
// row without the pair, as an older relay sends, falls back to the usual tick
// rule. "Big buying orders" in an alert therefore means big executed buying,
// which is what an institution working an order leaves on the tape, and "big
// selling orders" means the same on the other side.

// FlowCfg holds the thresholds. Owner order 2026-11-16: big orders are
// measured in shares, not PKR. MinShares is the smallest volume step between
// two live polls that earns its own alert; 0 MaxPerMin means every such order
// is announced, not only the first few in a minute.
type FlowCfg struct {
	Window    time.Duration // how far back the buying board is added up
	MinShares int64         // shares in one live poll to count as a big order
	MaxPerMin int           // 0 means no announcement cap
}

func defaultFlowCfg(minShares int64) FlowCfg {
	if minShares <= 0 {
		minShares = 100_000
	}
	return FlowCfg{Window: 60 * time.Second, MinShares: minShares, MaxPerMin: 0}
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
	buy   int64
	sell  int64
	pair  bool // the relay supplied its own measured B/S pair
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
	Kind      string  // "order" for a share-sized second, plus "price" alerts elsewhere
	Side      string  // "BUY" or "SELL"
	Value     float64 // the flagged quantity, in shares
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
func (f *Flow) SetMinShares(minShares int64) { f.cfg = defaultFlowCfg(minShares) }

// Reset forgets every baseline, for example after the relay was unreachable.
func (f *Flow) Reset() {
	for _, s := range f.sym {
		s.have, s.evts = false, nil
	}
}

func (s *symFlow) set(now time.Time, q LiveQuote) {
	s.have, s.t, s.px, s.vol = true, now, q.Price, q.Volume
	s.buy, s.sell, s.pair = 0, 0, false
	if b, sl, ok := relayPair(q); ok {
		s.buy, s.sell, s.pair = b, sl, true
	}
}

// relayPair is the relay capture's cumulative quote-rule pair. A row without
// that pair keeps the older local rule, so an old relay still works.
func relayPair(q LiveQuote) (int64, int64, bool) {
	if q.FlowMethod != methodMeasured || q.MeasuredBuy == nil || q.MeasuredSell == nil {
		return 0, 0, false
	}
	return *q.MeasuredBuy, *q.MeasuredSell, true
}

func pairAdvanced(sf *symFlow, q LiveQuote) bool {
	b, s, ok := relayPair(q)
	return ok && (!sf.pair || b != sf.buy || s != sf.sell)
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
		if lq.Volume == sf.vol && lq.Price == sf.px && !pairAdvanced(sf, lq) {
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
		prevPx := sf.px
		dv := lq.Volume - sf.vol
		sf.t, sf.px, sf.vol = now, lq.Price, lq.Volume
		if b, sl, ok := relayPair(lq); ok {
			if !sf.pair {
				// The first measured frame is a baseline, never a whole day of
				// shares sided by the local rule.
				sf.buy, sf.sell, sf.pair = b, sl, true
			} else if db, ds := b-sf.buy, sl-sf.sell; db >= 0 && ds >= 0 {
				// Exactly the shares the relay capture sided since the last
				// frame. A heavy sell at the bid therefore moves S even when the
				// last price did not move between the two frames.
				if db > 0 {
					sf.evts = append(sf.evts, flowEvt{now, db, lq.Price, 1})
					sf.side = 1
				}
				if ds > 0 {
					sf.evts = append(sf.evts, flowEvt{now, ds, lq.Price, -1})
					sf.side = -1
				}
				sf.buy, sf.sell = b, sl
			} else {
				// The relay's own pair restarted (a session reset) or was
				// corrected. Take the new pair as a baseline instead of
				// freezing this scrip for the rest of the day.
				sf.buy, sf.sell = b, sl
			}
		} else {
			side := sf.side
			switch {
			case lq.Price > prevPx:
				side = 1
			case lq.Price < prevPx:
				side = -1
			}
			sf.side = side
			if dv > 0 {
				sf.evts = append(sf.evts, flowEvt{now, dv, lq.Price, side})
			}
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
		if f.cfg.MaxPerMin > 0 && len(f.rang) > f.cfg.MaxPerMin {
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

// evaluate decides whether one side of one stock earns an alert now.
//
// Owner order 2026-11-16: every one-second volume step at or above
// MinShares is its own big order, on the side it printed. Owner order
// 2026-11-18: when the relay carries its measured quote-rule pair, that pair
// is the side; the local tick rule is only the fallback for an older relay.
// There is no minute aggregate, no relative multiple and no cooldown, so two
// large orders in consecutive seconds produce two alerts.
func (f *Flow) evaluate(now time.Time, sym string, sf *symFlow, q LiveQuote, side int) *Flag {
	want, word := int8(1), "BUY"
	if side == sideSell {
		want, word = -1, "SELL"
	}
	last := lastEvtFor(sf, want)
	if last == nil || now.Sub(last.t) > 2*time.Second {
		return nil
	}
	if last.side != want || last.dv < f.cfg.MinShares {
		return nil
	}
	mem := &sf.alert[side]
	mem.at, mem.val = now, float64(last.dv)
	fl := &Flag{Time: now, Symbol: sym, Kind: "order", Side: word,
		Value: float64(last.dv), Shares: last.dv, Share: 1,
		Price: q.Price, ChangePct: q.ChangePct}
	// Owner order 2026-11-16: the alert says the quantity, the scrip, the side
	// and the current price in one sentence, with the day's direction and
	// percentage. The log, the banner and the Windows notification all use it.
	verb := "were bought"
	if side == sideSell {
		verb = "were sold"
	}
	sentence := fmt.Sprintf("%s shares of %s %s at PKR %s",
		compactNum(float64(last.dv)), sym, verb, commaFloat(q.Price, 2))
	if q.ChangePct != nil {
		sentence += " " + changeText(*q.ChangePct)
	}
	fl.Text = sentence + "."
	fl.Detail = ""
	return fl
}

func lastEvt(sf *symFlow) *flowEvt {
	if len(sf.evts) == 0 {
		return nil
	}
	return &sf.evts[len(sf.evts)-1]
}

// lastEvtFor finds the newest event on one side. A relay frame can add B and
// S in the same poll, so the two sides must not share the single last event.
func lastEvtFor(sf *symFlow, want int8) *flowEvt {
	for i := len(sf.evts) - 1; i >= 0; i-- {
		if sf.evts[i].side == want {
			return &sf.evts[i]
		}
	}
	return nil
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
	// Owner order 2026-11-16: the ALERTS boards rank and filter on share
	// quantity, so a cheap 50k lot can stand where a costly 1M lot cannot.
	val := func(s FlowStat) int64 {
		if side == sideSell {
			return s.SellShares
		}
		return s.BuyShares
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
