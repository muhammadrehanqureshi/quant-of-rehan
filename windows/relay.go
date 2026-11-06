package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"net"
	"net/http"
	"net/url"
	"os"
	"sort"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

const (
	defaultRelay = "https://quant-of-rehan-relay.mrmrehanqureshi.workers.dev"
	maxBody      = 524288
	// The relay sits behind Cloudflare, whose browser integrity check refuses
	// some default client strings (the project report records an HTTP 403 with
	// error code 1010 for Python's urllib). A browser style prefix avoids it.
	userAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) QuantOfRehan-HUD/" + appVersion
)

var errPayloadTooLarge = errors.New("relay body exceeded 524288 characters")

// Relay talks to the Cloudflare worker. It is read only: every call is a GET.
type Relay struct {
	Base   string
	Client *http.Client
	reqs   atomic.Int64

	// The relay's own clock, read from the Date header of every answer. It is
	// the world's clock: the top right clock follows it, so a PC whose clock is
	// wrong still shows Karachi's real time.
	clockMu sync.Mutex
	skews   []float64 // seconds the relay is ahead of this PC, newest last
}

// validRelayURL accepts only http and https addresses with a host. The relay
// address ends up in HTTP calls and in the browser launcher, so nothing like
// a file: path or a program name is allowed through.
func validRelayURL(s string) bool {
	u, err := url.Parse(s)
	return err == nil && (u.Scheme == "http" || u.Scheme == "https") && u.Host != "" && u.User == nil
}

func NewRelay(base string) *Relay {
	base = strings.TrimRight(strings.TrimSpace(base), "/")
	if base == "" || !validRelayURL(base) {
		base = defaultRelay
	}
	return &Relay{
		Base: base,
		Client: &http.Client{
			Timeout: 20 * time.Second,
			Transport: &http.Transport{
				Proxy:                 http.ProxyFromEnvironment,
				DialContext:           (&net.Dialer{Timeout: 8 * time.Second}).DialContext,
				TLSHandshakeTimeout:   8 * time.Second,
				ResponseHeaderTimeout: 12 * time.Second,
				MaxIdleConns:          4,
				IdleConnTimeout:       60 * time.Second,
			},
		},
	}
}

// Requests returns how many HTTP calls this process has made.
func (r *Relay) Requests() int64 { return r.reqs.Load() }

// J is a loosely typed JSON object with accessors that mirror org.json's opt*.
type J map[string]any

func (j J) has(k string) bool { _, ok := j[k]; return ok }

func (j J) str(k, def string) string {
	switch v := j[k].(type) {
	case string:
		return v
	case json.Number:
		return v.String()
	case bool:
		return strconv.FormatBool(v)
	}
	return def
}

func (j J) boolean(k string, def bool) bool {
	if v, ok := j[k].(bool); ok {
		return v
	}
	return def
}

func (j J) intDef(k string, def int) int {
	if v, ok := j[k].(json.Number); ok {
		if f, err := v.Float64(); err == nil && !math.IsNaN(f) && !math.IsInf(f, 0) {
			return int(f)
		}
	}
	return def
}

// num is numberOrNull: a finite number, else nil.
func (j J) num(k string) *float64 {
	v, ok := j[k].(json.Number)
	if !ok {
		return nil
	}
	f, err := v.Float64()
	if err != nil || math.IsNaN(f) || math.IsInf(f, 0) {
		return nil
	}
	return &f
}

// integer is integerOrNull: a non negative whole number, else nil.
func (j J) integer(k string) *int64 {
	v, ok := j[k].(json.Number)
	if !ok {
		return nil
	}
	return asNonNegInt(v)
}

func asNonNegInt(v json.Number) *int64 {
	if n, err := strconv.ParseInt(v.String(), 10, 64); err == nil {
		if n < 0 {
			return nil
		}
		return &n
	}
	f, err := v.Float64()
	if err != nil || math.IsNaN(f) || math.IsInf(f, 0) || f < 0 || f != math.Trunc(f) || f > 9e15 {
		return nil
	}
	n := int64(f)
	return &n
}

func (j J) obj(k string) J {
	if v, ok := j[k].(map[string]any); ok {
		return J(v)
	}
	return nil
}

func (j J) arr(k string) []any {
	if v, ok := j[k].([]any); ok {
		return v
	}
	return nil
}

