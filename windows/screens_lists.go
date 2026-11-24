package main

import (
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
)

// selectRow draws the selected-row ground and registers its click.
func (a *App) selectRow(c *Canvas, x, y, w int, cur bool, act func()) RGB {
	th := a.th
	bg := c.BGAt(x, y)
	switch {
	case cur:
		bg = mix(bg, th.Accent, 0.22)
	case a.hovering(x, y, w, 1):
		bg = mix(bg, th.Accent, 0.1)
	}
	for k := 0; k < w; k++ {
		c.Set(x+k, y, ' ', th.Text, bg, false)
	}
	if act != nil {
		a.addHit(x, y, w, 1, act)
	}
	return bg
}

// ---------- scrolling ----------

// listView is the scroll state of one list. The drawer says how many items
// there are and how many fit, and the offset is kept inside that every frame,
// so a list can never be scrolled into emptiness or cut off at its end.
type listView struct{ off, total, view int }

func (l *listView) set(total, view int) {
	l.total, l.view = total, max(1, view)
	l.off = min(max(0, l.off), max(0, total-l.view))
}

func (l *listView) scroll(d int) { l.off = min(max(0, l.off+d), max(0, l.total-l.view)) }
func (l *listView) page(d int)   { l.scroll(d * max(1, l.view-1)) }
func (l *listView) top()         { l.off = 0 }
func (l *listView) bottom()      { l.off = max(0, l.total-l.view) }

// contentW is the width left for a list's rows: two columns less when the list
// scrolls, so the bar never touches the numbers.
func contentW(l *listView, iw int) int {
	if l.total > l.view {
		return iw - 2
	}
	return iw
}

// scrollbar draws a thin bar down column x from row y for h rows, only when
// the list does not fit. Clicking the track above the thumb pages up and
// below it pages down.
func (a *App) scrollbar(c *Canvas, x, y, h int, l *listView) {
	if l.total <= l.view || h < 3 {
		return
	}
	th := a.th
	thumb := max(1, h*l.view/l.total)
	pos := 0
	if span := l.total - l.view; span > 0 {
		pos = (h - thumb) * l.off / span
	}
	for i := 0; i < h; i++ {
		if i >= pos && i < pos+thumb {
			c.Put(x, y+i, '┃', th.Accent, true)
		} else {
			c.Put(x, y+i, '│', th.Line, false)
		}
	}
	if pos > 0 {
		a.addHit(x, y, 1, pos, func() { l.page(-1) })
	}
	if below := h - pos - thumb; below > 0 {
		a.addHit(x, y+pos+thumb, 1, below, func() { l.page(1) })
	}
}

// zebra tints every other item of a list and makes its rows clickable: a click
// opens the symbol in Search.
func (a *App) zebra(c *Canvas, x, y, w, rows, i int, sym string) {
	th := a.th
	hover := a.hovering(x, y, w, rows)
	for r := 0; r < rows; r++ {
		for k := 0; k < w; k++ {
			bg := c.BGAt(x+k, y+r)
			switch {
			case hover:
				bg = mix(bg, th.Accent, 0.12)
			case i%2 == 0:
				bg = mix(bg, th.Accent, 0.05)
			}
			c.Set(x+k, y+r, ' ', th.Text, bg, false)
		}
	}
	a.addHit(x, y, w, rows, func() { a.openSymbol(sym) })
}

// openSymbol shows one symbol in the search tile at the top of the scanner.
func (a *App) openSymbol(sym string) {
	a.setScreen(scrScanner)
	a.sectorOpen = false
	a.sectorQuery, a.sectorSearch = "", false
	a.lvSectorStk.top()
	a.searchText, a.searchCursor = sym, 0
	a.selectedSym = sym
	a.fetchOrDemo(sym)
}

// ---------- scanner ----------

// scanChoices are the six CUSTOM SCRIPS OF VOLUME sorts. Owner order 2026-11-12:
// the heading reads OF VOLUME, the two existing sorts keep their places, and
// four more are added. Each names three scrips, and every one of them is
// decided by volume.
var scanChoices = [6]string{
	"PRICES RISING FAST",
	"MORE BUYERS & LESS SELLERS",
	"MORE SELLERS & LESS BUYERS",
	"ALMOST NO VOLUME AT ALL",
	"SCRIPS WITH LOWER LOCK",
	"SCRIPS WITH UPPER LOCK",
}

// scanTable is the table the six sorts rank. The broker feed wins: when a
// symbol is in /quotes with a fresh tick, that is what is ranked, so the list
// moves with the market. The relay's /prices table fills in anything the feed
// does not carry. Buy, sell and volume come from the measured flow row.
func (a *App) scanTable() map[string]Quote {
	out := make(map[string]Quote, len(a.prices))
	for s, q := range a.prices {
		out[s] = q
	}
	if a.quotes == nil {
		return out
	}
	for s, lq := range a.quotes.Items {
		if !lq.Fresh || lq.Price <= 0 || !a.inUniverse(s) {
			continue
		}
		q := Quote{Price: lq.Price, ChangePct: lq.ChangePct}
		if lq.Volume > 0 {
			v := lq.Volume
			q.Volume = &v
		}
		if old, ok := out[s]; ok {
			q.Buy, q.Sell = old.Buy, old.Sell
			if q.Volume == nil {
				q.Volume = old.Volume
			}
		}
		// Owner order 2026-11-11: every scrip reads the same measured pair as
		// the Android app, taken from the relay's flow row. The day-range
		// estimate is gone from every Windows display.
		if a.of != nil {
			for _, fr := range a.of.Rows {
				if fr.Symbol == s && fr.Measured() {
					b, sl := *fr.Buy, *fr.Sell
					q.Buy, q.Sell = &b, &sl
					// Owner order 2026-11-12: the scanner ranks and draws the
					// measured capture's own total, so B + S + U = T on every row.
					total := b + sl
					q.Volume = &total
					break
				}
			}
		}
		if q.Volume == nil && q.Buy != nil && q.Sell != nil {
			total := *q.Buy + *q.Sell
			q.Volume = &total
		}
		out[s] = q
	}
	return out
}

