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
	// The sector tile sits between the search and the ranked list. It grows to
	// show every group it can while leaving the ranked list at least six rows,
	// and it scrolls when there are more groups than rows. Owner order
	// 2026-11-13: the tile shows six groups at most; the rest scroll. A tapped
	// sector opens its scrips inside this tile, and the CUSTOM SCRIPS tile below
	// stays on screen, so the two lists can be read together.
	sectorH := 7
	if a.sectorOpen {
		sectorH = min(max(len(a.visibleSectorMembers())+4, 9), 10)
	} else if n := len(a.visibleSectorIndices()); n > 0 {
		sectorH = min(n+4, 10)
	}
	// Owner order 2026-11-13: the calculator is a tile of its own under the
	// CUSTOM SCRIPS tile. It takes four rows at the bottom of the page and the
	// scrips list keeps the room above it. A window too short for the tile and
	// the lists hides the tile rather than cutting the scanner's own rows.
	calcH := 4
	if !a.calcOpen && y+h-sy-sectorH-1-calcH < 14 {
		calcH = 0
	}
	calcReserve := calcH
	if calcH > 0 {
		if y+h-sy-sectorH-1-calcH >= 17 {
			calcReserve++
		}
		defer a.drawCalculatorTile(c, x, y+h-calcH, w, calcH)
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
	if y+h-sy >= sectorH+1+calcReserve+6 {
		if a.sectorOpen {
			a.drawSectorOpen(c, x, sy, w, sectorH)
		} else {
			a.drawSectorTile(c, x, sy, w, sectorH)
		}
		sy += sectorH + 1
	}
	sh2 := y + h - sy - calcReserve
	if sh2 < 6 {
		return
	}
	// The sort instruction rides in the panel hint so the menu and the list keep
	// the row back that the sector search above took.
	// Owner order 2026-11-12 (latest): the UP, DOWN, PGUP, PGDN hint is
	// withdrawn, and the arrow keys keep working exactly as they did.
	// Owner order 2026-11-12 (latest): the hint names the arrows alone.
	hint := "Press LEFT & RIGHT arrow keys"
	if a.searchText != "" {
		hint = "ESC clears the search"
	}
	ix, iy, iw, ih := a.panel(c, x, sy, w, sh2, "CUSTOM SCRIPS OF VOLUME", hint)
	// Owner order 2026-11-12 (latest): every sort stands in the one left hand
	// column, the new ones under the two that were already there.
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
		bg := a.selectRow(c, ix, ry, min(iw, 48), cur, func() { a.pickScan(id) })
		mark := " "
		if cur {
			// Owner order 2026-11-11: the sub menu cursor is the diamond,
			// the same mark the rest of the build selects with.
			mark = "◆"
		}
		// Owner order 2026-11-11: the cursor and the chosen sort share one
		// diamond, never two side by side.
		chosen := "  "
		if a.scanChoice == id && !cur {
			chosen = "◆ "
		}
		// Owner order 2026-11-11: the sub menu cursor is blue, not white.
		c.Set(ix+1, ry, []rune(mark)[0], th.Accent, bg, true)
		// Owner order 2026-11-13: the six sorts carry their sequence numbers,
		// the same `1.` to `6.` the SECTORS tile uses, between the cursor and
		// the chosen sort's diamond.
		c.Text(ix+3, ry, 3, fmt.Sprintf("%2d.", id), th.Soft, false)
		c.Set(ix+7, ry, []rune(chosen)[0], th.Accent, bg, true)
		c.Text(ix+9, ry, max(1, min(44, iw-9)), name, th.Text, a.scanChoice == id)
	}
	head := iy + menu + 1 // the row after the menu, or the first row when it is hidden
	// Owner order 2026-11-12: each sort names three scrips and each scrip takes
	// two rows, its name and its KSE100 style values. When the blank row under
	// the menu would leave fewer than three, that row goes first, so the list
	// keeps its three scrips and the sector tile keeps its groups.
	if rows := iy + ih - (head + 1); rows/2 < 3 && head > iy+menu {
		head--
	}
	if a.scanChoice == 0 || head >= iy+ih {
		return
	}
	c.Text(ix, head, iw, scanChoices[a.scanChoice-1], th.Accent, true)
	top := head + 1
	rows := iy + ih - top
	if rows < 2 {
		return
	}
	tbl := a.scanTable()
	if len(tbl) == 0 {
		for i, ln := range wrap("No live quotes yet. Quotes arrive when the market is live.", iw) {
			c.Text(ix, top+i, iw, ln, th.Soft, false)
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
		c.Text(ix, top, iw, "No scrip qualifies right now.", th.Soft, false)
		return
	}
	a.lvScan.set(len(syms), rows/2)
	// Owner order 2026-11-12 (latest): the "1 to 3 of 3 scrips" count is
	// withdrawn from the sort's heading line, which now carries the sort's own
	// name and nothing else.
	row := top
	cw := contentW(&a.lvScan, iw)
	// Owner order 2026-11-12: the values on every scrip are the KSE100 tile's
	// own, in its own columns. B, S, U and T start on the same cell on every
	// scrip, the price follows the widest one, and the change and the bar close
	// the line, exactly as the three leaders on the KSE100 tile line up.
	cols := bstLeaderCols(scanLeaders(syms, tbl))
	pxW := 1
	for _, s := range syms {
		if q := tbl[s]; q.Price > 0 {
			pxW = max(pxW, runeLen(commaFloat(q.Price, 2)))
		}
	}
	for n := 0; n < a.lvScan.view; n++ {
		i := a.lvScan.off + n
		if i >= len(syms) {
			break
		}
		s := syms[i]
		q := tbl[s]
		pxKey, volKey := "px:"+s, "vol:"+s
		a.zebra(c, ix, row, cw, 2, i, s)
		c.Spans(ix, row, cw, []Span{{fmt.Sprintf("%d. ", i+1), th.Soft, false}, {s, th.Hot, true}})
		row++
		used := 0
		if cw >= 96 {
			used = a.putBSTCols(c, ix+3, row, q.Buy, q.Sell, q.Volume, cols, volKey, pxKey)
		} else {
			used = a.putBST(c, ix+3, row, q.Buy, q.Sell, q.Volume, volKey, pxKey)
		}
		if q.Price > 0 {
			const chgW = 8
			end := ix + cw - 1
			// Owner order 2026-11-12 (latest): the bar carries its NET DELTA
			// here too, so the field takes the bar and its figure at once.
			barStart := end - shareBarWidth + 1
			chgRight := barStart - 2
			priceRight := chgRight - chgW - 1
			px := commaFloat(q.Price, 2)
			showPrice := func(pkr, pxAt, chgAt int) {
				c.Text(pkr, row, 3, "PKR", th.Soft, false)
				a.flashText(c, pxAt, row, px, th.Text, true, pxKey)
				if q.ChangePct != nil {
					// Owner report 2026-11-12 (latest): PIM's price and its percentage
					// sat further apart than 14.00's, because the change was right
					// aligned and a digit wider. It starts on a fixed cell now, so the
					// gap after the price is the same on every row of the list.
					a.flashText(c, chgAt-chgW, row, fit(changeText(*q.ChangePct), chgW), a.dirColor(*q.ChangePct), true, pxKey)
				}
			}
			// Owner order 2026-11-12: the bar gives way first on a narrow row;
			// PKR and its price never leave the line.
			switch {
			case priceRight-pxW-4 >= ix+3+used+1:
				showPrice(priceRight-pxW-4, priceRight-pxW, chgRight)
				if q.Buy != nil && q.Sell != nil {
					if total := *q.Buy + *q.Sell; total > 0 {
						a.shareBar(c, barStart, row, shareBarWidth, *q.Buy, *q.Sell)
					}
				}
			case end-4-runeLen(px)-chgW-1 >= ix+3+used+1:
				pkr := end - 4 - runeLen(px) - chgW - 1
				showPrice(pkr, pkr+4, end)
			}
		}
		row++
	}
	a.scrollbar(c, x+w-2, top, a.lvScan.view*2, &a.lvScan)
}

