package main

import (
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
	"time"
)

// flowSorts are the orders the ORDER FLOW list can be in. O (or LEFT and
// RIGHT) steps through them, and every chip is a click target. Owner order
// 2026-11-13: NET DELTA is one of them, highest positive first, and ENTER on
// the page puts the list in that order.
var flowSorts = []string{"TOTAL VOLUME", "BUYING VOLUME", "SELLING VOLUME", "UNCLEAR", "NET DELTA", "NET DELTA %", "CHANGE"}

// flowSortNetDelta and flowSortNetDeltaPct are the two NET DELTA orders'
// indexes in flowSorts.
const (
	flowSortNetDelta    = 4
	flowSortNetDeltaPct = 5
)

// netDeltaPct is the NET DELTA as a share of the classified volume. A row
// with no measured pair, or with no classified volume, has no percentage.
func netDeltaPct(r FlowRow) (float64, bool) {
	if !r.Measured() {
		return 0, false
	}
	total := *r.Buy + *r.Sell
	if total <= 0 {
		return 0, false
	}
	return float64(*r.Buy-*r.Sell) / float64(total) * 100, true
}

// sortedFlow gives the rows in the chosen order. A row that has no number for
// the chosen order goes to the bottom, never to the top as a zero.
func (a *App) sortedFlow() []FlowRow {
	if a.of == nil {
		return nil
	}
	rows := make([]FlowRow, len(a.of.Rows))
	copy(rows, a.of.Rows)
	if q := a.ofQuery; q != "" {
		kept := rows[:0]
		for _, r := range rows {
			if strings.HasPrefix(r.Symbol, q) {
				kept = append(kept, r)
			}
		}
		rows = kept
	}
	key := func(r FlowRow) (float64, bool) {
		switch a.ofSort {
		case 0:
			if r.Volume != nil {
				return float64(*r.Volume), true
			}
		case 1:
			if r.Measured() {
				return float64(*r.Buy), true
			}
		case 2:
			if r.Measured() {
				return float64(*r.Sell), true
			}
		case 3:
			if r.Measured() && r.Unclassified != nil {
				return float64(*r.Unclassified), true
			}
		case flowSortNetDelta:
			if r.Measured() {
				return float64(*r.Buy - *r.Sell), true
			}
		case flowSortNetDeltaPct:
			if pct, ok := netDeltaPct(r); ok {
				return pct, true
			}
		case 6:
			if r.ChangePct != nil {
				return *r.ChangePct, true
			}
		}
		return 0, false
	}
	sort.SliceStable(rows, func(i, j int) bool {
		ki, oi := key(rows[i])
		kj, oj := key(rows[j])
		switch {
		case oi != oj:
			return oi
		case ki != kj:
			return ki > kj
		}
		return rows[i].Symbol < rows[j].Symbol
	})
	return rows
}

// putBSUT draws "B=1,234  S=5,678  U=12  &  T=6,924" for one stock. The three
// parts of a measured stock are written down exactly as the relay sent them
// and U is always written, so B + S + U = T can be checked by eye. A stock whose
// split is only an estimate has its B and S marked with a tilde, and a stock
// with no split shows only its total.
func (a *App) putBSUT(c *Canvas, x, y int, r FlowRow, keys ...string) int {
	th := a.th
	vx := x
	put := func(s string, fg RGB, bold bool) {
		vx += a.flashText(c, vx, y, s, fg, bold, keys...)
	}
	putVolume := func(v int64, fg RGB, bold bool) {
		value, comma, pad := volumeCommaParts(v)
		put(value, fg, bold)
		if comma != "" {
			put(comma, th.Soft, false)
		}
		if pad != "" {
			put(pad, fg, bold)
		}
	}
	switch {
	case r.Measured():
		// Owner order 2026-11-17: every inline B, S, U and T line uses the
		// KSE100 alignment, including ORDER FLOW's narrow rows and its totals.
		return a.putBST(c, x, y, r.Buy, r.Sell, r.Volume, keys...)
	case r.Method == methodEstimated && r.Buy != nil && r.Sell != nil:
		put("B~", th.Soft, false)
		putVolume(*r.Buy, mix(th.Good, th.Soft, 0.5), false)
		put("  S~", th.Soft, false)
		putVolume(*r.Sell, mix(th.Bad, th.Soft, 0.5), false)
		put("  &  T=", th.Soft, false)
		put(leaderVolumeField(*r.Volume), totalBlue, false)
	default:
		put("T=", th.Soft, false)
		if r.Volume != nil {
			put(leaderVolumeField(*r.Volume), totalBlue, false)
		} else {
			put("n/a", totalBlue, false)
		}
	}
	return vx - x
}

