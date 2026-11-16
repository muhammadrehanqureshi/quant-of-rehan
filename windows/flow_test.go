package main

import (
	"strings"
	"testing"
	"time"
)

// feed builds a /quotes answer with the given stocks.
func feedOf(items map[string]LiveQuote) *Quotes {
	return &Quotes{OK: true, Items: items}
}

func lq(price float64, vol int64) LiveQuote {
	return LiveQuote{Price: price, Fresh: true, Volume: vol, AgeSeconds: 0}
}

var flowT0 = time.Date(2026, 11, 2, 11, 0, 0, 0, pkt) // a Monday, mid session

// buy runs one stock up the tape: each second the price ticks up and shares
// are added. It returns every flag raised.
func buy(f *Flow, sym string, secs int, perSec int64, start float64, vol0 int64) []Flag {
	var out []Flag
	px, vol := start, vol0
	for i := 0; i < secs; i++ {
		px += 0.01
		vol += perSec
		out = append(out, f.Observe(flowT0.Add(time.Duration(i+1)*time.Second), feedOf(map[string]LiveQuote{sym: lq(px, vol)}), true)...)
	}
	return out
}

func TestFlowAlertsEveryOneSecondOrderWithTheOwnersWording(t *testing.T) {
	f := NewFlow(defaultFlowCfg(100_000))
	f.Observe(flowT0, feedOf(map[string]LiveQuote{"ECHO": lq(15, 1_000_000)}), true) // baseline
	flags := buy(f, "ECHO", 3, 100_000, 15, 1_000_000)
	if len(flags) != 3 {
		t.Fatalf("every 100k share second must alert, got %d: %+v", len(flags), flags)
	}
	fl := flags[0]
	if fl.Text != "ECHO is getting big buying orders" {
		t.Errorf("text: %q", fl.Text)
	}
	if fl.Kind != "order" || fl.Value != 100_000 || fl.Shares != 100_000 {
		t.Errorf("flag: %+v", fl)
	}
	if fl.Time.Sub(flowT0) != time.Second {
		t.Errorf("the first order flagged after %v", fl.Time.Sub(flowT0))
	}
	if !strings.Contains(fl.Detail, "Bought 100k shares in one second") {
		t.Errorf("detail: %q", fl.Detail)
	}
}

func TestFlowFlagsSellingAndHonoursTheSwitch(t *testing.T) {
	// Heavy volume while the price falls is selling, and each 100k share
	// second is its own order alert.
	f := NewFlow(defaultFlowCfg(100_000))
	f.Observe(flowT0, feedOf(map[string]LiveQuote{"SELL": lq(15, 1_000_000)}), true)
	px, vol := 15.0, int64(1_000_000)
	var got []Flag
	for i := 1; i <= 2; i++ {
		px -= 0.01
		vol += 100_000
		got = append(got, f.Observe(flowT0.Add(time.Duration(i)*time.Second), feedOf(map[string]LiveQuote{"SELL": lq(px, vol)}), true)...)
	}
	if len(got) != 2 || got[0].Side != "SELL" || got[0].Text != "SELL is getting big selling orders" || got[0].Value != 100_000 {
		t.Fatalf("selling must raise a SELL flag for each order: %+v", got)
	}
	if !strings.Contains(got[0].Detail, "Sold 100k shares in one second") {
		t.Errorf("detail: %q", got[0].Detail)
	}
	// With the selling flag off, the same tape raises nothing.
	f = NewFlow(defaultFlowCfg(100_000))
	f.Sell = false
	f.Observe(flowT0, feedOf(map[string]LiveQuote{"SELL": lq(15, 1_000_000)}), true)
	px, vol = 15.0, 1_000_000
	for i := 1; i <= 2; i++ {
		px -= 0.01
		vol += 100_000
		if got := f.Observe(flowT0.Add(time.Duration(i)*time.Second), feedOf(map[string]LiveQuote{"SELL": lq(px, vol)}), true); len(got) != 0 {
			t.Fatalf("selling flag is off but %+v was raised", got)
		}
	}
	// One share under the floor is not a big order.
	f = NewFlow(defaultFlowCfg(100_000))
	f.Observe(flowT0, feedOf(map[string]LiveQuote{"TINY": lq(15, 1_000_000)}), true)
	if got := buy(f, "TINY", 3, 99_999, 15, 1_000_000); len(got) != 0 {
		t.Fatalf("a sub-floor order was flagged: %+v", got)
	}
	// The same burst outside the session is not counted at all.
	f = NewFlow(defaultFlowCfg(100_000))
	px, vol = 15, 1_000_000
	for i := 0; i <= 3; i++ {
		px += 0.01
		vol += 100_000
		if got := f.Observe(flowT0.Add(time.Duration(i)*time.Second), feedOf(map[string]LiveQuote{"NIGHT": lq(px, vol)}), false); len(got) != 0 {
			t.Fatalf("flagged while not trading: %+v", got)
		}
	}
	if len(f.Board(flowT0.Add(4*time.Second), nil, 5)) != 0 {
		t.Errorf("nothing outside the session may reach the board")
	}
}