// drawScanner is the scanner with the search tile on top. The search tile is as
// tall as it needs to be (three rows when nothing is typed), and the scanner
// continues below it.
func (a *App) drawScanner(c *Canvas, x, y, w, h int) {
	th := a.th
	a.sectorY, a.sectorH = 0, 0
	sh := a.searchTileHeight(w, h)
	a.drawSearchTile(c, x, y, w, sh)
	// Owner order 2026-11-11: the SEARCH tile and the SECTORS tile are two
	// separate tiles, with one blank row between them so their frames never
	// read as one crowded box.
	sy := y + sh + 1
	// The new breathing rows inside the search tile cost two rows. On the
	// shortest windows the gap between the search and sector tiles gives one
	// back, so the ranked list keeps all three scrips.
	if h-sh < 28 {
		sy = y + sh
	}
	// The sector tile sits between the search and the ranked list. It grows to
	// show every group it can while leaving the ranked list at least six rows,
	// and it scrolls when there are more groups than rows. Owner order
	// 2026-11-13: the tile shows six groups at most; the rest scroll. A tapped
	// sector opens its scrips inside this tile, and the CUSTOM SCRIPS tile below
	// stays on screen, so the two lists can be read together.
	sectorH := 6
	if a.sectorOpen {
		sectorH = min(max(len(a.visibleSectorMembers())+3, 8), 9)
	} else if n := len(a.visibleSectorIndices()); n > 0 {
		// Owner order 2026-11-17: the blank row before the search field is
		// withdrawn, so the six groups fit one row lower than before. On a
		// short window the tile gives one more row to CUSTOM SCRIPS so all
		// three scrips and all six sorts fit.
		if h < 35 {
			// The short window spends its rows on CUSTOM SCRIPS: the field
			// stands tight under the title and three groups remain visible.
			sectorH = min(n+3, 6)
		} else {
			sectorH = min(n+4, 10)
		}
	}
	// Owner order 2026-11-13: the calculator is a tile of its own under the
	// CUSTOM SCRIPS tile. It takes four rows at the bottom of the page and the
	// scrips list keeps the room above it. A window too short for the tile and
	// the lists hides the tile rather than cutting the scanner's own rows.
	calcH := 4
	if !a.calcOpen && y+h-sy-sectorH-1-calcH < 13 {
		calcH = 0
	}
	calcReserve := calcH
	if calcH > 0 {
		// Owner order 2026-11-17: one blank line always stands between CUSTOM
		// SCRIPS OF VOLUME and the calculator pair.
		calcReserve++
		defer a.drawCalcPair(c, x, y+h-calcH, w, calcH)
	}
	// The gap costs one row. On a short window, keep the ranked list at four
	// stocks by letting the sector list scroll instead of taking that row. The
	// calculator already owns the rows it needs, so this old trade only runs
	// when the tile is hidden.
	if calcH == 0 && a.scanChoice != 0 && !a.sectorOpen && sectorH > 5 {
		for sectorH > 5 {
			sh2 := y + h - sy - sectorH - 1 - calcReserve
			if sh2 < 6 {
				break
			}
			ih := sh2 - 2
			// Owner order 2026-11-11 (fourth pass): the sort rows are part of
			// the tile and are never traded away to give the sector list room,
			// so this test always reserves them. A scrip opened from a sector
			// grows the search tile above, and without this reservation that
			// growth used to hide the sub menus.
			//
			// Owner order 2026-11-12 (latest): the six sorts stand in one
			// column, so the sector list gives up two of its rows when the three
			// scrips would not otherwise fit.
			menu := len(scanChoices)
			rows := ih - menu - 2
			if rows/2 >= 3 {
				break
			}
			sectorH--
		}
	}
	if avail := y + h - sy; avail-sectorH-calcReserve < 6 {
		sectorH = max(5, avail-calcReserve-6)
	}
	// Owner order 2026-11-18: the shortest window gives the gutter between the
	// SECTORS and CUSTOM SCRIPS tiles to the three spaced scrips, after the gap
	// between SEARCH and SECTORS has already gone.
	tileGap := 1
	if h < 28 {
		tileGap = 0
	}
	if y+h-sy >= sectorH+tileGap+calcReserve+6 {
		if a.sectorOpen {
			a.drawSectorOpen(c, x, sy, w, sectorH)
		} else {
			a.drawSectorTile(c, x, sy, w, sectorH)
		}
		sy += sectorH + tileGap
	}
	sh2 := y + h - sy - calcReserve
	if sh2 < 6 {
		return
	}
	// The sort instruction rides in the panel hint so the menu and the list keep
	// the row back that the sector search above took.
	// Owner order 2026-11-12 (latest): the UP, DOWN, PGUP, PGDN hint is
	// withdrawn, and the arrow keys keep working exactly as they did.
	// Owner order 2026-11-15: the hint carries the owner's exact words, the
	// keys in capitals, and no full stop after "to move".
	hint := "Press " + `"LEFT & RIGHT ARROW KEYS"` + " to move"
	if a.searchText != "" {
		hint = "ESC clears the search"
	}
	ix, iy, iw, ih := a.panel(c, x, sy, w, sh2, "CUSTOM SCRIPS OF VOLUME", hint)
	// Owner order 2026-11-12 (latest): every sort stands in the one left hand
	// column, the new ones under the two that were already there. Owner order
	// 2026-11-18: that column is narrower, so the chosen sort reveals its three
	// scrips on the right where the tile has room, not under the menu.
	menuW := min(iw, 40)
	menu := len(scanChoices)
	if ih < menu+1 {
		// Only a tile with no room left at all drops a sort row.
		menu = max(0, ih-1)
	}
	if menu == 0 {
		return
	}
	for i, name := range scanChoices {
		if i >= menu {
			break
		}
		ry := iy + i
		id := i + 1
		cur := i == a.scanCursor
		bg := a.selectRow(c, ix, ry, menuW, cur, func() { a.pickScan(id) })
		mark := " "
		if cur {
			// Owner order 2026-11-11: the sub menu cursor is the diamond,
			// the same mark the rest of the build selects with.
			mark = "◆"
		}
		// Owner order 2026-11-16: the CUSTOM SCRIPS list carries one diamond,
		// on the cursor's own left edge. The chosen sort's inline diamond is
		// withdrawn, so the list never shows two at once.
		// Owner order 2026-11-11: the sub menu cursor is blue, not white.
		c.Set(ix+1, ry, []rune(mark)[0], th.Accent, bg, true)
		// Owner order 2026-11-13: the six sorts carry their sequence numbers,
		// the same `1.` to `6.` the SECTORS tile uses.
		c.Text(ix+3, ry, 3, fmt.Sprintf("%2d.", id), th.Soft, false)
		c.Text(ix+7, ry, max(1, menuW-7), name, th.Text, a.scanChoice == id)
	}
	head := iy + menu + 1 // the row after the menu, or the first row when it is hidden
	listX, listW := ix, iw
	rightList, showHead := false, true
	if rx := ix + menuW + 3; ih >= 8 && iw-menuW-3 >= 72 {
		// The sub menu's scrips stand on the right, beside the six sorts. Each
		// scrip keeps its three rows; the price, its change and the bar share
		// the name row, where the width now is.
		head, listX, listW, rightList = iy, rx, iw-menuW-3, true
	} else if rows := iy + ih - (head + 1); rows/3 < 3 && head > iy+menu {
		// Owner order 2026-11-18: the blank row and the duplicate sort heading
		// go before the third scrip does. The chosen sort already carries its
		// mark in the menu above.
		head, showHead = iy+menu-1, false
	}
	if a.scanChoice == 0 || head >= iy+ih {
		return
	}
	if showHead {
		c.Text(listX, head, listW, scanChoices[a.scanChoice-1], th.Accent, true)
	}
	top := head + 1
	rows := iy + ih - top
	if rows < 2 {
		return
	}
	tbl := a.scanTable()
	if len(tbl) == 0 {
		for i, ln := range wrap("No live quotes yet. Quotes arrive when the market is live.", listW) {
			c.Text(listX, top+i, listW, ln, th.Soft, false)
		}
		return
	}
	var syms []string
	switch a.scanChoice {
	case 1:
		syms = rankedSpeedSymbols(tbl)
	case 2:
		syms = rankedSplitSymbols(tbl)
	case 3:
		syms = rankedSellerSymbols(tbl)
	case 4:
		syms = rankedQuietSymbols(tbl)
	case 5:
		syms = rankedLowerLockSymbols(tbl)
	case 6:
		syms = rankedUpperLockSymbols(tbl)
	}
	if len(syms) == 0 {
		c.Text(listX, top, listW, "No scrip qualifies right now.", th.Soft, false)
		return
	}
	// Owner order 2026-11-20: a CUSTOM SCRIPS scrip reads on two rows, its name
	// and its values, with no blank row between them, so the tile shows more
	// scrips and no scrip is pushed out by an empty line.
	a.lvScan.set(len(syms), rows/2)
	// Owner order 2026-11-12 (latest): the "1 to 3 of 3 scrips" count is
	// withdrawn from the sort's heading line, which now carries the sort's own
	// name and nothing else.
	row := top
	cw := contentW(&a.lvScan, listW)
	// Owner order 2026-11-12: the values on every scrip are the KSE100 tile's
	// own, in its own columns. B, S, U and T start on the same cell on every
	// scrip, the price follows the widest one, and the change and the bar close
	// the line, exactly as the three leaders on the KSE100 tile line up.
	cols := scanBSTCols(tbl)
	pxW := 1
	for _, s := range syms {
		if q := tbl[s]; q.Price > 0 {
			pxW = max(pxW, runeLen(commaFloat(q.Price, 2)))
		}
	}
	// Owner order 2026-11-21 (second pass): the NET DELTA field is only as wide
	// as the widest figure this list carries, so a short 3M stands one gutter
	// after its bar instead of at the tile's far edge.
	netW := scanNetW(syms, tbl)
	for n := 0; n < a.lvScan.view; n++ {
		i := a.lvScan.off + n
		if i >= len(syms) {
			break
		}
		s := syms[i]
		q := tbl[s]
		pxKey, volKey := "px:"+s, "vol:"+s
		a.zebra(c, listX, row, cw, 2, i, s)
		c.Spans(listX, row, cw, []Span{{fmt.Sprintf("%d. ", i+1), th.Soft, false}, {s, th.Hot, true}})
		if rightList {
			// Owner order 2026-11-20: the price, the percentage, the bar and
			// its NET DELTA move to the tile's right edge, on the scrip's own
			// row, instead of starting on the T column in the middle.
			// Owner order 2026-11-22: the group stands two cells further left,
			// so it no longer clings to the tile's frame.
			a.drawScanQuote(c, row, x+w-6, listX+3+runeLen(s)+2, false, q, pxW, netW, pxKey)
		}
		row++ // the values row, on the row under the name
		// Owner order 2026-11-15: every sort uses one fixed set of B, S, U
		// and T columns, at every window width. The old narrow fallback packed
		// the values, so S, U and T started on different cells from row to row.
		used := a.putBSTCols(c, listX+3, row, q.Buy, q.Sell, q.Volume, cols, volKey, pxKey)
		if !rightList {
			// Owner order 2026-11-22: the same two cells back apply when the
			// group follows the volumes on one row.
			a.drawScanQuote(c, row, x+w-6, listX+3+used+1, false, q, pxW, netW, pxKey)
		}
		row++
	}
	a.scrollbar(c, x+w-2, top, a.lvScan.view*2, &a.lvScan)
}

// scanTTextX is the cell the T label stands on, counted from the B block's
// first cell. putBSTWide writes B, S and U in fixed eleven cell fields, so the
// revealed CUSTOM SCRIPS list can start its quote group on that column.
const scanTTextX = 48

// drawScanQuote draws a scanner scrip's PKR price, its change and its bar at
// the right of one row. Owner order 2026-11-18: the scrip list on the right of
// CUSTOM SCRIPS puts them on the scrip's name row, so the B, S, U and T line
// below keeps its fixed columns. Owner order 2026-11-19: that revealed list
// starts the whole quote group on the T column instead of the far right. The
// bar gives way before the price does. Owner order 2026-11-20: end is the tile's
// own right edge, two places further right than the old scrollbar aware edge.
// Owner order 2026-11-21 (second pass): the caller ends the group two cells
// inside the frame and passes the widest NET DELTA the list carries, so the
// figure sits against its bar and never on the tile's border.
func (a *App) drawScanQuote(c *Canvas, row, end, left int, atT bool, q Quote, pxW, netW int, pxKey string) {
	if q.Price <= 0 {
		return
	}
	px := commaFloat(q.Price, 2)
	groupW := quoteWidth(pxW)
	if atT {
		if left+groupW-1 > end {
			return
		}
		a.drawQuote(c, left, row, pxW, px, q.ChangePct, pxKey)
		barStart := left + groupW + quoteGap
		fieldW := shareBarSpan + shareBarGap + netW
		if q.Buy != nil && q.Sell != nil && barStart+fieldW <= end+1 {
			if total := *q.Buy + *q.Sell; total > 0 {
				a.shareBarNetLeft(c, barStart, row, fieldW, netW, *q.Buy, *q.Sell)
			}
		}
		return
	}
	fieldW := shareBarSpan + shareBarGap + netW
	barStart := end - fieldW + 1
	pkrX := barStart - quoteGap - groupW
	if pkrX < left {
		pkrX = end - groupW + 1
		barStart = 0
	}
	if pkrX < left {
		return
	}
	a.drawQuote(c, pkrX, row, pxW, px, q.ChangePct, pxKey)
	if barStart > 0 && q.Buy != nil && q.Sell != nil {
		if total := *q.Buy + *q.Sell; total > 0 {
			a.shareBarNetLeft(c, barStart, row, fieldW, netW, *q.Buy, *q.Sell)
		}
	}
}

