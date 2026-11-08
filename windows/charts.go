package main

import (
	"context"
	"errors"
	"fmt"
	"math"
	"net/url"
	"strings"
	"time"
)

// ChartBar is one bar of the relay's /history answer.
type ChartBar struct {
	At     time.Time
	Minute string
	Open   float64
	High   float64
	Low    float64
	Close  float64
	Volume int64
}

// ChartHistory is the parsed /history answer for one stock and one day. Bars
// the relay did not send are never invented: an empty Bars slice is shown as
// an empty chart with the relay's own note.
type ChartHistory struct {
	Symbol    string
	TF        string
	Day       string
	Days      int
	Retention int
	LiveOnly  bool
	Bars      []ChartBar
	Forming   bool
	Demo      bool
	Notes     []string
	Err       string
	FetchedAt time.Time
}

// ParseHistory reads {ok, day, forming, bars:[{t,o,h,l,c,v}], notes:[...]}.
func ParseHistory(o J, sym string) *ChartHistory {
	h := &ChartHistory{Symbol: sym, Day: o.str("day", ""), Forming: o.boolean("forming", false)}
	if h.Day == "" {
		h.Day = o.str("date", "")
	}
	if h.Day == "" {
		h.Day = o.str("as_of", "")
	}
	if !o.boolean("ok", true) {
		h.Err = o.str("error", "The relay did not return any bars.")
	}
	for _, raw := range o.arr("notes") {
		if s, ok := raw.(string); ok && strings.TrimSpace(s) != "" {
			h.Notes = append(h.Notes, s)
		}
	}
	for _, raw := range o.arr("bars") {
		obj := objOf(raw)
		if obj == nil {
			continue
		}
		at, err := time.Parse(time.RFC3339, obj.str("t", ""))
		if err != nil {
			continue
		}
		local := at.In(pkt)
		b := ChartBar{At: local, Minute: local.Format("15:04")}
		if f := obj.num("o"); f != nil {
			b.Open = *f
		}
		if f := obj.num("h"); f != nil {
			b.High = *f
		}
		if f := obj.num("l"); f != nil {
			b.Low = *f
		}
		if f := obj.num("c"); f != nil {
			b.Close = *f
		}
		if f := obj.num("v"); f != nil {
			b.Volume = int64(math.Round(*f))
		}
		if b.High <= 0 || b.Low <= 0 {
			continue
		}
		h.Bars = append(h.Bars, b)
	}
	return h
}

// FetchHistory reads the minute bars for one stock. The relay writes only what
// the broker sent; the desktop draws only what the relay wrote.
func (r *Relay) FetchHistory(ctx context.Context, sym, day string) (*ChartHistory, error) {
	sym = strings.ToUpper(strings.TrimSpace(sym))
	path := "/history?symbol=" + url.QueryEscape(sym)
	if day != "" {
		path += "&day=" + url.QueryEscape(day)
	}
	o, _, err := r.get(ctx, path)
	if err != nil {
		return nil, err
	}
	h := ParseHistory(o, sym)
	h.FetchedAt = time.Now()
	if h.Err != "" {
		return h, errors.New(h.Err)
	}
	return h, nil
}

// Owner order 2026-11-07: ten frames for KSE100, KMIALLSHR and every KMIALL
// scrip. The relay stores one minute and every longer frame; the two second
// frames are built here from this desk's own live samples, because the broker
// feed samples a symbol every 30 to 90 seconds and a stored second bar would
// claim detail the wire never had.
var chartFrames = []string{"1s", "5s", "1m", "5m", "15m", "30m", "1h", "1D", "1W", "1M"}

func chartFrameIndex(tf string) int {
	for i, f := range chartFrames {
		if f == tf {
			return i
		}
	}
	return -1
}

func (a *App) chartFrame() string {
	if chartFrameIndex(a.chartTF) < 0 {
		return "1m"
	}
	return a.chartTF
}

func (a *App) liveFrame() bool {
	f := a.chartFrame()
	return f == "1s" || f == "5s"
}

