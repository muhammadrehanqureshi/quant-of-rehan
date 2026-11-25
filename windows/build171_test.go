package main

import (
	"testing"
	"time"
)

// Owner order 2026-11-25: the post-market window prints real trades, 15:32 to
// 15:49 Monday to Thursday and 16:32 to 16:49 on Friday, so the HUD counts
// them. Outside it nothing counts: not the two minute gap after the live
// close, not the tail after the window, not a holiday.
func TestBuild171ThePostMarketWindowCountsTrades(t *testing.T) {
	a := newTestApp(t)
	a.link, a.checking = true, false
	a.market = marketIn("POST_CLOSE")
	cases := []struct {
		at   time.Time
		want bool
	}{
		{time.Date(2026, 11, 23, 15, 31, 59, 0, pkt), false},
		{time.Date(2026, 11, 23, 15, 32, 0, 0, pkt), true},
		{time.Date(2026, 11, 23, 15, 48, 0, 0, pkt), true},
		{time.Date(2026, 11, 23, 15, 50, 0, 0, pkt), false},
		// Friday's post-market is an hour later; 15:40 there is still the
		// live band and not a post-market minute.
		{time.Date(2026, 11, 27, 15, 40, 0, 0, pkt), false},
		{time.Date(2026, 11, 27, 16, 31, 59, 0, pkt), false},
		{time.Date(2026, 11, 27, 16, 32, 0, 0, pkt), true},
		{time.Date(2026, 11, 27, 16, 48, 0, 0, pkt), true},
		{time.Date(2026, 11, 27, 16, 50, 0, 0, pkt), false},
		// A PSX holiday prints nothing, whatever the clock says.
		{time.Date(2026, 11, 9, 15, 40, 0, 0, pkt), false},
	}
	for _, c := range cases {
		a.now = c.at
		if got := a.trading(); got != c.want {
			t.Errorf("%s: trading is %v, want %v",
				c.at.Format("Mon 15:04:05"), got, c.want)
		}
	}
}

// Owner order 2026-11-25: one post-market print is one transaction, so the
// boards, the leaders and the ALERTS LOG carry it. This is the defect the
// owner reported: the rows stayed on the live close's numbers.
func TestBuild171APostMarketPrintReachesTheBoards(t *testing.T) {
	step := func(at time.Time) int64 {
		a := newTestApp(t)
		a.link, a.checking = true, false
		a.market = marketIn("POST_CLOSE")
		a.now = at
		q := &Quotes{OK: true, FetchedAt: at, Items: map[string]LiveQuote{
			"KEL": {Price: 6.09, Volume: 1_000_000, Fresh: true},
		}}
		// The first frame seeds the baseline, exactly as it does live.
		a.flow.Observe(a.now, q, a.trading())
		kel := q.Items["KEL"]
		kel.Volume = 1_060_000
		q.Items["KEL"] = kel
		a.now = at.Add(time.Second)
		a.flow.Observe(a.now, q, a.trading())
		sf := a.flow.sym["KEL"]
		if sf == nil || len(sf.evts) == 0 {
			return 0
		}
		return sf.evts[0].dv
	}
	if got := step(time.Date(2026, 11, 23, 15, 40, 0, 0, pkt)); got != 60_000 {
		t.Fatalf("Monday's post-market print recorded %d shares, want 60000", got)
	}
	if got := step(time.Date(2026, 11, 27, 16, 40, 0, 0, pkt)); got != 60_000 {
		t.Fatalf("Friday's post-market print recorded %d shares, want 60000", got)
	}
	if got := step(time.Date(2026, 11, 23, 15, 55, 0, 0, pkt)); got != 0 {
		t.Fatalf("a print after the window recorded %d shares, want none", got)
	}
	if got := step(time.Date(2026, 11, 23, 15, 31, 0, 0, pkt)); got != 0 {
		t.Fatalf("a print before the window recorded %d shares, want none", got)
	}
}
