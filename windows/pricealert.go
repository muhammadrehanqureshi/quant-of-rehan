package main

import (
	"fmt"
	"strconv"
	"strings"
	"time"
)

// Owner order 2026-11-13: PRICE ALERT. The ALERTS page carries three slots, each
// a KMIALL scrip and the price the owner wants to be told about. The HUD checks
// them on every broker answer; when one is reached it puts the banner on the top
// line, sends the Windows toast, writes the hit into the ALERTS LOG and plays
// its own four note chime through the Windows Beep call, the same call
// PowerShell's [console]::beep makes. Three is all the owner asked for.
const priceAlertSlots = 3

// PriceAlert is one slot. Rises says which side the price has to come from: it
// is measured against the price when the alert was set, so a target below the
// market rings on the way down and one above rings on the way up.
type PriceAlert struct {
	Symbol string  `json:"symbol"`
	Target float64 `json:"target"`
	Rises  bool    `json:"rises"`
	Wait   bool    `json:"wait_price"` // no live price when set: the first one picks the side
	Fired  bool    `json:"fired"`
	Hit    float64 `json:"hit_price"`
	HitAt  string  `json:"hit_at"`
}

// Set is true when the slot holds a scrip and a usable price.
func (p PriceAlert) Set() bool { return p.Symbol != "" && p.Target > 0 }

// TargetText is the target the way every price in the build is written.
func (p PriceAlert) TargetText() string { return commaFloat(p.Target, 2) }

// alertCrossed is the whole trigger rule: the target is reached from the side
// the price was on when the alert was set.
func alertCrossed(p PriceAlert, price float64) bool {
	if !p.Set() || p.Fired || price <= 0 {
		return false
	}
	if p.Rises {
		return price >= p.Target
	}
	return price <= p.Target
}

// parsePriceField reads a typed price. Anything that is not a plain number
// above zero is refused, so a typo never becomes a live alert.
func parsePriceField(s string) (float64, bool) {
	v, err := strconv.ParseFloat(strings.TrimSpace(s), 64)
	if err != nil || v <= 0 || v > 1_000_000 {
		return 0, false
	}
	return v, true
}

// priceOf is the last price the HUD knows for a scrip: the live broker feed
// first, then the relay's own table.
func (a *App) priceOf(sym string) (float64, bool) {
	if q, ok := a.liveQuote(sym); ok {
		return q.Price, true
	}
	if q, ok := a.prices[sym]; ok && q.Price > 0 {
		return q.Price, true
	}
	return 0, false
}

// knownSymbol keeps a typo out of the slots. Before the KMIALL table arrives
// every symbol is let through, the same rule the flow detector uses.
func (a *App) knownSymbol(sym string) bool {
	if sym == "" {
		return false
	}
	if a.inUniverse(sym) {
		return true
	}
	for _, s := range a.symbols {
		if s == sym {
			return true
		}
	}
	return false
}

// startPriceEdit puts the keys in slot's editor.
func (a *App) startPriceEdit(slot int) {
	if a.priceEdit >= 0 {
		return
	}
	slot = min(max(0, slot), priceAlertSlots-1)
	a.priceCursor, a.priceEdit, a.priceField = slot, slot, 0
	a.priceSym = a.cfg.PriceAlerts[slot].Symbol
	a.priceBuf, a.priceMsg = a.priceSym, ""
	a.calcOpen = false
	a.alertFocus = 3
}

// keyPriceEdit handles the editor: type the scrip, ENTER, type the price, ENTER.
func (a *App) keyPriceEdit(k Key) {
	switch k.Kind {
	case KEsc:
		a.priceEdit, a.priceMsg = -1, ""
	case KEnter, KTab, KDown, KUp:
		a.priceStep()
	case KBackspace:
		if r := []rune(a.priceBuf); len(r) > 0 {
			a.priceBuf = string(r[:len(r)-1])
			a.priceMsg = ""
		}
	case KDel:
		a.priceBuf, a.priceMsg = "", ""
	case KRune:
		a.priceType(k.R)
	}
}

func (a *App) priceType(r rune) {
	if r >= 'a' && r <= 'z' {
		r -= 'a' - 'A'
	}
	if a.priceField == 1 {
		if (r >= '0' && r <= '9') || r == '.' {
			if runeLen(a.priceBuf) < 12 {
				a.priceBuf += string(r)
				a.priceMsg = ""
			}
		}
		return
	}
	if (r >= 'A' && r <= 'Z') || (r >= '0' && r <= '9') || r == '.' || r == '-' || r == '_' {
		if runeLen(a.priceBuf) < 10 {
			a.priceBuf += string(r)
			a.priceMsg = ""
		}
	}
}

