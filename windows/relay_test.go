package main

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func mustJ(t *testing.T, s string) J {
	t.Helper()
	dec := json.NewDecoder(strings.NewReader(s))
	dec.UseNumber()
	var m map[string]any
	if err := dec.Decode(&m); err != nil {
		t.Fatal(err)
	}
	return J(m)
}

const marketOpenJSON = `{
 "ok": true, "market_open": true, "date": "2026-11-02", "karachi_now": "2026-11-02 11:42 PKT",
 "cache_age_seconds": 3, "kmiall_members": 313,
 "top_volume_basis": "current session volume, top 3",
 "volume_split_basis": "B/S estimated from the day's range, not order flow",
 "market_state": {"phase": "OPEN", "condition": "OPERATIONAL", "condition_text": "", "trading_day": true, "market_open": true,
   "next_event": {"event": "BREAK", "at_pk": "2026-11-02 12:00"}},
 "market_feed": {"status": "ACTIVE", "raw_status": "A", "as_of": "11:42:10", "fresh": true},
 "market_transition": {"state": "OPEN", "evidence": "feed", "delivered": true},
 "index": {"value": 166409.25, "change": -784.18, "change_pct": -0.469, "as_of": "11:42:09", "source": "broker feed"},
 "top_volume": [
   {"symbol": "ECHO", "volume": 2505082, "price": 15.07, "change_pct": 5.09, "buy_volume": 2125082, "sell_volume": 380000, "split_method": "range"},
   {"symbol": "CHRL", "volume": 12162108, "price": 7.87, "change_pct": -0.45, "buy_volume": 5262108, "sell_volume": 6900000},
   {"symbol": "ALFA", "volume": 4700728, "price": 42.11, "change_pct": 2.38, "buy_volume": 3450728, "sell_volume": 1250000},
   {"symbol": "EXTRA", "volume": 1}
 ],
 "notes": ["first note", "second note"]
}`

func TestParseMarket(t *testing.T) {
	m := ParseMarket(mustJ(t, marketOpenJSON))
	if !m.Answered || !m.Open || m.Phase != "OPEN" || m.Condition != "OPERATIONAL" || !m.TradingDay {
		t.Errorf("state: %+v", m)
	}
	if m.Date != "2026-11-02" || m.Members != 313 || m.NextEvent != "BREAK 2026-11-02 12:00" {
		t.Errorf("fields: date=%q members=%d next=%q", m.Date, m.Members, m.NextEvent)
	}
	if !m.HasIndex() || *m.IndexValue != 166409.25 || *m.IndexChange != -784.18 || m.IndexSource != "broker feed" {
		t.Errorf("index: %+v", m)
	}
	if len(m.Leaders) != 3 {
		t.Fatalf("only the top three are kept, got %d", len(m.Leaders))
	}
	l := m.Leaders[0]
	if l.Symbol != "ECHO" || *l.Volume != 2505082 || *l.Buy != 2125082 || *l.Sell != 380000 || !l.HasSplit() || !l.HasVolume() {
		t.Errorf("leader: %+v", l)
	}
	if m.FeedStatus != "ACTIVE" || !m.FeedStatusFresh || m.FeedHalted {
		t.Errorf("feed: %+v", m)
	}
	if m.Note != "first note" {
		t.Errorf("note: %q", m.Note)
	}
	if marketEvent(m) != "online" {
		t.Errorf("event")
	}
}

