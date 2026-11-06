package main

import (
	"context"
	"sort"
	"strings"
	"time"
)

// The ORDER FLOW screen reads the relay's /orderflow answer (the same answer is
// at /flow). Every number on the screen is the relay's own number, written down
// as it arrived. Nothing is rounded, merged or filled in here:
//
//   - buy and sell volume are shown only when the relay measured them
//     (split_method "quote_rule": every volume increment sided by the wire's
//     own bid and ask);
//   - volume the capture never saw as an increment is the relay's
//     unclassified_volume and is shown on its own as U, never added to B or S;
//   - a split that is only an estimate from the day's range (range_position) is
//     marked as an estimate and is never counted in the measured totals;
//   - a stock with no split at all shows its total volume and no B or S.

const (
	methodMeasured  = "quote_rule"
	methodEstimated = "range_position"
	methodNone      = "unavailable"
)

// FlowRow is one stock of the answer.
type FlowRow struct {
	Symbol    string
	Price     float64
	Bid, Ask  *float64
	Spread    *float64
	ChangePct *float64
	High, Low *float64

	Volume       *int64
	Buy, Sell    *int64
	Classified   *int64
	Unclassified *int64
	BuyShare     *float64 // percent of the classified volume
	SellShare    *float64
	Method       string
	Source       string
	Fresh        bool
	ObservedAt   string
	AgeSeconds   *int64

	LargeBuyCount, LargeSellCount int64
	LargeBuyValue, LargeSellValue float64
	LastLargeAt                   string
}

// Measured says whether this row's buy and sell are the relay's measured split.
func (r FlowRow) Measured() bool {
	return r.Method == methodMeasured && r.Buy != nil && r.Sell != nil
}

// Balanced reports whether B + S + U equals T, which must hold for every
// measured row. A row that fails is shown with a CHECK mark instead of being
// quietly smoothed over.
func (r FlowRow) Balanced() bool {
	if !r.Measured() || r.Volume == nil || r.Unclassified == nil {
		return true
	}
	return *r.Buy+*r.Sell+*r.Unclassified == *r.Volume
}

// LargePrint is one large observed increment on the relay's board.
type LargePrint struct {
	Symbol string
	Side   string // BUY or SELL
	Shares int64
	Price  float64
	Value  float64
	At     string
}

// OrderFlow is the whole answer.
type OrderFlow struct {
	OK       bool
	Day      string
	AsOf     string
	AsOfTime time.Time
	Universe int
	Included int
	Missing  int
	Fresh    int
	Rows     []FlowRow
	Absent   []string // symbols with no frame for the day

	LargeThreshold float64
	LargeTotal     int
	Prints         []LargePrint

	FetchedAt time.Time
	Path      string // /orderflow or /flow, whichever answered
	Basis     string
}

// FlowTotals adds up the rows the way the screen states it.
type FlowTotals struct {
	Measured      int // stocks whose split is measured
	Estimated     int // stocks with a range estimate only
	NoSplit       int // stocks with no split at all
	Buy, Sell     int64
	Unclassified  int64
	MeasuredTotal int64 // T of the measured stocks
	OtherTotal    int64 // T of the stocks that are not measured
	Unbalanced    int
}

// Totals sums only measured rows into B, S, U and T. Estimated and unsplit
// stocks add their volume to OtherTotal and nothing to B or S.
func (o *OrderFlow) Totals() FlowTotals {
	var t FlowTotals
	for _, r := range o.Rows {
		vol := int64(0)
		if r.Volume != nil {
			vol = *r.Volume
		}
		switch {
		case r.Measured():
			t.Measured++
			t.Buy += *r.Buy
			t.Sell += *r.Sell
			if r.Unclassified != nil {
				t.Unclassified += *r.Unclassified
			}
			t.MeasuredTotal += vol
			if !r.Balanced() {
				t.Unbalanced++
			}
		case r.Method == methodEstimated:
			t.Estimated++
			t.OtherTotal += vol
		default:
			t.NoSplit++
			t.OtherTotal += vol
		}
	}
	return t
}