// setChartFrame switches the panel to one frame. A live frame needs no relay
// read; a stored frame asks for its bars at once.
func (a *App) setChartFrame(tf string) {
	if chartFrameIndex(tf) < 0 || tf == a.chartFrame() {
		return
	}
	a.chartTF = tf
	a.chart, a.chartErr = nil, ""
	if a.demo || a.liveFrame() {
		a.chartSt = "ok"
		return
	}
	a.chartSt = "loading"
	a.next["history"] = time.Time{}
}

func (a *App) moveChartFrame(d int) {
	i := chartFrameIndex(a.chartFrame())
	if i < 0 {
		i = 2
	}
	i = (i + d + len(chartFrames)) % len(chartFrames)
	a.setChartFrame(chartFrames[i])
}

// ParseBars reads {ok, tf, days, retention_days, bars:[{t,o,h,l,c,v}], notes}.
// A daily or longer bar is labelled with its date; an intraday bar with its
// Karachi clock time. No bar the relay did not send is invented.
func ParseBars(o J, sym, tf string) *ChartHistory {
	h := &ChartHistory{Symbol: sym, TF: tf, Days: o.intDef("days", 0),
		Retention: o.intDef("retention_days", 0)}
	if chartFrameIndex(h.TF) < 0 {
		h.TF = o.str("tf", "1m")
	}
	if chartFrameIndex(h.TF) < 0 {
		h.TF = "1m"
	}
	h.LiveOnly = h.TF == "1s" || h.TF == "5s"
	if !o.boolean("ok", false) {
		h.Err = o.str("error", "The relay did not return any bars.")
	}
	for _, raw := range o.arr("notes") {
		if s, ok := raw.(string); ok && strings.TrimSpace(s) != "" {
			h.Notes = append(h.Notes, s)
		}
	}
	daily := h.TF == "1D" || h.TF == "1W" || h.TF == "1M"
	for _, raw := range o.arr("bars") {
		obj := objOf(raw)
		if obj == nil {
			continue
		}
		at, err := time.Parse(time.RFC3339, obj.str("t", ""))
		if err != nil {
			continue
		}
		local := at.In(pkt)
		label := local.Format("15:04")
		if daily {
			label = local.Format("02 Jan 06")
		}
		b := ChartBar{At: local, Minute: label}
		if f := obj.num("o"); f != nil {
			b.Open = *f
		}
		if f := obj.num("h"); f != nil {
			b.High = *f
		}
		if f := obj.num("l"); f != nil {
			b.Low = *f
		}
		if f := obj.num("c"); f != nil {
			b.Close = *f
		}
		if f := obj.num("v"); f != nil {
			b.Volume = int64(math.Round(*f))
		}
		if b.High <= 0 || b.Low <= 0 {
			continue
		}
		h.Bars = append(h.Bars, b)
	}
	if len(h.Bars) > 0 {
		h.Day = h.Bars[len(h.Bars)-1].At.Format("2006-01-02")
	}
	return h
}

// FetchBars reads one frame for one symbol, newest limit bars inside the
// rolling day window. The relay does the aggregation; this side only parses.
func (r *Relay) FetchBars(ctx context.Context, sym, tf string, days, limit int) (*ChartHistory, error) {
	sym = strings.ToUpper(strings.TrimSpace(sym))
	path := fmt.Sprintf("/bars?symbol=%s&tf=%s&days=%d&limit=%d",
		url.QueryEscape(sym), url.QueryEscape(tf), days, limit)
	o, _, err := r.get(ctx, path)
	if err != nil {
		return nil, err
	}
	h := ParseBars(o, sym, tf)
	h.FetchedAt = time.Now()
	if h.Err != "" {
		return h, errors.New(h.Err)
	}
	return h, nil
}