// ofAge words how old the relay's frame is, from its own as_of stamp.
func (a *App) ofAge() (string, bool) {
	if a.of == nil || a.of.AsOfTime.IsZero() {
		return "", false
	}
	d := a.now.Sub(a.of.AsOfTime)
	if d < 0 {
		d = 0
	}
	return d.Round(time.Second).String(), true
}

func (a *App) drawOrderFlow(c *Canvas, x, y, w, h int) {
	th := a.th
	// Owner order 2026-11-12 (latest): the scroll hint is withdrawn from the
	// page, and the hint names the key that gives the search box the keys.
	hint := pressSearchHint
	ix, iy, iw, ih := a.panel(c, x, y, w, h, "ORDER FLOW", hint)
	if a.of == nil {
		msg := "Reading ORDER FLOW from the relay."
		col := th.Soft
		if a.ofErr != "" {
			msg = "ORDER FLOW is not available right now: " + a.ofErr
			col = th.Warn
		}
		for i, ln := range wrap(msg, iw) {
			if i < ih {
				c.Text(ix, iy+i, iw, ln, col, false)
			}
		}
		return
	}
	of := a.of
	tot := of.Totals()
	row := iy

	// Line 1: what this answer is and how old it is.
	sp := []Span{{"DAY ", th.Soft, false}, {of.Day, th.Text, true}}
	if t := of.AsOfTime; !t.IsZero() {
		age, _ := a.ofAge()
		sp = append(sp, Span{"   AS OF ", th.Soft, false}, Span{t.In(pkt).Format("15:04:05") + " PKT", th.Text, true},
			Span{"  (" + age + " ago)", th.Soft, false})
	}
	sp = append(sp, Span{"   STOCKS ", th.Soft, false}, Span{fmt.Sprintf("%d of %d", of.Included, of.Universe), th.Text, true})
	if of.Missing > 0 {
		sp = append(sp, Span{fmt.Sprintf("  (%d without a frame)", of.Missing), th.Warn, false})
	}
	c.Spans(ix, row, iw, sp)
	row++

	// Line 2: the measured totals, added up from the measured stocks only.
	t2 := []Span{{"MEASURED ", th.Soft, false}, {fmt.Sprintf("%d stocks  ", tot.Measured), th.Text, true},
		{"B=", th.Soft, false}}
	t2 = append(t2, volumeCommaSpans(tot.Buy, th.Good, true, th.Soft)...)
	t2 = append(t2, Span{"  S=", th.Soft, false})
	t2 = append(t2, volumeCommaSpans(tot.Sell, th.Bad, true, th.Soft)...)
	// Owner order 2026-11-18: U carries no comma; the ampersand already
	// separates it from T.
	t2 = append(t2, Span{"  U=", th.Soft, false})
	t2 = append(t2, volumeFieldSpans(tot.Unclassified, th.Warn, tot.Unclassified > 0)...)
	t2 = append(t2, Span{"  &  T=", th.Soft, false}, Span{leaderVolumeField(tot.MeasuredTotal), totalBlue, false})
	c.Spans(ix, row, iw, t2)
	row++

	// Line 3: what is not in the totals, and why. A shorter wording is used
	// when the long one does not fit the width.
	var long, short []string
	if tot.Estimated > 0 {
		long = append(long, fmt.Sprintf("%d with a range estimate only (B~ S~, left out of the totals)", tot.Estimated))
		short = append(short, fmt.Sprintf("%d estimated (B~ S~, not in totals)", tot.Estimated))
	}
	if tot.NoSplit > 0 {
		long = append(long, fmt.Sprintf("%d with no buy or sell split", tot.NoSplit))
		short = append(short, fmt.Sprintf("%d no split", tot.NoSplit))
	}
	if tot.Unbalanced > 0 {
		long = append(long, fmt.Sprintf("%d CHECK: B+S+U is not T", tot.Unbalanced))
		short = append(short, fmt.Sprintf("%d CHECK B+S+U<>T", tot.Unbalanced))
	}
	if len(long) == 0 {
		long, short = []string{"every stock is measured"}, []string{"all measured"}
	}
	note := strings.Join(long, "  ·  ")
	if runeLen(note) > iw {
		note = strings.Join(short, "  ·  ")
	}
	nc := th.Soft
	if tot.Unbalanced > 0 {
		nc = th.Warn
	}
	c.Text(ix, row, iw, fit(note, iw), nc, false)
	row++

	// Line 4: the order, as chips that can be clicked.
	c.Text(ix, row, 6, "ORDER ", th.Soft, false)
	cx := ix + 6
	for i, name := range flowSorts {
		i := i
		lab := name
		if i == a.ofSort {
			lab = "◆ " + name
		}
		if cx+runeLen(lab)+2 > ix+iw {
			break
		}
		fg := th.Soft
		if i == a.ofSort {
			fg = th.Hot
		}
		if a.hovering(cx, row, runeLen(lab), 1) {
			fg = th.Accent
		}
		c.Text(cx, row, runeLen(lab), lab, fg, i == a.ofSort)
		a.addHit(cx, row, runeLen(lab), 1, func() { a.ofSort = i; a.lvOF.top() })
		cx += runeLen(lab) + 2
	}
	row++ // one blank row under the chips
	row++ // one blank row above the search box
	a.drawFlowSearch(c, ix, row, iw)
	row++ // one blank row under the search box
	row++

	rows := a.sortedFlow()
	if len(rows) == 0 {
		msg := "The relay answered with no stock rows."
		if a.sessionDate != "" && !sameSessionDay(a.sessionDate, a.karachiNow()) {
			msg = "No stock rows from the relay. The last stored session is " + a.storedSessionDay() + "."
		}
		if a.ofQuery != "" {
			msg = fmt.Sprintf("No stock matches %q.", a.ofQuery)
		}
		c.Text(ix, row, iw, fit(msg, iw), th.Soft, false)
		return
	}
	// Owner order 2026-11-20: HIGH and LOW join the one line table, so the
	// columns are measured on every answer and the table reads from PRICE to
	// TOTAL without folding into two rows as soon as it used to.
	wide := iw >= 100
	per := 2
	if wide {
		per = 1
	}
	// The table's columns, measured once for the whole answer so the headings
	// and every row stand on the same cells.
	var cols [10]flowCell
	barX := 0
	pctX := 0
	barFieldW := 0
	showNetPct := false
	flowDropHL = false
	// Column header for the one-line table.
	if wide {
		// Owner order 2026-11-10 (latest): every heading sits on the very first
		// cell of its own column, which is exactly where that column's data
		// starts, because every column is left aligned on that cell.
		// Owner order 2026-11-21: the numbering is back as a "#" column on the
		// panel's first cell, and the SYMBOL field is the heading's own six cells
		// instead of build 152's eight, which takes the two spare cells out of
		// the gap before PRICE.
		cols, barX = flowColumns(rows)
		barFieldW, pctX, showNetPct = flowTail(iw, barX)
		if !showNetPct {
			// Owner order 2026-11-20 (latest): the last thing to give way is HIGH
			// and LOW, so the bar keeps its cells and both NET DELTA columns stay.
			flowDropHL = true
			cols, barX = flowColumns(rows)
			barFieldW, pctX, showNetPct = flowTail(iw, barX)
		}
		c.Text(ix+flowNumX, row, flowNumW, flowNumHeading, th.Soft, false)
		c.Text(ix+flowSymX, row, flowSymW, flowSymHeading, th.Soft, false)
		for k, hd := range flowHeads {
			if flowDropHL && (k == 2 || k == 3) {
				continue
			}
			// Owner order 2026-11-10 (latest): every value ends on its own
			// column's right edge, so the gap to the next column is the same two
			// cells on every row, and the heading sits over that edge.
			// Owner order 2026-11-11: every heading starts on its column's first
			// cell, so the table reads from the left edge.
			// Owner order 2026-11-20 (latest): the six price columns read from
			// their right edge, heading and value alike, so the two cells a shorter
			// figure used to leave behind come out of PRICE and CHANGE, HIGH and
			// LOW, LOW and BID, BID and ASK, and ASK and BUYING, and the heading
			// still stands over the figure it names.
			lab := hd
			if k <= 5 {
				lab = padLeft(hd, cols[k].w)
			}
			c.Text(ix+cols[k].x, row, cols[k].w, lab, th.Soft, false)
		}
		if iw-barX >= barFieldW {
			// Owner order 2026-11-12 (latest): the bar's own column, then a NET
			// DELTA column of its own after it, over the value every row writes.
			barSpan := barFieldW
			if barSpan > shareBarSpan {
				barSpan = shareBarSpan
			}
			if barFieldW-shareNetW-shareBarGap >= shareBarBoxes {
				barSpan = barFieldW - shareNetW - shareBarGap
			}
			c.Text(ix+barX, row, barSpan, "BARS", th.Soft, false)
			c.Text(ix+barX+barSpan+shareBarGap, row, shareNetW, "NET DELTA", th.Soft, false)
			// Owner order 2026-11-13: clicking the NET DELTA heading, like its
			// own order chip, puts the list in delta order, highest positive
			// first.
			a.addHit(ix+barX+barSpan+shareBarGap, row, shareNetW, 1, func() {
				a.ofSort = flowSortNetDelta
				a.lvOF.top()
			})
			if showNetPct {
				// Owner order 2026-11-14: the percentage has its own column
				// after NET DELTA and its own order.
				c.Text(ix+pctX, row, flowNetPctW, "NET DELTA %", th.Soft, false)
				a.addHit(ix+pctX, row, flowNetPctW, 1, func() {
					a.ofSort = flowSortNetDeltaPct
					a.lvOF.top()
				})
			}
		}
		row++
	}
	foot := 1
	view := (iy + ih - row - foot) / per
	if view < 1 {
		return
	}
	a.lvOF.set(len(rows), view)
	cw := contentW(&a.lvOF, iw)
	top := row
	for n := 0; n < a.lvOF.view; n++ {
		i := a.lvOF.off + n
		if i >= len(rows) {
			break
		}
		r := rows[i]
		pxKey := "px:" + r.Symbol
		volKey := "vol:" + r.Symbol
		a.zebra(c, ix, row, cw, per, i, r.Symbol)
		symCol := th.Hot
		if !r.Fresh {
			symCol = th.Soft
		}
		bidAsk := func(p *float64) string {
			if p == nil {
				return "n/a"
			}
			return flowPrice(*p)
		}
		// Owner report 2026-11-12 (latest): PIM read one price on the scanner and
		// another here, because each page read its own feed. A fresh broker quote
		// now moves the price and the change together on this page too, so a
		// scrip's price and percentage are one pair wherever they are shown.
		px, pct := r.Price, r.ChangePct
		if a.quotes != nil {
			if lq, ok := a.quotes.Items[r.Symbol]; ok && lq.Fresh && lq.Price > 0 {
				px = lq.Price
				if lq.ChangePct != nil {
					pct = lq.ChangePct
				}
			}
		}
		chg := ""
		chgCol := th.Soft
		if pct != nil {
			chg, chgCol = changeText(*pct), a.dirColor(*pct)
		}
		warn := ""
		if !r.Balanced() {
			warn = " CHECK"
		} else if !r.Fresh {
			warn = " STALE"
		}
		if wide {
			// Owner order 2026-11-21: the row's own number stands right aligned
			// in the "#" column on the panel's first cell, and the symbol follows
			// one gutter after it.
			c.Text(ix+flowNumX, row, flowNumW, padLeft(strconv.Itoa(i+1), flowNumW), th.Soft, false)
			// A name longer than the heading borrows the two cells the field gave
			// up, so an eight letter ticker is never cut. The price field is right
			// aligned, so a short quote leaves those cells blank.
			c.Text(ix+flowSymX, row, flowSymDrawW, r.Symbol, symCol, true)
			// Owner order 2026-11-10 (latest): every value starts on its column's
			// first cell, under its own heading.
			// Owner order 2026-11-11: every value starts on its column's first
			// cell too, BID and ASK included, so no column floats right.
			// Owner order 2026-11-20 (latest): PRICE, CHANGE, HIGH, LOW, BID and
			// ASK end on their column's right edge, so the gap that follows each of
			// them is the one cell of the gutter instead of three, and the two cells
			// a short figure leaves behind no longer widen the column.
			a.flashRight(c, ix+cols[0].x+cols[0].w, row, flowPrice(px), th.Text, true, pxKey)
			a.flashRight(c, ix+cols[1].x+cols[1].w, row, chg, chgCol, true, pxKey)
			if !flowDropHL {
				c.Text(ix+cols[2].x, row, cols[2].w, padLeft(bidAsk(r.High), cols[2].w), th.Good, false)
				c.Text(ix+cols[3].x, row, cols[3].w, padLeft(bidAsk(r.Low), cols[3].w), th.Bad, false)
			}
			c.Text(ix+cols[4].x, row, cols[4].w, padLeft(bidAsk(r.Bid), cols[4].w), th.Text, false)
			c.Text(ix+cols[5].x, row, cols[5].w, padLeft(bidAsk(r.Ask), cols[5].w), th.Text, false)
			a.drawFlowCols(c, ix, row, r, cols, volKey)
			if iw-barX >= barFieldW && r.Measured() && *r.Buy+*r.Sell > 0 {
				// Owner order 2026-11-10 (latest): the bar is back on ORDER FLOW,
				// ten boxes two cells wide, so it is longer without one extra box.
				// Owner order 2026-11-12 (latest): the NET DELTA stands in its own
				// column after the bar, buy minus sell, signed.
				a.shareBar(c, ix+barX, row, barFieldW, *r.Buy, *r.Sell)
			}
			if showNetPct {
				txt, ink, bold := "--", th.Soft, false
				if pct, ok := netDeltaPct(r); ok {
					txt = fmt.Sprintf("%.2f%%", math.Abs(pct))
					ink, bold = th.Soft, true
					switch {
					case pct > 0:
						ink = th.Good
					case pct < 0:
						ink = th.Bad
					}
				}
				c.Text(ix+pctX, row, flowNetPctW, txt, ink, bold)
			}
			if warn != "" {
				c.Text(ix+cw-len(warn), row, len(warn), warn, th.Warn, true)
			}
		} else {
			c.Spans(ix, row, cw, []Span{{fmt.Sprintf("%3d. ", i+1), th.Soft, false}, {r.Symbol, symCol, true}})
			vx := ix + 14
			vx += a.flashText(c, vx, row, "PKR "+commaFloat(px, 2), th.Text, true, pxKey)
			vx += 2
			vx += a.flashText(c, vx, row, chg, chgCol, true, pxKey)
			// Owner order 2026-11-20: the two row form carries HIGH and LOW too,
			// in the same order the one line table uses.
			vx += 2
			vx += a.flashText(c, vx, row, "HIGH "+bidAsk(r.High), th.Good, false)
			vx += 2
			vx += a.flashText(c, vx, row, "LOW "+bidAsk(r.Low), th.Bad, false)
			c.Spans(vx+2, row, max(0, ix+cw-vx-2), []Span{{"BID ", th.Soft, false}, {bidAsk(r.Bid), th.Text, false}, {"  ASK ", th.Soft, false}, {bidAsk(r.Ask), th.Text, false}})
			if warn != "" {
				c.Text(ix+cw-len(warn), row, len(warn), warn, th.Warn, true)
			}
			a.putBSUT(c, ix+5, row+1, r, volKey)
		}
		row += per
	}
	a.scrollbar(c, x+w-2, top, a.lvOF.view*per, &a.lvOF)

	// Foot: how U is defined, and what the large print board saw when there is room.
	if foot > 0 {
		fy := iy + ih - 1
		// Owner order 2026-11-13: the heading above the column is UNCLEAR, so the
		// foot says UNCLEAR too and names the feed and both totals in full.
		line := "U = UNCLEAR: The volume that the feed could not capture, U is never added to either B or S."
		if of.LargeTotal > 0 {
			more := fmt.Sprintf("  ·  %d large prints of QTY %s and more.", of.LargeTotal, compactNum(float64(boardFloorShares)))
			if runeLen(line)+runeLen(more) <= iw {
				line += more
			}
		}
		c.Text(ix, fy, iw, fit(line, iw), th.Soft, false)
	}
}