func TestFlowBigOrderPrint(t *testing.T) {
	f := NewFlow(defaultFlowCfg(100_000))
	f.Observe(flowT0, feedOf(map[string]LiveQuote{"BLOK": lq(50, 2_000_000)}), true)
	// A quiet second, then one second with 1,000,000 shares at a higher price.
	f.Observe(flowT0.Add(time.Second), feedOf(map[string]LiveQuote{"BLOK": lq(50.05, 2_001_000)}), true)
	got := f.Observe(flowT0.Add(2*time.Second), feedOf(map[string]LiveQuote{"BLOK": lq(50.10, 3_001_000)}), true)
	if len(got) != 1 || got[0].Kind != "order" || got[0].Symbol != "BLOK" {
		t.Fatalf("big order: %+v", got)
	}
	if !strings.Contains(got[0].Detail, "Bought 1M shares in one second") {
		t.Errorf("detail: %q", got[0].Detail)
	}
}

func TestFlowAlertsEveryOrderWithoutCooldown(t *testing.T) {
	f := NewFlow(defaultFlowCfg(100_000))
	f.Observe(flowT0, feedOf(map[string]LiveQuote{"ECHO": lq(15, 1_000_000)}), true)
	flags := buy(f, "ECHO", 5, 100_000, 15, 1_000_000)
	if len(flags) != 5 {
		t.Fatalf("five orders must raise five alerts, got %d: %+v", len(flags), flags)
	}
	for i, fl := range flags {
		if want := flowT0.Add(time.Duration(i+1) * time.Second); !fl.Time.Equal(want) {
			t.Errorf("alert %d at %v, want %v", i, fl.Time, want)
		}
	}
}

func TestFlowGapResetsTheBaseline(t *testing.T) {
	f := NewFlow(defaultFlowCfg(100_000))
	f.Observe(flowT0, feedOf(map[string]LiveQuote{"GAP": lq(15, 1_000_000)}), true)
	// Thirty seconds of silence, then a huge volume jump. Nobody knows how that
	// volume was split over the gap, so it is not counted as buying.
	got := f.Observe(flowT0.Add(30*time.Second), feedOf(map[string]LiveQuote{"GAP": lq(15.5, 9_000_000)}), true)
	if len(got) != 0 {
		t.Fatalf("a gap must not become a flag: %+v", got)
	}
	// A volume that goes backwards (a new day) also starts again.
	got = f.Observe(flowT0.Add(31*time.Second), feedOf(map[string]LiveQuote{"GAP": lq(15.5, 100)}), true)
	if len(got) != 0 {
		t.Fatalf("volume going backwards: %+v", got)
	}
}

func TestFlowNeverSilencesAQualifyingOrder(t *testing.T) {
	f := NewFlow(defaultFlowCfg(100_000))
	items0, items := map[string]LiveQuote{}, map[string]LiveQuote{}
	syms := []string{"S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9"}
	for _, s := range syms {
		items0[s] = lq(15, 1_000_000)
	}
	f.Observe(flowT0, feedOf(items0), true)
	var all []Flag
	for i := 1; i <= 10; i++ {
		for _, s := range syms {
			items[s] = lq(15+0.01*float64(i), 1_000_000+int64(i)*1_000_000)
		}
		all = append(all, f.Observe(flowT0.Add(time.Duration(i)*time.Second), feedOf(copyItems(items)), true)...)
	}
	quiet := 0
	for _, fl := range all {
		if fl.Silent {
			quiet++
		}
	}
	if quiet != 0 {
		t.Errorf("%d qualifying orders were silenced", quiet)
	}
	if len(f.Log) != len(all) {
		t.Errorf("every order belongs in the log: %d of %d", len(f.Log), len(all))
	}
}