// liveChart builds the 1s or 5s frame from this desk's own samples. It is
// labelled live-only because the wire does not publish second bars.
func (a *App) liveChart(sym, tf string) *ChartHistory {
	var vals []float64
	switch {
	case sym == "KSE100" && a.quotes != nil && a.quotes.Index != nil:
		vals = a.idxHist.v
	case a.symHist[sym] != nil:
		vals = a.symHist[sym].v
	}
	h := &ChartHistory{Symbol: sym, TF: tf, LiveOnly: true}
	if len(vals) == 0 {
		h.Notes = append(h.Notes, "waiting for the next live sample")
		return h
	}
	if len(vals) > 120 {
		vals = vals[len(vals)-120:]
	}
	end := a.karachiNow().Truncate(time.Second)
	if tf == "5s" {
		bars := make([]ChartBar, 0, (len(vals)+4)/5)
		for i := 0; i < len(vals); i += 5 {
			j := min(len(vals), i+5)
			at := end.Add(-time.Duration(len(vals)-i) * time.Second)
			b := ChartBar{At: at, Minute: at.Format("15:04"), Open: vals[i],
				High: vals[i], Low: vals[i], Close: vals[j-1]}
			for _, v := range vals[i:j] {
				b.High = math.Max(b.High, v)
				b.Low = math.Min(b.Low, v)
			}
			bars = append(bars, b)
		}
		h.Bars = bars
	} else {
		bars := make([]ChartBar, 0, len(vals))
		for i, v := range vals {
			at := end.Add(-time.Duration(len(vals)-1-i) * time.Second)
			bars = append(bars, ChartBar{At: at, Minute: at.Format("15:04:05"),
				Open: v, High: v, Low: v, Close: v})
		}
		h.Bars = bars
	}
	h.Day = end.Format("2006-01-02")
	return h
}

// chartLive is the last price for the panel's live line. KSE100 reads the index
// quote the relay carries; every other symbol reads its live scrip quote.
func (a *App) chartLive(sym string) (float64, *float64, bool) {
	if sym == "KSE100" {
		if a.quotes != nil && a.quotes.Index != nil && a.quotes.Index.Value > 0 {
			pct := a.quotes.Index.ChangePct
			return a.quotes.Index.Value, &pct, true
		}
		if a.demo {
			h := a.demoHistory(sym)
			last := h.Bars[len(h.Bars)-1].Close
			return last, nil, true
		}
		return 0, nil, false
	}
	if q, ok := a.liveQuote(sym); ok && q.Price > 0 {
		return q.Price, q.ChangePct, true
	}
	return 0, nil, false
}

// demoBars relabels the invented demo session to the chosen frame. It is
// always labelled DEMO; no demo bar is ever shown as a relay bar.
func (a *App) demoBars(sym, tf string) *ChartHistory {
	base := a.demoHistory(sym)
	if tf == "1m" || chartFrameIndex(tf) < 0 {
		return base
	}
	d := time.Minute
	switch tf {
	case "1s":
		d = time.Second
	case "5s":
		d = 5 * time.Second
	case "5m":
		d = 5 * time.Minute
	case "15m":
		d = 15 * time.Minute
	case "30m":
		d = 30 * time.Minute
	case "1h":
		d = time.Hour
	case "1D":
		d = 24 * time.Hour
	case "1W":
		d = 7 * 24 * time.Hour
	case "1M":
		d = 30 * 24 * time.Hour
	}
	const n = 120
	end := a.karachiNow().In(pkt).Truncate(d)
	bars := make([]ChartBar, 0, n)
	for i := 0; i < n; i++ {
		src := base.Bars[i%len(base.Bars)]
		at := end.Add(-time.Duration(n-1-i) * d)
		label := at.Format("15:04")
		if tf == "1D" || tf == "1W" || tf == "1M" {
			label = at.Format("02 Jan 06")
		}
		bars = append(bars, ChartBar{At: at, Minute: label, Open: src.Open,
			High: src.High, Low: src.Low, Close: src.Close, Volume: src.Volume})
	}
	return &ChartHistory{Symbol: sym, TF: tf, Day: end.Format("2006-01-02"),
		Bars: bars, Forming: true, Demo: true}
}