func objOf(v any) J {
	if m, ok := v.(map[string]any); ok {
		return J(m)
	}
	return nil
}

// skewKeep is how many answers the clock offset is averaged over. The Date
// header only has whole seconds, so one answer is good to a second and thirty
// answers are good to a small fraction of one.
const skewKeep = 30

// noteDate records how far the relay's clock is ahead of this PC, from one
// answer. The header is the edge's own time truncated to the second, so half a
// second is added back, and the PC's side is taken at the middle of the round
// trip.
func (r *Relay) noteDate(header string, sent, got time.Time) {
	edge, err := http.ParseTime(header)
	if err != nil || got.Before(sent) {
		return
	}
	mid := sent.Add(got.Sub(sent) / 2)
	skew := edge.Add(500 * time.Millisecond).Sub(mid).Seconds()
	if math.Abs(skew) > 86400 {
		return
	}
	r.clockMu.Lock()
	defer r.clockMu.Unlock()
	r.skews = append(r.skews, skew)
	if len(r.skews) > skewKeep {
		r.skews = r.skews[len(r.skews)-skewKeep:]
	}
}

// ClockSkew is how far the relay's clock is ahead of this PC's (negative when
// behind), or zero until an answer has arrived.
func (r *Relay) ClockSkew() time.Duration {
	r.clockMu.Lock()
	defer r.clockMu.Unlock()
	if len(r.skews) == 0 {
		return 0
	}
	sum := 0.0
	for _, v := range r.skews {
		sum += v
	}
	return time.Duration(sum / float64(len(r.skews)) * float64(time.Second))
}

// get fetches one path and returns the decoded object, like Watcher.get.
func (r *Relay) get(ctx context.Context, path string) (J, time.Duration, error) {
	return r.getLimit(ctx, path, maxBody)
}

// maxFlowBody is the size limit for /orderflow, which carries a row for every
// KMIALL stock and the large print board.
const maxFlowBody = 4 << 20

var errFlowNotOK = errors.New("the relay's order flow answer did not say ok")

// getLimit is get with its own size limit for the body.
func (r *Relay) getLimit(ctx context.Context, path string, limit int) (J, time.Duration, error) {
	start := time.Now()
	r.reqs.Add(1)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, r.Base+path, nil)
	if err != nil {
		return nil, 0, err
	}
	req.Header.Set("User-Agent", userAgent)
	req.Header.Set("Accept", "application/json")
	resp, err := r.Client.Do(req)
	if err != nil {
		return nil, time.Since(start), err
	}
	defer resp.Body.Close()
	r.noteDate(resp.Header.Get("Date"), start, time.Now())
	body, err := io.ReadAll(io.LimitReader(resp.Body, int64(limit)+1))
	if err != nil {
		return nil, time.Since(start), err
	}
	if len(body) > limit {
		return nil, time.Since(start), errPayloadTooLarge
	}
	dec := json.NewDecoder(bytes.NewReader(body))
	dec.UseNumber()
	var out map[string]any
	if err := dec.Decode(&out); err != nil {
		return nil, time.Since(start), fmt.Errorf("relay returned HTTP %d with a body that is not a JSON object", resp.StatusCode)
	}
	return J(out), time.Since(start), nil
}

// errKind gives a short, stable name for a failure, like the exception names
// the phone shows.
func errKind(err error) string {
	var dns *net.DNSError
	var op *net.OpError
	switch {
	case err == nil:
		return ""
	case errors.Is(err, errPayloadTooLarge):
		return "PayloadTooLarge"
	case errors.Is(err, context.DeadlineExceeded):
		return "Timeout"
	case errors.As(err, &dns):
		return "UnknownHost"
	case errors.As(err, &op):
		if op.Timeout() {
			return "Timeout"
		}
		return "ConnectException"
	}
	var ne net.Error
	if errors.As(err, &ne) && ne.Timeout() {
		return "Timeout"
	}
	return "Error"
}

func unreachableText(err error) string {
	k := errKind(err)
	msg := "The relay did not answer in time. Will retry."
	if k == "UnknownHost" || k == "ConnectException" {
		msg = "No route to the relay from this PC. Check internet or VPN."
	}
	return msg + " (" + k + ")"
}