// scanLeaders turns the three ranked quotes into the rows bstLeaderCols
// measures, so the scanner shares the KSE100 tile's own value columns.
func scanLeaders(syms []string, tbl map[string]Quote) []Leader {
	out := make([]Leader, 0, len(syms))
	for _, s := range syms {
		q := tbl[s]
		out = append(out, Leader{Symbol: s, Buy: q.Buy, Sell: q.Sell, Volume: q.Volume})
	}
	return out
}

// searchTileHeight is how tall the search tile is: three rows with nothing
// typed, and as many more as the matches and the chosen symbol need, but never
// more than a third of the screen.
func (a *App) searchTileHeight(w, h int) int {
	if a.searchText == "" && a.selectedSym == "" {
		return 3
	}
	m := len(a.matches())
	need := max(m, 1)
	if a.selectedSym != "" {
		need = max(need, 4)
	}
	if w < 64 {
		need += 4 // the details go under the matches
	}
	return min(3+need+1, max(5, h/3+1))
}

// searchBox draws the one filled field every search uses: SEARCH on the
// scanner, the SECTORS tile and ORDER FLOW. It returns the field's width.
func (a *App) searchBox(c *Canvas, x, y, w int, text, hint string, focused bool) int {
	th := a.th
	bw := min(w, 40)
	if bw < 1 {
		bw = 1
	}
	field := mix(th.Panel, th.Accent, 0.14)
	for k := 0; k < bw; k++ {
		c.Set(x+k, y, ' ', th.Text, field, false)
	}
	if text == "" {
		c.Text(x+2, y, max(1, bw-3), fit(hint, max(1, bw-3)), th.Soft, false)
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
	hint := pressSearchHint
	if a.searchText != "" {
		hint = "UP and DOWN choose, ENTER opens"
	}
	ix, iy, iw, ih := a.panel(c, x, y, w, h, "SEARCH", hint)
	a.searchBox(c, ix, iy, min(iw, 40), a.searchText, scripSearchHint, true)
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
	dx, dy, dw := ix+listW+3, row, iw-listW-3
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
				put(dy+1, "   LOW ", th.Soft, false)
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
	used := a.putBST(c, dx, dy+2, buy, sell, tot)
	// Owner order 2026-11-10 (latest): the chosen stock's bar is back on the
	// search tile, at the right edge of its own volume row.
	if buy != nil && sell != nil && *buy+*sell > 0 && dw-used-2 >= shareBarWidth {
		a.shareBar(c, dx+dw-shareBarWidth, dy+2, shareBarWidth, *buy, *sell)
	}
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
	ix, iy, iw, ih := a.panel(c, x, y, w, h, "SECTORS", "")
	// Owner order 2026-11-11: the SECTORS title carries no diamond logo; the
	// thin rule of the frame takes its place.
	c.Put(x+2, y, '─', th.Line, false)
	a.sectorY, a.sectorH = y, h
	searchRows := 0
	if ih > 0 {
		a.drawSectorSearch(c, ix, iy, iw, false)
		// One row for the field and one blank row before the list begins.
		searchRows = 2
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
		pctText, pctInk := "--", th.Soft
		if cnt > 0 {
			// Owner order 2026-11-13: the direction is an arrow, never a
			// plus or minus sign. The value is right aligned in the same
			// nine cells the scanner gives its NET DELTA, so the two right
			// hand columns end on one edge.
			pctText = changeText(pct)
			if pct < 0 {
				pctInk = th.Bad
			} else if pct > 0 {
				pctInk = th.Good
			}
		}
		c.Text(ix+3, ry, 3, fmt.Sprintf("%2d.", i+1), th.Soft, false)
		pctW := shareNetW
		pctX := ix + cw - pctW
		nameW := max(1, pctX-(ix+7)-2)
		c.Text(ix+7, ry, nameW, fit(g.Name, nameW), th.Text, idx == a.sectorChoice)
		rightAlign(c, pctX, ry, pctW, []Span{{pctText, pctInk, true}})
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
	ix, iy, iw, ih := a.panel(c, x, y, w, h, "SECTORS", "")
	// Owner order 2026-11-11: the SECTORS title carries no diamond logo.
	c.Put(x+2, y, '─', th.Line, false)
	a.drawSectorSearch(c, ix, iy+1, iw, true)
	// The field is on iy+1, iy+2 is the blank separator, and the table starts
	// on iy+3.
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
		c.Text(ix, iy+3, iw, "None of this sector's scrips is in KMIALLSHR right now.", th.Soft, false)
		return
	}
	if len(member) == 0 {
		c.Text(ix, iy+3, iw, "No scrip in this sector starts with "+a.sectorQueryText()+".", th.Soft, false)
		return
	}
	rows := ih - 3
	if rows < 1 {
		return
	}
	a.lvSectorStk.set(len(member), rows)
	tbl := a.scanTable()
	cw := contentW(&a.lvSectorStk, iw)
	for n := 0; n < a.lvSectorStk.view; n++ {
		i := a.lvSectorStk.off + n
		if i >= len(member) || iy+3+n >= iy+ih {
			break
		}
		sym := member[i]
		ry := iy + 3 + n
		a.selectRow(c, ix, ry, cw, false, func() { a.openSymbol(sym) })
		c.Spans(ix+1, ry, cw-1, []Span{{fmt.Sprintf("%3d. %-9s", i+1, sym), th.Hot, true}})
		if q, ok := tbl[sym]; ok && q.Price > 0 {
			c.Spans(ix+16, ry, cw-16, []Span{{"PKR ", th.Soft, false}, {commaFloat(q.Price, 2), th.Text, true}})
			if q.ChangePct != nil {
				rightAlign(c, ix, ry, cw, []Span{{changeText(*q.ChangePct), a.dirColor(*q.ChangePct), true}})
			}
		}
	}
	a.scrollbar(c, ix+iw-1, iy+3, a.lvSectorStk.view, &a.lvSectorStk)
}

// openSector opens group i in the SECTORS tile without leaving the scanner.
func (a *App) openSector(i int) {
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

// hoveredSector is the group row under the pointer in the closed sector tile,
// or -1. It lets ENTER open the row the owner is pointing at.
func (a *App) hoveredSector() int {
	if a.sectorOpen || a.sectorH <= 0 || a.hoverY < a.sectorY+2 || a.hoverY >= a.sectorY+a.sectorH-1 {
		return -1
	}
	i := a.lvSector.off + a.hoverY - (a.sectorY + 2)
	vis := a.visibleSectorIndices()
	if i < 0 || i >= len(vis) {
		return -1
	}
	return vis[i]
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

// shareBarSpan is the cells the ten boxes cover. Owner order 2026-11-11
// (second pass): the patch 30 look is undone and the patch 29 bar is back, so
// the bar is 16 cells again, exactly as long as it was, and the ten boxes
// share those cells instead of standing apart with a gap between them.
const shareBarSpan = shareBarBoxes * 16 / 10

// shareNetW is the cells a bar gives to its NET DELTA, left aligned like every
// other value, so a sign and a compact figure start on the same cell.
const shareNetW = 9

// shareBarGap is the gutter between two columns. Owner order 2026-11-12
// (latest): every column on ORDER FLOW is separated by the same two cells, the
// bar's own NET DELTA included, so no pair of columns is tighter than another.
const shareBarGap = 2

// shareBarWidth is the field a labelled bar asks for: its span, the gutter and
// the NET DELTA after it.
const shareBarWidth = shareBarSpan + shareBarGap + shareNetW

// shareBar draws a buy versus sell bar: its sixteen cells split at the buyers'
// exact share, then one gutter, then the NET DELTA, so the two sides' strength
// and the difference between them read in one glance.
func (a *App) shareBar(c *Canvas, x, y, w int, buy, sell int64) {
	a.drawShareBar(c, x, y, w, buy, sell, true)
}

// shareBarOnly draws the same bar with no NET DELTA after it, for the leaders
// card and the scanner, where the row already carries its own volumes. It
// returns the cells used.
func (a *App) shareBarOnly(c *Canvas, x, y, w int, buy, sell int64) int {
	return a.drawShareBar(c, x, y, w, buy, sell, false)
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
func (a *App) drawShareBar(c *Canvas, x, y, w int, buy, sell int64, label bool) int {
	th := a.th
	total := buy + sell
	if total <= 0 {
		return 0
	}
	// The bar is 16 cells; a caller with less room (the ALERTS boards pass the
	// ten cells of a compact bar) gets a bar of exactly the room it has.
	span := shareBarSpan
	if w > 0 && w < span {
		span = w
		if label && w-shareNetW-shareBarGap >= shareBarBoxes {
			span = w - shareNetW - shareBarGap
		}
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
		c.Text(x+width+shareBarGap, y, shareNetW, signedCompact(net), ink, bold)
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
	if w >= 84 {
		// Owner order 2026-11-13: both boards are the same width, so the PKR
		// values, the changes and the bars end on one column. The old split
		// made the selling board one cell narrower, which moved its values.
		bw := (w - 1) / 2
		a.drawBoardPanel(c, x, y, bw, boardH, sideBuy)
		a.drawBoardPanel(c, x+bw+1, y, bw, boardH, sideSell)
		a.alertSplitX = x + bw + 1
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
	a.drawAlertLog(c, x, ly, w, lh)
}

// drawBoardPanel draws one side's board: who is being bought (or sold) hardest
// over the last minute.
func (a *App) drawBoardPanel(c *Canvas, x, y, w, h int, side int) {
	th := a.th
	title, word, on, focus := "BIG BUYING NOW", "buyers", a.cfg.BigBuy, 0
	lv := &a.lvBoard
	good := th.Good
	rows := a.boardRows
	flagKey := "B"
	if side == sideSell {
		title, word, on, focus = "BIG SELLING NOW", "sellers", a.cfg.BigSell, 1
		lv = &a.lvSell
		good = th.Bad
		rows = a.sellRows
		flagKey = "S"
	}
	hint := "The flag is off."
	if on {
		// Owner order 2026-11-12 (latest): the heading names the floor the
		// board really keeps, so no row can be smaller than the words.
		hint = "PKR " + compactNum(boardFloor) + " or above orders"
	}
	_ = word
	a.focusNext = a.alertFocus == focus
	ix, iy, iw, ih := a.panel(c, x, y, w, h, title, hint)
	// Owner order 2026-11-07: the buying heading is green and the selling
	// heading is red, even when the focused panel would otherwise be hot.
	titleInk := good
	c.Put(x+2, y, '◆', titleInk, false)
	c.Text(x+4, y, w-8, fit(title, w-12), titleInk, true)
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
		msg := "Watching every broker tick. Nothing is being traded in size right now."
		if !a.trading() {
			msg = "Watching the feed. It is counted while the market is trading."
		}
		for i, ln := range wrap(msg, iw) {
			if i < ih {
				c.Text(ix, iy+i, iw, ln, th.Soft, false)
			}
		}
		return
	}
	lv.set(len(board), ih)
	cw := contentW(lv, iw)
	// Owner order 2026-11-13: one bar pair for the whole build. The boards
	// rank their rows on the last minute, but each bar reads the measured day
	// B and S pair the scanner, the search tile and the KSE100 leaders use.
	tbl := a.scanTable()
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
		a.flashText(c, ix+15, ry, padRight(commaFloat(b.Price, 2), 9), th.Text, true, pxKey)
		// Owner order 2026-11-10 (latest): both boards carry their PKR value and
		// their bar. The bar keeps the row's right edge, the value stands on the
		// same two cell gutter to its left, and the change steps out first when
		// the row is narrow, because the value and the bar are the two fields the
		// owner asked to see. The value is this side's own: bought volume on the
		// buying board, sold volume on the selling board.
		const chgW = 9
		val := b.BuyValue
		if side == sideSell {
			val = b.SellValue
		}
		pkrTxt := "PKR " + compactNum(val)
		// Owner order 2026-11-13: the board bar shows only the B versus S
		// dominance. The NET DELTA label is gone from these two boards; the
		// PKR value is right aligned on a fixed column instead. The bar still
		// reads the row's own measured pair, never the board's chosen side.
		barW := shareBarSpan
		if barW > cw {
			barW = cw
		}
		barX := ix + cw - barW
		pkrFieldW := 10
		pkrX := barX - 2 - pkrFieldW
		if pkrX < ix+25 {
			pkrX = ix + 25
			pkrFieldW = max(1, barX-2-pkrX)
		}
		if pkrFieldW < 1 {
			pkrFieldW = 1
		}
		if b.ChangePct != nil && pkrX-(ix+25) >= chgW+2 {
			a.flashText(c, ix+25, ry, padRight(changeText(*b.ChangePct), chgW), a.dirColor(*b.ChangePct), true, pxKey)
		}
		rightAlign(c, pkrX, ry, pkrFieldW, []Span{{pkrTxt, good, true}})
		// Owner order 2026-11-12 (latest): both boards draw the one bar, so a
		// selling board is red because the sellers are in front, never green
		// because that board's own side is selling, and the pair is the same
		// measured day pair every other page prints for the scrip.
		barBuy, barSell := barPair(tbl, b.Symbol, b.BuyShares, b.SellShares)
		a.drawShareBar(c, barX, ry, barW, barBuy, barSell, false)
	}
	a.scrollbar(c, x+w-2, iy, ih, lv)
}

// alertLog is the flag log cut to the scrip being searched. Owner order
// 2026-11-11 (tenth pass): the ALERTS LOG carries its own SEARCH box, and a
// scrip typed there shows every alert it has.
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
	// Owner order 2026-11-12 (latest): the key line closes after the search
	// sentence, and the test sentence is withdrawn from the log's frame.
	hint := pressSearchHint
	title := "ALERTS LOG (" + strconv.Itoa(len(log)) + ")"
	if a.alertQuery != "" {
		title = "ALERTS LOG (" + strconv.Itoa(len(log)) + " of " + strconv.Itoa(len(all)) + ")"
	}
	a.focusNext = a.alertFocus == 2
	lx, liy, liw, lih := a.panel(c, x, y, w, h, title, hint)
	a.addHit(x, y, w, h, func() { a.alertFocus = 2 })
	bw := a.searchBox(c, lx, liy, min(liw, 40), a.alertQuery, scripSearchHint, a.alertSearch)
	a.addHit(lx, liy, bw, 1, func() { a.alertFocus, a.alertSearch = 2, true; a.lvLog.top() })
	const per = 3 // a title and up to two lines of detail
	listY := liy + 1
	if len(log) == 0 {
		msg := "No flag yet. A flag is raised when a stock is bought or sold in size within a minute and one side is well ahead of the other. " +
			"It appears here and in the banner at the top, with a Windows notification and a tone. Buying and selling have their own tones. " +
			"Press ENTER to hear a test."
		if a.alertQuery != "" {
			msg = fmt.Sprintf("No alert matches %q.", a.alertQuery)
		}
		for i, ln := range wrap(msg, liw) {
			if i < lih-1 {
				c.Text(lx, listY+i, liw, ln, th.Soft, false)
			}
		}
		return
	}
	if lih < 2 {
		return
	}
	a.lvLog.set(len(log), (lih-1)/per)
	row := listY
	lw := contentW(&a.lvLog, liw)
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
		kind := "FLOW"
		switch f.Kind {
		case "block":
			kind = "BLOCK"
		case "price":
			kind = "PRICE"
		}
		sp := []Span{{f.Time.In(pkt).Format("15:04:05") + "  ", th.Soft, false},
			{padRight(f.Side+" "+kind, 11), sc, true}, {f.Text, th.Hot, true}}
		if f.Silent {
			sp = append(sp, Span{"  (silent)", th.Soft, false})
		}
		c.Spans(lx, row, lw, sp)
		row++
		lines := wrap(f.Detail, lw-10)
		for k := 0; k < len(lines) && k < 2; k++ {
			ln := lines[k]
			if k == 1 && len(lines) > 2 {
				ln = fit(ln+" "+lines[2], lw-10)
			}
			c.Text(lx+10, row, lw-10, ln, th.Soft, false)
			row++
		}
		row = listY + (n+1)*per
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