// chartSymbols is every KMIALL stock, sorted. /prices is the full membership
// list; before it arrives the symbols the feed has named stand in.
func (a *App) chartSymbols() []string {
	set := map[string]bool{"KSE100": true, "KMIALLSHR": true}
	for s := range a.prices {
		set[s] = true
	}
	if len(a.prices) == 0 {
		for _, s := range a.symbols {
			set[s] = true
		}
	}
	// The relay's sector answer carries the full KMIALLSHR membership even
	// when the market is closed and /prices is empty.
	if a.sectors != nil {
		for _, sec := range a.sectors.Items {
			for _, sym := range sec.Symbols {
				set[sym] = true
			}
		}
	}
	out := make([]string, 0, len(set))
	for _, s := range []string{"KSE100", "KMIALLSHR"} {
		out = append(out, s)
		delete(set, s)
	}
	return append(out, sortedKeys(set)...)
}

// chartMatches is the list the CHARTS search box lets through.
func (a *App) chartMatches() []string {
	all := a.chartSymbols()
	q := strings.ToUpper(strings.TrimSpace(a.chartQuery))
	if q == "" {
		return all
	}
	out := make([]string, 0, len(all))
	for _, s := range all {
		if strings.HasPrefix(s, q) {
			out = append(out, s)
		}
	}
	return out
}

// selectChart opens one stock. It asks for that stock's bars at once; the old
// chart is cleared so another stock's candles are never shown under this name.
func (a *App) selectChart(sym string) {
	if sym == "" {
		return
	}
	a.chartQuery, a.chartSearch = "", false
	if sym == a.chartSym && a.chart != nil && a.chart.TF == a.chartFrame() {
		return
	}
	a.chartSym = sym
	a.chart, a.chartErr = nil, ""
	if a.demo {
		a.chart, a.chartSt = a.demoBars(sym, a.chartFrame()), "ok"
		return
	}
	if a.liveFrame() {
		a.chartSt = "ok"
		return
	}
	a.chartSt = "loading"
	a.next["history"] = time.Time{}
}

// stepChart moves the chart selection by one row and opens it.
func (a *App) stepChart(d int) {
	m := a.chartMatches()
	if len(m) == 0 {
		return
	}
	a.chartCursor = min(max(0, a.chartCursor+d), len(m)-1)
	a.selectChart(m[a.chartCursor])
	if a.chartCursor < a.lvChart.off {
		a.lvChart.off = a.chartCursor
	}
	if a.chartCursor >= a.lvChart.off+a.lvChart.view {
		a.lvChart.off = a.chartCursor - a.lvChart.view + 1
	}
}

// keyCharts handles the CHARTS tab. Letters and digits go into the chart search
// as they are typed, UP and DOWN open the previous or next match, and ESC
// clears the search before it goes Home.
func (a *App) keyCharts(k Key) {
	switch k.Kind {
	case KEsc:
		if a.chartQuery != "" || a.chartSearch {
			a.chartQuery, a.chartSearch = "", false
			a.chartCursor = 0
			a.lvChart.top()
			return
		}
		a.setScreen(scrHome)
	case KUp:
		a.stepChart(-1)
	case KDown:
		a.stepChart(1)
	case KLeft:
		a.stepChart(-1)
	case KRight:
		a.stepChart(1)
	case KPgUp:
		a.lvChart.page(-1)
	case KPgDn:
		a.lvChart.page(1)
	case KHome:
		a.lvChart.top()
	case KEnd:
		a.lvChart.bottom()
	case KEnter:
		if m := a.chartMatches(); len(m) > 0 {
			a.chartCursor = min(a.chartCursor, len(m)-1)
			a.selectChart(m[a.chartCursor])
		}
	case KBackspace:
		if r := []rune(a.chartQuery); len(r) > 0 {
			a.chartQuery = strings.ToUpper(string(r[:len(r)-1]))
			if a.chartQuery == "" {
				a.chartSearch = false
			}
			a.chartCursor = 0
			a.lvChart.top()
		}
	case KRune:
		r := k.R
		if r == '[' {
			a.moveChartFrame(-1)
			return
		}
		if r == ']' {
			a.moveChartFrame(1)
			return
		}
		if r >= 'a' && r <= 'z' {
			r -= 'a' - 'A'
		}
		if (r >= 'A' && r <= 'Z') || (r >= '0' && r <= '9') || r == '.' || r == '-' || r == '_' {
			if runeLen(a.chartQuery) < 16 {
				a.chartQuery += string(r)
			}
			a.chartSearch = true
			a.chartCursor = 0
			a.lvChart.top()
		}
	}
}