func TestParseMarketClosedAndOddInputs(t *testing.T) {
	m := ParseMarket(mustJ(t, `{"ok": true, "market_open": false, "stale": true, "notes": ["old"],
	  "market_state": {"phase": "CLOSED", "condition": "CLOSED", "condition_text": "Market is closed right now.", "trading_day": false},
	  "market_feed": {"status": "HALTED", "fresh": true}, "top_volume": []}`))
	if m.Open || m.Phase != "CLOSED" || m.TradingDay || len(m.Leaders) != 0 {
		t.Errorf("closed: %+v", m)
	}
	if !m.FeedHalted || !strings.HasPrefix(m.Note, "relay last refreshed earlier") {
		t.Errorf("halted/stale: halted=%v note=%q", m.FeedHalted, m.Note)
	}
	// Negative, fractional or non numeric volumes must not become numbers.
	m = ParseMarket(mustJ(t, `{"ok": true, "top_volume": [
	  {"symbol": "A", "volume": -5, "buy_volume": 1.5, "sell_volume": "x"}, "junk", {"symbol": "B", "volume": 7}]}`))
	if len(m.Leaders) != 2 || m.Leaders[0].Volume != nil || m.Leaders[0].HasSplit() || *m.Leaders[1].Volume != 7 {
		t.Errorf("odd rows: %+v", m.Leaders)
	}
	empty := ParseMarket(mustJ(t, `{}`))
	if empty.Answered || empty.PhaseKnown() || empty.HasIndex() {
		t.Errorf("empty body: %+v", empty)
	}
}

func TestParseHead(t *testing.T) {
	h := ParseHead(mustJ(t, `{"ok": true, "market_open": false, "karachi_now": "2026-10-31 02:50 PKT",
	  "market_state": {"phase": "CLOSED", "condition": "CLOSED", "condition_text": "Market is closed right now.",
	  "next_event": {"event": "OPEN", "at_pk": "2026-11-02 09:32"}}}`), phaseLine)
	if !h.Reachable || h.MarketOpen || h.Online() || h.NextEvent != "OPEN 2026-11-02 09:32" {
		t.Errorf("head: %+v", h)
	}
	if h.Detail != "Karachi: 2026-10-31 02:50 PKT\nMarket is closed right now." {
		t.Errorf("detail: %q", h.Detail)
	}
	bad := ParseHead(mustJ(t, `{"ok": false}`), phaseLine)
	if bad.Reachable || bad.Detail == "" {
		t.Errorf("fault: %+v", bad)
	}
}

func TestParsePricesAndQuotes(t *testing.T) {
	p := ParsePrices(mustJ(t, `{"prices": [["ENGRO", 285.5, 1.25, 1000, 400], ["LUCK", 700, -0.5],
	  ["BAD", 0, 1], ["NEG", -3, 1], [7, 1, 1], ["SHORT"], ["NAN", "x", 1], ["NOCHG", 10, "n/a"]]}`))
	if len(p) != 3 {
		t.Fatalf("rows kept: %v", sortedKeys(p))
	}
	e := p["ENGRO"]
	if e.Price != 285.5 || *e.ChangePct != 1.25 || *e.Buy != 1000 || *e.Sell != 400 {
		t.Errorf("ENGRO: %+v", e)
	}
	if l := p["LUCK"]; l.Buy != nil || l.Sell != nil || *l.ChangePct != -0.5 {
		t.Errorf("LUCK: %+v", l)
	}
	if n := p["NOCHG"]; n.ChangePct != nil || n.Price != 10 {
		t.Errorf("NOCHG: %+v", n)
	}

	q := ParseQuotes(mustJ(t, `{"ok": true, "index": {"value": 166400, "change": 10, "change_pct": 0.006, "fresh": true, "as_of": "11:42:09"},
	  "quotes": [{"symbol": "AAA", "price": 11.5, "change_pct": 2, "fresh": true}, {"symbol": "", "price": 1}, {"symbol": "BBB", "fresh": false}]}`))
	if !q.OK || q.Index == nil || q.Index.Value != 166400 || len(q.Items) != 2 || !q.Items["AAA"].Fresh || q.Items["BBB"].Price != 0 {
		t.Errorf("quotes: %+v", q)
	}
	stale := ParseQuotes(mustJ(t, `{"ok": true, "index": {"value": 5, "change": 1, "change_pct": 1, "fresh": false}}`))
	if stale.Index == nil || stale.Index.Fresh || stale.Index.Value != 5 {
		t.Errorf("a stale index is kept, marked as not fresh: %+v", stale.Index)
	}
	if ParseQuotes(mustJ(t, `{"ok": false}`)).OK {
		t.Errorf("not ok")
	}
}

// ---------- against a mock relay ----------

type mock struct {
	srv   *httptest.Server
	hits  atomic.Int64
	agent atomic.Value
	last  atomic.Value
}