// flowTail is the bar column and the NET DELTA % column at the right of the
// table. Owner order 2026-11-20 (latest): the bar gives cells down to
// shareBarMinSpan before either NET DELTA column is dropped, so both figures
// stay on the page on the owner's window.
func flowTail(iw, barX int) (barFieldW, pctX int, showNetPct bool) {
	barFieldW = shareBarWidth
	if room := iw - 2 - barX - shareBarGap - flowNetPctW; room >= shareNetW+shareBarGap+shareBarBoxes && room < barFieldW {
		barFieldW = room
	}
	pctX = barX + barFieldW + shareBarGap
	showNetPct = iw-barX >= barFieldW && pctX+flowNetPctW <= iw-2
	return barFieldW, pctX, showNetPct
}

// The one-line table's geometry. Owner order 2026-11-10 (latest): every column
// is as wide as its own heading or the widest value it carries, whichever is
// wider, and every pair of columns is separated by the same two cells. Every
// value is right aligned on its column's right edge, so the visible gap from
// one column to the next is those same two cells on every row, not a wider one
// after a short number and a narrower one after a long one.
// Owner order 2026-11-20 (latest): one cell between the columns, not two, so the
// bar and both NET DELTA columns fit beside the ten columns the owner asked for.
const flowGutter = 1