// priceStep moves from the scrip to the price, and from the price to the saved
// slot. Nothing is stored until the price is a real number.
func (a *App) priceStep() {
	if a.priceField == 0 {
		sym := strings.ToUpper(strings.TrimSpace(a.priceBuf))
		if !a.knownSymbol(sym) {
			a.priceMsg = "No KMIALL scrip is called that."
			return
		}
		a.priceSym, a.priceBuf, a.priceField = sym, "", 1
		if t := a.cfg.PriceAlerts[a.priceEdit].Target; t > 0 {
			a.priceBuf = strconv.FormatFloat(t, 'f', -1, 64)
		}
		a.priceMsg = ""
		return
	}
	v, ok := parsePriceField(a.priceBuf)
	if !ok {
		a.priceMsg = "Type a price above zero."
		return
	}
	a.setPriceAlert(a.priceEdit, a.priceSym, v)
	a.priceEdit, a.priceMsg = -1, ""
}

// setPriceAlert stores the slot and fixes the side the price has to come from.
func (a *App) setPriceAlert(slot int, sym string, target float64) {
	p := PriceAlert{Symbol: sym, Target: target}
	if px, ok := a.priceOf(sym); ok && px > 0 {
		p.Rises = target >= px
	} else {
		p.Rises, p.Wait = true, true
	}
	a.cfg.PriceAlerts[slot] = p
	a.alertsTouched, a.dirty = true, true
	a.priceCursor = min(slot+1, priceAlertSlots-1)
}

// clearPriceAlert empties one slot.
func (a *App) clearPriceAlert(slot int) {
	if slot < 0 || slot >= priceAlertSlots || !a.cfg.PriceAlerts[slot].Set() {
		return
	}
	a.cfg.PriceAlerts[slot] = PriceAlert{}
	a.alertsTouched, a.dirty = true, true
}

// checkPriceAlerts is called on every broker answer. A hit rings once: the slot
// keeps Fired until the owner sets it again, so a price that stays above the
// target never rings on every tick.
func (a *App) checkPriceAlerts() {
	for i := 0; i < priceAlertSlots; i++ {
		p := a.cfg.PriceAlerts[i]
		if !p.Set() || p.Fired {
			continue
		}
		q, ok := a.liveQuote(p.Symbol)
		if !ok {
			continue
		}
		if p.Wait {
			p.Rises, p.Wait = p.Target >= q.Price, false
			a.cfg.PriceAlerts[i] = p
			a.alertsTouched, a.dirty = true, true
			continue
		}
		if !alertCrossed(p, q.Price) {
			continue
		}
		p.Fired, p.Hit = true, q.Price
		p.HitAt = a.now.In(pkt).Format("15:04")
		a.cfg.PriceAlerts[i] = p
		a.alertsTouched, a.dirty = true, true
		a.raisePriceAlert(p)
	}
}

// raisePriceAlert announces a hit: the banner, its own tone, the toast and the
// ALERTS LOG entry.
func (a *App) raisePriceAlert(p PriceAlert) {
	side := "BUY"
	if !p.Rises {
		side = "SELL"
	}
	// Owner order 2026-11-25: the ALERTS LOG sentence reads "<scrip> hit its
	// price alert of PKR <price>", and the price it names is the print that
	// rang the alert, the number the row's own price column carries.
	body := fmt.Sprintf("%s hit its price alert of PKR %s.", p.Symbol, commaFloat(p.Hit, 2))
	a.bannerTitle, a.bannerBody = "PRICE ALERT: "+p.Symbol, body
	a.bannerUntil = a.now.Add(25 * time.Second)
	a.bannerKind = "price"
	a.bannerSell = !p.Rises
	a.tone(tonePrice)
	if a.cfg.Notify {
		sendToast("PRICE ALERT", body)
	}
	// Owner order 2026-11-20: the ALERTS LOG keeps the price and the percentage
	// of the moment the alert was raised, so the row is written once with the
	// move the market carried then.
	var pct *float64
	if q, ok := a.liveQuote(p.Symbol); ok && q.ChangePct != nil {
		pct = q.ChangePct
	}
	a.flow.addFlag(Flag{
		Time:      a.now,
		Symbol:    p.Symbol,
		Kind:      "price",
		Side:      side,
		Price:     p.Hit,
		ChangePct: pct,
		// Owner order 2026-11-25: the row is the one sentence. The detail
		// sentence is left empty because the ALERTS LOG joins it to the text,
		// which would print the same words twice; the banner and the toast
		// already take their own copy above.
		Text: fmt.Sprintf("%s hit its price alert of PKR %s", p.Symbol, commaFloat(p.Hit, 2)),
	})
}