// ParseOrderFlow reads one /orderflow answer. A row without a symbol or a
// positive price is dropped, because it has nothing to show.
func ParseOrderFlow(o J) *OrderFlow {
	f := &OrderFlow{}
	if !o.boolean("ok", false) {
		return f
	}
	f.OK = true
	f.Day = o.str("day", "")
	f.AsOf = o.str("as_of", "")
	if t, err := time.Parse(time.RFC3339Nano, f.AsOf); err == nil {
		f.AsOfTime = t
	}
	if c := o.obj("counts"); c != nil {
		f.Universe, f.Included = c.intDef("universe", 0), c.intDef("included", 0)
		f.Missing, f.Fresh = c.intDef("missing", 0), c.intDef("fresh", 0)
	}
	for _, it := range o.arr("rows") {
		ro := objOf(it)
		if ro == nil {
			continue
		}
		sym := strings.ToUpper(ro.str("symbol", ""))
		p := ro.num("price")
		if sym == "" || p == nil || *p <= 0 {
			continue
		}
		r := FlowRow{
			Symbol: sym, Price: *p,
			Bid: ro.num("bid"), Ask: ro.num("ask"), Spread: ro.num("spread"),
			ChangePct: ro.num("change_pct"), High: ro.num("high"), Low: ro.num("low"),
			Volume: ro.integer("volume"), Buy: ro.integer("buy_volume"), Sell: ro.integer("sell_volume"),
			Classified: ro.integer("classified_volume"), Unclassified: ro.integer("unclassified_volume"),
			BuyShare: ro.num("buy_share_pct"), SellShare: ro.num("sell_share_pct"),
			Method: ro.str("split_method", methodNone), Source: ro.str("split_source", ""),
			Fresh: ro.boolean("fresh", false), ObservedAt: ro.str("observed_at", ""),
			AgeSeconds:    ro.integer("age_seconds"),
			LargeBuyCount: valInt(ro.integer("large_buy_count")), LargeSellCount: valInt(ro.integer("large_sell_count")),
			LastLargeAt: ro.str("last_large_at", ""),
		}
		if v := ro.num("large_buy_value_pkr"); v != nil {
			r.LargeBuyValue = *v
		}
		if v := ro.num("large_sell_value_pkr"); v != nil {
			r.LargeSellValue = *v
		}
		f.Rows = append(f.Rows, r)
	}
	for _, it := range o.arr("missing") {
		if mo := objOf(it); mo != nil {
			if s := strings.ToUpper(mo.str("symbol", "")); s != "" {
				f.Absent = append(f.Absent, s)
			}
		}
	}
	sort.Strings(f.Absent)
	if lg := o.obj("large"); lg != nil {
		if v := lg.num("threshold_pkr"); v != nil {
			f.LargeThreshold = *v
		}
		f.LargeTotal = lg.intDef("total", 0)
		for _, it := range lg.arr("prints") {
			po := objOf(it)
			if po == nil {
				continue
			}
			lp := LargePrint{Symbol: strings.ToUpper(po.str("symbol", "")), Side: po.str("side", ""),
				Shares: valInt(po.integer("shares")), At: po.str("at", "")}
			if v := po.num("price"); v != nil {
				lp.Price = *v
			}
			if v := po.num("value_pkr"); v != nil {
				lp.Value = *v
			}
			if lp.Symbol != "" {
				f.Prints = append(f.Prints, lp)
			}
		}
	}
	if b := o.obj("basis"); b != nil {
		f.Basis = b.str("unclassified", "")
	}
	return f
}

func valInt(p *int64) int64 {
	if p == nil {
		return 0
	}
	return *p
}

// FetchOrderFlow asks /orderflow and, when that does not answer as a relay
// answer should, /flow, which carries the same data. The body can be large (a
// row for every KMIALL stock plus the large print board), so it has its own,
// larger size limit.
func (r *Relay) FetchOrderFlow(ctx context.Context) (*OrderFlow, error) {
	var firstErr error
	for _, path := range []string{"/orderflow", "/flow"} {
		o, _, err := r.getLimit(ctx, path, maxFlowBody)
		if err != nil {
			if firstErr == nil {
				firstErr = err
			}
			continue
		}
		f := ParseOrderFlow(o)
		if !f.OK {
			if firstErr == nil {
				firstErr = errFlowNotOK
			}
			continue
		}
		f.FetchedAt = time.Now()
		f.Path = path
		return f, nil
	}
	return nil, firstErr
}
