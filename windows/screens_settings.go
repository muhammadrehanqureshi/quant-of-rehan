package main

// ---------- settings ----------

// drawSettings is the SETTINGS page. Owner order 2026-11-11: the page is three
// tiles stacked in one column instead of one long panel - the switches in
// SETTINGS, the palette in THEMES, and every read-only fact in its own tile
// headed BUILD VERSION & RELAY.
func (a *App) drawSettings(c *Canvas, x, y, w, h int) {
	th := a.th
	settingsH := settingsItems + 2 // the eight switch rows, plus the frame
	themesH := len(themes) + 2     // one row per theme, plus the frame
	relayH := h - settingsH - themesH - 2
	if relayH < 4 {
		// A short window gives the facts tile its floor first, then the
		// themes tile, and only then the switches.
		short := 4 - relayH
		if take := min(short, themesH-4); take > 0 {
			themesH -= take
			relayH += take
			short -= take
		}
		if short > 0 {
			if take := min(short, settingsH-4); take > 0 {
				settingsH -= take
				relayH += take
			}
		}
	}
	if relayH < 1 {
		relayH = 1
	}

	// Owner order 2026-11-12 (latest): the UP/DOWN + ENTER hint is withdrawn.
	ix, iy, iw, _ := a.panel(c, x, y, w, settingsH, "SETTINGS", "")
	row := iy
	rowW := min(iw, 72)
	item := func(i int, left string, right []Span) {
		cur := i == a.setCursor
		idx := i
		bg := a.selectRow(c, ix, row, rowW, cur, func() { a.activateSetting(idx) })
		mark := ' '
		if cur {
			mark = '◆'
		}
		// Owner order 2026-11-11: the setting cursor is blue, not white.
		c.Set(ix+1, row, mark, th.Accent, bg, true)
		c.Text(ix+3, row, 22, left, th.Text, cur)
		c.Spans(ix+26, row, rowW-26, right)
		row++
	}
	onoff := func(b bool, extra string) []Span {
		if b {
			return []Span{{"ON", th.Good, true}, {extra, th.Soft, false}}
		}
		return []Span{{"OFF", th.Bad, true}, {extra, th.Soft, false}}
	}
	item(0, "RELAY STATUS", []Span{{"Opens the relay's health page.", th.Soft, false}})
	item(1, "NOTIFICATIONS", onoff(a.cfg.Notify, "  Windows pop-ups and the banner."))
	item(2, "BIG BUYING FLAG", onoff(a.cfg.BigBuy, "  Alerts you when buyers dominate."))
	item(3, "BIG SELLING FLAG", onoff(a.cfg.BigSell, "  Alerts you when sellers dominate."))
	item(4, "SOUND", onoff(a.cfg.Sound, "  A tone plays with alerts."))
	item(5, "BIG ORDER SIZE", []Span{{"PKR " + compactNum(float64(a.cfg.BigBuyValue)), th.Hot, true}, {" a minute.", th.Soft, false}})
	item(6, "TEST BUYING ALERT", []Span{{"Plays the buying tone and a test pop-up.", th.Soft, false}})
	item(7, "TEST SELLING ALERT", []Span{{"Plays the selling tone and a test pop-up.", th.Soft, false}})

	tx, ty, _, _ := a.panel(c, x, y+settingsH+1, w, themesH, "THEMES", "")
	trow := ty
	for i := range themes {
		t := &themes[i]
		idx := i + settingsItems
		themeNo := i
		cur := idx == a.setCursor
		bg := a.selectRow(c, tx, trow, rowW, cur, func() { a.activateSetting(idx) })
		mark := ' '
		if cur {
			mark = '◆'
		}
		// Owner order 2026-11-12 (latest): the chosen theme carries no second
		// diamond - the cursor's own mark is the only one in the tile - and the
		// name stands on the SETTINGS tile's own column, one cell after the
		// cursor, so the two tiles read down one line. The chips take the
		// column the SETTINGS values take.
		// Owner order 2026-11-11: the theme cursor is blue, not white.
		c.Set(tx+1, trow, mark, th.Accent, bg, true)
		c.Text(tx+3, trow, 22, t.Name, th.Text, a.cfg.Theme == themeNo)
		for k, col := range []RGB{t.BG, t.Panel, t.Line, t.Accent, t.Hot} {
			c.Set(tx+26+k*2, trow, '█', col, bg, false)
			c.Set(tx+27+k*2, trow, '█', col, bg, false)
		}
		trow++
	}

	bx, by, bw, bh := a.panel(c, x, y+settingsH+themesH+2, w, relayH, "BUILD VERSION & RELAY", "")
	brow := by
	// Owner order 2026-11-12 (latest): the facts read down the same column the
	// SETTINGS and THEMES tiles read down, three cells in from the frame, with
	// their values on one column after the key field like the other two tiles.
	info := func(k, v string, col RGB) {
		if brow >= by+bh {
			return
		}
		// Owner order 2026-11-13: the facts read on the SETTINGS and THEMES
		// cells exactly, key three cells in and value on the column those two
		// tiles put their values on, so all three tiles line up.
		c.Text(bx+3, brow, 22, k, th.Soft, false)
		c.Text(bx+26, brow, max(1, bw-26), fit(v, max(1, bw-26)), col, false)
		brow++
	}
	// Owner order 2026-11-12: VERSION stands before RELAY in the facts tile.
	// Owner order 2026-11-09: the settings page names the app version alone,
	// with no Windows build number and no ported app version beside it.
	// Owner order 2026-11-12 (latest): the RELAY row carries the relay's address
	// and nothing else, and the reset stands on the line under the count.
	info("VERSION", appVersionLabel, th.Hot)
	info("RELAY", a.relay.Base, th.Text)
	info("REQUESTS TODAY", commaInt(a.reqToday())+" of 100,000.", th.Text)
	info("", "The requests reset at 05:00 PKT.", th.Text)
	info("SCANNING", "Every second from 09:00 until the post-market closes.", th.Text)
	info("", "That is at 15:49 from Monday to Thursday and at 16:49 on Friday.", th.Text)
	info("SETTINGS FILE", settingsPath(), th.Soft)
}