// scanNetW is the widest NET DELTA figure a scrip list will draw, so the
// figure's field is no wider than the numbers it carries. A short value then
// stands beside its bar instead of at the tile's right edge.
func scanNetW(syms []string, tbl map[string]Quote) int {
	w := 2
	for _, s := range syms {
		q := tbl[s]
		if q.Buy == nil || q.Sell == nil || *q.Buy+*q.Sell <= 0 {
			continue
		}
		w = max(w, runeLen(signedCompact(*q.Buy-*q.Sell)))
	}
	return min(w, shareNetW)
}

// scanBSTCols measures the whole scan table, not only the three scrips a sort
// happens to show, so every sort opens on the same B, S, U and T cells and the
// columns stay put when the owner moves from one sub menu to another.
func scanBSTCols(tbl map[string]Quote) bstCols {
	leaders := make([]Leader, 0, len(tbl))
	for s, q := range tbl {
		leaders = append(leaders, Leader{Symbol: s, Buy: q.Buy, Sell: q.Sell, Volume: q.Volume})
	}
	return bstLeaderCols(leaders)
}

// searchTileHeight is how tall the search tile is: three rows with nothing
// typed, and as many more as the matches and the chosen symbol need, but never
// more than a third of the screen.
func (a *App) searchTileHeight(w, h int) int {
	if a.searchText == "" && a.selectedSym == "" {
		if h < 35 {
			return 3 // the field alone on a short window
		}
		return 4 // one blank row after the field; no row before it
	}
	m := len(a.matches())
	need := max(m, 1)
	if a.selectedSym != "" {
		need = max(need, 4)
	}
	if w < 64 {
		need += 4 // the details go under the matches
	}
	return min(4+need, max(7, h/3+1))
}

// searchBox draws the one filled field every search uses: SEARCH on the
// scanner, the SECTORS tile and ORDER FLOW. It returns the field's width.
func (a *App) searchBox(c *Canvas, x, y, w int, text, hint string, focused bool) int {
	th := a.th
	// Owner order 2026-11-14 (latest): one cell of padding stands on each
	// side of the search words. Typed text keeps the field as wide as it needs.
	bw := min(w, 32)
	if text == "" {
		bw = min(bw, max(3, runeLen(hint)+2))
	} else {
		bw = min(bw, max(3, runeLen(text)+2))
	}
	if bw < 1 {
		bw = 1
	}
	field := mix(th.Panel, th.Accent, 0.14)
	for k := 0; k < bw; k++ {
		c.Set(x+k, y, ' ', th.Text, field, false)
	}
	if text == "" {
		c.Text(x+1, y, max(1, bw-2), fit(hint, max(1, bw-2)), th.Soft, false)
	} else {
		// Owner order 2026-11-12 (latest): the ">" prompt is withdrawn from every
		// search box, so the typed text starts on the field's own first cell.
		c.Text(x+1, y, max(1, bw-2), fit(text, max(1, bw-2)), th.Hot, true)
		if focused && int(a.animSeconds()*2)%2 == 0 {
			c.Set(x+1+min(runeLen(text), max(1, bw-2)-1), y, '█', th.Accent, field, false)
		}
	}
	return bw
}

// drawSearchTile is the search tile: the box you type in, the matching scrips
// under it and, for the one chosen, its live price, volume, range and its
// buying and selling.
func (a *App) drawSearchTile(c *Canvas, x, y, w, h int) {
	th := a.th
	// Owner order 2026-11-12 (latest): the page's search box wears the key
	// that puts the keys in it while it is empty, and the match count once
	// there is something to choose.
	// Owner order 2026-11-18: the search tile carries no key instruction once
	// there is something to choose; the list and the diamond say it.
	hint := pressSearchHint
	if a.screen == scrAlerts {
		// Owner order 2026-11-18: the ALERTS page gives its SEARCH tile to
		// the S key, while the log keeps the slash key for its own box.
		hint = alertSearchHint
	}
	if a.searchText != "" {
		hint = ""
	}
	ix, iy, iw, ih := a.panel(c, x, y, w, h, "SEARCH", hint)
	// Owner order 2026-11-17: the blank row before the box is withdrawn, so
	// the SEARCH tile is one row shorter; one blank row still follows it.
	focused := true
	if a.screen == scrAlerts {
		focused = a.alertFocus == 4
	}
	a.searchBox(c, ix, iy, min(iw, 40), a.searchText, scripSearchHint, focused)
	if a.searchText == "" && a.selectedSym == "" {
		return
	}
	if len(a.symbols) == 0 {
		c.Text(ix, iy+2, iw, "Symbols load with the next relay answer.", th.Soft, false)
		return
	}
	m := a.matches()
	q := strings.ToUpper(strings.TrimSpace(a.searchText))
	row := iy + 2
	if len(m) == 0 && q != "" {
		c.Text(ix, row, iw, "No KMIALL scrip starts with "+q+".", th.Soft, false)
		return
	}
	listW := 24
	for i, s := range m {
		if row+i >= iy+ih {
			break
		}
		sym := s
		idx := i
		bg := a.selectRow(c, ix, row+i, min(iw, listW), i == a.searchCursor, func() {
			a.searchCursor = idx
			if a.screen == scrAlerts {
				a.alertFocus = 4
			}
			a.pickSymbol(sym)
		})
		// Owner order 2026-11-12 (latest): the row being scrolled through carries
		// the diamond, the same mark every other list in the build selects with,
		// and so does the scrip that is open in the tile.
		marker := " "
		if i == a.searchCursor || s == a.selectedSym {
			marker = "◆"
		}
		c.Set(ix+1, row+i, []rune(marker)[0], th.Accent, bg, true)
		c.Text(ix+3, row+i, len(q), s[:len(q)], th.Hot, true)
		c.Text(ix+3+len(q), row+i, 20, s[len(q):], th.Text, false)
	}
	if a.selectedSym == "" {
		return
	}
	// The details sit to the right of the matches, or under them in a narrow window.
	// Owner order 2026-11-18: the scrip detail starts on the search box's own
	// row, so the SEARCH tile no longer leaves the top of the block empty.
	dx, dy, dw := ix+listW+3, iy, iw-listW-3
	if iw < 60 {
		dx, dy, dw = ix, row+len(m)+1, iw
	}
	bottom := iy + ih
	if dy >= bottom || dw < 30 {
		return
	}
	if lq, ok := a.liveQuote(a.selectedSym); ok {
		pxKey := "px:" + a.selectedSym
		vx := dx
		put := func(row int, s string, fg RGB, bold bool, keys ...string) {
			vx += a.flashText(c, vx, row, s, fg, bold, keys...)
		}
		put(dy, a.selectedSym+"  ", th.Hot, true)
		put(dy, "PKR ", th.Soft, false)
		put(dy, commaFloat(lq.Price, 2), th.Text, true, pxKey)
		if lq.ChangePct != nil {
			put(dy, "  "+changeText(*lq.ChangePct), a.dirColor(*lq.ChangePct), true, pxKey)
		}
		if dy+1 < bottom {
			vx = dx
			// Owner order 2026-11-13: VOL is withdrawn from the search tile.
			// The B, S, U and T line already carries the volume under HIGH and
			// LOW, so printing VOL here repeated it in a different place.
			// Owner order 2026-11-10 (latest): HIGH comes before LOW.
			if lq.High > 0 && lq.Low > 0 {
				put(dy+1, "HIGH ", th.Soft, false)
				put(dy+1, commaFloat(lq.High, 2), th.Good, false)
				put(dy+1, "  &  LOW ", th.Soft, false)
				put(dy+1, commaFloat(lq.Low, 2), th.Bad, false)
			}
		}
	}
	if dy+2 >= bottom {
		return
	}
	switch a.selectedSt {
	case "loading":
		c.Text(dx, dy+2, dw, "Reading the symbol.", th.Soft, false)
		return
	case "failed", "":
		if _, ok := a.liveQuote(a.selectedSym); !ok {
			c.Text(dx, dy, dw, "That symbol has no live quote from the broker feed yet.", th.Warn, false)
		}
		return
	}
	in := a.selectedInfo
	var buy, sell, tot *int64
	if in.Buy != nil && in.Sell != nil {
		b, sl := int64(math.Round(*in.Buy)), int64(math.Round(*in.Sell))
		buy, sell = &b, &sl
	}
	if in.Volume != nil {
		t := int64(math.Round(*in.Volume))
		tot = &t
	}
	a.drawSearchLedger(c, dx, dy+2, dw, bottom, buy, sell, tot, a.screen == scrScanner)
}

// drawSearchLedger is the chosen scrip's volume block on the SEARCH tile.
// Owner order 2026-11-18: the ALERTS tile keeps T below B, S and U and starts
// the bar four cells after T, with no BARS word. The SCANNER tile puts T after
// U, then the bar with NET DELTA and NET DELTA % on its own line below.
func (a *App) drawSearchLedger(c *Canvas, x, y, w, bottom int, buy, sell, tot *int64, scanner bool) {
	th := a.th
	if y >= bottom {
		return
	}
	if buy == nil || sell == nil {
		if tot != nil {
			c.Spans(x, y, w, []Span{{"T=", th.Soft, false}, {leaderVolumeField(*tot), totalBlue, false}})
		}
		return
	}
	b, s := *buy, *sell
	if scanner {
		// Owner order 2026-11-18: the SCANNER keeps all four volumes on one
		// line, then the bar and both NET DELTA figures below it.
		a.putBSTWide(c, x, y, buy, sell, tot)
		if y+1 >= bottom || b+s <= 0 {
			return
		}
		barW := min(shareBarSpan, w)
		if barW < shareBarBoxes {
			return
		}
		a.shareBarOnly(c, x, y+1, barW, b, s)
		netX := x + barW + 2
		if netX+netRowW > x+w {
			return
		}
		a.drawNetRow(c, netX, y+1, b, s)
		return
	}
	sp := []Span{{"B=", th.Soft, false}}
	sp = append(sp, volumeCommaSpans(b, th.Good, true, th.Soft)...)
	sp = append(sp, Span{"  S=", th.Soft, false})
	sp = append(sp, volumeCommaSpans(s, th.Bad, true, th.Soft)...)
	sp = append(sp, Span{"  U=", th.Soft, false})
	var un int64
	if tot != nil {
		un = *tot - b - s
		if un < 0 {
			un = 0
		}
	}
	sp = append(sp, volumeFieldSpans(un, th.Warn, un > 0)...)
	c.Spans(x, y, w, sp)

	tY := y + 1
	if tot != nil && tY < bottom {
		field := leaderVolumeField(*tot)
		c.Spans(x, tY, w, []Span{{"T=", th.Soft, false}, {field, totalBlue, false}})
					barX := x + 2 + runeLen(field) + 2
		if b+s > 0 && barX+shareBarSpan <= x+w {
			a.shareBarOnly(c, barX, tY, shareBarSpan, b, s)
		}
	}

	nY := y + 2
	if nY >= bottom {
		return
	}
	// Owner order 2026-11-19 (latest): this line is the SCANNER tile's own line,
	// so the two pages read the same figures the same way.
	a.drawNetRow(c, x, nY, b, s)
}

