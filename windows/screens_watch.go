package main

import (
	"fmt"
	"math"
)

// The WATCH LIST page (owner order 2026-11-24): the owner's own scrips, in his
// own order, each one drawn with the ORDER FLOW page's own columns, so the
// SCRIP, its PRICE, CHANGE, HIGH, LOW, BID, ASK, BUYING, SELLING, UNCLEAR,
// TOTAL, the BARS, the NET DELTA and the NET DELTA % all read exactly as they
// read on the page he already knows. Nothing here is invented: every number is
// the relay's own frame for that scrip, and a scrip the relay has not sent yet
// stands on the list with no numbers until it does.

// watchRows is the owner's list as table rows. A ticker with no frame in the
// latest ORDER FLOW answer keeps its row, so the list never hides a scrip he
// put on it.
func (a *App) watchRows() []FlowRow {
	rows := make([]FlowRow, 0, len(a.cfg.Watch))
	bySym := map[string]FlowRow{}
	if a.of != nil {
		for _, r := range a.of.Rows {
			bySym[r.Symbol] = r
		}
	}
	for _, sym := range a.cfg.Watch {
		if r, ok := bySym[sym]; ok {
			rows = append(rows, r)
			continue
		}
		rows = append(rows, FlowRow{Symbol: sym})
	}
	return rows
}

// watchNum is one price the page prints, n/a when the relay has not sent it.
func watchNum(p *float64) string {
	if p == nil {
		return "n/a"
	}
	return flowPrice(*p)
}

// watchVol is one volume the page prints, n/a when the relay has not sent it.
func watchVol(p *int64) string {
	if p == nil {
		return "n/a"
	}
	return commaInt(*p)
}

// netDeltaText is the NET DELTA as a magnitude, the same figure the bars carry,
// with no minus anywhere in the build.
func netDeltaText(r FlowRow) string {
	if !r.Measured() {
		return "n/a"
	}
	return signedCompact(*r.Buy - *r.Sell)
}