// drawPriceTile is the PRICE ALERTS tile under the two boards.
func (a *App) drawPriceTile(c *Canvas, x, y, w, h int) {
	th := a.th
	// Owner order 2026-11-15: clicking the PRICE ALERTS tile no longer
	// highlights its frame; the click still moves the page's keyboard focus.
	ix, iy, iw, ih := a.panel(c, x, y, w, h, "PRICE ALERTS", "Press \"A\" to set alerts, \"del\" clears them")
	a.addHit(x, y, w, h, func() { a.alertFocus = 3 })
	for i := 0; i < priceAlertSlots && i < ih; i++ {
		p := a.cfg.PriceAlerts[i]
		ry := iy + i
		cur := a.alertFocus == 3 && a.priceCursor == i
		slot := i
		// Owner order 2026-11-25: the slots wear the BIG BUYING NOW tile's own
		// alternating shades, with the cursor row lifting over them.
		a.zebraBand(c, ix, ry, iw, 1, i)
		bg := a.selectRow(c, ix, ry, iw, cur, func() { a.alertFocus, a.priceCursor = 3, slot })
		mark := ' '
		if cur {
			mark = '◆'
		}
		// Owner order 2026-11-20 (latest): the slot number, the mark and the EMPTY
		// word stand on the same cells as the BIG BUYING NOW tile's number, mark
		// and symbol, so the tiles stacked above each other read as one column.
		c.Text(ix, ry, 4, fmt.Sprintf("%2d.", i+1), th.Soft, false)
		c.Set(ix+4, ry, mark, th.Accent, bg, true)
		if !p.Set() {
			c.Text(ix+6, ry, max(1, iw-6), fit("EMPTY", max(1, iw-6)), th.Soft, false)
			continue
		}
		c.Text(ix+6, ry, 9, p.Symbol, th.Hot, true)
		c.Text(ix+16, ry, 14, "PKR "+p.TargetText(), th.Text, true)
		// Owner order 2026-11-20: the RISES TO TARGET and FALLS TO TARGET words are
		// withdrawn. A slot that is armed says nothing; only a hit or a slot still
		// waiting for its first price writes on that column.
		state, ink := "", th.Soft
		switch {
		case p.Fired:
			state, ink = "HIT "+p.HitAt, th.Warn
		case p.Wait:
			state = "WAITING FOR A PRICE"
		}
		if state != "" && iw > 31 {
			c.Text(ix+31, ry, min(iw-31, 21), fit(state, min(iw-31, 21)), ink, p.Fired)
		}
		if px, ok := a.priceOf(p.Symbol); ok {
			txt := "NOW PKR " + commaFloat(px, 2)
			if n := runeLen(txt); iw-n-1 > 31+21 {
				c.Text(ix+iw-n-1, ry, n, txt, th.Soft, false)
			}
		}
	}
}

// priceMatches lists the KMIALL scrips that carry the letters typed in the
// scrip box, the way the SEARCH tile lists its own matches, so a scrip can be
// found from the middle of its name as well as its start.
func (a *App) priceMatches() []string {
	q := strings.ToUpper(strings.TrimSpace(a.priceBuf))
	if q == "" {
		return nil
	}
	var out []string
	for _, s := range a.symbols {
		if strings.Contains(s, q) {
			out = append(out, s)
		}
	}
	return out
}

// drawPriceEditor is the two field form that sets one slot: the scrip, then the
// price. It floats over the screen so it fits any window. Owner order
// 2026-11-20: both boxes say what to type, and the scrip box lists the scrips
// that carry the letters typed so far.
func (a *App) drawPriceEditor(c *Canvas) {
	if a.priceEdit < 0 {
		return
	}
	var matches []string
	if a.priceField == 0 {
		matches = a.priceMatches()
	}
	shown := min(len(matches), 8)
	w := min(54, a.w-4)
	h := 6 + shown
	if w < 24 || h > a.h-2 {
		return
	}
	x, y := (a.w-w)/2, (a.h-h)/2
	title := fmt.Sprintf("PRICE ALERT %d OF %d", a.priceEdit+1, priceAlertSlots)
	ix, iy, iw, ih := a.panel(c, x, y, w, h, title, "")
	sym, price := a.priceSym, a.storedTarget()
	if a.priceField == 0 {
		sym = a.priceBuf
	} else {
		price = a.priceBuf
	}
	a.inputRow(c, ix, iy, iw, "SCRIP", sym, "Enter scrip", a.priceField == 0, false)
	row := iy + 1
	for i := 0; i < shown; i++ {
		// The first match is the one ENTER takes when the whole name is typed.
		mark := "  "
		if i == 0 {
			mark = "◆ "
		}
		c.Text(ix+1, row, 3, mark, a.th.Accent, true)
		c.Text(ix+3, row, max(1, iw-4), fit(matches[i], max(1, iw-4)), a.th.Text, i == 0)
		row++
	}
	if more := len(matches) - shown; more > 0 && row < iy+ih-2 {
		c.Text(ix+3, row, max(1, iw-4), fmt.Sprintf("and %d more", more), a.th.Soft, false)
	}
	a.inputRow(c, ix, iy+ih-1, iw, "PRICE", price, "Enter price", a.priceField == 1, false)
}

// storedTarget is the slot's price as text, for the row that is not in hand.
func (a *App) storedTarget() string {
	if p := a.cfg.PriceAlerts[a.priceEdit]; p.Target > 0 {
		return strconv.FormatFloat(p.Target, 'f', -1, 64)
	}
	return ""
}