// searchNet is the NET DELTA on the SEARCH tile's bar line, as a magnitude in
// the ink of the side that owns it.
func (a *App) searchNet(buy, sell int64) (string, RGB, bool) {
	net := buy - sell
	ink, bold := a.th.Soft, false
	switch {
	case net > 0:
		ink, bold = a.th.Good, true
	case net < 0:
		ink, bold = a.th.Bad, true
	}
	return compactNum(math.Abs(float64(net))), ink, bold
}

// Owner order 2026-11-19 (latest): the two NET DELTA figures read as one line on
// the SEARCH tile of both pages. "NET DELTA=" and "NET DELTA %=" carry their
// equals sign hard against the label, the figures take six and seven cells, and
// "  &  " stands between them with two cells on each side.
const (
	netLabelEq    = quoteNetLabelW + 1
	netPctLabelEq = 11 + 1
	netAmpW       = 5
	netRowW       = netLabelEq + quoteNetValW + netAmpW + netPctLabelEq + 7
)

// drawNetRow writes that one line, in the ink of the side that is in front.
// Owner order 2026-11-20: the owner still saw a gap between each label and its
// figure, because the figure was right aligned in a fixed six cell field. Each
// figure now stands on the cell after its own equals sign, on both SEARCH
// tiles, so the line reads NET DELTA=<net>  &  NET DELTA %=<pct> with no cell
// left empty in between.
func (a *App) drawNetRow(c *Canvas, x, y int, buy, sell int64) {
	net, ink, bold := a.searchNet(buy, sell)
	c.Text(x, y, netLabelEq, "NET DELTA=", a.th.Soft, false)
	valX := x + netLabelEq
	valW := runeLen(net)
	c.Text(valX, y, valW, net, ink, bold)
	ampX := valX + valW
	c.Text(ampX, y, netAmpW, "  &  ", a.th.Soft, false)
	pctX := ampX + netAmpW
	c.Text(pctX, y, netPctLabelEq, "NET DELTA %=", a.th.Soft, false)
	pct := searchNetPct(buy, sell)
	c.Text(pctX+netPctLabelEq, y, runeLen(pct), pct, ink, bold)
}

// searchNetPct is the NET DELTA as a percentage of the classified volume.
func searchNetPct(buy, sell int64) string {
	total := buy + sell
	if total <= 0 {
		return "--"
	}
	return fmt.Sprintf("%.2f%%", math.Abs(float64(buy-sell))/float64(total)*100)
}

// showing words which part of a list is on screen.
func (a *App) showing(l *listView, noun string) string {
	last := min(l.total, l.off+l.view)
	return fmt.Sprintf("%d to %d of %s", l.off+1, last, plural(l.total, noun))
}

// drawSectorTile shows the relay's KMIALL sector groups as a drop down with a
// search box of its own: every group is listed, the chosen one is marked, and
// the wheel or the scrollbar moves through the list. Clicking a row picks that
// group. The box filters by sector name or by any scrip it carries.
func (a *App) drawSectorTile(c *Canvas, x, y, w, h int) {
	th := a.th
	ix, iy, iw, ih := a.panel(c, x, y, w, h, "SECTORS", sectorMoveHint)
	// Owner order 2026-11-19 (latest): the SECTORS title carries the panel's own
	// hot diamond, like every other tile.
	c.Put(x+2, y, '◆', th.Hot, false)
	a.sectorY, a.sectorH = y, h
	searchRows := 0
	if ih > 0 {
		// Owner order 2026-11-17: the blank row before the SECTORS field is
		// withdrawn; the box stands on the first inner row and one blank row
		// still follows it.
		a.drawSectorSearch(c, ix, iy, iw, false)
		searchRows = 2
		if h <= 6 {
			searchRows = 1
		}
	}
	listY := iy + searchRows
	listRows := max(1, ih-searchRows)
	groups := a.sectorGroups()
	if len(groups) == 0 {
		msg := "Reading the sector groups from the relay."
		if a.sectorsErr != "" {
			msg = "Sectors are unavailable right now: " + a.sectorsErr
		}
		if ih > 0 {
			c.Text(ix, listY, iw, fit(msg, iw), th.Warn, false)
		}
		return
	}
	vis := a.visibleSectorIndices()
	if len(vis) == 0 {
		a.lvSector.set(0, listRows)
		if ih > 0 {
			c.Text(ix, listY, iw, "No sector or scrip starts with "+a.sectorQueryText()+".", th.Soft, false)
		}
		return
	}
	if a.sectorChoice >= len(groups) || a.sectorChoice < 0 {
		a.sectorChoice = 0
	}
	chosenVisible := false
	for _, idx := range vis {
		if idx == a.sectorChoice {
			chosenVisible = true
			break
		}
	}
	if !chosenVisible {
		a.sectorChoice = vis[0]
	}
	a.lvSector.set(len(vis), listRows)
	// The list is never snapped back to the chosen group: the wheel may scroll
	// the groups freely, even when the chosen one is the first row.
	cw := contentW(&a.lvSector, iw)
	tbl := a.scanTable()
	for n := 0; n < a.lvSector.view; n++ {
		i := a.lvSector.off + n
		if i >= len(vis) {
			break
		}
		idx := vis[i]
		g := groups[idx]
		ry := listY + n
		bg := a.selectRow(c, ix, ry, cw, idx == a.sectorChoice, func() { a.openSector(idx) })
		mark := "  "
		if idx == a.sectorChoice {
			mark = "◆ "
		}
		c.Set(ix+1, ry, []rune(mark)[0], th.Accent, bg, true)
		// Owner order 2026-11-13: every group carries its overall percentage at
		// the far right of the tile, in the colour of its side, and the rows
		// above it are the groups that percentage ranks higher.
		pct, cnt := sectorChangeIn(tbl, g)
		pctText, pctInk, pctArrow := "--", th.Soft, ""
		if cnt > 0 {
			// Owner order 2026-11-19: one cell stands between the arrow and the
			// percentage, the same gutter every quote group uses.
			pctText = strconv.FormatFloat(math.Abs(pct), 'f', 2, 64) + "%"
			pctArrow = "▲"
			if pct < 0 {
				pctArrow, pctInk = "▼", th.Bad
			} else if pct > 0 {
				pctInk = th.Good
			}
		}
		c.Text(ix+3, ry, 3, fmt.Sprintf("%2d.", i+1), th.Soft, false)
		pctW := 1 + 1 + quotePctW
		// Owner order 2026-11-20 (latest): with the groups alone on the tile,
		// the overall percentage moves one cell right, and never into the frame
		// when the list is short enough to need no scrollbar.
		pctX := ix + cw - pctW + 1
		if pctX+pctW > ix+cw {
			pctX = ix + cw - pctW
		}
		nameW := max(1, pctX-(ix+7)-2)
		c.Text(ix+7, ry, nameW, fit(g.Name, nameW), th.Text, idx == a.sectorChoice)
		c.Text(pctX, ry, 1, pctArrow, pctInk, cnt > 0)
		c.Text(pctX+2, ry, quotePctW, pctText, pctInk, cnt > 0)

	}
	a.scrollbar(c, ix+iw-1, listY, a.lvSector.view, &a.lvSector)
}

// drawSectorSearch draws the SECTORS tile's own field below the title, in the
// same filled box SCANNER uses. The field is a hit region: clicking it gives
// this box the keys. Owner order 2026-11-12 (latest): the slash key belongs to
// the page's own SEARCH box, so the click is this field's only way in.
func (a *App) drawSectorSearch(c *Canvas, x, y, w int, scrips bool) {
	hint := "Search for a sector"
	if scrips {
		hint = "Search for a scrip"
	}
	// Owner order 2026-11-08 (build 27): the SECTORS tile carries the filled
	// field alone; the word SEARCH is gone.
	a.searchBox(c, x, y, max(1, w), a.sectorQuery, hint, a.sectorSearch)
	a.addHit(x, y, w, 1, func() {
		a.sectorSearch = true
		a.lvSector.top()
		a.lvSectorStk.top()
	})
}

// inKMIALLSHR says whether the relay's KMIALL list carries this scrip. Until
// that list has arrived, every name the sector sends is shown.
func (a *App) inKMIALLSHR(sym string) bool {
	if len(a.symbols) == 0 {
		return true
	}
	for _, s := range a.symbols {
		if s == sym {
			return true
		}
	}
	return false
}

// sectorStockRows is the rows an opened sector shows before it scrolls.
const sectorStockRows = 5

