package main

import (
	"testing"
	"time"
)

// Owner order 2026-11-18: the live /quotes row carries its own measured
// quote-rule pair. The parser must keep it, and the ALERTS boards must use
// those exact shares. A heavy sell at the bid must move S even when the last
// price did not move between two frames.
func TestParseQuotesKeepsTheMeasuredPair(t *testing.T) {
	q := ParseQuotes(flowJSON(t, `{"ok":true,"quotes":[{"symbol":"ECHO","price":10,"volume":1300,"bid":9.9,"ask":10,"buy_volume":500,"sell_volume":800,"measured_buy":500,"measured_sell":800,"flow_method":"quote_rule","fresh":true}]}`))
	lq, ok := q.Items["ECHO"]
	if !ok || lq.MeasuredBuy == nil || lq.MeasuredSell == nil {
		t.Fatalf("the measured pair was dropped: %+v", lq)
	}
	if *lq.MeasuredBuy != 500 || *lq.MeasuredSell != 800 || lq.FlowMethod != methodMeasured {
		t.Fatalf("measured pair read as B=%d S=%d method=%q", *lq.MeasuredBuy, *lq.MeasuredSell, lq.FlowMethod)
	}
}

func TestFlowUsesTheRelayMeasuredPair(t *testing.T) {
	f := NewFlow(FlowCfg{Window: time.Minute, MinShares: 1})
	at := flowT0
	firstBuy, firstSell := int64(1000), int64(900)
	first := quotesAt(10, 1900)
	lq := first.Items["ECHO"]
	lq.FlowMethod = methodMeasured
	lq.MeasuredBuy, lq.MeasuredSell = &firstBuy, &firstSell
	first.Items["ECHO"] = lq
	if got := f.Observe(at, first, true); len(got) != 0 {
		t.Fatalf("the first frame is a baseline, not a flag: %+v", got)
	}

	nextBuy, nextSell := int64(1000), int64(1200)
	next := quotesAt(10, 2200) // the last price is deliberately unchanged
	lq = next.Items["ECHO"]
	lq.FlowMethod = methodMeasured
	lq.MeasuredBuy, lq.MeasuredSell = &nextBuy, &nextSell
	next.Items["ECHO"] = lq
	f.Observe(at.Add(3*time.Second), next, true)

	sf := f.sym["ECHO"]
	if sf == nil {
		t.Fatal("ECHO was not observed")
	}
	buy, sell, _, _, _, _ := f.sums(at.Add(3*time.Second), sf)
	if buy != 0 || sell != 300 {
		t.Fatalf("measured sell 300 read as B=%d S=%d", buy, sell)
	}
}

// Both sides can advance in one relay frame. Neither side may be lost because
// the other side happened to be appended last.
func TestFlowKeepsBothMeasuredSidesInOneFrame(t *testing.T) {
	f := NewFlow(FlowCfg{Window: time.Minute, MinShares: 1})
	at := flowT0
	buy, sell := int64(1000), int64(1000)
	first := quotesAt(10, 2000)
	lq := first.Items["ECHO"]
	lq.FlowMethod = methodMeasured
	lq.MeasuredBuy, lq.MeasuredSell = &buy, &sell
	first.Items["ECHO"] = lq
	f.Observe(at, first, true)

	nextBuy, nextSell := int64(1250), int64(1100)
	next := quotesAt(10, 2350)
	lq = next.Items["ECHO"]
	lq.FlowMethod = methodMeasured
	lq.MeasuredBuy, lq.MeasuredSell = &nextBuy, &nextSell
	next.Items["ECHO"] = lq
	f.Observe(at.Add(2*time.Second), next, true)

	sf := f.sym["ECHO"]
	buyTotal, sellTotal, _, _, _, _ := f.sums(at.Add(2*time.Second), sf)
	if buyTotal != 250 || sellTotal != 100 {
		t.Fatalf("both sides read as B=%d S=%d, want B=250 S=100", buyTotal, sellTotal)
	}
}