func copyItems(m map[string]LiveQuote) map[string]LiveQuote {
	out := make(map[string]LiveQuote, len(m))
	for k, v := range m {
		out[k] = v
	}
	return out
}

func TestFlowAllowListAndStaleQuotes(t *testing.T) {
	f := NewFlow(defaultFlowCfg(100_000))
	f.Allow = func(s string) bool { return s == "KEEP" }
	f.Observe(flowT0, feedOf(map[string]LiveQuote{"KEEP": lq(15, 1_000_000), "DROP": lq(15, 1_000_000)}), true)
	px, vol := 15.0, int64(1_000_000)
	var got []Flag
	for i := 1; i <= 30; i++ {
		px += 0.01
		vol += 100_000
		stale := lq(px, vol)
		stale.Fresh = false
		got = append(got, f.Observe(flowT0.Add(time.Duration(i)*time.Second),
			feedOf(map[string]LiveQuote{"KEEP": lq(px, vol), "DROP": lq(px, vol), "OLD": stale}), true)...)
	}
	for _, fl := range got {
		if fl.Symbol != "KEEP" {
			t.Errorf("only the allowed fresh symbol may flag, got %s", fl.Symbol)
		}
	}
	if len(got) == 0 {
		t.Errorf("KEEP should have flagged")
	}
}

func TestFlowBoardOrder(t *testing.T) {
	f := NewFlow(defaultFlowCfg(1_000_000_000)) // flags off the table, board only
	base := map[string]LiveQuote{"AAA": lq(10, 1_000_000), "BBB": lq(20, 1_000_000), "CCC": lq(30, 1_000_000)}
	f.Observe(flowT0, feedOf(base), true)
	for i := 1; i <= 5; i++ {
		f.Observe(flowT0.Add(time.Duration(i)*time.Second), feedOf(map[string]LiveQuote{
			"AAA": lq(10+0.01*float64(i), 1_000_000+int64(i)*10_000),  // PKR 0.1M a second
			"BBB": lq(20+0.01*float64(i), 1_000_000+int64(i)*100_000), // PKR 2M
			"CCC": lq(30-0.01*float64(i), 1_000_000+int64(i)*500_000), // selling
		}), true)
	}
	board := f.Board(flowT0.Add(5*time.Second), nil, 10)
	if len(board) != 2 || board[0].Symbol != "BBB" || board[1].Symbol != "AAA" {
		t.Fatalf("board: %+v", board)
	}
	if board[0].Share < 0.99 {
		t.Errorf("share: %v", board[0].Share)
	}
}

func TestCompactNum(t *testing.T) {
	for _, c := range []struct {
		in   float64
		want string
	}{{950, "950"}, {1250, "1.25k"}, {18_400_000, "18.4M"}, {3.1e9, "3.10B"}, {10_000_000, "10M"}, {1000, "1k"}, {1_000_000, "1M"}} {
		if got := compactNum(c.in); got != c.want {
			t.Errorf("compactNum(%v) = %q want %q", c.in, got, c.want)
		}
	}
}

func TestRangeSplitMatchesTheRelaysOwnFigure(t *testing.T) {
	// KEL on 2026-10-30, as the relay reported it.
	q := LiveQuote{Price: 5.79, Low: 5.76, High: 6.03, Volume: 21_471_271}
	b, s, ok := q.RangeSplit()
	if !ok || b != 2_385_696 && b != 2_385_697 || b+s != q.Volume {
		t.Errorf("split: %d %d %v", b, s, ok)
	}
	if _, _, ok := (LiveQuote{Price: 5, Low: 5, High: 5, Volume: 10}).RangeSplit(); ok {
		t.Errorf("a flat range has no split")
	}
	if _, _, ok := (LiveQuote{Price: 9, Low: 5, High: 6, Volume: 10}).RangeSplit(); ok {
		t.Errorf("a price outside its own range has no split")
	}
}