// drawCharts is the CHARTS tab: every KMIALL stock in a searchable list on the
// left, and the chosen stock's live intraday candles on the right.
func (a *App) drawCharts(c *Canvas, x, y, w, h int) {
	syms := a.chartSymbols()
	if a.chartSym == "" && len(syms) > 0 {
		a.chartSym, a.chartSt = syms[0], "loading"
	}
	listW := min(34, max(26, w/3))
	if w-listW-1 < 40 {
		listW = max(20, w-41)
	}
	a.drawChartList(c, x, y, listW, h, syms)
	a.drawChartPanel(c, x+listW+1, y, w-listW-1, h)
}

func (a *App) drawChartList(c *Canvas, x, y, w, h int, syms []string) {
	th := a.th
	hint := ""
	if a.chartQuery != "" {
		hint = "ESC clears"
	}
	ix, iy, iw, ih := a.panel(c, x, y, w, h, "CHARTS", hint)
	if ih < 2 {
		return
	}
	a.searchBox(c, ix, iy, iw, a.chartQuery, "Search for a KMIALL scrip", a.chartSearch)
	matches := a.chartMatches()
	if a.chartCursor >= len(matches) {
		a.chartCursor = max(0, len(matches)-1)
	}
	rows := ih - 1
	a.lvChart.set(len(matches), rows)
	cw := contentW(&a.lvChart, iw)
	for n := 0; n < a.lvChart.view; n++ {
		i := a.lvChart.off + n
		if i >= len(matches) {
			break
		}
		sym := matches[i]
		ry := iy + 1 + n
		bg := a.selectRow(c, ix, ry, cw, i == a.chartCursor, func() {
			a.chartCursor = i
			a.selectChart(sym)
		})
		mark := "  "
		if sym == a.chartSym {
			mark = "◆ "
		}
		c.Set(ix, ry, []rune(mark)[0], th.Accent, bg, true)
		c.Text(ix+2, ry, max(1, cw-2), sym, th.Hot, sym == a.chartSym)
		if q, ok := a.liveQuote(sym); ok && q.Price > 0 {
			ps := commaFloat(q.Price, 2)
			right := ix + cw
			if q.ChangePct != nil {
				ch := " " + changeText(*q.ChangePct)
				if runeLen(ps)+runeLen(ch)+6 < cw {
					a.flashRight(c, right, ry, ch, a.dirColor(*q.ChangePct), true, "px:"+sym)
					right -= runeLen(ch)
				}
			}
			if runeLen(ps)+6 < cw {
				a.flashRight(c, right, ry, ps, th.Text, false, "px:"+sym)
			}
		}
	}
	a.scrollbar(c, ix+iw-1, iy+1, rows, &a.lvChart)
}