// drawSectorOpen is a tapped sector, shown inside the SECTORS tile: every one
// of its scrips that is in KMIALLSHR, with the live price when the feed has
// one. The CUSTOM SCRIPS tile below stays on screen. The wheel or the
// scrollbar moves through the scrips, a click opens one in the search tile, and
// BACKSPACE (or ESC) brings all the sectors back without changing screen.
func (a *App) drawSectorOpen(c *Canvas, x, y, w, h int) {
	th := a.th
	a.sectorY, a.sectorH = y, h
	if h < 4 {
		return
	}
	ix, iy, iw, ih := a.panel(c, x, y, w, h, "SECTORS", sectorMoveHint)
	// Owner order 2026-11-19 (latest): the SECTORS title carries the panel's own
	// hot diamond, like every other tile.
	c.Put(x+2, y, '◆', th.Hot, false)
	a.drawSectorSearch(c, ix, iy+1, iw, true)
	// Owner order 2026-11-20: the field is on iy+1 and the table starts on the
	// row under it. The blank separator row is gone, so an opened sector shows
	// four of its scrips in the height the scanner gives this tile, and the
	// owner no longer scrolls to read the fourth.
	groups := a.sectorGroups()
	if a.sectorChoice < 0 || a.sectorChoice >= len(groups) {
		a.sectorOpen = false
		return
	}
	g := groups[a.sectorChoice]
	all := a.sectorMembers()
	member := a.visibleSectorMembers()
	detail := fmt.Sprintf("%d of %d scrips in KMIALLSHR", len(all), len(g.Symbols))
	if len(member) != len(all) {
		detail += fmt.Sprintf(", %d match", len(member))
	}
	spans := []Span{{g.Name, th.Hot, true}}
	if v, n := a.sectorChange(g); n > 0 {
		spans = append(spans, Span{"  ·  ", th.Soft, false},
			Span{changeText(v), a.dirColor(v), true})
	}
	spans = append(spans, Span{"  ·  ", th.Soft, false}, Span{detail, th.Soft, false})
	c.Spans(ix, iy, iw, spans)
	if len(all) == 0 {
		c.Text(ix, iy+2, iw, "None of this sector's scrips is in KMIALLSHR right now.", th.Soft, false)
		return
	}
	if len(member) == 0 {
		c.Text(ix, iy+2, iw, "No scrip in this sector starts with "+a.sectorQueryText()+".", th.Soft, false)
		return
	}
	// Owner order 2026-11-19 (latest): an opened sector always shows five
	// scrips, so one selection reads the same height as the next, and the rest
	// of its scrips are a scroll away.
	rows := min(sectorStockRows, ih-2)
	if rows < 1 {
		return
	}
	a.lvSectorStk.set(len(member), rows)
	tbl := a.scanTable()
	cw := contentW(&a.lvSectorStk, iw)
	for n := 0; n < a.lvSectorStk.view; n++ {
		i := a.lvSectorStk.off + n
		if i >= len(member) || iy+2+n >= iy+ih {
			break
		}
		sym := member[i]
		ry := iy + 2 + n
		a.selectRow(c, ix, ry, cw, false, func() { a.openSymbol(sym) })
		const priceW = 8
		priceX := ix + cw - quoteWidth(priceW)
		nameW := max(1, priceX-(ix+1)-2)
		c.Text(ix+1, ry, nameW, fit(fmt.Sprintf("%3d. %-9s", i+1, sym), nameW), th.Hot, true)
		if q, ok := tbl[sym]; ok && q.Price > 0 {
			// Owner order 2026-11-19: PKR holds one column, the price its own
			// field, and the arrow keeps one cell before the percentage, exactly
			// as the quote group does on every other tile.
			a.drawQuote(c, priceX, ry, priceW, commaFloat(q.Price, 2), q.ChangePct, "px:"+sym)
		}
	}
	a.scrollbar(c, ix+iw-1, iy+2, a.lvSectorStk.view, &a.lvSectorStk)
}

// moveSectorChoice moves the SECTORS selection by d rows of the visible list,
// keeping the selected group inside the six-row window. Owner order
// 2026-11-15: the SECTORS selection is moved by UP and DOWN only. Owner order
// 2026-11-20 (latest): the list wraps, so DOWN on the last sector lands on the
// first and UP on the first lands on the last.
func (a *App) moveSectorChoice(d int) {
	vis := a.visibleSectorIndices()
	if len(vis) == 0 {
		return
	}
	pos := 0
	for i, idx := range vis {
		if idx == a.sectorChoice {
			pos = i
			break
		}
	}
	pos += d
	if pos < 0 {
		pos = len(vis) - 1
	}
	if pos >= len(vis) {
		pos = 0
	}
	a.sectorChoice = vis[pos]
	if a.lvSector.view > 0 {
		if pos < a.lvSector.off {
			a.lvSector.off = pos
		}
		if pos >= a.lvSector.off+a.lvSector.view {
			a.lvSector.off = pos - a.lvSector.view + 1
		}
	}
}

// openSector opens group i in the SECTORS tile without leaving the scanner.
func (a *App) openSector(i int) {
	a.scanFocus = 0
	groups := a.sectorGroups()
	if i < 0 || i >= len(groups) {
		return
	}
	a.sectorChoice = i
	a.sectorOpen = true
	a.sectorQuery, a.sectorSearch = "", false
	a.lvSectorStk.top()
}

// sectorMembers is the chosen sector's scrips that the relay's KMIALLSHR list
// carries. The demo's groups are invented, so they are shown whole.
func (a *App) sectorMembers() []string {
	groups := a.sectorGroups()
	if a.sectorChoice < 0 || a.sectorChoice >= len(groups) {
		return nil
	}
	g := groups[a.sectorChoice]
	var member []string
	for _, s := range g.Symbols {
		if a.demo || a.inKMIALLSHR(s) {
			member = append(member, s)
		}
	}
	return member
}

func (a *App) sectorQueryText() string {
	return strings.ToUpper(strings.TrimSpace(a.sectorQuery))
}

// visibleSectorIndices are the groups the tile lists, ordered by the day's
// overall percentage, highest first. Owner order 2026-11-13: the SCANNER's
// sectors read in descending order of their aggregate change, so the strongest
// group is the first row. A group with no priced scrip yet sorts after every
// measured one, and equal percentages fall back to the alphabetical order the
// relay sends. The indices stay the groups' own, so a click still opens the
// group the row names. A group matches the search when its name starts with
// the query or when any scrip it carries does, so typing CHRL finds CEMENT.
func (a *App) visibleSectorIndices() []int {
	groups := a.sectorGroups()
	q := a.sectorQueryText()
	var out []int
	for i, g := range groups {
		if q == "" {
			out = append(out, i)
			continue
		}
		if strings.HasPrefix(g.Name, q) {
			out = append(out, i)
			continue
		}
		for _, sym := range g.Symbols {
			if strings.HasPrefix(strings.ToUpper(sym), q) {
				out = append(out, i)
				break
			}
		}
	}
	tbl := a.scanTable()
	pct := make(map[int]float64, len(out))
	measured := make(map[int]bool, len(out))
	for _, i := range out {
		v, n := sectorChangeIn(tbl, groups[i])
		pct[i], measured[i] = v, n > 0
	}
	sort.SliceStable(out, func(x, y int) bool {
		i, j := out[x], out[y]
		if measured[i] != measured[j] {
			return measured[i]
		}
		if measured[i] && pct[i] != pct[j] {
			return pct[i] > pct[j]
		}
		return groups[i].Name < groups[j].Name
	})
	return out
}

// sectorChangeIn is a group's overall day percentage: the equal weight mean of
// its members' own change, read from one scan table, which is the figure the
// SCANNER prints in front of the group and sorts the list by. The count is how
// many members carry a percentage; at zero the group has no figure and sorts
// last.
func sectorChangeIn(tbl map[string]Quote, g Sector) (float64, int) {
	sum, n := 0.0, 0
	for _, sym := range g.Symbols {
		if q, ok := tbl[sym]; ok && q.ChangePct != nil {
			sum += *q.ChangePct
			n++
		}
	}
	if n == 0 {
		return 0, 0
	}
	return sum / float64(n), n
}

// sectorChange is sectorChangeIn against the live table, for a single group.
func (a *App) sectorChange(g Sector) (float64, int) {
	return sectorChangeIn(a.scanTable(), g)
}

// visibleSectorMembers are the open group's scrips that match the box.
func (a *App) visibleSectorMembers() []string {
	members := a.sectorMembers()
	q := a.sectorQueryText()
	if q == "" {
		return members
	}
	var out []string
	for _, s := range members {
		if strings.HasPrefix(strings.ToUpper(s), q) {
			out = append(out, s)
		}
	}
	return out
}

// demoSectorGroups gives the demo scanner a real-looking set of groups, so the
// tile can be judged outside market hours without pretending they are live.
var demoSectorGroups = []Sector{
	{"AUTOMOBILE", []string{"ALFA", "BRVO", "DLTA", "HTEL"}},
	{"CEMENT", []string{"CHRL", "ECHO", "GOLF"}},
	{"FERTILIZER", []string{"FXTR", "ALFA", "CHRL"}},
}

func (a *App) sectorGroups() []Sector {
	if a.demo {
		return demoSectorGroups
	}
	if a.sectors == nil {
		return nil
	}
	return a.sectors.Items
}

// Owner order 2026-11-11: the bar sits on the cell's centre line again. The
// lower blocks put it on the floor of the cell, so every bar read as a bar at
// the bottom of its box. The heavy horizontal rule is the one glyph that joins
// edge to edge with no seam and no small box inside it, and it is drawn on the
// cell's centre line. The bar's span, row and colours do not move.
//
// The lower and upper blocks are not used because they stand on the floor or
// the top of the cell.
//
// Owner order 2026-11-12: the full-cell fill was too tall. The bar is the heavy
// rule again: the one centred glyph that joins edge to edge with no seam and no
// small box or line inside it, and it never reaches the top or the bottom of
// its box.
//
// Owner order 2026-11-12 (latest): the owner sees a box edge between the cells
// of every bar, so the bar is the heavy rule in the bold cut. Every other glyph
// the console can draw as a bar is narrower than its cell - the rectangle and
// the square leave a gap at each side, which is the seam - while the rule
// reaches both edges and joins its neighbours into one line. Its span, its ten
// boxes, its row and its two inks do not change, and nothing is drawn inside.
const barBlock = '━'

