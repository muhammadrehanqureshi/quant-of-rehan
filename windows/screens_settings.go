package main

// ---------- settings ----------

func (a *App) drawSettings(c *Canvas, x, y, w, h int) {
	th := a.th
	ix, iy, iw, ih := a.panel(c, x, y, w, h, "SETTINGS", "UP/DOWN + ENTER")
	row := iy
	rowW := min(iw, 72)
	item := func(i int, left string, right []Span) {
		cur := i == a.setCursor
		idx := i
		bg := a.selectRow(c, ix, row, rowW, cur, func() { a.activateSetting(idx) })
		mark := ' '
		if cur {
			mark = '>'
		}
		c.Set(ix+1, row, mark, th.Hot, bg, true)
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
	item(5, "BIG ORDER SIZE", []Span{{"PKR " + compactNum(float64(a.cfg.BigBuyValue)), th.Hot, true}, {" a minute. LEFT and RIGHT.", th.Soft, false}})
	item(6, "TEST BUYING ALERT", []Span{{"Plays the buying tone and a test pop-up.", th.Soft, false}})
	item(7, "TEST SELLING ALERT", []Span{{"Plays the selling tone and a test pop-up.", th.Soft, false}})
	row++
	c.Text(ix, row, iw, "THEMES  THE APP'S COVER & HEADINGS.", th.Accent, true)
	row++
	for i := range themes {
		t := &themes[i]
		idx := i + settingsItems
		themeNo := i
		cur := idx == a.setCursor
		bg := a.selectRow(c, ix, row, rowW, cur, func() { a.activateSetting(idx) })
		mark := ' '
		if cur {
			mark = '>'
		}
		sel := ' '
		if a.cfg.Theme == themeNo {
			sel = '◆'
		}
		c.Set(ix+1, row, mark, th.Hot, bg, true)
		c.Set(ix+3, row, sel, th.Accent, bg, true)
		c.Text(ix+5, row, 20, t.Name, th.Text, a.cfg.Theme == themeNo)
		for k, col := range []RGB{t.BG, t.Panel, t.Line, t.Accent, t.Hot} {
			c.Set(ix+27+k*2, row, '█', col, bg, false)
			c.Set(ix+28+k*2, row, '█', col, bg, false)
		}
		row++
	}
	row++
	info := func(k, v string, col RGB) {
		if row >= iy+ih {
			return
		}
		c.Text(ix, row, 16, k, th.Soft, false)
		c.Text(ix+16, row, iw-16, fit(v, iw-16), col, false)
		row++
	}
	info("RELAY", a.relay.Base, th.Text)
	info("VERSION", appVersion+" (Windows build "+hudBuild+")", th.Hot)
	info("REQUESTS TODAY", commaInt(a.reqToday())+" of 100,000 on the free tier.", th.Text)
	info("", "The count resets at 05:00 PKT.", th.Text)
	info("SCANNING", "Every second from 08:55 until the post-market closes.", th.Text)
	info("", "That is 15:49 Monday to Thursday and 16:49 on Friday.", th.Text)
	info("SETTINGS FILE", settingsPath(), th.Soft)
}