func (a *App) drawChartPanel(c *Canvas, x, y, w, h int) {
	th := a.th
	tf := a.chartFrame()
	title := "CHARTS"
	hint := "live intraday"
	if a.chartSym != "" {
		title = a.chartSym + " INTRADAY"
		if tf == "1D" || tf == "1W" || tf == "1M" {
			title = a.chartSym + " " + tf
		}
	}
	switch {
	case a.demo:
		hint = "demo bars"
	case a.liveFrame():
		hint = "live samples"
	case tf != "1m":
		hint = tf + " bars"
	}
	ix, iy, iw, ih := a.panel(c, x, y, w, h, title, hint)
	if ih < 6 {
		return
	}
	sym := a.chartSym
	if sym == "" {
		c.Text(ix, iy, iw, "Pick a KMIALL stock on the left to see its chart.", th.Soft, false)
		return
	}
	a.drawChartFrames(c, ix, iy, iw)
	hst := a.chart
	if hst != nil && hst.Symbol != sym {
		hst = nil
	}
	if a.liveFrame() {
		hst = a.liveChart(sym, tf)
	} else if a.demo {
		hst = a.demoBars(sym, tf)
		a.chart = hst
	} else if hst != nil && hst.TF != tf {
		hst = nil
	}
	price, pct, live := a.chartLive(sym)
	q := LiveQuote{Price: price, ChangePct: pct}
	// Line 1: the day, the live quote and the day's range as the bars have it.
	sp := []Span{{"DAY ", th.Soft, false}}
	day := "--"
	if hst != nil && hst.Day != "" {
		day = hst.Day
	}
	sp = append(sp, Span{day, th.Text, true})
	if live && q.Price > 0 {
		sp = append(sp, Span{"   LIVE PKR ", th.Soft, false}, Span{commaFloat(q.Price, 2), th.Hot, true})
		if q.ChangePct != nil {
			sp = append(sp, Span{"  " + changeText(*q.ChangePct), a.dirColor(*q.ChangePct), true})
		}
	}
	if hst != nil && len(hst.Bars) > 0 {
		hi, lo := hst.Bars[0].High, hst.Bars[0].Low
		for _, b := range hst.Bars {
			hi = math.Max(hi, b.High)
			lo = math.Min(lo, b.Low)
		}
		if live && q.Price > 0 {
			hi = math.Max(hi, q.Price)
			lo = math.Min(lo, q.Price)
		}
		sp = append(sp, Span{"   HI ", th.Soft, false}, Span{commaFloat(hi, 2), th.Good, false},
			Span{"  LO ", th.Soft, false}, Span{commaFloat(lo, 2), th.Bad, false})
	}
	c.Spans(ix, iy+1, iw, sp)

	// Line 2: the last bar, exactly as the relay wrote it.
	if hst != nil && len(hst.Bars) > 0 {
		b := hst.Bars[len(hst.Bars)-1]
		line := fmt.Sprintf("O %s  H %s  L %s  C %s", commaFloat(b.Open, 2), commaFloat(b.High, 2),
			commaFloat(b.Low, 2), commaFloat(b.Close, 2))
		if b.Volume > 0 {
			line += "   V " + commaInt(b.Volume)
		}
		if hst.Forming {
			line += "   ·   forming"
		}
		c.Text(ix, iy+2, iw, fit(line, iw), th.Soft, false)
	}

	plotY := iy + 3
	plotH := ih - 4
	if plotH < 2 {
		return
	}
	msg, col := "", th.Soft
	switch {
	case hst == nil && (a.chartSt == "loading" || a.chartSt == ""):
		msg = "Reading today's one minute bars from the relay."
	case hst == nil && a.chartSt == "failed":
		msg, col = "The chart is not available right now: "+a.chartErr, th.Warn
	case hst == nil || len(hst.Bars) == 0:
		switch {
		case a.liveFrame():
			msg = "This frame is built from live samples; waiting for the next tick."
		case tf == "1m":
			msg = "No one minute bars are stored for " + sym + " in the last 45 days."
		default:
			msg = "No " + tf + " bars are stored for " + sym + " in the last 365 days."
		}
		if !a.trading() {
			if next := a.nextOpenLine(); next != "" {
				msg = "Market closed. Next " + next + ". " + msg
			}
		}
		if hst != nil && len(hst.Notes) > 0 {
			msg += " " + hst.Notes[0]
		}
		col = th.Warn
	}
	if msg != "" {
		for i, ln := range wrap(msg, iw) {
			if plotY+i < iy+ih {
				c.Text(ix, plotY+i, iw, ln, col, false)
			}
		}
		c.Text(ix, iy+ih-1, iw, "Bars start at the first tick of the session; nothing is filled in.", mix(th.Panel, th.Soft, 0.8), false)
		return
	}

	step := a.drawCandles(c, ix, plotY, iw, plotH, hst.Bars, live && q.Price > 0, q.Price)
	first, last := hst.Bars[0].Minute, hst.Bars[len(hst.Bars)-1].Minute
	foot := fmt.Sprintf("%s to %s   ·   %d bars   ·   %s", first, last, len(hst.Bars), tf)
	if step > 1 {
		foot += fmt.Sprintf(", %d bars a candle", step)
	}
	switch {
	case hst.LiveOnly:
		foot += "   ·   live samples"
	case hst.Demo:
		foot += "   ·   DEMO"
	case hst.Retention > 0:
		foot += fmt.Sprintf("   ·   %d day store", hst.Retention)
	}
	c.Text(ix, iy+ih-1, iw, fit(foot, iw), mix(th.Panel, th.Soft, 0.8), false)
}

