package main

import (
	"fmt"
	"math"
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

var scanChoices = [3]string{"PRICES RISING FAST", "MORE BUYERS & LESS SELLERS", "BIG BUYING & SELLING NOW (LIVE FLOW)"}

// scanTable is the table the first two sorts rank. The broker feed wins: when
// a symbol is in /quotes with a fresh tick, that is what is ranked, so the list
// moves with the market. The relay's /prices table fills in anything the
// feed does not carry. Buy and sell come from the relay's range estimate.
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
		if b, sl, ok := lq.RangeSplit(); ok {
			q.Buy, q.Sell = &b, &sl
		} else if old, ok := out[s]; ok {
			q.Buy, q.Sell = old.Buy, old.Sell
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
	sy := y + sh + 1
	// The sector tile sits between the search and the ranked list. It grows to
	// show every group it can while leaving the ranked list at least seven rows,
	// and it scrolls when there are more groups than rows. A tapped sector opens
	// its scrips inside this tile, and the CUSTOM SCRIPS tile below stays on
	// screen, so the two lists can be read together.
	sectorH := 6
	if a.sectorOpen {
		sectorH = min(max(len(a.visibleSectorMembers())+2, 7), 15)
	} else if n := len(a.visibleSectorIndices()); n > 0 {
		sectorH = min(n+2, 15)
	}
	if avail := y + h - sy; avail-sectorH < 7 {
		sectorH = max(5, avail-7)
	}
	if y+h-sy >= sectorH+7 {
		if a.sectorOpen {
			a.drawSectorOpen(c, x, sy, w, sectorH)
		} else {
			a.drawSectorTile(c, x, sy, w, sectorH)
		}
		sy += sectorH + 1
	}
	sh2 := y + h - sy
	if sh2 < 6 {
		return
	}
	hint := ""
	if a.scanChoice > 0 {
		hint = "UP, DOWN, PGUP, PGDN or the wheel scroll"
	}
	if a.searchText != "" {
		hint = "ESC clears the search"
	}
	ix, iy, iw, ih := a.panel(c, x, sy, w, sh2, "CUSTOM SCRIPS BY VOLUME", hint)
	c.Text(ix, iy, iw, "Pick a sort: click one, or press LEFT or RIGHT. BACKSPACE clears it.", th.Soft, false)
	menu := 3
	if ih < 11 {
		menu = 0 // a short window: the sort is chosen with LEFT and RIGHT only
	}
	for i, name := range scanChoices {
		if i >= menu {
			break
		}
		ry := iy + 1 + i
		id := i + 1
		cur := i == a.scanCursor
		bg := a.selectRow(c, ix, ry, min(iw, 48), cur, func() { a.pickScan(id) })
		mark := " "
		if cur {
			mark = ">"
		}
		chosen := "  "
		if a.scanChoice == id {
			chosen = "◆ "
		}
		c.Set(ix+1, ry, []rune(mark)[0], th.Hot, bg, true)
		c.Set(ix+3, ry, []rune(chosen)[0], th.Accent, bg, true)
		c.Text(ix+5, ry, min(44, iw-5), name, th.Text, a.scanChoice == id)
	}
	head := iy + 1 + menu + 1
	if menu == 0 {
		head = iy + 1
	}
	if a.scanChoice == 0 {
		return
	}
	c.Text(ix, head, iw, scanChoices[a.scanChoice-1], th.Accent, true)
	top := head + 1
	rows := iy + ih - top
	if a.scanChoice == 3 {
		a.drawFlowList(c, ix, head, top, iw, rows, x+w-2)
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
	if a.scanChoice == 1 {
		syms = rankedSpeedSymbols(tbl)
	} else {
		syms = rankedSplitSymbols(tbl)
	}
	if len(syms) == 0 {
		c.Text(ix, top, iw, "No scrip qualifies right now.", th.Soft, false)
		return
	}
	a.lvScan.set(len(syms), rows/2)
	rightAlign(c, ix, head, iw, []Span{{a.showing(&a.lvScan, "scrip"), th.Soft, false}})
	row := top
	cw := contentW(&a.lvScan, iw)
	for n := 0; n < a.lvScan.view; n++ {
		i := a.lvScan.off + n
		if i >= len(syms) {
			break
		}
		s := syms[i]
		q := tbl[s]
		pxKey := "px:" + s
		a.zebra(c, ix, row, cw, 2, i, s)
		c.Spans(ix, row, cw, []Span{{fmt.Sprintf("%3d. ", i+1), th.Soft, false}, {s, th.Hot, true}})
		right := ix + cw
		if q.ChangePct != nil {
			t := " " + changeText(*q.ChangePct)
			a.flashRight(c, right, row, t, a.dirColor(*q.ChangePct), true, pxKey)
			right -= runeLen(t)
		}
		ps := commaFloat(q.Price, 2)
		a.flashRight(c, right, row, ps, th.Text, true, pxKey)
		c.Text(right-runeLen(ps)-4, row, 4, "PKR ", th.Soft, false)
		var total int64
		if q.Buy != nil && q.Sell != nil {
			total = *q.Buy + *q.Sell
		}
		// The bar goes on the block's top row, in the free gap between the
		// symbol and the numbers, so its foot is the block's centre line and
		// the extra height grows upward from it.
		if total > 0 && cw >= 74 {
			a.shareBar(c, ix+24, row, 22, float64(*q.Buy)/float64(total))
		}
		row++
		if q.Buy != nil && q.Sell != nil {
			a.putBST(c, ix+5, row, q.Buy, q.Sell, &total, pxKey, "vol:"+s)
		}
		row++
	}
	a.scrollbar(c, x+w-2, top, a.lvScan.view*2, &a.lvScan)
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

// drawSearchTile is the search tile: the box you type in, the matching scrips
// under it and, for the one chosen, its live price, volume, range and its
// buying and selling.
func (a *App) drawSearchTile(c *Canvas, x, y, w, h int) {
	th := a.th
	hint := ""
	if a.searchText != "" {
		hint = "UP and DOWN choose, ENTER opens"
	}
	ix, iy, iw, ih := a.panel(c, x, y, w, h, "SEARCH", hint)
	fw := min(iw, 40)
	field := mix(th.Panel, th.Accent, 0.14)
	for k := 0; k < fw; k++ {
		c.Set(ix+k, iy, ' ', th.Text, field, false)
	}
	if a.searchText == "" {
		c.Text(ix+2, iy, fw-3, scripSearchHint, th.Soft, false)
	} else {
		c.Text(ix+1, iy, 1, ">", th.Accent, true)
		c.Text(ix+3, iy, fw-4, a.searchText, th.Hot, true)
		if int(a.animSeconds()*2)%2 == 0 {
			c.Set(ix+3+runeLen(a.searchText), iy, '█', th.Accent, field, false)
		}
	}
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
		marker := " "
		if s == a.selectedSym {
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
		pxKey, volKey := "px:"+a.selectedSym, "vol:"+a.selectedSym
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
			if lq.Volume > 0 {
				put(dy+1, "VOL ", th.Soft, false)
				put(dy+1, commaInt(lq.Volume), th.Text, false, volKey)
			}
			if lq.High > 0 && lq.Low > 0 {
				put(dy+1, "   LOW ", th.Soft, false)
				put(dy+1, commaFloat(lq.Low, 2), th.Bad, false)
				put(dy+1, "   HIGH ", th.Soft, false)
				put(dy+1, commaFloat(lq.High, 2), th.Good, false)
			}
		}
		if hs := a.symHist[a.selectedSym]; hs != nil && len(hs.v) >= 3 && dy+4 <= bottom && dw >= 50 {
			col := th.Good
			if hs.v[len(hs.v)-1] < hs.v[0] {
				col = th.Bad
			}
			sparkline(c, dx+dw-min(dw-30, 26), dy, min(dw-30, 26), 2, hs.v, col, th.Panel)
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
	a.putBST(c, dx, dy+2, buy, sell, tot)
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
	a.sectorY, a.sectorH = y, h
	a.drawSectorSearch(c, x, y, w, false)
	groups := a.sectorGroups()
	if len(groups) == 0 {
		msg := "Reading the sector groups from the relay."
		if a.sectorsErr != "" {
			msg = "Sectors are unavailable right now: " + a.sectorsErr
		}
		if ih > 0 {
			c.Text(ix, iy, iw, fit(msg, iw), th.Warn, false)
		}
		return
	}
	vis := a.visibleSectorIndices()
	if len(vis) == 0 {
		a.lvSector.set(0, max(1, ih))
		if ih > 0 {
			c.Text(ix, iy, iw, "No sector or scrip starts with "+a.sectorQueryText()+".", th.Soft, false)
		}
		return
	}
	if a.sectorChoice >= len(groups) || a.sectorChoice < 0 {
		a.sectorChoice = 0
	}
	rows := max(1, ih)
	a.lvSector.set(len(vis), rows)
	// The list is never snapped back to the chosen group: the wheel may scroll
	// the groups freely, even when the chosen one is the first row.
	cw := contentW(&a.lvSector, iw)
	for n := 0; n < a.lvSector.view; n++ {
		i := a.lvSector.off + n
		if i >= len(vis) {
			break
		}
		idx := vis[i]
		g := groups[idx]
		ry := iy + n
		bg := a.selectRow(c, ix, ry, cw, idx == a.sectorChoice, func() { a.openSector(idx) })
		mark := "  "
		if idx == a.sectorChoice {
			mark = "◆ "
		}
		c.Set(ix+1, ry, []rune(mark)[0], th.Accent, bg, true)
		name := fmt.Sprintf("%2d. %s", idx+1, g.Name)
		c.Text(ix+3, ry, max(1, cw-3), fit(name, max(1, cw-3)), th.Text, idx == a.sectorChoice)
		rightAlign(c, ix, ry, cw, []Span{{fmt.Sprintf("%d", len(g.Symbols)), th.Soft, false}})
	}
	a.scrollbar(c, ix+iw-1, iy, a.lvSector.view, &a.lvSector)
}

// drawSectorSearch draws the SECTORS tile's own field in the tile's top edge,
// to the right of the title. The field is a hit region: clicking it gives the
// box the keys, and the slash key does the same while the top scrip search is
// empty. It lives on the border so it does not take a row from the lists.
func (a *App) drawSectorSearch(c *Canvas, x, y, w int, scrips bool) {
	th := a.th
	fx := x + 14
	hint := "Search sectors"
	if scrips {
		hint = "Search scrips"
	}
	field, col := a.sectorQuery, th.Text
	if field == "" {
		field, col = hint, th.Soft
	}
	if a.sectorSearch {
		field += "▏"
	}
	bw := runeLen(hint) + 1
	if limit := w - 20; bw > limit {
		bw = max(8, limit)
	}
	bg := mix(th.Panel, th.Accent, 0.14)
	for i := 0; i < bw+2; i++ {
		c.Set(fx+i, y, ' ', th.Text, bg, false)
	}
	c.Put(fx, y, '[', th.Accent, true)
	c.Text(fx+1, y, bw, fit(field, bw), col, a.sectorSearch)
	c.Put(fx+1+bw, y, ']', th.Accent, true)
	if a.sectorQuery != "" {
		n := len(a.visibleSectorIndices())
		if scrips {
			n = len(a.visibleSectorMembers())
		}
		if w > 82 {
			c.Text(fx+bw+3, y, 9, fmt.Sprintf("%d match", n), th.Soft, false)
		}
	}
	a.addHit(fx, y, bw+2, 1, func() {
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
	a.drawSectorSearch(c, x, y, w, true)
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
	c.Spans(ix, iy, iw, []Span{{"◆ " + g.Name, th.Hot, true},
		{"  ·  ", th.Soft, false},
		{detail, th.Soft, false}})
	if len(all) == 0 {
		c.Text(ix, iy+1, iw, "None of this sector's scrips is in KMIALLSHR right now.", th.Soft, false)
		return
	}
	if len(member) == 0 {
		c.Text(ix, iy+1, iw, "No scrip in this sector starts with "+a.sectorQueryText()+".", th.Soft, false)
		return
	}
	rows := ih - 1
	if rows < 1 {
		return
	}
	a.lvSectorStk.set(len(member), rows)
	tbl := a.scanTable()
	cw := contentW(&a.lvSectorStk, iw)
	for n := 0; n < a.lvSectorStk.view; n++ {
		i := a.lvSectorStk.off + n
		if i >= len(member) || iy+1+n >= iy+ih {
			break
		}
		sym := member[i]
		ry := iy + 1 + n
		a.selectRow(c, ix, ry, cw, false, func() { a.openSymbol(sym) })
		c.Spans(ix+1, ry, cw-1, []Span{{fmt.Sprintf("%3d. %-9s", i+1, sym), th.Hot, true}})
		if q, ok := tbl[sym]; ok && q.Price > 0 {
			c.Spans(ix+16, ry, cw-16, []Span{{"PKR ", th.Soft, false}, {commaFloat(q.Price, 2), th.Text, true}})
			if q.ChangePct != nil {
				rightAlign(c, ix, ry, cw, []Span{{changeText(*q.ChangePct), a.dirColor(*q.ChangePct), true}})
			}
		}
	}
	a.scrollbar(c, ix+iw-1, iy+1, a.lvSectorStk.view, &a.lvSectorStk)
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

// visibleSectorIndices are the groups the SECTORS search box lets through, as
// indices into sectorGroups. A group matches when its name starts with the
// query or when any scrip it carries does, so typing CHRL finds CEMENT too.
func (a *App) visibleSectorIndices() []int {
	groups := a.sectorGroups()
	q := a.sectorQueryText()
	if q == "" {
		out := make([]int, len(groups))
		for i := range out {
			out[i] = i
		}
		return out
	}
	var out []int
	for i, g := range groups {
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
	return out
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
	if a.sectorOpen || a.sectorH <= 0 || a.hoverY < a.sectorY+1 || a.hoverY >= a.sectorY+a.sectorH-1 {
		return -1
	}
	i := a.lvSector.off + a.hoverY - (a.sectorY + 1)
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

// drawFlowList lists the stocks moving hardest on either side in the last
// minute, every one of them, with the list scrolling when they do not all fit.
func (a *App) drawFlowList(c *Canvas, ix, head, top, iw, rows, barX int) {
	th := a.th
	board := a.flowRows(200)
	if len(board) == 0 {
		msg := "No stock is being bought or sold in size right now."
		if !a.trading() {
			msg = "This list fills while the market is trading."
		}
		c.Text(ix, top, iw, msg, th.Soft, false)
		return
	}
	a.lvScan.set(len(board), rows/2)
	rightAlign(c, ix, head, iw, []Span{{a.showing(&a.lvScan, "stock"), th.Soft, false}})
	c.Text(ix+runeLen(scanChoices[2])+2, head, iw, "·  last 60 seconds", th.Soft, false)
	row := top
	cw := contentW(&a.lvScan, iw)
	for n := 0; n < a.lvScan.view; n++ {
		i := a.lvScan.off + n
		if i >= len(board) {
			break
		}
		b := board[i]
		pxKey := "px:" + b.Symbol
		a.zebra(c, ix, row, cw, 2, i, b.Symbol)
		flag := ""
		if b.Flagged {
			flag = " ◆"
		}
		c.Spans(ix, row, cw, []Span{{fmt.Sprintf("%3d. ", i+1), th.Soft, false}, {b.Symbol, th.Hot, true}, {flag, th.Warn, true}})
		if cw >= 70 {
			// On the block's top row, the foot of the cell is the block's
			// centre line, so the bar grows upward from it.
			a.shareBar(c, ix+24, row, 22, b.Share)
		}
		right := ix + cw
		if b.ChangePct != nil {
			t := " " + changeText(*b.ChangePct)
			a.flashRight(c, right, row, t, a.dirColor(*b.ChangePct), true, pxKey)
			right -= runeLen(t)
		}
		ps := commaFloat(b.Price, 2)
		a.flashRight(c, right, row, ps, th.Text, true, pxKey)
		c.Text(right-runeLen(ps)-4, row, 4, "PKR ", th.Soft, false)
		row++
		buy, sell, tot := b.BuyShares, b.SellShares, b.BuyShares+b.SellShares
		w := a.putBST(c, ix+5, row, &buy, &sell, &tot, pxKey)
		if left := cw - 5 - w - 2; left > 12 {
			c.Spans(ix+5+w+2, row, left, []Span{{"PKR ", th.Soft, false}, {compactNum(b.BuyValue), th.Good, true},
				{" bought / ", th.Soft, false}, {compactNum(b.SellValue), th.Bad, true}, {" sold", th.Soft, false}})
		}
		row++
	}
	a.scrollbar(c, barX, top, a.lvScan.view*2, &a.lvScan)
}

// barBlock is the lower seven eighths of a cell. The owner asked for fifteen
// percent more than the three quarters of the last build; seven eighths is the
// terminal font's next step, sixteen and two thirds over three quarters and the
// closest it can come.
const barBlock = '▇'

// shareBarTabs is the number of ten percent tabs in every buy versus sell
// bar. Owner order 2026-11-07: ten tabs, and the bar keeps its previous
// 17-cell span, so the tabs share the old length instead of shrinking it to
// ten cells.
const shareBarTabs = 10

// shareBarTabWidths splits total cells into at most tabs tabs, spreading the
// cells from the left. Every cell belongs to one tab, so the bar has no holes.
// At 17 cells and ten tabs the widths are 2,2,2,1,2,2,1,2,2,1.
func shareBarTabWidths(total int) []int {
	if total <= 0 {
		return nil
	}
	n := shareBarTabs
	if total < n {
		n = total
	}
	widths := make([]int, n)
	for i := 0; i < total; i++ {
		widths[i*n/total]++
	}
	return widths
}

// shareBar draws a buy versus sell bar of w columns, seven eighths of a cell
// tall. The coloured part keeps its previous 17-cell span, split into ten
// ten-percent tabs; one space follows it, then the percentage, so "98%" and
// "100%" both sit the same distance from the right edge.
func (a *App) shareBar(c *Canvas, x, y, w int, buyShare float64) {
	a.shareBarRune(c, x, y, w, buyShare, barBlock)
}

// shareBarMid draws the same split through the middle of a single-row box, which
// is what the ORDER FLOW table has: the bar is centred in the row, not along its
// top edge. A filled rectangle gives that one-row bar the thickness the owner
// asked for.
func (a *App) shareBarMid(c *Canvas, x, y, w int, buyShare float64) {
	a.shareBarRune(c, x, y, w, buyShare, '▬')
}

// shareBarRune draws the bar with the caller's character, always followed by
// one space and the percentage. The ten tabs are coloured at ten percent steps,
// while their widths share the full old span.
func (a *App) shareBarRune(c *Canvas, x, y, w int, buyShare float64, ch rune) {
	th := a.th
	full := max(1, w-5)
	widths := shareBarTabWidths(full)
	green := int(math.Round(buyShare * float64(len(widths))))
	if green < 0 {
		green = 0
	}
	if green > len(widths) {
		green = len(widths)
	}
	at := x
	for i, tw := range widths {
		ink := mix(th.Panel, th.Bad, 0.8)
		if i < green {
			ink = th.Good
		}
		for j := 0; j < tw; j++ {
			c.Put(at+j, y, ch, ink, false)
		}
		at += tw
	}
	c.Text(x+full+1, y, 4, strconv.FormatFloat(math.Round(buyShare*100), 'f', 0, 64)+"%", th.Soft, false)
}

// ---------- alerts ----------

// drawAlerts is the Alerts screen: the big buying board and the big selling
// board side by side (stacked in a narrow window), and the alert log below.
func (a *App) drawAlerts(c *Canvas, x, y, w, h int) {
	boardH := min(12, max(7, h/2-1))
	if w >= 84 {
		lw := w / 2
		rw := w - lw - 1
		a.drawBoardPanel(c, x, y, lw, boardH, sideBuy)
		a.drawBoardPanel(c, x+lw+1, y, rw, boardH, sideSell)
		a.alertSplitX = x + lw + 1
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
		hint = "From PKR " + compactNum(float64(a.cfg.BigBuyValue)) + " a minute"
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
		if cw >= 44 && b.ChangePct != nil {
			a.flashText(c, ix+25, ry, padRight(changeText(*b.ChangePct), 9), a.dirColor(*b.ChangePct), true, pxKey)
		}
		vx := ix + 35
		if cw < 44 {
			vx = ix + 25
		}
		if vx+12 < ix+cw {
			c.Spans(vx, ry, ix+cw-vx, []Span{{"PKR ", th.Soft, false}, {compactNum(b.BuyValue), good, true}})
		}
		if cw >= 62 {
			a.shareBar(c, ix+cw-22, ry, 22, b.Share)
		}
	}
	a.scrollbar(c, x+w-2, iy, ih, lv)
}

// drawAlertLog is the log of every flag raised, buying and selling, newest first.
func (a *App) drawAlertLog(c *Canvas, x, y, w, h int) {
	th := a.th
	log := a.flagLog()
	hint := "ENTER plays a test. DEL clears the log."
	title := "ALERT LOG (" + strconv.Itoa(len(log)) + ")"
	a.focusNext = a.alertFocus == 2
	lx, liy, liw, lih := a.panel(c, x, y, w, h, title, hint)
	a.addHit(x, y, w, h, func() { a.alertFocus = 2 })
	if len(log) == 0 {
		for i, ln := range wrap("No flag yet. A flag is raised when a stock is bought or sold in size within a minute and one side is well ahead of the other. "+
			"It appears here and in the banner at the top, with a Windows notification and a tone. Buying and selling have their own tones. "+
			"Press ENTER to hear a test.", liw) {
			if i < lih {
				c.Text(lx, liy+i, liw, ln, th.Soft, false)
			}
		}
		return
	}
	const per = 3 // a title and up to two lines of detail
	a.lvLog.set(len(log), lih/per)
	row := liy
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
		if f.Kind == "block" {
			kind = "BLOCK"
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
		row = liy + (n+1)*per
	}
	a.scrollbar(c, x+w-2, liy, a.lvLog.view*per, &a.lvLog)
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
