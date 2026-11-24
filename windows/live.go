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
	old := a.quotes
	a.quotes = q
	a.quoteCount++
	// Owner order 2026-11-16: the relay can keep repeating timestamps it calls
	// fresh while the values stand still. Only a real price, volume or observed
	// timestamp change may keep the light LIVE.
	moved := a.feedMoved.IsZero() || old == nil
	if old != nil {
		if q.Index != nil && q.Index.Fresh {
			if old.Index == nil || old.Index.Value != q.Index.Value {
				moved = true
			}
		}
		for sym, lq := range q.Items {
			if !lq.Fresh || lq.Price <= 0 {
				continue
			}
			o, ok := old.Items[sym]
			if !ok || o.Price != lq.Price || o.Volume != lq.Volume || o.ObservedAt != lq.ObservedAt {
				moved = true
			}
		}
	}
	if moved {
		a.feedMoved = a.now
	}
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
	a.applySnapshotIndex(q)
	a.rebuildSymbols()
	a.checkPriceAlerts()
	a.flow.Buy, a.flow.Sell = a.cfg.BigBuy, a.cfg.BigSell
	if a.cfg.BigBuy || a.cfg.BigSell {
		for _, fl := range a.flow.Observe(a.now, q, a.trading()) {
			a.flagCount++
			a.raiseFlag(fl)
		}
	}
}

// applySnapshotIndex puts the KSE100 reading from the live snapshot onto the
// card, which is what the header draws. The card's own answer arrives every
// fifteen seconds; the snapshot arrives at the live pace and carries the same
// reading from the same hub, so the index line never waits for the slower route.
// Owner order 2026-11-12 (latest): the owner reported a five second lag, and
// the index was the one live number read at the card's pace. The source name
// and the leaders stay the card's, and no extra request is spent.
func (a *App) applySnapshotIndex(q *Quotes) {
	if q == nil || q.Index == nil || a.market == nil {
		return
	}
	v, c, p := q.Index.Value, q.Index.Change, q.Index.ChangePct
	a.market.IndexValue, a.market.IndexChange, a.market.IndexPct = &v, &c, &p
	if q.Index.AsOf != "" {
		a.market.IndexAsOf = q.Index.AsOf
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
	// Owner order 2026-11-18: a big-order flash stays on screen for four
	// seconds.
	a.bannerUntil = a.now.Add(4 * time.Second)
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

// feedState describes the broker feed for the feed row: how old the freshest
// tick is right now, counting on from the moment the answer arrived.
func (a *App) feedState() (word string, age int, ok bool) {
	if a.quotes == nil || a.quotes.FetchedAt.IsZero() || a.feedMinAge < 0 {
		return "NO FEED", 0, false
	}
	age = a.feedMinAge + max(0, int(a.now.Sub(a.quotes.FetchedAt).Seconds()))
	// A fresh timestamp is not enough: the values themselves must have moved.
	if !a.feedMoved.IsZero() {
		age = max(age, max(0, int(a.now.Sub(a.feedMoved).Seconds())))
	}
	// Owner order 2026-11-11 (seventh pass): the relay calls a market feed
	// frame fresh until it is ninety seconds old. The HUD uses the same
	// boundary, so a normal broker burst, which repeats a symbol about every
	// 24 seconds, is LAGGING rather than a false STALE. A real outage still
	// reaches STALE after the relay's own freshness window.
	//
	// Owner order 2026-11-18: the opposite of the 2026-11-17 rule. The owner
	// sees the prices change only twice in eleven seconds, so the feed must not
	// wear LIVE through that gap. LIVE is the last five seconds; anything older
	// is LAGGING until the relay's ninety second freshness boundary.
	if age <= feedLiveSeconds {
		return "LIVE", age, true
	}
	if age <= 90 {
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
		sectorHover := a.sectorH > 0 && a.hoverY >= a.sectorY && a.hoverY < a.sectorY+a.sectorH
		switch {
		case a.sectorOpen && sectorHover:
			a.lvSectorStk.scroll(d * 2)
		case !a.sectorOpen && sectorHover:
			// The sector tile wins over the search and the ranked list: hovering
			// it and turning the wheel always moves the groups, even while a
			// search is typed above it.
			a.lvSector.scroll(d)
		case a.searchText != "":
			if n := len(a.matches()); n > 0 {
				a.searchCursor = min(max(0, a.searchCursor+d), n-1)
			}
		case a.scanChoice > 0:
			a.lvScan.scroll(d * 2)
		}
	case scrAlerts:
		// The wheel scrolls the list the pointer is over. The PRICE ALERTS tile
		// sits above the log, so it is asked before the log's own row.
		switch {
		case a.priceH > 0 && a.hoverY >= a.priceY && a.hoverY < a.priceY+a.priceH:
			a.alertFocus = 3
			a.priceCursor = min(max(0, a.priceCursor+d), priceAlertSlots-1)
		case a.alertSearchH > 0 && a.hoverX >= a.alertSearchX && a.hoverX < a.alertSearchX+a.alertSearchW &&
			a.hoverY >= a.alertSearchY && a.hoverY < a.alertSearchY+a.alertSearchH:
			a.alertFocus = 4
		case a.hoverY >= a.alertSplit:
			a.alertFocus = 2
		case a.hoverX >= a.alertSplitX:
			a.alertFocus = 1
		default:
			a.alertFocus = 0
		}
		switch a.alertFocus {
		case 3:
		case 4:
			if n := len(a.matches()); n > 0 {
				a.searchCursor = min(max(0, a.searchCursor+d), n-1)
			}
		default:
			a.alertList().scroll(d * 2)
		}
	case scrOrderFlow:
		a.lvOF.scroll(d * 3)
	case scrWatch:
		a.lvWatch.scroll(d * 3)
	case scrSettings:
		a.setCursor = min(max(0, a.setCursor+d), settingsRows-1)
	}
}

// ---------- big buying board ----------

// boardFloorShares is the quantity a stock must have traded on a board's own
// side in the window before the board names it. Owner order 2026-11-16: both
// ALERTS boards read "QTY 50k and above", not a PKR amount.
const boardFloorShares int64 = 50_000

// aboveFloor keeps the rows that traded at least boardFloorShares on the
// board's own side, so the list and the heading can never disagree.
func aboveFloor(rows []FlowStat, side int) []FlowStat {
	out := make([]FlowStat, 0, len(rows))
	for _, r := range rows {
		v := r.BuyShares
		if side == sideSell {
			v = r.SellShares
		}
		if v >= boardFloorShares {
			out = append(out, r)
		}
	}
	return out
}

// capRows keeps at most limit rows, and every row when limit is zero.
func capRows(rows []FlowStat, limit int) []FlowStat {
	if limit > 0 && len(rows) > limit {
		rows = rows[:limit]
	}
	return rows
}

// boardRows lists who is being bought hardest right now, from the flow engine.
func (a *App) boardRows(limit int) []FlowStat {
	return capRows(aboveFloor(a.flow.Board(a.now, a.quotes, 0), sideBuy), limit)
}

// sellRows lists who is being sold hardest right now.
func (a *App) sellRows(limit int) []FlowStat {
	return capRows(aboveFloor(a.flow.BoardSide(a.now, a.quotes, 0, sideSell), sideSell), limit)
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