// shareBarBoxes is how many boxes a buy versus sell bar holds. Owner order
// 2026-11-11: the bar carries ten boxes and not sixteen, and each box grows in
// length so the ten of them fill exactly the same span the sixteen did. The
// span itself, and the bar's height, do not move.
const shareBarBoxes = 10

// shareBarMinBoxes is how far the bar gives way before either NET DELTA column
// steps out of a narrow window. Owner order 2026-11-24 (later): SCRIP keeps its
// blank cell on every width, and the bar is what loses the cell at the tightest
// one, so both NET DELTA columns stay on the page.
const shareBarMinBoxes = shareBarBoxes - 1

// shareBarSpan is the cells the ten boxes cover. Owner order 2026-11-11
// (second pass): the patch 30 look is undone and the patch 29 bar is back, so
// the bar is 16 cells again, exactly as long as it was, and the ten boxes
// share those cells instead of standing apart with a gap between them.
const shareBarSpan = shareBarBoxes * 16 / 10

// shareNetW is the cells a bar gives to its NET DELTA, left aligned like every
// other value, so a sign and a compact figure start on the same cell.
const shareNetW = 9

// shareBarGap is the gutter between two columns. Owner order 2026-11-12
// (latest): every column on ORDER FLOW is separated by the same gutter, the
// bar's own NET DELTA included, so no pair of columns is tighter than another.
// Owner order 2026-11-20 (latest): that gutter is one cell, so the two NET DELTA
// columns fit beside the bar on the owner's window.
const shareBarGap = 1


// shareBarWidth is the field a labelled bar asks for: its span, the gutter and
// the NET DELTA after it.
const shareBarWidth = shareBarSpan + shareBarGap + shareNetW

// shareBar draws a buy versus sell bar: its sixteen cells split at the buyers'
// exact share, then one gutter, then the NET DELTA, so the two sides' strength
// and the difference between them read in one glance.
func (a *App) shareBar(c *Canvas, x, y, w int, buy, sell int64) {
	a.drawShareBar(c, x, y, w, buy, sell, true, 0)
}

// shareBarNetRight is the bar with its NET DELTA right aligned in its own
// field, for CUSTOM SCRIPS OF VOLUME. Owner order 2026-11-21: every unit of
// that tile's NET DELTA ends on one cell, so 4.8M and 3M stand with their M on
// the same column instead of each figure starting on the same one.
func (a *App) shareBarNetRight(c *Canvas, x, y, w int, buy, sell int64) {
	a.drawShareBar(c, x, y, w, buy, sell, true, shareNetW)
}

// shareBarNetField is the bar with its NET DELTA right aligned in a field of
// exactly netW cells, the widest figure the caller's list carries.
func (a *App) shareBarNetField(c *Canvas, x, y, w, netW int, buy, sell int64) {
	a.drawShareBar(c, x, y, w, buy, sell, true, netW)
}

// shareBarNetLeft is the bar with its NET DELTA left aligned in a field of
// exactly netW cells. Owner order 2026-11-24 (later): CUSTOM SCRIPS OF VOLUME
// asks for this, so 2.8M, 8.51k and 268.31k all start on the cell the widest
// figure starts on instead of each ending on the tile's own last cell.
func (a *App) shareBarNetLeft(c *Canvas, x, y, w, netW int, buy, sell int64) {
	a.drawShareBar(c, x, y, w, buy, sell, true, -netW)
}

// shareBarOnly draws the same bar with no NET DELTA after it, for the leaders
// card and the scanner, where the row already carries its own volumes. It
// returns the cells used.
func (a *App) shareBarOnly(c *Canvas, x, y, w int, buy, sell int64) int {
	return a.drawShareBar(c, x, y, w, buy, sell, false, 0)
}

// drawShareBar is the one buy versus sell bar the whole build draws. Owner
// order 2026-11-12 (latest): the green is always the buyers' share of the
// classified volume and the red is always the sellers', on every page and on
// both ALERTS boards, so a bar can never mean one side here and the other side
// there, and the side it shows is always the side that is in front. The share
// is buy/(buy+sell) and the label is the NET DELTA, buy-sell, as a magnitude:
// the ink carries the side and the figure carries the size. Owner order
// 2026-11-13: the minus is gone from the whole build. Owner order 2026-11-11 (third
// pass): one shade of green and one shade of red, no paler step, and no cell
// drawn between the boxes.
func (a *App) drawShareBar(c *Canvas, x, y, w int, buy, sell int64, label bool, netW int) int {
	th := a.th
	total := buy + sell
	if total <= 0 {
		return 0
	}
	// netW is the cells the NET DELTA is written in. Zero keeps the column the
	// table's own width: a left aligned figure in shareNetW cells. A positive
	// width is that narrower field, right aligned; a negative one is the same
	// field, left aligned, which is what CUSTOM SCRIPS asks for.
	fieldW := shareNetW
	if netW > 0 {
		fieldW = netW
	} else if netW < 0 {
		fieldW = -netW
	}
	// The bar is 16 cells; a caller with less room (the ALERTS boards pass the
	// ten cells of a compact bar) gets a bar of exactly the room it has.
	span := shareBarSpan
	if label && w > 0 && w-fieldW-shareBarGap >= shareBarMinBoxes && w-fieldW-shareBarGap < shareBarSpan {
		// A narrower ORDER FLOW table gives cells to the NET DELTA % column.
		// The bar and its heading then shorten together, and the NET DELTA still
		// starts on the cell its heading starts on.
		span = w - fieldW - shareBarGap
	} else if w > 0 && w < span {
		span = w
	}
	// Owner order 2026-11-13: the split stands on the bar's own cells, not on
	// the ten boxes. Rounding to four of ten boxes drew 39 percent of buying as
	// eight of sixteen green cells, a false 50/50; the same share is six green
	// cells here. One shade of green and one shade of red, no paler step.
	green := shareGreenCells(buy, sell, span)
	for k := 0; k < span; k++ {
		// Owner order 2026-11-12 (latest): the centred rectangle in the bold
		// cut, the taller glyph the owner chose. Nothing else about the bar
		// changes.
		ink := th.Bad
		if k < green {
			ink = th.Good
		}
		c.Put(x+k, y, barBlock, ink, true)
	}
	width := span
	if label {
		// Owner order 2026-11-12 (latest): the percentage is gone and the NET
		// DELTA takes its place as a magnitude in the same cells, green when the
		// buyers are ahead and red when the sellers are.
		net := buy - sell
		ink, bold := th.Soft, false
		switch {
		case net > 0:
			ink, bold = th.Good, true
		case net < 0:
			ink, bold = th.Bad, true
		}
		// Owner order 2026-11-12 (latest): the NET DELTA starts on its column's
		// first cell, like every other value on ORDER FLOW, one full gutter after
		// the bar, so the gap between the bar and its figure is the same two
		// cells as the gap between every other pair of columns.
		// Owner order 2026-11-21: CUSTOM SCRIPS asks for the same field with the
		// figure right aligned, so every compact unit ends on one cell.
		field := signedCompact(net)
		if netW > 0 {
			field = padLeft(field, fieldW)
		}
		c.Text(x+width+shareBarGap, y, fieldW, field, ink, bold)
	}
	return width
}

// shareGreenCells is the green cells a buy and sell pair earns on a bar of
// span cells. Owner order 2026-11-13: the pair is split on the bar's own cells,
// so the bar carries the buyers' exact share instead of rounding it to one of
// ten boxes.
func shareGreenCells(buy, sell int64, span int) int {
	if buy <= 0 || span <= 0 {
		return 0
	}
	total := buy + sell
	if total <= 0 {
		return 0
	}
	green := int(math.Round(float64(buy) / float64(total) * float64(span)))
	if green < 0 {
		return 0
	}
	if green > span {
		return span
	}
	return green
}

// barPair returns the one buy and sell pair a bar may draw: the measured day
// pair from the scan table when it has one, and the caller's own pair only as
// a fallback. Owner order 2026-11-13: every bar in the build answers the same
// question, which side owns more of the same B and S volumes.
func barPair(tbl map[string]Quote, sym string, buy, sell int64) (int64, int64) {
	if q, ok := tbl[sym]; ok && q.Buy != nil && q.Sell != nil {
		return *q.Buy, *q.Sell
	}
	return buy, sell
}

// ---------- alerts ----------

// drawAlerts is the Alerts screen: the big buying board and the big selling
// board side by side (stacked in a narrow window), and the alert log below.
func (a *App) drawAlerts(c *Canvas, x, y, w, h int) {
	boardH := min(12, max(7, h/2-1))
	// Owner order 2026-11-13: the PRICE ALERTS tile sits between the boards and
	// the log and takes its five rows from the boards' spare rows first, so the
	// ALERTS LOG keeps the twelve rows the owner reads it at. The boards never
	// go under their own floor of seven, and a window with no room at all keeps
	// the boards and the log rather than cutting a tile in half.
	priceH := 5
	for boardH > 7 && h-boardH-7 < 12 {
		boardH--
	}
	if h-boardH-7 < 5 {
		priceH = 0
	}
	a.boardFields = a.measureBoards()
			if w >= 84 {
		// Owner order 2026-11-16: both boards are exactly equal and together
		// fill the page width. An even width takes a two cell gutter, an odd
		// width one, so neither board loses its right hand cell.
		gap := 1
		if w%2 == 0 {
			gap = 2
		}
		bw := (w - gap) / 2
		a.drawBoardPanel(c, x, y, bw, boardH, sideBuy)
		a.drawBoardPanel(c, x+bw+gap, y, bw, boardH, sideSell)
		a.alertSplitX = x + bw + gap
	} else {
		side := sideBuy
		if a.alertFocus == 1 {
			side = sideSell
		}
		a.drawBoardPanel(c, x, y, w, boardH, side)
		a.alertSplitX = x + w + 1
	}
	a.alertSplit = y + boardH
	ly := y + boardH + 1
	a.priceY, a.priceH = 0, 0
	if priceH > 0 {
		a.priceY, a.priceH = ly, priceH
		a.drawPriceTile(c, x, ly, w, priceH)
		ly += priceH + 1
	}
	lh := y + h - ly
	if lh < 5 {
		return
	}
	a.alertSearchX, a.alertSearchY, a.alertSearchW, a.alertSearchH = 0, 0, 0, 0
	if w >= 72 {
		// Owner order 2026-11-18: the ALERTS LOG keeps the left side and the
		// scanner's own SEARCH tile stands on the right, with the page's one
		// cell gutter between them.
		const gap = 1
		// The log keeps the larger share, so its alert sentences stay whole;
		// the SEARCH tile takes the remaining right hand side.
		lw := (w - gap) * 3 / 5
		sx := x + lw + gap
		sw := w - gap - lw
		a.drawAlertLog(c, x, ly, lw, lh)
		a.alertSearchX, a.alertSearchY, a.alertSearchW, a.alertSearchH = sx, ly, sw, lh
		a.addHit(sx, ly, sw, lh, func() { a.alertFocus, a.alertLogSearch = 4, false })
		a.drawSearchTile(c, sx, ly, sw, lh)
		return
	}
	a.drawAlertLog(c, x, ly, w, lh)
}