func newMock(t *testing.T, routes map[string]func(w http.ResponseWriter, r *http.Request)) *mock {
	t.Helper()
	m := &mock{}
	m.srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		m.hits.Add(1)
		m.agent.Store(r.Header.Get("User-Agent"))
		m.last.Store(r.URL.RequestURI())
		if r.Method != http.MethodGet {
			http.Error(w, "read only", http.StatusMethodNotAllowed)
			return
		}
		if h, ok := routes[r.URL.Path]; ok {
			h(w, r)
			return
		}
		http.NotFound(w, r)
	}))
	t.Cleanup(m.srv.Close)
	return m
}

func jsonBody(s string) func(http.ResponseWriter, *http.Request) {
	return func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(s))
	}
}

func TestRelayEndpoints(t *testing.T) {
	m := newMock(t, map[string]func(http.ResponseWriter, *http.Request){
		"/market":  jsonBody(marketOpenJSON),
		"/health":  jsonBody(`{"ok": true, "market_open": true, "karachi_now": "now", "market_state": {"phase": "OPEN", "condition": "OPERATIONAL"}}`),
		"/signals": jsonBody(`{"ok": true, "signals": "QUANT OF REHAN 2026-11-02\nNO TRADE today"}`),
		"/quotes":  jsonBody(`{"ok": true, "quotes": [{"symbol": "AAA", "price": 1, "fresh": true}]}`),
		"/prices":  jsonBody(`{"prices": [["AAA", 1, 1, 5, 2]]}`),
		"/stock": func(w http.ResponseWriter, r *http.Request) {
			_, _ = w.Write([]byte(`{"ok": true, "stock": {"symbol": "` + r.URL.Query().Get("symbol") + `", "buy_volume": 10, "sell_volume": 4, "volume": 14}}`))
		},
	})
	r := NewRelay(m.srv.URL)
	ctx := context.Background()

	mk, rtt, err := r.FetchMarket(ctx)
	if err != nil || !mk.Open || len(mk.Leaders) != 3 || rtt <= 0 {
		t.Fatalf("market: %v %+v", err, mk)
	}
	h, _, err := r.FetchHead(ctx, phaseLine)
	if err != nil || !h.Online() {
		t.Fatalf("head: %v %+v", err, h)
	}
	if s, ok := r.FetchSignals(ctx); !ok || !strings.Contains(s, "NO TRADE") {
		t.Fatalf("signals: %q %v", s, ok)
	}
	if q, err := r.FetchQuotes(ctx); err != nil || len(q.Items) != 1 {
		t.Fatalf("quotes: %v %+v", err, q)
	}
	if p, err := r.FetchPrices(ctx); err != nil || *p["AAA"].Buy != 5 {
		t.Fatalf("prices: %v %+v", err, p)
	}
	st, err := r.FetchStock(ctx, "A&B C")
	if err != nil || st.Symbol != "A&B C" || *st.Buy != 10 || *st.Volume != 14 {
		t.Fatalf("stock: %v %+v", err, st)
	}
	if got := m.last.Load().(string); got != "/stock?symbol=A%26B+C" {
		t.Errorf("query must be escaped: %q", got)
	}
	if ua := m.agent.Load().(string); !strings.HasPrefix(ua, "Mozilla/5.0") || !strings.Contains(ua, "QuantOfRehan-HUD/"+appVersion) {
		t.Errorf("user agent: %q", ua)
	}
	if r.Requests() != 6 || m.hits.Load() != 6 {
		t.Errorf("request counter %d, server saw %d", r.Requests(), m.hits.Load())
	}
}

