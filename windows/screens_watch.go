package main

import (
	"fmt"
	"math"
	"sort"
	"strings"
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

// watchSorts are the orders the WATCH LIST can be in: the same seven chips the
// ORDER FLOW page carries. Owner order 2026-11-24 (later): the MY ORDER chip is
// gone from the page, so every list is read through one of those seven figures.
var watchSorts = flowSorts

// watchUniverse is every scrip the build holds by ticker: the ORDER FLOW
// answer's own rows first, then the live price table for a scrip that answer
// has not carried yet, one entry each and in ticker order, so one search reads
// the same list twice.
func (a *App) watchUniverse() []FlowRow {
	rows := make([]FlowRow, 0, len(a.cfg.Watch))
	seen := make(map[string]bool, len(a.cfg.Watch))
	add := func(r FlowRow) {
		if r.Symbol == "" || seen[r.Symbol] {
			return
		}
		seen[r.Symbol] = true
		rows = append(rows, r)
	}
	if a.of != nil {
		for _, r := range a.of.Rows {
			add(r)
		}
	}
	for sym, q := range a.prices {
		add(FlowRow{Symbol: sym, Price: q.Price, ChangePct: q.ChangePct,
			Buy: q.Buy, Sell: q.Sell, Volume: q.Volume, Fresh: true})
	}
	sort.SliceStable(rows, func(i, j int) bool { return rows[i].Symbol < rows[j].Symbol })
	return rows
}

// watchMatches is every scrip whose ticker starts with what the box holds.
// Owner order 2026-11-26: typing E answers as the letter is typed. Owner order
// 2026-11-26 (later): those answers stand in the box's own drop down, so the
// page's list is never swapped for them.
func (a *App) watchMatches(q string) []FlowRow {
	if q == "" {
		return nil
	}
	rows := a.watchUniverse()
	kept := rows[:0]
	for _, r := range rows {
		if strings.HasPrefix(r.Symbol, q) {
			kept = append(kept, r)
		}
	}
	return kept
}

// watchSuggestRows is how many matches the box's drop down holds. The footer
// still counts them all, so a fifth match is a figure away, not a taller box.
const watchSuggestRows = 4

// drawWatchMatches writes the search's answers in a drop down under the box,
// one scrip a row, with the letters he typed hot and the rest of the ticker in
// the text ink. A row tapped adds that scrip. It returns the rows the drop down
// took, none when the box is empty. The owner's list under it is never filtered
// by the search: the box is the only place the search shows.
func (a *App) drawWatchMatches(c *Canvas, ix, row, iw int) int {
	th := a.th
	q := strings.ToUpper(strings.TrimSpace(a.watchQuery))
	if q == "" {
		return 0
	}
	m := a.watchMatches(q)
	if len(m) == 0 {
		c.Text(ix, row, min(iw, 40), "No scrip starts with "+q+".", th.Soft, false)
		return 1
	}
	for i, r := range m {
		if i >= watchSuggestRows {
			break
		}
		ry := row + i
		sym := r.Symbol
		// Owner order 2026-11-27: the blue diamond is withdrawn from the search's
		// answers, and the row the arrows are on is the pick, drawn by its own
		// band instead of by a mark beside it.
		cur := i == a.watchSuggest
		a.selectRow(c, ix, ry, min(iw, 40), cur, func() { a.addWatchSymbol(sym) })
		cut := min(len(q), len(sym))
		c.Text(ix+1, ry, max(1, iw-1), sym[:cut], th.Hot, true)
		c.Text(ix+1+cut, ry, max(0, iw-1-cut), sym[cut:], th.Text, false)
	}
	return min(len(m), watchSuggestRows)
}

// watchRows is the owner's list as table rows. A ticker with no frame in the
// latest ORDER FLOW answer keeps its row, so the list never hides a scrip he
// put on it. The box's search leaves this list alone.
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

// watchSorted is the list in the order the page is showing it: the same figures
// the ORDER FLOW chips name, with the rows that carry no figure for the chosen
// order at the bottom.
func (a *App) watchSorted() []FlowRow {
	rows := a.watchRows()
	if a.watchSort < 0 || a.watchSort >= len(watchSorts) {
		return rows
	}
	s := a.watchSort
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

// watchColumns is the ORDER FLOW table with the one extra cell the WATCH LIST
// keeps between its CHANGE column and HIGH. Owner order 2026-11-25 (build 173):
// a change of 10% and above is one cell wider than the rest, so that gap is
// what keeps it from running into the high beside it.
func watchColumns(rows []FlowRow) ([10]flowCell, int) {
	cols, barX := flowColumns(rows)
	for k := 2; k < len(cols); k++ {
		cols[k].x++
	}
	return cols, barX + 1
}

// watchNum is one price the page prints, N/A when the relay has not sent it.
func watchNum(p *float64) string {
	if p == nil {
		return "N/A"
	}
	return flowPrice(*p)
}

// watchVol is one volume the page prints, N/A when the relay has not sent it.
func watchVol(p *int64) string {
	if p == nil {
		return "N/A"
	}
	return commaInt(*p)
}

// netDeltaText is the NET DELTA as a magnitude, the same figure the bars carry,
// with no minus anywhere in the build.
func netDeltaText(r FlowRow) string {
	if !r.Measured() {
		return "N/A"
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
// Owner order 2026-11-26: while the box holds letters the row says what the
// search has found instead.
func (a *App) drawWatchFoot(c *Canvas, ix, y, iw, found int) {
	if iw < 1 {
		return
	}
	th := a.th
	line := watchFooter
	if q := a.watchQuery; q != "" {
		switch found {
		case 0:
			line = fmt.Sprintf("No KMIALL scrip starts with %q.", q)
		case 1:
			line = fmt.Sprintf("1 scrip starts with %q. Tap it to add it.", q)
		default:
			line = fmt.Sprintf("%d scrips start with %q. Tap one to add it.", found, q)
		}
	}
	// The whole sentence is one ink, the word del included, so nothing in it
	// stands out in colour.
	c.Text(ix, y, iw, fit(line, iw), th.Soft, false)
}

// drawWatch is the WATCH LIST page: the box that adds a scrip, its own drop
// down of search answers while it holds letters, one blank line, the ORDER line
// of chips, and the table of the owner's own tickers. The page's one
// instruction stands on its last row.
func (a *App) drawWatch(c *Canvas, x, y, w, h int) {
	th := a.th
	ix, iy, iw, ih := a.panel(c, x, y, w, h, "WATCH LIST", watchAddHint)

	row := iy
	bw := a.searchBox(c, ix, row, min(iw, 40), a.watchQuery, watchPlaceholder, a.watchSearch)
	a.addHit(ix, row, bw, 1, func() { a.watchSearch = true })
	row++
	if ih < 3 {
		return
	}
	// Owner order 2026-11-26 (later): the box's search reads in a drop down just
	// under the box, and one blank line stands between it and the ORDER line of
	// chips. Owner order 2026-11-27: one blank line stands between the box and
	// the answers as well, so the search never starts on the box's own next row.
	if a.watchQuery != "" {
		row++
		row += a.drawWatchMatches(c, ix, row, iw)
	}
	row++
	a.drawWatchSorts(c, ix, row, iw)
	row++
	row++ // one blank row above the table, as ORDER FLOW keeps it
	// The page's one instruction stands on the panel's own last row, above the
	// tab bar that carries TAB, R and Q again. It counts the search's own rows
	// while the box holds letters.
	rows := a.watchSorted()
	found := len(rows)
	if a.watchQuery != "" {
		found = len(a.watchMatches(strings.ToUpper(strings.TrimSpace(a.watchQuery))))
	}
	a.drawWatchFoot(c, ix, iy+ih-1, iw, found)
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
	cols, barX := watchColumns(rows)
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
		px := "N/A"
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
			} else if iw-barX >= barFieldW {
				// Owner order 2026-11-27 (build 187): a row whose bar is not drawn
				// keeps its NET DELTA column, with the page's one dash.
				c.Text(ix+barX+barFieldW-shareNetW, ry, shareNetW, "-", th.Soft, true)
			}
			if showNetPct {
				// Owner order 2026-11-27 (build 187): one dash, not two, so both
				// NET DELTA columns read alike when there is no figure.
				txt, ink := "-", th.Soft
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
			// Owner order 2026-11-26 (later): the search adds a scrip from its own
			// drop down, so a tap on the list only picks the row.
			a.watchPick = key
			a.watchSearch = true
		})
		row += per
	}
	// Owner order 2026-11-27 (build 187): the average change of the list stands
	// under its last scrip, while it still fits above the page's own footer.
	// Owner order 2026-11-28 (build 188): "move the line for the average change
	// on WATCH LIST page 2 lines space above", so two blank rows stand under
	// the last scrip instead of four.
	if len(rows) > 1 {
		if avgRow := row + 2; avgRow <= iy+ih-2 {
			a.drawWatchAverage(c, ix, avgRow, iw, rows)
		}
	}
	a.scrollbar(c, x+w-2, top, a.lvWatch.view*per, &a.lvWatch)
}

// watchAverage is the average CHANGE of the list, taken over the scrips the
// relay has a percentage for. A scrip it has not sent yet takes no part in it.
func watchAverage(rows []FlowRow) (float64, bool) {
	sum, n := 0.0, 0
	for _, r := range rows {
		if r.ChangePct != nil {
			sum += *r.ChangePct
			n++
		}
	}
	if n == 0 {
		return 0, false
	}
	return sum / float64(n), true
}

// drawWatchAverage writes the average change of the list under its rows. Owner
// order 2026-11-27 (build 187): "The average change of the above scrips is
// ▲ 5%" under the last scrip, the sentence in the page's soft ink and only
// the arrow and the figure in the direction's green or red.
//
// Owner order 2026-11-28 (build 188): "remove the commas around the result of
// the mean average and have only one single spacing after drop down/up icon"
// and the mean itself read 0 when his scrips averaged 0.27, because the figure
// was cut to whole percent. The average now reads two decimals, as every
// scrip's own change does, and no quotes stand around it.
func (a *App) drawWatchAverage(c *Canvas, x, y, w int, rows []FlowRow) {
	avg, ok := watchAverage(rows)
	if !ok || w < 1 {
		return
	}
	ink := a.dirColor(avg)
	pct := fmt.Sprintf("%.2f%%", math.Abs(avg))
	c.Spans(x, y, w, []Span{
		{"The average change of the above scrips is ", a.th.Soft, false},
		{arrow(avg) + " ", ink, true},
		{pct, ink, true},
	})
}
