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

func TestFlowFlagsSustainedBuyingWithTheOwnersWording(t *testing.T) {
	f := NewFlow(defaultFlowCfg(10_000_000))
	f.Observe(flowT0, feedOf(map[string]LiveQuote{"ECHO": lq(15, 1_000_000)}), true) // baseline
	flags := buy(f, "ECHO", 30, 100_000, 15, 1_000_000)                              // PKR 1.5M every second
	if len(flags) != 1 {
		t.Fatalf("one flag expected for one burst, got %d: %+v", len(flags), flags)
	}
	fl := flags[0]
	if fl.Text != "ECHO is getting big buying orders" {
		t.Errorf("text: %q", fl.Text)
	}
	if fl.Kind != "flow" || fl.Value < 10_000_000 || fl.Share < 0.99 {
		t.Errorf("flag: %+v", fl)
	}
	// It must not fire before PKR 10M has gone through: at 1.5M a second that
	// is the seventh second at the earliest.
	if got := fl.Time.Sub(flowT0).Seconds(); got < 7 || got > 9 {
		t.Errorf("flagged after %.0f s, want 7 to 9", got)
	}
	if !strings.Contains(fl.Detail, "Buyers made up 100%") || !strings.Contains(fl.Detail, "PKR") {
		t.Errorf("detail: %q", fl.Detail)
	}
}

func TestFlowFlagsSellingAndHonoursTheSwitch(t *testing.T) {
	// Heavy volume while the price falls is selling, and it is flagged as such.
	f := NewFlow(defaultFlowCfg(10_000_000))
	f.Observe(flowT0, feedOf(map[string]LiveQuote{"SELL": lq(15, 1_000_000)}), true)
	px, vol := 15.0, int64(1_000_000)
	var got []Flag
	for i := 1; i <= 40; i++ {
		px -= 0.01
		vol += 100_000
		got = append(got, f.Observe(flowT0.Add(time.Duration(i)*time.Second), feedOf(map[string]LiveQuote{"SELL": lq(px, vol)}), true)...)
	}
	if len(got) != 1 || got[0].Side != "SELL" || got[0].Text != "SELL is getting big selling orders" || got[0].Value < 10_000_000 {
		t.Fatalf("selling must raise one SELL flag: %+v", got)
	}
	if !strings.Contains(got[0].Detail, "Sold PKR") || !strings.Contains(got[0].Detail, "Sellers made up") {
		t.Errorf("detail: %q", got[0].Detail)
	}
	// With the selling flag off, the same tape raises nothing.
	f = NewFlow(defaultFlowCfg(10_000_000))
	f.Sell = false
	f.Observe(flowT0, feedOf(map[string]LiveQuote{"SELL": lq(15, 1_000_000)}), true)
	px, vol = 15.0, 1_000_000
	for i := 1; i <= 40; i++ {
		px -= 0.01
		vol += 100_000
		if got := f.Observe(flowT0.Add(time.Duration(i)*time.Second), feedOf(map[string]LiveQuote{"SELL": lq(px, vol)}), true); len(got) != 0 {
			t.Fatalf("selling flag is off but %+v was raised", got)
		}
	}
	// Small trades going up are not big.
	f = NewFlow(defaultFlowCfg(10_000_000))
	f.Observe(flowT0, feedOf(map[string]LiveQuote{"TINY": lq(15, 1_000_000)}), true)
	if got := buy(f, "TINY", 55, 3_000, 15, 1_000_000); len(got) != 0 {
		t.Fatalf("small buying was flagged: %+v", got)
	}
	// The same burst outside the session is not counted at all.
	f = NewFlow(defaultFlowCfg(10_000_000))
	px, vol = 15, 1_000_000
	for i := 0; i <= 30; i++ {
		px += 0.01
		vol += 100_000
		if got := f.Observe(flowT0.Add(time.Duration(i)*time.Second), feedOf(map[string]LiveQuote{"NIGHT": lq(px, vol)}), false); len(got) != 0 {
			t.Fatalf("flagged while not trading: %+v", got)
		}
	}
	if len(f.Board(flowT0.Add(31*time.Second), nil, 5)) != 0 {
		t.Errorf("nothing outside the session may reach the board")
	}
}

func TestFlowBlockPrint(t *testing.T) {
	f := NewFlow(defaultFlowCfg(10_000_000))
	f.Observe(flowT0, feedOf(map[string]LiveQuote{"BLOK": lq(50, 2_000_000)}), true)
	// A quiet second, then one second with 1,000,000 shares at a higher price.
	f.Observe(flowT0.Add(time.Second), feedOf(map[string]LiveQuote{"BLOK": lq(50.05, 2_001_000)}), true)
	got := f.Observe(flowT0.Add(2*time.Second), feedOf(map[string]LiveQuote{"BLOK": lq(50.10, 3_001_000)}), true)
	if len(got) != 1 || got[0].Kind != "block" || got[0].Symbol != "BLOK" {
		t.Fatalf("block print: %+v", got)
	}
	if !strings.Contains(got[0].Detail, "A block buy of PKR 50.1M") {
		t.Errorf("detail: %q", got[0].Detail)
	}
}

func TestFlowCooldownAndEscalation(t *testing.T) {
	f := NewFlow(defaultFlowCfg(10_000_000))
	f.Observe(flowT0, feedOf(map[string]LiveQuote{"ECHO": lq(15, 1_000_000)}), true)
	// A long burst at 1.5M a second: one flag at about 10M, and no second flag
	// until the buying has tripled and a minute has passed.
	flags := buy(f, "ECHO", 90, 100_000, 15, 1_000_000)
	for _, fl := range flags {
		t.Logf("flag at +%v: PKR %.1fM", fl.Time.Sub(flowT0), fl.Value/1e6)
	}
	if len(flags) == 0 || len(flags) > 2 {
		t.Fatalf("a long burst must flag once, or twice at most, got %d", len(flags))
	}
	if len(flags) == 2 && flags[1].Time.Sub(flags[0].Time) < time.Minute {
		t.Errorf("a second flag came inside a minute")
	}
}

func TestFlowGapResetsTheBaseline(t *testing.T) {
	f := NewFlow(defaultFlowCfg(10_000_000))
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

func TestFlowQuietAfterTooManyInAMinute(t *testing.T) {
	f := NewFlow(defaultFlowCfg(10_000_000))
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
	loud, quiet := 0, 0
	for _, fl := range all {
		if fl.Silent {
			quiet++
		} else {
			loud++
		}
	}
	if loud != f.cfg.MaxPerMin || quiet == 0 {
		t.Errorf("loud %d quiet %d, want %d loud then the rest quiet", loud, quiet, f.cfg.MaxPerMin)
	}
	if len(f.Log) != len(all) {
		t.Errorf("quiet flags still belong in the log: %d of %d", len(f.Log), len(all))
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
	f := NewFlow(defaultFlowCfg(10_000_000))
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
	}{{950, "950"}, {1250, "1.25K"}, {18_400_000, "18.4M"}, {3.1e9, "3.10B"}, {10_000_000, "10.0M"}, {1000, "1K"}} {
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