func readPhase(o J, m *Market) {
	if o == nil {
		return
	}
	if v := o.str("phase", ""); v != "" {
		m.Phase = v
	}
	if v := o.str("condition", ""); v != "" {
		m.Condition = v
	}
	m.ConditionText = o.str("condition_text", "")
	m.TradingDay = o.boolean("trading_day", m.TradingDay)
	if o.has("market_open") {
		m.Open = o.boolean("market_open", m.Open)
	}
	if ne := o.obj("next_event"); ne != nil {
		if at := ne.str("at_pk", ""); at != "" {
			m.NextEvent = strings.TrimSpace(ne.str("event", "") + " " + at)
		}
	}
}

// ParseMarket turns a /market body into a Market (exported for tests).
func ParseMarket(o J) *Market {
	m := NewMarket()
	m.Answered = o.boolean("ok", false)
	m.Open = o.boolean("market_open", false)
	m.Date = o.str("date", "")
	m.KarachiNow = o.str("karachi_now", "")
	if tr := o.obj("market_transition"); tr != nil {
		m.TransitionState = tr.str("state", "")
		m.TransitionEvidence = tr.str("evidence", "")
		m.TransitionDelivered = tr.boolean("delivered", false)
	}
	m.CacheAgeSeconds = o.intDef("cache_age_seconds", -1)
	m.Basis = o.str("top_volume_basis", "")
	m.SplitBasis = o.str("volume_split_basis", "")
	m.Members = o.intDef("kmiall_members", 0)
	readPhase(o.obj("market_state"), m)
	if f := o.obj("market_feed"); f != nil {
		m.FeedStatus = f.str("status", "UNKNOWN")
		m.FeedHalted = m.FeedStatus == "HALTED" && f.boolean("fresh", false)
		m.FeedStatusRaw = f.str("raw_status", "")
		m.FeedStatusAsOf = f.str("as_of", "")
		m.FeedStatusFresh = f.boolean("fresh", false)
	}
	if idx := o.obj("index"); idx != nil {
		m.IndexValue = idx.num("value")
		m.IndexChange = idx.num("change")
		m.IndexPct = idx.num("change_pct")
		m.IndexAsOf = idx.str("as_of", "")
		m.IndexSource = idx.str("source", "")
	}
	for i, v := range o.arr("top_volume") {
		if i >= 3 {
			break
		}
		lo := objOf(v)
		if lo == nil {
			continue
		}
		m.Leaders = append(m.Leaders, Leader{
			Symbol:      lo.str("symbol", ""),
			Volume:      lo.integer("volume"),
			Price:       lo.num("price"),
			ChangePct:   lo.num("change_pct"),
			Buy:         lo.integer("buy_volume"),
			Sell:        lo.integer("sell_volume"),
			SplitMethod: lo.str("split_method", ""),
		})
	}
	if wl := o.obj("win_loss"); wl != nil && wl.has("wins") && wl.has("losses") {
		w := &WinLoss{Wins: wl.intDef("wins", 0), Losses: wl.intDef("losses", 0)}
		if wl.has("closed") {
			c := wl.intDef("closed", 0)
			w.Closed = &c
		}
		if wl.has("rate_pct") && wl["rate_pct"] != nil {
			r := wl.intDef("rate_pct", 0)
			w.RatePct = &r
		}
		m.WinLoss = w
	}
	m.QuoteSnapshotStale = o.boolean("quote_snapshot_stale", false)
	if notes := o.arr("notes"); len(notes) > 0 {
		if s, ok := notes[0].(string); ok {
			m.Note = s
		}
	}
	if o.boolean("stale", false) {
		m.Note = "relay last refreshed earlier: " + m.Note
	}
	return m
}

// FetchMarket ports Watcher.fetchMarket. It never returns nil.
func (r *Relay) FetchMarket(ctx context.Context) (*Market, time.Duration, error) {
	o, rtt, err := r.get(ctx, "/market")
	if err != nil {
		m := NewMarket()
		if errors.Is(err, errPayloadTooLarge) {
			m.Note = "The relay sent more data than this app accepts, so the card was skipped."
		} else {
			m.Note = "Market card could not load (" + errKind(err) + ")."
		}
		return m, rtt, err
	}
	return ParseMarket(o), rtt, nil
}