// flowNetPctW is the width of the NET DELTA % column. Its heading is the
// widest thing the column holds.
const flowNetPctW = 11

// The number column and the symbol column that follows it. Owner order
// 2026-11-21: "#" stands on the panel's very first cell with the row's own
// number, and SYMBOL follows one gutter later. Its field is the heading's six
// cells, two fewer than build 152's eight, so the gap before PRICE is one cell
// instead of three; a longer name is drawn into those two cells and the gutter
// so it is never cut.
const (
	flowNumX, flowNumW = 0, 3
	flowNumHeading     = "#"
	flowSymX           = flowNumX + flowNumW + flowGutter
	flowSymW           = 6 // the cells between SYMBOL and PRICE
	flowSymDrawW       = 8 // the cells a long ticker may use without being cut
	flowSymHeading     = "SYMBOL"
)

// flowPriceW is the widest figure an ORDER FLOW price field carries before its
// thousands separator is the thing that goes. Owner order 2026-11-20 (latest):
// the five price columns are measured on this field, so the widest quote in the
// answer holds them at eight cells instead of nine and SYMBOL to PRICE, CHANGE
// to HIGH, HIGH to LOW, LOW to BID and BID to ASK each stand one cell closer.
const flowPriceW = 8

// flowPrice is one price as the relay sent it, two decimals with its thousands
// separator, and without the separator only when that form is wider than the
// field. No digit is ever dropped: a figure too wide for the field loses its
// separator and nothing else.
func flowPrice(v float64) string {
	s := commaFloat(v, 2)
	if runeLen(s) > flowPriceW {
		s = strconv.FormatFloat(v, 'f', 2, 64)
	}
	return s
}