// drawBoardPanel draws one side's board: the transactions at or above the 50k
// floor, each one its own row, the largest first.
func (a *App) drawBoardPanel(c *Canvas, x, y, w, h int, side int) {
	th := a.th
	title, on := "BIG BUYING NOW", a.cfg.BigBuy
	lv := &a.lvBoard
	good := th.Good
	rows := a.boardRows
	flagKey := "B"
	focus := 0
	if side == sideSell {
		title, on, focus = "BIG SELLING NOW", a.cfg.BigSell, 1
		lv = &a.lvSell
		good = th.Bad
		rows = a.sellRows
		flagKey = "S"
	}
	hint := "The flag is off."
	if on {
		// Owner order 2026-11-16: both boards name the 50k share floor they keep.
		hint = "QTY " + compactNum(float64(boardFloorShares)) + " and above"
	}
	// Owner order 2026-11-15: clicking an ALERTS tile no longer highlights its
	// frame. The hit still moves the page's keyboard focus.
	ix, iy, iw, ih := a.panel(c, x, y, w, h, title, hint)
	// Owner order 2026-11-24 (later): both boards wear the heading ink every
	// other tile wears, the panel's own accent (hot while it holds the keys),
	// so neither board reads as a warning because its words were green or red.
	// The panel drew that title above; only its hint and frame are added here.
	a.addHit(x, y, w, h, func() { a.alertFocus = focus })
	if !on {
		for i, ln := range wrap("The flag is off. Press "+flagKey+" or use Settings to turn it on.", iw) {
			if i < ih {
				c.Text(ix, iy+i, iw, ln, th.Warn, false)
			}
		}
		return
	}
	board := rows(200)
	if len(board) == 0 {
		// Owner order 2026-11-16: the empty sentence is withdrawn too. The
		// heading above already names the quantity the board keeps, so an empty
		// board stays empty.
		return
	}
	lv.set(len(board), ih)
	cw := contentW(lv, iw)
	// Owner order 2026-11-23 (latest): both boards keep the two cells the
	// scrollbar uses clear, so a board that does not scroll still ends its rows
	// on the cell the other board's rows end on.
	layW := min(cw, iw-2)
	// Owner order 2026-11-20 (latest): the board writes the one quote group
	// every other tile uses, so PKR holds one column down the board and the
	// price is right aligned in its own field. The field is measured on the rows
	// the board is showing, because the label may not step left for a scrip that
	// carries fewer digits; the field still ends on the cell the old right
	// aligned blob ended on, so the percentage keeps its own column.
	pxW, qtyW, valW := a.boardFields.pxW, a.boardFields.qtyW, a.boardFields.valW
	// Owner order 2026-11-13: one bar pair for the whole build. The boards
	// rank their rows on the last minute, but each bar reads the measured day
	// B and S pair the scanner, the search tile and the KSE100 leaders use.
	tbl := a.scanTable()
	if pxW == 0 {
		// A board drawn on its own measures its own rows; the Alerts page
		// measures both boards first, so the two share every column.
		pxW, qtyW, valW = 6, 1, 3
		for n := 0; n < lv.view; n++ {
			i := lv.off + n
			if i >= len(board) {
				break
			}
			pxW = max(pxW, runeLen(commaFloat(board[i].Price, 2)))
			qty := board[i].BuyShares
			if side == sideSell {
				qty = board[i].SellShares
			}
			qtyW = max(qtyW, runeLen(compactNum(float64(qty))))
			buy, sell := barPair(tbl, board[i].Symbol, board[i].BuyShares, board[i].SellShares)
			valW = max(valW, runeLen(signedCompact(buy-sell)))
		}
	}
	// Owner order 2026-11-23 (latest): the price, the percentage, the quantity
	// and the bar step left as one group, and NET DELTA and its figure close the
	// row right after the bar. The group is measured once for the whole board, so
	// every column keeps one cell down every row.
	lay := boardRowLayout(ix, layW, pxW, qtyW, valW)
	for n := 0; n < lv.view; n++ {
		i := lv.off + n
		if i >= len(board) {
			break
		}
		b := board[i]
		ry := iy + n
		pxKey := "px:" + b.Symbol
		a.zebra(c, ix, ry, cw, 1, i, b.Symbol)
		star := "  "
		if b.Flagged {
			star = "◆ "
		}
		c.Text(ix, ry, 4, fmt.Sprintf("%2d.", i+1), th.Soft, false)
		c.Text(ix+4, ry, 2, star, th.Warn, true)
		c.Text(ix+6, ry, 8, b.Symbol, th.Hot, true)
		// Owner order 2026-11-16: both boards name the current price with PKR.
		// Owner order 2026-11-20 (latest): PKR stands on one column and the price
		// is right aligned in its own field, so the three rows read as one quote
		// group and the label no longer floats with the number of digits.
		a.drawQuoteStart(c, lay.priceX, ry, lay.pxW, commaFloat(b.Price, 2), pxKey)
		// Owner order 2026-11-16: both boards carry the side's share quantity and
		// its bar. The quantity is this side's own: bought shares on the buying
		// board, sold shares on the selling board. Owner order 2026-11-23
		// (latest): the quantity and the bar stand on the columns the row layout
		// fixes once for the whole board.
		qty := b.BuyShares
		if side == sideSell {
			qty = b.SellShares
		}
		// Owner order 2026-11-16: the board's figure is the share quantity alone;
		// the old "sh" suffix is withdrawn from both tiles.
		qtyTxt := compactNum(float64(qty))
		if lay.chgFits && b.ChangePct != nil {
			// Owner order 2026-11-24 (later): the percentage is right aligned in
			// its field, so every board row's percent ends on one cell.
			a.flashText(c, lay.chgX, ry, padLeft(changeText(*b.ChangePct), lay.chgW), a.dirColor(*b.ChangePct), true, pxKey)
		}
		rightAlign(c, lay.qtyX, ry, lay.qtyW, []Span{{qtyTxt, good, true}})
		// Owner order 2026-11-12 (latest): both boards draw the one bar, so a
		// selling board is red because the sellers are in front, never green
		// because that board's own side is selling, and the pair is the same
		// measured day pair every other page prints for the scrip.
		barBuy, barSell := barPair(tbl, b.Symbol, b.BuyShares, b.SellShares)
		a.drawShareBar(c, lay.barX, ry, lay.barW, barBuy, barSell, false, 0)
		// Owner order 2026-11-23 (latest): NET DELTA and its figure stand right
		// after the bar, and the figure's last cell closes the row.
		if lay.netW > 0 {
			net := barBuy - barSell
			ink, bold := th.Soft, false
			switch {
			case net > 0:
				ink, bold = th.Good, true
			case net < 0:
				ink, bold = th.Bad, true
			}
			// Owner order 2026-11-24: the words NET DELTA leave both boards. Only
			// its value stands after the bar, on the block's first cell, so the
			// figure sits one cell after the bar instead of at the row's end.
			c.Text(lay.netX, ry, lay.netW, signedCompact(net), ink, bold)
		}
	}
	a.scrollbar(c, x+w-2, iy, ih, lv)
}

// boardRow is the geometry of one ALERTS board row. Owner order 2026-11-23
// (latest): the price, the percentage, the quantity and the bar step left as
// one group and NET DELTA and its figure close the row right after the bar, so
// the figure's last cell stands on the row's last content cell.
type boardGeom struct {
	pxW, priceX int
	chgX, chgW  int
	chgFits     bool
	qtyX, qtyW  int
	barX, barW  int
	netX, netW  int // netW is 0 when the board has no room for the block
}

// boardRowLayout right anchors that group. The bar keeps its sixteen cells
// while the group fits; when it does not, the bar gives way first, then the
// percentage steps out, and a board with no room for the NET DELTA block keeps
// the geometry the boards had before it, with the bar on the row's own edge.
func boardRowLayout(ix, cw, pxW, qtyW, vW int) boardGeom {
	const chgW = 9
	right := ix + cw - 1
	// The row's number, its flagged mark and its symbol keep the first fourteen
	// cells, so the quote group may never step left of ix+14.
	left := ix + 14
	// Owner order 2026-11-24: the block holds the figure alone now, so it is
	// exactly as wide as the widest figure and it stands right after the bar.
	netW := max(1, vW)
	for _, withChange := range []bool{true, false} {
		// Owner order 2026-11-24: the percentage and the quantity stand one
		// cell closer than build 161 had them, and the quantity and the bar do
		// too, so each of those two gaps is one space tighter.
		w, gap := chgW, 0
		if !withChange {
			w, gap = 0, 0
		}
		for barW := shareBarSpan; barW >= 6; barW-- {
			netX := right - netW + 1
			barX := netX - 1 - barW
			qtyX := barX - 1 - qtyW
			chgX := qtyX - gap - w
			priceX := chgX - 1 - (quoteLabelW + pxW)
			if priceX >= left {
				return boardGeom{pxW: pxW, priceX: priceX, chgX: chgX, chgW: w,
					chgFits: withChange, qtyX: qtyX, qtyW: qtyW,
					barX: barX, barW: barW, netX: netX, netW: netW}
			}
		}
	}
	// No room for NET DELTA: the boards keep the geometry they had, with the
	// bar on the row's right edge and the quantity two cells to its left.
	barW := min(shareBarSpan, cw)
	barX := ix + cw - barW
	qtyW = 10
	qtyX := barX - 1 - qtyW
	if qtyX < ix+25 {
		qtyX = ix + 25
		qtyW = max(1, barX-2-qtyX)
	}
	return boardGeom{pxW: pxW, priceX: ix + 28 - quoteLabelW - pxW, chgX: ix + 29,
		chgW: chgW, chgFits: qtyX-(ix+29) >= chgW+2, qtyX: qtyX, qtyW: qtyW,
		barX: barX, barW: barW}
}