// ParseHead turns a /health body into a Head (exported for tests).
func ParseHead(o J, phaseLine func(*Market) string) *Head {
	h := &Head{Phase: NewMarket()}
	h.Reachable = o.boolean("ok", false)
	h.MarketOpen = o.boolean("market_open", false)
	h.KarachiNow = o.str("karachi_now", "")
	h.Phase.Open = h.MarketOpen
	readPhase(o.obj("market_state"), h.Phase)
	h.NextEvent = h.Phase.NextEvent
	if ne := o.obj("next_event"); ne != nil && h.NextEvent == "" {
		if at := ne.str("at_pk", ""); at != "" {
			h.NextEvent = strings.TrimSpace(ne.str("event", "") + " " + at)
		}
	}
	if !h.Reachable {
		h.Detail = "The relay answered but reported a fault."
		return h
	}
	var sb strings.Builder
	sb.WriteString("Karachi: " + h.KarachiNow)
	if pl := phaseLine(h.Phase); pl != "" {
		sb.WriteByte('\n')
		sb.WriteString(pl)
	}
	h.Detail = sb.String()
	return h
}

// FetchHead ports Watcher.fetchHead's /health half, with the same one retry.
func (r *Relay) FetchHead(ctx context.Context, phaseLine func(*Market) string) (*Head, time.Duration, error) {
	var o J
	var rtt time.Duration
	var err error
	for i := 0; i < 2; i++ {
		o, rtt, err = r.get(ctx, "/health")
		if err == nil {
			break
		}
		select {
		case <-time.After(1500 * time.Millisecond):
		case <-ctx.Done():
			return nil, rtt, ctx.Err()
		}
	}
	if err != nil {
		return nil, rtt, err
	}
	return ParseHead(o, phaseLine), rtt, nil
}

// FetchSignals ports the /signals half of fetchHead, including its fallbacks.
func (r *Relay) FetchSignals(ctx context.Context) (string, bool) {
	o, _, err := r.get(ctx, "/signals")
	if err != nil {
		return "Signals could not load just now.", false
	}
	if o.boolean("ok", false) {
		return o.str("signals", ""), true
	}
	return "Signals are unavailable from the relay.", false
}

// ParseQuotes ports Watcher.applyLiveQuotes' reading half.
func ParseQuotes(o J) *Quotes {
	q := &Quotes{Items: map[string]LiveQuote{}}
	if !o.boolean("ok", false) {
		return q
	}
	q.OK = true
	if idx := o.obj("index"); idx != nil {
		// A reading that is not fresh is still kept: it is the broker's own last
		// tick, which beats a delayed number from anywhere else.
		v, c, p := idx.num("value"), idx.num("change"), idx.num("change_pct")
		if v != nil && c != nil && p != nil && *v > 0 {
			q.Index = &IndexQuote{Value: *v, Change: *c, ChangePct: *p, AsOf: idx.str("as_of", ""), Fresh: idx.boolean("fresh", false)}
		}
	}
	for _, it := range o.arr("quotes") {
		qo := objOf(it)
		if qo == nil {
			continue
		}
		sym := qo.str("symbol", "")
		if sym == "" {
			continue
		}
		lq := LiveQuote{Fresh: qo.boolean("fresh", false), ChangePct: qo.num("change_pct"), Change: qo.num("change"),
			AgeSeconds: qo.intDef("age_seconds", -1), SourceTick: qo.str("source_tick_time", ""), ObservedAt: qo.str("observed_at", "")}
		if p := qo.num("price"); p != nil {
			lq.Price = *p
		}
		if v := qo.num("volume"); v != nil && *v > 0 {
			lq.Volume = int64(*v)
		}
		for k, dst := range map[string]*float64{"high": &lq.High, "low": &lq.Low, "bid": &lq.Bid, "ask": &lq.Ask} {
			if v := qo.num(k); v != nil {
				*dst = *v
			}
		}
		q.Items[sym] = lq
	}
	return q
}

func (r *Relay) FetchQuotes(ctx context.Context) (*Quotes, error) {
	o, _, err := r.get(ctx, "/quotes")
	if err != nil {
		return nil, err
	}
	q := ParseQuotes(o)
	q.FetchedAt = time.Now()
	return q, nil
}