// nextOpenLine is the relay's next session event, used to explain an empty
// chart while the market is closed.
func (a *App) nextOpenLine() string {
	if a.market != nil && a.market.NextEvent != "" {
		return a.market.NextEvent
	}
	if a.head != nil && a.head.NextEvent != "" {
		return a.head.NextEvent
	}
	return ""
}

// drawChartFrames draws the ten frame chips. A click switches the panel, and
// the brackets do the same from the keyboard.
func (a *App) drawChartFrames(c *Canvas, x, y, w int) {
	th := a.th
	tf := a.chartFrame()
	fx := x
	for _, f := range chartFrames {
		label := " " + f + " "
		lw := runeLen(label)
		if fx+lw > x+w {
			break
		}
		fg, bg := th.Soft, th.Panel
		if f == tf {
			fg, bg = th.Panel, th.Accent
		}
		for i, r := range []rune(label) {
			c.Set(fx+i, y, r, fg, bg, f == tf)
		}
		frame := f
		a.addHit(fx, y, lw, 1, func() { a.setChartFrame(frame) })
		fx += lw + 1
	}
}

// drawCandles draws the day's bars as candles and returns how many minutes one
// candle covers. Every candle is one column of body and wick with a gap after
// it, so a whole session fits without pretending it has more detail than it has.
func (a *App) drawCandles(c *Canvas, x, y, w, h int, bars []ChartBar, live bool, price float64) int {
	th := a.th
	axisW := 8
	plotW := max(4, w-axisW)
	maxBars := max(1, plotW/3)
	candles, step := chartCandles(bars, maxBars)
	if len(candles) == 0 {
		return step
	}
	lo, hi := candles[0].Low, candles[0].High
	for _, b := range candles {
		lo = math.Min(lo, b.Low)
		hi = math.Max(hi, b.High)
	}
	if live && price > 0 {
		lo = math.Min(lo, price)
		hi = math.Max(hi, price)
	}
	if hi <= lo {
		hi = lo + 1
	}
	pad := (hi - lo) * 0.06
	lo -= pad
	hi += pad
	py := func(v float64) int {
		f := (hi - v) / (hi - lo)
		if f < 0 {
			f = 0
		}
		if f > 1 {
			f = 1
		}
		return y + int(math.Round(f*float64(h-1)))
	}
	// The right edge carries three price labels; a dot at the quarter marks
	// keeps the scale readable without drawing over the candles.
	for _, frac := range []float64{0, 0.25, 0.5, 0.75, 1} {
		gy := y + int(math.Round(frac*float64(h-1)))
		c.Put(x+plotW-1, gy, '·', th.Line, false)
	}
	axisX := x + plotW + 1
	for i, v := range []float64{hi, (hi + lo) / 2, lo} {
		yy := py(v)
		if i == 0 {
			yy = y
		}
		if i == 2 {
			yy = y + h - 1
		}
		c.Text(axisX, yy, max(1, w-plotW-1), fit(commaFloat(v, 2), max(1, w-plotW-1)), th.Soft, false)
	}
	gap := max(2, min(3, plotW/max(1, len(candles))))
	for i, b := range candles {
		cx := x + i*gap
		if cx >= x+plotW-1 {
			break
		}
		body := th.Good
		if b.Close < b.Open {
			body = th.Bad
		}
		wick := mix(body, th.Panel, 0.35)
		for yy := py(b.High); yy <= py(b.Low); yy++ {
			c.Put(cx, yy, '│', wick, false)
		}
		top, bot := py(math.Max(b.Open, b.Close)), py(math.Min(b.Open, b.Close))
		if top == bot {
			c.Put(cx, top, '▬', body, true)
			continue
		}
		for yy := top; yy <= bot; yy++ {
			c.Put(cx, yy, '█', body, false)
			if gap >= 3 && cx+1 < x+plotW {
				c.Put(cx+1, yy, '█', body, false)
			}
		}
	}
	if live && price > 0 {
		ly := py(price)
		for xx := x; xx < x+plotW; xx += 2 {
			c.Put(xx, ly, '┄', th.Hot, false)
		}
		c.Put(x+plotW, ly, '◆', th.Hot, true)
	}
	return step
}