// Owner order 2026-11-12 (latest): the unclassified column is written in full.
// Owner order 2026-11-20: HIGH and LOW stand after CHANGE, before BID, so the
// day's range reads beside the move it came from.
var flowHeads = [10]string{"PRICE", "CHANGE", "HIGH", "LOW", "BID", "ASK", "BUYING (B)", "SELLING (S)", "UNCLEAR (U)", "TOTAL (T)"}

// flowCell is one column of the table: the cell it starts on and its width.
type flowCell struct{ x, w int }

// flowDropHL is set for a frame when the window cannot hold every column.
// Owner order 2026-11-20 (latest): NET DELTA and NET DELTA % outrank HIGH and
// LOW, which step out on a narrow window and come back when the room returns.
var flowDropHL bool

// flowColumns measures the whole answer and returns the ten columns and the
// cell the bar column starts on. A column is never narrower than its heading.
func flowColumns(rows []FlowRow) ([10]flowCell, int) {
	var w [10]int
	for i, hd := range flowHeads {
		w[i] = runeLen(hd)
	}
	num := func(p *int64) string {
		if p == nil {
			return "n/a"
		}
		return commaInt(*p)
	}
	set := func(i int, s string) { w[i] = max(w[i], runeLen(s)) }
	flt := func(i int, p *float64) {
		if p == nil {
			set(i, "n/a")
			return
		}
		set(i, flowPrice(*p))
	}
	for _, r := range rows {
		set(0, flowPrice(r.Price))
		if r.ChangePct != nil {
			set(1, changeText(*r.ChangePct))
		} else {
			set(1, "n/a")
		}
		flt(2, r.High)
		flt(3, r.Low)
		flt(4, r.Bid)
		flt(5, r.Ask)
		switch {
		case r.Measured():
			set(6, num(r.Buy))
			set(7, num(r.Sell))
			set(8, num(r.Unclassified))
			set(9, num(r.Volume))
		case r.Method == methodEstimated && r.Buy != nil && r.Sell != nil:
			set(6, "~"+num(r.Buy))
			set(7, "~"+num(r.Sell))
			set(8, "estimate")
			set(9, num(r.Volume))
		default:
			set(6, "no split")
			set(9, num(r.Volume))
		}
	}
	if flowDropHL {
		w[2], w[3] = 0, 0
	}
	x := flowSymX + flowSymW + flowGutter
	var cols [10]flowCell
	for i := 0; i < 10; i++ {
		if w[i] == 0 && (i == 2 || i == 3) {
			// The column has stepped out: its cell goes to the one after it.
			cols[i] = flowCell{x: x, w: 0}
			continue
		}
		cols[i] = flowCell{x: x, w: w[i]}
		x += w[i] + flowGutter
	}
	return cols, x
}

