package main

import (
	"fmt"
	"sort"
	"strings"
	"time"
)

// flowSorts are the orders the ORDER FLOW list can be in. O (or LEFT and
// RIGHT) steps through them.
var flowSorts = []string{"TOTAL VOLUME", "BUYING VOLUME", "SELLING VOLUME", "UNCLASSIFIED", "CHANGE", "SYMBOL"}

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
		case 4:
			if r.ChangePct != nil {
				return *r.ChangePct, true
			}
		}
		return 0, false
	}
	sort.SliceStable(rows, func(i, j int) bool {
		if a.ofSort == 5 {
			return rows[i].Symbol < rows[j].Symbol
		}
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

// putBSUT draws "B=1,234, S=5,678, U=12 & T=6,924" for one stock. The three
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
	num := func(p *int64) string {
		if p == nil {
			return "n/a"
		}
		return commaInt(*p)
	}
	switch {
	case r.Measured():
		put("B=", th.Soft, false)
		put(num(r.Buy), th.Good, true)
		put(", S=", th.Soft, false)
		put(num(r.Sell), th.Bad, true)
		put(", U=", th.Soft, false)
		uc := th.Soft
		if r.Unclassified != nil && *r.Unclassified > 0 {
			uc = th.Warn
		}
		put(num(r.Unclassified), uc, r.Unclassified != nil && *r.Unclassified > 0)
		put(" & T=", th.Soft, false)
		put(num(r.Volume), totalBlue, false)
	case r.Method == methodEstimated && r.Buy != nil && r.Sell != nil:
		put("B~", th.Soft, false)
		put(num(r.Buy), mix(th.Good, th.Soft, 0.5), false)
		put(", S~", th.Soft, false)
		put(num(r.Sell), mix(th.Bad, th.Soft, 0.5), false)
		put(" & T=", th.Soft, false)
		put(num(r.Volume), totalBlue, false)
	default:
		put("T=", th.Soft, false)
		put(num(r.Volume), totalBlue, false)
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
	hint := "/ searches. UP and DOWN scroll."
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
		{"B=", th.Soft, false}, {commaInt(tot.Buy), th.Good, true},
		{", S=", th.Soft, false}, {commaInt(tot.Sell), th.Bad, true},
		{", U=", th.Soft, false}, {commaInt(tot.Unclassified), th.Warn, tot.Unclassified > 0},
		{" & T=", th.Soft, false}, {commaInt(tot.MeasuredTotal), totalBlue, false}}
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
	a.drawFlowSearch(c, ix, row, iw)
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
	wide := iw >= 102
	per := 2
	if wide {
		per = 1
	}
	// Column header for the one-line table.
	if wide {
		c.Text(ix, row, 4, "  #", th.Soft, false)
		c.Text(ix+5, row, 8, "SYMBOL", th.Soft, false)
		for k, hd := range []string{"PRICE", "CHANGE", "BID", "ASK"} {
			c.Text(ix+colX[k], row, colW[k], padLeft(hd, colW[k]), th.Soft, false)
		}
		for k, hd := range []string{"BUYING (B)", "SELLING (S)", "UNCL. (U)", "TOTAL (T)"} {
			c.Text(ix+colX[4+k], row, colW[4+k], padLeft(hd, colW[4+k]), th.Soft, false)
		}
		if bw := contentW(&a.lvOF, iw) - flowBarX; bw >= 12 {
			bw = min(shareBarWidth, bw)
			c.Text(ix+flowBarX, row, bw, padLeft("BARS", bw), th.Soft, false)
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
			return commaFloat(*p, 2)
		}
		chg := ""
		chgCol := th.Soft
		if r.ChangePct != nil {
			chg, chgCol = changeText(*r.ChangePct), a.dirColor(*r.ChangePct)
		}
		warn := ""
		if !r.Balanced() {
			warn = " CHECK"
		} else if !r.Fresh {
			warn = " STALE"
		}
		if wide {
			c.Text(ix, row, 4, fmt.Sprintf("%3d.", i+1), th.Soft, false)
			c.Text(ix+5, row, 8, r.Symbol, symCol, true)
			a.flashText(c, ix+colX[0], row, padLeft(commaFloat(r.Price, 2), colW[0]), th.Text, true, pxKey)
			a.flashText(c, ix+colX[1], row, padLeft(chg, colW[1]), chgCol, true, pxKey)
			c.Text(ix+colX[2], row, colW[2], padLeft(bidAsk(r.Bid), colW[2]), th.Text, false)
			c.Text(ix+colX[3], row, colW[3], padLeft(bidAsk(r.Ask), colW[3]), th.Text, false)
			a.drawFlowCols(c, ix, row, r, volKey)
			if bw := cw - flowBarX; bw >= 12 && r.Measured() && *r.Buy+*r.Sell > 0 {
				a.shareBarMid(c, ix+flowBarX, row, min(shareBarWidth, bw), float64(*r.Buy)/float64(*r.Buy+*r.Sell))
			}
			if warn != "" {
				c.Text(ix+cw-len(warn), row, len(warn), warn, th.Warn, true)
			}
		} else {
			c.Spans(ix, row, cw, []Span{{fmt.Sprintf("%3d. ", i+1), th.Soft, false}, {r.Symbol, symCol, true}})
			vx := ix + 14
			vx += a.flashText(c, vx, row, "PKR "+commaFloat(r.Price, 2), th.Text, true, pxKey)
			vx += 2
			vx += a.flashText(c, vx, row, chg, chgCol, true, pxKey)
			c.Spans(vx+2, row, ix+cw-vx-2, []Span{{"BID ", th.Soft, false}, {bidAsk(r.Bid), th.Text, false}, {"  ASK ", th.Soft, false}, {bidAsk(r.Ask), th.Text, false}})
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
		line := "U = unclassified: volume the capture could not side, never added to B or S"
		if runeLen(line) > iw {
			line = "U = unclassified, never added to B or S"
		}
		if of.LargeTotal > 0 {
			more := fmt.Sprintf("  ·  %d large prints of PKR %s or more today", of.LargeTotal, compactNum(of.LargeThreshold))
			if runeLen(line)+runeLen(more) <= iw {
				line += more
			}
		}
		c.Text(ix, fy, iw, fit(line, iw), th.Soft, false)
	}
}

// The one-line table's columns, as offsets from the panel's left edge and widths.
// Price, change, bid, ask, then B, S, U and T.
var (
	colX = [8]int{13, 23, 33, 43, 54, 66, 78, 90}
	colW = [8]int{9, 9, 9, 9, 11, 11, 11, 11}
)

const flowBarX = 102

// drawFlowCols draws the four volume columns of the one-line table. Each value
// sits under its header, with U never merged into B or S.
func (a *App) drawFlowCols(c *Canvas, ix, y int, r FlowRow, volKey string) {
	th := a.th
	cell := func(k int, p *int64, fg RGB, bold bool, prefix string) {
		s := "n/a"
		if p != nil {
			s = commaInt(*p)
		}
		a.flashText(c, ix+colX[k], y, padLeft(prefix+s, colW[k]), fg, bold, volKey)
	}
	switch {
	case r.Measured():
		cell(4, r.Buy, th.Good, true, "")
		cell(5, r.Sell, th.Bad, true, "")
		uc, ub := th.Soft, false
		if r.Unclassified != nil && *r.Unclassified > 0 {
			uc, ub = th.Warn, true
		}
		cell(6, r.Unclassified, uc, ub, "")
		cell(7, r.Volume, totalBlue, false, "")
	case r.Method == methodEstimated && r.Buy != nil && r.Sell != nil:
		cell(4, r.Buy, mix(th.Good, th.Soft, 0.5), false, "~")
		cell(5, r.Sell, mix(th.Bad, th.Soft, 0.5), false, "~")
		c.Text(ix+colX[6], y, colW[6], padLeft("estimate", colW[6]), th.Soft, false)
		cell(7, r.Volume, totalBlue, false, "")
	default:
		c.Text(ix+colX[4], y, colW[4], padLeft("no split", colW[4]), th.Soft, false)
		cell(7, r.Volume, totalBlue, false, "")
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
	if iw > 70 {
		rightAlign(c, ix, y, iw, []Span{{"/ searches  ESC clears", th.Soft, false}})
	}
	a.addHit(ix, y, iw, 1, func() { a.ofSearch = true; a.lvOF.top() })
}

func padLeft(s string, w int) string {
	n := runeLen(s)
	if n >= w {
		return s
	}
	return strings.Repeat(" ", w-n) + s
}