// chartCandles groups consecutive minute bars into at most maxBars candles. A
// group's open is its first open, its close its last close, and its high and
// low the extremes of the group, so the shape of the session is kept.
func chartCandles(bars []ChartBar, maxBars int) ([]ChartBar, int) {
	if len(bars) == 0 {
		return nil, 1
	}
	if maxBars < 1 {
		maxBars = 1
	}
	if len(bars) <= maxBars {
		return bars, 1
	}
	step := (len(bars) + maxBars - 1) / maxBars
	out := make([]ChartBar, 0, maxBars)
	for i := 0; i < len(bars); i += step {
		j := min(len(bars), i+step)
		b := bars[i]
		b.Volume = 0
		for _, x := range bars[i:j] {
			b.High = math.Max(b.High, x.High)
			b.Low = math.Min(b.Low, x.Low)
			b.Close = x.Close
			b.Volume += x.Volume
		}
		out = append(out, b)
	}
	return out, step
}

// demoHistory invents a session of minute bars for demo mode, ending at the
// live demo price. It is labelled DEMO everywhere it is drawn.
func (a *App) demoHistory(sym string) *ChartHistory {
	now := a.karachiNow().In(pkt)
	end := now.Truncate(time.Minute)
	base := 100.0
	if q, ok := a.liveQuote(sym); ok && q.Price > 0 {
		base = q.Price
	} else if sym == "KSE100" && a.quotes != nil && a.quotes.Index != nil && a.quotes.Index.Value > 0 {
		// The index has no scrip quote; its demo session must sit at the index
		// level, or the live line would flatten every invented candle.
		base = a.quotes.Index.Value
	}
	seed := 0
	for _, r := range sym {
		seed = seed*37 + int(r)
	}
	const n = 120
	start := end.Add(-time.Duration(n-1) * time.Minute)
	bars := make([]ChartBar, 0, n)
	price := base * (1 + 0.012*math.Sin(float64(seed%13)))
	for i := 0; i < n; i++ {
		at := start.Add(time.Duration(i) * time.Minute)
		drift := math.Sin(float64(i+seed%17)/7)*base*0.0013 + math.Sin(float64(i)/29)*base*0.0008
		o := price
		c := o + drift
		if i == n-1 {
			c = base
		}
		hi := math.Max(o, c) + base*0.0008*(1+math.Sin(float64(i+seed)/5))
		lo := math.Min(o, c) - base*0.0008*(1+math.Cos(float64(i+seed)/6))
		v := int64(3000 + (i*977+seed*31)%14000)
		bars = append(bars, ChartBar{At: at, Minute: at.Format("15:04"),
			Open: chartRound2(o), High: chartRound2(hi), Low: chartRound2(lo), Close: chartRound2(c), Volume: v})
		price = c
	}
	return &ChartHistory{Symbol: sym, Day: now.Format("2006-01-02"), Bars: bars, Forming: true, Demo: true}
}

func chartRound2(v float64) float64 { return math.Round(v*100) / 100 }
