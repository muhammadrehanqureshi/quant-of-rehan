package main

import (
	"math"
	"sort"
	"time"
)

// This file holds what makes the numbers move: flashes when a value changes,
// the rolling charts, the feed health, the big buying alerts and the mouse.

const flashFor = 900 * time.Millisecond

// flash marks a value that just changed. dir is +1 when it rose, -1 when it fell.
type flash struct {
	dir   int
	until time.Time
}

// mark records a new reading under key and starts a flash when it differs
// from the last one.
func (a *App) mark(key string, v float64) {
	if old, ok := a.lastVal[key]; ok && old != v {
		dir := 1
		if v < old {
			dir = -1
		}
		a.flashes[key] = flash{dir, a.now.Add(flashFor)}
	}
	a.lastVal[key] = v
}

// flashAmount is 1 right after a change and fades to 0, with the direction.
func (a *App) flashAmount(key string) (k float64, dir int) {
	f, ok := a.flashes[key]
	if !ok || !a.now.Before(f.until) {
		return 0, 0
	}
	k = float64(f.until.Sub(a.now)) / float64(flashFor)
	return k * k, f.dir
}

// ingestQuotes takes one /quotes answer: it keeps the table, starts flashes,
// extends the charts, feeds the big buying detector and notes the answer's
// time for the updates per second figure.
func (a *App) ingestQuotes(q *Quotes) {
	a.quotes = q
	a.quoteCount++
	a.answers = append(a.answers, a.now)
	cut := a.now.Add(-10 * time.Second)
	i := 0
	for i < len(a.answers) && a.answers[i].Before(cut) {
		i++
	}
	a.answers = a.answers[i:]

	if q.Index != nil && q.Index.Fresh {
		a.mark("idx", q.Index.Value)
		a.idxHist.push(q.Index.Value, histLen)
	}
	for sym, lq := range q.Items {
		if !lq.Fresh || lq.Price <= 0 {
			continue
		}
		a.mark("px:"+sym, lq.Price)
		if lq.Volume > 0 {
			a.mark("vol:"+sym, float64(lq.Volume))
		}
		h := a.symHist[sym]
		if h == nil {
			h = &series{}
			a.symHist[sym] = h
		}
		h.push(lq.Price, histLen)
	}
	a.feed = quoteAges(q)
	a.feedMinAge = a.feed.Min
	a.rebuildSymbols()
	a.flow.Buy, a.flow.Sell = a.cfg.BigBuy, a.cfg.BigSell
	if a.cfg.BigBuy || a.cfg.BigSell {
		for _, fl := range a.flow.Observe(a.now, q, a.trading()) {
			a.flagCount++
			a.raiseFlag(fl)
		}
	}
}

// histLen is how many one second readings each chart keeps.
const histLen = 300

// raiseFlag announces one big buying or selling flag: the banner, the tone and
// the toast.
func (a *App) raiseFlag(fl Flag) {
	if fl.Silent {
		return
	}
	a.bannerTitle, a.bannerBody = fl.Text, fl.Detail
	a.bannerUntil = a.now.Add(25 * time.Second)
	a.bannerKind = "flow"
	a.bannerSell = fl.Side == "SELL"
	if a.bannerSell {
		a.tone(toneBigSell)
	} else {
		a.tone(toneBigBuy)
	}
	if a.cfg.Notify {
		sendToast(fl.Text, fl.Detail)
	}
}

// tone plays a sound when Settings allow it. Where the console cannot play a
// tone itself, the terminal bell stands in.
func (a *App) tone(steps []toneStep) {
	if !a.cfg.Sound {
		return
	}
	if toneNative {
		playTone(steps)
	} else {
		a.bell = true
	}
}

