package main

import (
	"fmt"
	"math"
	"sort"
)

// The WATCH LIST page (owner order 2026-11-24): the owner's own scrips, in his
// own order, each one drawn with the ORDER FLOW page's own columns, so the
// SCRIP, its PRICE, CHANGE, HIGH, LOW, BID, ASK, BUYING, SELLING, UNCLEAR,
// TOTAL, the BAR, the NET DELTA and the NET DELTA % all read exactly as they
// read on the page he already knows. Nothing here is invented: every number is
// the relay's own frame for that scrip, and a scrip the relay has not sent yet
// stands on the list with no numbers until it does.
//
// Owner order 2026-11-24 (later): the box says Add a KMIALL scrip, no words sit
// under it, the footer carries the one sentence that says how to take a scrip
// out, the rows carry the ORDER FLOW page's own numbers and no diamond, and the
// ORDER line of chips stands under the box exactly as it stands on ORDER FLOW.

// watchPlaceholder is what the add box says while it is empty.
const watchPlaceholder = "Add a KMIALL scrip"

// watchFooter is the one line the WATCH LIST page writes in its footer.
const watchFooter = `Select a scrip and press "del" to remove that.`

// watchAddHint is what the tile's own title bar says. Owner order 2026-11-24
// (later): the page names the key that opens its box.
const watchAddHint = `Press "/" to add`

// watchSorts are the orders the WATCH LIST can be in. Its first order is the
// owner's own: the list reads in the order he put the scrips on it, and that is
// where the page starts.
var watchSorts = append([]string{"MY ORDER"}, flowSorts...)

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

// watchSorted is the list in the order the page is showing it. The first order
// is the owner's own, so the page starts exactly as he put the list together;
// every other order sorts it by the same figures the ORDER FLOW chips name, and
// the rows that carry no figure for the chosen order go to the bottom.
func (a *App) watchSorted() []FlowRow {
	rows := a.watchRows()
	if a.watchSort <= 0 || a.watchSort >= len(watchSorts) {
		return rows
	}
	s := a.watchSort - 1
	sort.SliceStable(rows, func(i, j int) bool {
		ki, oi := flowKey(rows[i], s)
		kj, oj := flowKey(rows[j], s)
		switch {
		case oi != oj:
			return oi
		case ki != kj:
			return ki > kj
		}
		return false // two equal rows keep the owner's own order
	})
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

// drawWatchSorts is the ORDER line of the WATCH LIST: the same chips, on the
// same cells, that the ORDER FLOW page carries. A chip clicked is the order the
// list takes, and the chip the list is in wears the diamond.
func (a *App) drawWatchSorts(c *Canvas, ix, row, iw int) {
	th := a.th
	c.Text(ix, row, 6, "ORDER ", th.Soft, false)
	cx := ix + 6
	for i, name := range watchSorts {
		i := i
		lab := name
		if i == a.watchSort {
			lab = "◆ " + name
		}
		if cx+runeLen(lab)+2 > ix+iw {
			break
		}
		fg := th.Soft
		if i == a.watchSort {
			fg = th.Hot
		}
		if a.hovering(cx, row, runeLen(lab), 1) {
			fg = th.Accent
		}
		c.Text(cx, row, runeLen(lab), lab, fg, i == a.watchSort)
		a.addHit(cx, row, runeLen(lab), 1, func() { a.watchSort = i; a.lvWatch.top() })
		cx += runeLen(lab) + 2
	}
}

// drawWatchFoot writes the page's one instruction on the panel's own last row.
func (a *App) drawWatchFoot(c *Canvas, ix, y, iw int) {
	if iw < runeLen(watchFooter) {
		return
	}
	th := a.th
	c.Spans(ix, y, iw, []Span{
		{"Select a scrip and press ", th.Soft, false},
		{"\"del\"", th.Warn, true},
		{" to remove that.", th.Soft, false},
	})
}

// drawWatch is the WATCH LIST page: the box that adds a scrip, one blank line,
// the ORDER line of chips, and the table of the owner's own tickers. Nothing is
// written under the box: the page's one instruction stands on its last row.
func (a *App) drawWatch(c *Canvas, x, y, w, h int) {
	th := a.th
	ix, iy, iw, ih := a.panel(c, x, y, w, h, "WATCH LIST", watchAddHint)
	a.addHit(x, y, w, h, func() { a.watchSearch = true })

	row := iy
	bw := a.searchBox(c, ix, row, min(iw, 40), a.watchQuery, watchPlaceholder, a.watchSearch)
	a.addHit(ix, row, bw, 1, func() { a.watchSearch = true })
	row++
	if ih < 3 {
		return
	}
	// Owner order 2026-11-24 (later): one blank line stands between the box and
	// the ORDER line of chips.
	row++
	a.drawWatchSorts(c, ix, row, iw)
	row++
	row++ // one blank row above the table, as ORDER FLOW keeps it
	// The page's one instruction stands on the panel's own last row, above the
	// tab bar that carries TAB, R and Q again.
	a.drawWatchFoot(c, ix, iy+ih-1, iw)

	rows := a.watchSorted()
	if len(rows) == 0 {
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
			barSpan := min(shareBarSpan, barFieldW-shareNetW-shareBarGap)
			if barSpan < 1 {
				barSpan = 1
			}
			c.Text(ix+barX, row, barSpan, "BAR", th.Soft, false)
			c.Text(ix+barX+barSpan+shareBarGap, row, shareNetW, "NET DELTA", th.Soft, false)
			if showNetPct {
				c.Text(ix+pctX, row, flowNetPctW, "NET DELTA %", th.Soft, false)
			}
		}
		row++
	}

	view := (iy + ih - row - 1) / per // the panel's last row is the page's footer
	if view < 1 {
		return
	}
	a.lvWatch.set(len(rows), view)
	cw := contentW(&a.lvWatch, iw)
	top := row
	pick := a.watchSymbol()
	for n := 0; n < a.lvWatch.view; n++ {
		i := a.lvWatch.off + n
		if i >= len(rows) {
			break
		}
		r := rows[i]
		ry := row
		key := a.watchIndex(r.Symbol)
		if key < 0 {
			key = i
		}
		a.zebra(c, ix, ry, cw, per, i, r.Symbol)
		// Owner order 2026-11-24 (later): the row carries its own number and a
		// full stop, exactly as ORDER FLOW numbers its rows. The diamond the
		// picked row used to wear under the # is gone; the number itself turns
		// to the hot ink so the pick still reads.
		num := fmt.Sprintf("%d.", i+1)
		numCol := th.Soft
		if r.Symbol != "" && r.Symbol == pick {
			numCol = th.Hot
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
			c.Text(ix+flowNumX, ry, flowNumW+flowGutter, num, numCol, false)
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
			sp := []Span{{num + " ", numCol, false}, {r.Symbol, symCol, true},
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