// ParsePrices ports Watcher.fetchPrices. Rows are [symbol, price, change, buy, sell].
func ParsePrices(o J) map[string]Quote {
	out := map[string]Quote{}
	for _, row := range o.arr("prices") {
		a, ok := row.([]any)
		if !ok || len(a) < 3 {
			continue
		}
		sym, _ := a[0].(string)
		pn, _ := a[1].(json.Number)
		if sym == "" || pn == "" {
			continue
		}
		price, err := pn.Float64()
		if err != nil || math.IsNaN(price) || math.IsInf(price, 0) || price <= 0 {
			continue
		}
		q := Quote{Price: price}
		if cn, ok := a[2].(json.Number); ok {
			if f, err := cn.Float64(); err == nil && !math.IsNaN(f) && !math.IsInf(f, 0) {
				q.ChangePct = &f
			}
		}
		if len(a) > 3 {
			if n, ok := a[3].(json.Number); ok {
				if f, err := n.Float64(); err == nil {
					v := int64(f)
					q.Buy = &v
				}
			}
		}
		if len(a) > 4 {
			if n, ok := a[4].(json.Number); ok {
				if f, err := n.Float64(); err == nil {
					v := int64(f)
					q.Sell = &v
				}
			}
		}
		out[sym] = q
	}
	return out
}

func (r *Relay) FetchPrices(ctx context.Context) (map[string]Quote, error) {
	o, _, err := r.get(ctx, "/prices")
	if err != nil {
		return nil, err
	}
	return ParsePrices(o), nil
}

// StockInfo is the /stock answer for one symbol.
type StockInfo struct {
	Symbol string
	Buy    *float64
	Sell   *float64
	Volume *float64
}

func (r *Relay) FetchStock(ctx context.Context, sym string) (*StockInfo, error) {
	o, _, err := r.get(ctx, "/stock?symbol="+url.QueryEscape(sym))
	if err != nil {
		return nil, err
	}
	so := o.obj("stock")
	if !o.boolean("ok", false) || so == nil {
		return nil, errors.New("no stock data")
	}
	return &StockInfo{
		Symbol: so.str("symbol", sym),
		Buy:    so.num("buy_volume"),
		Sell:   so.num("sell_volume"),
		Volume: so.num("volume"),
	}, nil
}

// sortedKeys returns the symbols of a price table in order.
func sortedKeys[V any](m map[string]V) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		if k != "" {
			out = append(out, k)
		}
	}
	sort.Strings(out)
	return out
}

// phaseLine ports Watcher.phaseLine (the sentence under the status pill).
func phaseLine(m *Market) string {
	if m != nil && m.FeedHalted && m.FeedStatusFresh {
		return "Market is halted now. Quant is offline until the market reopens."
	}
	if m == nil || !m.PhaseKnown() {
		return "Market status not reported by the relay yet."
	}
	switch m.Condition {
	case "OPERATIONAL":
		return ""
	case "BREAK":
		if m.ConditionText == "" {
			return "Market is on a break right now. Quant is offline."
		}
		return m.ConditionText
	case "CLOSED":
		if m.ConditionText == "" {
			return "Market is closed right now."
		}
		return m.ConditionText
	}
	switch m.Phase {
	case "OPEN", "WARMUP":
		return ""
	case "BREAK":
		return "Market is on a break right now."
	}
	return "Market is closed right now."
}

// selfTest hits every read endpoint once and prints what came back. It is the
// quickest way to check the PC can reach the relay.
func selfTest(base string) int {
	r := NewRelay(base)
	ctx := context.Background()
	fmt.Println("Relay:", r.Base)
	fmt.Println("User-Agent:", userAgent)
	fail := 0
	check := func(path string) {
		o, rtt, err := r.get(ctx, path)
		if err != nil {
			fmt.Printf("  FAIL  %-22s %6dms  %s (%s)\n", path, rtt.Milliseconds(), errKind(err), err)
			fail++
			return
		}
		keys := make([]string, 0, len(o))
		for k := range o {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		fmt.Printf("  OK    %-22s %6dms  ok=%v keys=%s\n", path, rtt.Milliseconds(), o.boolean("ok", false), strings.Join(keys, ","))
	}
	for _, p := range []string{"/health", "/market", "/signals", "/quotes", "/prices", "/sectors"} {
		check(p)
	}
	if fail > 0 {
		fmt.Fprintf(os.Stderr, "%d endpoint(s) failed\n", fail)
		return 1
	}
	fmt.Println("All read endpoints answered.")
	return 0
}