// feedState describes the broker feed for the header light: how old the
// freshest tick is right now, counting on from the moment the answer arrived.
func (a *App) feedState() (word string, age int, ok bool) {
	if a.quotes == nil || a.quotes.FetchedAt.IsZero() || a.feedMinAge < 0 {
		return "NO FEED", 0, false
	}
	age = a.feedMinAge + max(0, int(a.now.Sub(a.quotes.FetchedAt).Seconds()))
	switch {
	case age <= 5:
		return "LIVE", age, true
	case age <= 30:
		return "LAGGING", age, true
	}
	return "STALE", age, false
}

// updatesPerSecond is the rate of /quotes answers over the last ten seconds.
func (a *App) updatesPerSecond() float64 {
	if len(a.answers) < 2 {
		return 0
	}
	span := a.answers[len(a.answers)-1].Sub(a.answers[0]).Seconds()
	if span <= 0 {
		return 0
	}
	return float64(len(a.answers)-1) / span
}

// ---------- hit regions and the mouse ----------

type hit struct {
	x, y, w, h int
	act        func()
}

func (a *App) addHit(x, y, w, h int, act func()) {
	a.hits = append(a.hits, hit{x, y, w, h, act})
}

func (a *App) hovering(x, y, w, h int) bool {
	return a.hoverX >= x && a.hoverX < x+w && a.hoverY >= y && a.hoverY < y+h
}

// click runs the action of the top most region under the pointer.
func (a *App) click(x, y int) bool {
	for i := len(a.hits) - 1; i >= 0; i-- {
		h := a.hits[i]
		if x >= h.x && x < h.x+h.w && y >= h.y && y < h.y+h.h {
			if h.act != nil {
				h.act()
			}
			return true
		}
	}
	return false
}

func (a *App) onMouse(k Key) {
	a.hoverX, a.hoverY = k.X, k.Y
	switch k.Btn {
	case MouseLeft:
		a.click(k.X, k.Y)
	case MouseRight:
		if a.now.Before(a.bannerUntil) {
			a.bannerUntil = time.Time{}
		} else {
			a.setScreen(scrHome)
		}
	case MouseWheelUp:
		a.wheel(-1)
	case MouseWheelDown:
		a.wheel(1)
	}
}

func (a *App) wheel(d int) {
	switch a.screen {
	case scrScanner:
		if a.searchText != "" {
			if n := len(a.matches()); n > 0 {
				a.searchCursor = min(max(0, a.searchCursor+d), n-1)
			}
		} else if a.scanChoice > 0 {
			a.lvScan.scroll(d * 2)
		}
	case scrAlerts:
		// The wheel scrolls the list the pointer is over.
		switch {
		case a.hoverY >= a.alertSplit:
			a.alertFocus = 2
		case a.hoverX >= a.alertSplitX:
			a.alertFocus = 1
		default:
			a.alertFocus = 0
		}
		a.alertList().scroll(d * 2)
	case scrOrderFlow:
		a.lvOF.scroll(d * 3)
	case scrSettings:
		a.setCursor = min(max(0, a.setCursor+d), settingsRows-1)
	}
}

// ---------- big buying board ----------

// boardRows lists who is being bought hardest right now, from the flow engine.
func (a *App) boardRows(limit int) []FlowStat {
	return a.flow.Board(a.now, a.quotes, limit)
}

// sellRows lists who is being sold hardest right now.
func (a *App) sellRows(limit int) []FlowStat {
	return a.flow.BoardSide(a.now, a.quotes, limit, sideSell)
}

// flowRows lists the stocks moving most on either side, for the combined
// scanner table.
func (a *App) flowRows(limit int) []FlowStat {
	return a.flow.BoardBoth(a.now, a.quotes, limit)
}

// sortedFlagLog gives the log newest first.
func (a *App) flagLog() []Flag {
	out := make([]Flag, len(a.flow.Log))
	copy(out, a.flow.Log)
	sort.SliceStable(out, func(i, j int) bool { return out[i].Time.After(out[j].Time) })
	return out
}

var _ = math.Abs