// drawFlowCols draws the four volume columns of the one-line table, which start
// after HIGH, LOW, BID and ASK. Each value sits under its header, with U never
// merged into B or S.
func (a *App) drawFlowCols(c *Canvas, ix, y int, r FlowRow, cols [10]flowCell, volKey string) {
	th := a.th
	cell := func(k int, p *int64, fg RGB, bold bool, prefix string) {
		s := "n/a"
		if p != nil {
			s = commaInt(*p)
		}
		a.flashText(c, ix+cols[k].x, y, prefix+s, fg, bold, volKey)
	}
	switch {
	case r.Measured():
		cell(6, r.Buy, th.Good, true, "")
		cell(7, r.Sell, th.Bad, true, "")
		uc, ub := th.Soft, false
		if r.Unclassified != nil && *r.Unclassified > 0 {
			uc, ub = th.Warn, true
		}
		cell(8, r.Unclassified, uc, ub, "")
		cell(9, r.Volume, totalBlue, false, "")
	case r.Method == methodEstimated && r.Buy != nil && r.Sell != nil:
		cell(6, r.Buy, mix(th.Good, th.Soft, 0.5), false, "~")
		cell(7, r.Sell, mix(th.Bad, th.Soft, 0.5), false, "~")
		c.Text(ix+cols[8].x, y, cols[8].w, padLeft("estimate", cols[8].w), th.Soft, false)
		cell(9, r.Volume, totalBlue, false, "")
	default:
		c.Text(ix+cols[6].x, y, cols[6].w, "no split", th.Soft, false)
		cell(9, r.Volume, totalBlue, false, "")
	}
}

// drawFlowSearch draws the ORDER FLOW search box in the same filled field as
// the SCANNER tile. The slash key focuses it, letters and digits go into the
// box, and ESC clears the filter.
func (a *App) drawFlowSearch(c *Canvas, ix, y, iw int) {
	th := a.th
	// Owner order 2026-11-09 (build 29): the field stands alone. The word
	// SEARCH before it is gone, exactly as the SECTORS field already was.
	bw := iw
	if bw > 40 {
		bw = 40
	}
	if bw < 1 {
		bw = 1
	}
	fw := a.searchBox(c, ix, y, bw, a.ofQuery, scripSearchHint, a.ofSearch)
	if a.ofQuery != "" {
		c.Text(ix+2+fw, y, 12, fmt.Sprintf("%d match", len(a.sortedFlow())), th.Soft, false)
	}
	// Owner order 2026-11-12 (latest): the ESC clears note is withdrawn from the
	// right of the search box as well, so the line carries nothing but the box.
	a.addHit(ix, y, iw, 1, func() { a.ofSearch = true; a.lvOF.top() })
}

func padLeft(s string, w int) string {
	n := runeLen(s)
	if n >= w {
		return s
	}
	return strings.Repeat(" ", w-n) + s
}