// drawWatch is the WATCH LIST page: the box that adds a scrip, the sentence
// that says how, and the table of the owner's own tickers.
func (a *App) drawWatch(c *Canvas, x, y, w, h int) {
	th := a.th
	ix, iy, iw, ih := a.panel(c, x, y, w, h, "WATCH LIST", pressSearchHint)
	a.addHit(x, y, w, h, func() { a.watchSearch = true })

	row := iy
	bw := a.searchBox(c, ix, row, min(iw, 40), a.watchQuery, "Add a scrip", a.watchSearch)
	a.addHit(ix, row, bw, 1, func() { a.watchSearch = true })
	if a.watchMsg != "" && iw > bw+3 {
		c.Text(ix+bw+2, row, iw-bw-2, fit(a.watchMsg, iw-bw-2), th.Soft, false)
	}
	row++
	if ih >= 2 {
		line := "Type a scrip and press ENTER to add it. Pick a row and press DEL to take it out."
		c.Text(ix, row, iw, fit(line, iw), th.Soft, false)
		row++
	}
	if a.of == nil {
		if a.ofErr != "" {
			msg := "ORDER FLOW is not available right now: " + a.ofErr
			c.Text(ix, row, iw, fit(msg, iw), th.Warn, false)
			return
		}
		msg := "Reading ORDER FLOW from the relay. Your list is kept; the numbers arrive with the feed."
		c.Text(ix, row, iw, fit(msg, iw), th.Soft, false)
		return
	}

	rows := a.watchRows()
	if len(rows) == 0 {
		empty := "The list is empty. Type a scrip in the box and press ENTER to add it."
		c.Text(ix, row, iw, fit(empty, iw), th.Soft, false)
		return
	}

	// The table's columns are measured exactly as ORDER FLOW measures them, so
	// the two pages read the same. A narrow window drops the one line table for
	// the two row form, as ORDER FLOW does.
	wide := iw >= 100
	per := 1
	if !wide {
		per = 2
	}
	flowDropHL = false
	cols, barX := flowColumns(rows)
	barFieldW, pctX, showNetPct := flowTail(iw, barX)
	if wide {
		c.Text(ix+flowNumX, row, flowNumW, flowNumHeading, th.Soft, false)
		c.Text(ix+flowSymX, row, flowSymW, flowSymHeading, th.Soft, false)
		for k, hd := range flowHeads {
			c.Text(ix+cols[k].x, row, cols[k].w, hd, th.Soft, false)
		}
		if iw-barX >= barFieldW {
			barSpan := barFieldW
			if barSpan > shareBarSpan {
				barSpan = shareBarSpan
			}
			if barFieldW-shareNetW-shareBarGap >= shareBarBoxes {
				barSpan = barFieldW - shareNetW - shareBarGap
			}
			c.Text(ix+barX, row, barSpan, "BARS", th.Soft, false)
			c.Text(ix+barX+barSpan+shareBarGap, row, shareNetW, "NET DELTA", th.Soft, false)
			if showNetPct {
				c.Text(ix+pctX, row, flowNetPctW, "NET DELTA %", th.Soft, false)
			}
		}
		row++
	}

	view := (iy + ih - row) / per
	if view < 1 {
		return
	}
	a.lvWatch.set(len(rows), view)
	cw := contentW(&a.lvWatch, iw)
	top := row
	for n := 0; n < a.lvWatch.view; n++ {
		i := a.lvWatch.off + n
		if i >= len(rows) {
			break
		}
		r := rows[i]
		ry := row
		key := i
		a.zebra(c, ix, ry, cw, per, i, r.Symbol)
		num := fmt.Sprintf("%d.", i+1)
		if i == a.watchPick {
			num = "◆"
		}
		symCol := th.Hot
		if !r.Fresh && r.Volume == nil {
			symCol = th.Soft
		}
		chg, chgCol := "", th.Soft
		if r.ChangePct != nil {
			chg, chgCol = changeText(*r.ChangePct), a.dirColor(*r.ChangePct)
		}
		px := "n/a"
		if r.Price > 0 {
			px = flowPrice(r.Price)
		}
		if wide {
			c.Text(ix+flowNumX, ry, flowNumW, num, th.Soft, false)
			c.Text(ix+flowSymX, ry, flowSymDrawW, r.Symbol, symCol, true)
			c.Text(ix+cols[0].x, ry, cols[0].w, px, th.Text, true)
			c.Text(ix+cols[1].x, ry, cols[1].w, chg, chgCol, true)
			c.Text(ix+cols[2].x, ry, cols[2].w, watchNum(r.High), th.Good, true)
			c.Text(ix+cols[3].x, ry, cols[3].w, watchNum(r.Low), th.Bad, true)
			c.Text(ix+cols[4].x, ry, cols[4].w, watchNum(r.Bid), th.Text, true)
			c.Text(ix+cols[5].x, ry, cols[5].w, watchNum(r.Ask), th.Text, true)
			c.Text(ix+cols[6].x, ry, cols[6].w, watchVol(r.Buy), th.Good, true)
			c.Text(ix+cols[7].x, ry, cols[7].w, watchVol(r.Sell), th.Bad, true)
			uc := th.Soft
			if r.Unclassified != nil && *r.Unclassified > 0 {
				uc = th.Warn
			}
			c.Text(ix+cols[8].x, ry, cols[8].w, watchVol(r.Unclassified), uc, true)
			c.Text(ix+cols[9].x, ry, cols[9].w, watchVol(r.Volume), totalBlue, true)
			if iw-barX >= barFieldW && r.Measured() && *r.Buy+*r.Sell > 0 {
				a.shareBar(c, ix+barX, ry, barFieldW, *r.Buy, *r.Sell)
			}
			if showNetPct {
				txt, ink := "--", th.Soft
				if pct, ok := netDeltaPct(r); ok {
					txt = fmt.Sprintf("%.2f%%", math.Abs(pct))
					switch {
					case pct > 0:
						ink = th.Good
					case pct < 0:
						ink = th.Bad
					}
				}
				c.Text(ix+pctX, ry, flowNetPctW, txt, ink, true)
			}
		} else {
			sp := []Span{{num + " ", th.Soft, false}, {r.Symbol, symCol, true},
				{"  PKR " + px, th.Text, true}, {"  " + chg, chgCol, true}}
			c.Spans(ix, ry, cw, sp)
			line := fmt.Sprintf("H=%s  L=%s  B=%s  S=%s  U=%s  &  T=%s  NET DELTA=%s",
				watchNum(r.High), watchNum(r.Low), watchVol(r.Buy), watchVol(r.Sell),
				watchVol(r.Unclassified), watchVol(r.Volume), netDeltaText(r))
			tw := max(0, cw-4)
			c.Text(ix+4, ry+1, tw, fit(line, tw), th.Soft, false)
		}
		a.addHit(ix, ry, cw, per, func() {
			a.watchPick = key
			a.watchSearch = true
		})
		row += per
	}
	a.scrollbar(c, x+w-2, top, a.lvWatch.view*per, &a.lvWatch)
}