func TestRelayFailures(t *testing.T) {
	big := bytes.Repeat([]byte("a"), maxBody+10)
	m := newMock(t, map[string]func(http.ResponseWriter, *http.Request){
		"/market": func(w http.ResponseWriter, r *http.Request) {
			_, _ = w.Write(append(append([]byte(`{"ok": true, "pad": "`), big...), []byte(`"}`)...))
		},
		"/health":  func(w http.ResponseWriter, r *http.Request) { _, _ = w.Write([]byte("<html>error code: 1010</html>")) },
		"/signals": jsonBody(`{"ok": false}`),
		"/quotes":  func(w http.ResponseWriter, r *http.Request) { http.Error(w, `{"ok": false}`, 500) },
		"/stock":   jsonBody(`{"ok": false}`),
	})
	r := NewRelay(m.srv.URL)
	ctx := context.Background()

	mk, _, err := r.FetchMarket(ctx)
	if err == nil || errKind(err) != "PayloadTooLarge" || mk == nil || !strings.Contains(mk.Note, "more data than this app accepts") {
		t.Errorf("oversize: err=%v market=%+v", err, mk)
	}
	if _, _, err := r.get(ctx, "/health"); err == nil || !strings.Contains(err.Error(), "not a JSON object") {
		t.Errorf("html body: %v", err)
	}
	if s, ok := r.FetchSignals(ctx); ok || s != "Signals are unavailable from the relay." {
		t.Errorf("signals not ok: %q %v", s, ok)
	}
	if q, err := r.FetchQuotes(ctx); err != nil || q.OK {
		t.Errorf("a 500 with a JSON body parses as not ok: %v %+v", err, q)
	}
	if _, err := r.FetchStock(ctx, "ZZZ"); err == nil {
		t.Errorf("stock not ok must be an error")
	}
	if _, err := r.FetchPrices(ctx); err == nil {
		t.Errorf("404 page is not JSON, should fail")
	}
}

func TestRelayUnreachableAndCancel(t *testing.T) {
	r := NewRelay("http://127.0.0.1:1") // nothing listens on port 1
	_, _, err := r.FetchMarket(context.Background())
	if err == nil {
		t.Fatal("expected a connection error")
	}
	if k := errKind(err); k != "ConnectException" {
		t.Errorf("kind: %s (%v)", k, err)
	}
	if got := unreachableText(err); got != "No route to the relay from this PC. Check internet or VPN. (ConnectException)" {
		t.Errorf("text: %q", got)
	}

	slow := newMock(t, map[string]func(http.ResponseWriter, *http.Request){
		"/market": func(w http.ResponseWriter, r *http.Request) { time.Sleep(2 * time.Second) },
	})
	ctx, cancel := context.WithTimeout(context.Background(), 150*time.Millisecond)
	defer cancel()
	start := time.Now()
	_, _, err = NewRelay(slow.srv.URL).FetchMarket(ctx)
	if err == nil || errKind(err) != "Timeout" || time.Since(start) > time.Second {
		t.Errorf("timeout: %v after %v", err, time.Since(start))
	}
	if got := unreachableText(err); got != "The relay did not answer in time. Will retry. (Timeout)" {
		t.Errorf("text: %q", got)
	}
}

func TestHealthRetriesOnce(t *testing.T) {
	var calls atomic.Int64
	m := newMock(t, map[string]func(http.ResponseWriter, *http.Request){
		"/health": func(w http.ResponseWriter, r *http.Request) {
			if calls.Add(1) == 1 {
				hj, _ := w.(http.Hijacker)
				c, _, _ := hj.Hijack()
				_ = c.Close() // drop the first call
				return
			}
			_, _ = w.Write([]byte(`{"ok": true, "market_open": false, "market_state": {"phase": "CLOSED"}}`))
		},
	})
	h, _, err := NewRelay(m.srv.URL).FetchHead(context.Background(), phaseLine)
	if err != nil || h == nil || !h.Reachable || calls.Load() != 2 {
		t.Fatalf("retry: err=%v calls=%d head=%+v", err, calls.Load(), h)
	}
}

func TestRelayIsReadOnly(t *testing.T) {
	// Every call this program makes is a GET; the mock rejects anything else,
	// and the code has no other method in it.
	m := newMock(t, map[string]func(http.ResponseWriter, *http.Request){"/health": jsonBody(`{"ok": true}`)})
	resp, err := http.Post(m.srv.URL+"/health", "text/plain", strings.NewReader("x"))
	if err != nil || resp.StatusCode != http.StatusMethodNotAllowed {
		t.Fatalf("mock sanity: %v", err)
	}
	resp.Body.Close()
}