// boardMeasure is the width of the three fields the ALERTS boards must share:
// the price, the side's own quantity and the bar's NET DELTA figure. Owner
// order 2026-11-23 (latest): the Alerts page measures both boards before it
// draws either, so the buying rows and the selling rows stand on the same
// columns instead of each board measuring whatever it happens to hold.
type boardMeasure struct{ pxW, qtyW, valW int }

func (a *App) measureBoards() boardMeasure {
	m := boardMeasure{pxW: 6, qtyW: 1, valW: 3}
	tbl := a.scanTable()
	for _, side := range []int{sideBuy, sideSell} {
		rows := a.boardRows(200)
		if side == sideSell {
			rows = a.sellRows(200)
		}
		for _, b := range rows {
			m.pxW = max(m.pxW, runeLen(commaFloat(b.Price, 2)))
			qty := b.BuyShares
			if side == sideSell {
				qty = b.SellShares
			}
			m.qtyW = max(m.qtyW, runeLen(compactNum(float64(qty))))
			buy, sell := barPair(tbl, b.Symbol, b.BuyShares, b.SellShares)
			m.valW = max(m.valW, runeLen(signedCompact(buy-sell)))
		}
	}
	return m
}

// alertPct is the move the alert was raised at. Owner order 2026-11-20: the
// ALERTS LOG is the record of what was bought or sold, so it keeps the price and
// the percentage of that moment and no longer follows the live quote after the
// row is written.
func (a *App) alertPct(f Flag) *float64 {
	return f.ChangePct
}

// alertLog is the flag log cut to the scrip typed in the ALERTS LOG's own
// search box. Owner order 2026-11-18: that box is back inside the log, so this
// filter is separate from the scanner's SEARCH tile beside it.
func (a *App) alertLog() []Flag {
	log := a.flagLog()
	if a.alertQuery == "" {
		return log
	}
	kept := log[:0]
	for _, f := range log {
		if strings.HasPrefix(f.Symbol, a.alertQuery) {
			kept = append(kept, f)
		}
	}
	return kept
}

// drawAlertLog is the log of every flag raised, buying and selling, newest first.
func (a *App) drawAlertLog(c *Canvas, x, y, w, h int) {
	th := a.th
	all := a.flagLog()
	log := a.alertLog()
	// Owner order 2026-11-18: the ALERTS LOG carries its own search box again.
	// One blank row stands between the box and the first alert.
	title := "ALERTS LOG (" + strconv.Itoa(len(log)) + ")"
	if a.alertQuery != "" {
		title = "ALERTS LOG (" + strconv.Itoa(len(log)) + " of " + strconv.Itoa(len(all)) + ")"
	}
	// Owner order 2026-11-15: the ALERTS LOG frame does not highlight on a click.
	// Owner order 2026-11-24: the tile's own edge names the quantity the log
	// keeps and the key that gives its box the keys.
	hint := "QTY " + compactNum(float64(alertFloorShares)) + " and above. " + pressSearchHint
	lx, liy, liw, lih := a.panel(c, x, y, w, h, title, hint)
	a.addHit(x, y, w, h, func() { a.alertFocus, a.alertLogSearch = 2, false })
	searchY := liy
	bw := a.searchBox(c, lx, searchY, min(liw, 40), a.alertQuery, scripSearchHint, a.alertLogSearch)
	a.addHit(lx, searchY, bw, 1, func() { a.alertFocus, a.alertLogSearch = 2, true; a.lvLog.top() })
	// Owner order 2026-11-17: alerts sit on consecutive rows, with no blank
	// row between them. A price alert's detail sentence joins its title on the
	// one row.
	const per = 1
	listY := searchY + 2
	if lih < 3 {
		return
	}
	a.lvLog.set(len(log), (lih-2)/per)
	row := listY
	lw := contentW(&a.lvLog, liw)
	// The quantity and the scrip fields are measured over the whole log, so a
	// short figure or a short scrip leaves blanks at its field's end instead of
	// pushing the words after it onto cells of their own.
	qtyW, symW := 1, 1
	for _, f := range log {
		if f.Kind == "order" && f.Shares > 0 && f.Symbol != "" {
			qtyW = max(qtyW, runeLen(compactNum(float64(f.Shares))))
			symW = max(symW, runeLen(f.Symbol))
		}
	}
	for n := 0; n < a.lvLog.view; n++ {
		i := a.lvLog.off + n
		if i >= len(log) {
			break
		}
		f := log[i]
		sc := th.Good
		if f.Side == "SELL" {
			sc = th.Bad
		}
		kind := "ORDER"
		switch f.Kind {
		case "flow":
			kind = "FLOW"
		case "block":
			kind = "BLOCK"
		case "price":
			kind = "PRICE"
		}
		// Owner order 2026-11-19: everything except the current price and the
		// percentage stays on the left. Those two end on fixed right hand
		// columns, so a long sentence can no longer cut either of them off and
		// a fall ends on the same cell as a rise.
		pct := a.alertPct(f)
		// A flag reserves the right hand columns only when it brings its own
		// price or move. A live quote alone must not narrow a plain sentence.
		showGroup := f.Price > 0 || f.ChangePct != nil
		text := f.Text
		if at := strings.Index(text, " at PKR "); at >= 0 {
			stem := strings.TrimRight(text[:at], " .")
			if showGroup {
				// Owner order 2026-11-19: bought and sold lead into the price
				// column with the word at, never a full stop.
				text = stem + " at"
			} else {
				text = stem + "."
			}
		}
		if f.Detail != "" {
			detail := f.Detail
			if at := strings.Index(detail, " at PKR "); at >= 0 {
				stem := strings.TrimRight(detail[:at], " .")
				if showGroup {
					detail = stem + " at"
				} else {
					detail = stem + "."
				}
			}
			text += "  " + detail
		}
		if f.Silent {
			text += "  (silent)"
		}
		// A flag without a price keeps the whole row for its sentence; only a
		// priced flag gives the right hand columns their cells.
		const priceW = 8
		groupX, leadW := lx+lw, lw
		if showGroup {
			groupX = lx + lw - quoteWidth(priceW)
			leadW = max(1, groupX-lx-1)
		}
		// Owner order 2026-11-24 (later): every order row reads in columns. The
		// quantity holds its own right aligned field, the scrip holds a further
		// one on the left, and the two words that follow are the one width, so
		// shares, of, the scrip, were bought and were sold all start on one cell
		// down the whole log and lead into the price and percentage columns.
		lead := []Span{{f.Time.In(pkt).Format("15:04:05") + "  ", th.Soft, false},
			{padRight(f.Side+" "+kind, 11), sc, true}}
		if f.Kind == "order" && f.Shares > 0 && f.Symbol != "" {
			verb := "were bought"
			if f.Side == "SELL" {
				verb = "were sold"
			}
			body := padLeft(compactNum(float64(f.Shares)), qtyW) + " shares of " +
				padRight(f.Symbol, symW) + " " + verb
			if showGroup {
				body += " at"
			} else {
				body += "."
			}
			lead = append(lead, Span{body, th.Hot, true})
		} else {
			lead = append(lead, Span{text, th.Hot, true})
		}
		c.Spans(lx, row, leadW, lead)
		if showGroup {
			if f.Price > 0 {
				// Owner order 2026-11-20: the log's figures are written once, so
				// they carry no live flash key.
				a.drawQuote(c, groupX, row, priceW, commaFloat(f.Price, 2), nil, "")
				if pct != nil {
					// Owner order 2026-11-24 (later): the whole move,
					// arrow, gap and figure, is right aligned in the eight
					// cells the group reserves, so 5.56% ends on the cell
					// 10.01% ends on and the price keeps its own column.
					c.Text(groupX+quoteLabelW+priceW+quoteGap, row, quotePctW+2,
						padLeft(changeText(*pct), quotePctW+2), a.dirColor(*pct), true)
				}
			} else if pct != nil {
				a.drawQuotePct(c, groupX+quoteLabelW+priceW+quoteGap, row, *pct)
			}
		}
		row += per
	}
	a.scrollbar(c, x+w-2, listY, a.lvLog.view*per, &a.lvLog)
}

// fetchOrDemo loads a symbol's detail the way the search screen does.
func (a *App) fetchOrDemo(sym string) {
	if a.demo {
		a.selectedSt, a.selectedInfo = "ok", demoStock(sym)
		return
	}
	a.fetchStock(sym)
}

// liveQuote is the broker feed reading of a symbol, when it has a fresh one.
func (a *App) liveQuote(sym string) (LiveQuote, bool) {
	if a.quotes == nil {
		return LiveQuote{}, false
	}
	q, ok := a.quotes.Items[sym]
	return q, ok && q.Fresh && q.Price > 0
}

// pickSymbol selects a symbol on the search screen and loads its detail.
func (a *App) pickSymbol(sym string) {
	a.selectedSym = sym
	a.fetchOrDemo(sym)
}
