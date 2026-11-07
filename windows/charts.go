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
	Day       string
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

// chartSymbols is every KMIALL stock, sorted. /prices is the full membership
// list; before it arrives the symbols the feed has named stand in.
func (a *App) chartSymbols() []string {
	set := map[string]bool{}
	for s := range a.prices {
		set[s] = true
	}
	if len(set) == 0 {
		for _, s := range a.symbols {
			set[s] = true
		}
	}
	return sortedKeys(set)
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
	if sym == a.chartSym {
		if a.demo {
			if a.chart == nil || a.chart.Symbol != sym {
				a.chart, a.chartSt = a.demoHistory(sym), "ok"
			}
		} else if a.chart == nil {
			a.chartSt = "loading"
			a.next["history"] = time.Time{}
		}
		return
	}
	a.chartSym = sym
	a.chart, a.chartErr, a.chartSt = nil, "", "loading"
	if a.demo {
		a.chart, a.chartSt = a.demoHistory(sym), "ok"
	} else {
		a.next["history"] = time.Time{}
	}
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
	title := "CHARTS"
	hint := "live intraday"
	if a.chartSym != "" {
		title = a.chartSym + " INTRADAY"
	}
	if a.demo {
		hint = "demo bars"
	}
	ix, iy, iw, ih := a.panel(c, x, y, w, h, title, hint)
	if ih < 4 {
		return
	}
	sym := a.chartSym
	if sym == "" {
		c.Text(ix, iy, iw, "Pick a KMIALL stock on the left to see its chart.", th.Soft, false)
		return
	}
	if a.demo && (a.chart == nil || a.chart.Symbol != sym) {
		a.chart, a.chartSt, a.chartErr = a.demoHistory(sym), "ok", ""
	}
	hst := a.chart
	if hst != nil && hst.Symbol != sym {
		hst = nil
	}
	q, live := a.liveQuote(sym)
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
	c.Spans(ix, iy, iw, sp)

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
		c.Text(ix, iy+1, iw, fit(line, iw), th.Soft, false)
	}

	plotY := iy + 2
	plotH := ih - 3
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
		msg = "No one minute bars are stored for " + sym + " today."
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
	foot := fmt.Sprintf("%s to %s   ·   %d bars", first, last, len(hst.Bars))
	if step > 1 {
		foot += fmt.Sprintf(", %d min candles", step)
	}
	if a.demo {
		foot += "   ·   DEMO"
	}
	c.Text(ix, iy+ih-1, iw, fit(foot, iw), mix(th.Panel, th.Soft, 0.8), false)
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
