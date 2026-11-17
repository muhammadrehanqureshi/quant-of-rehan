package main

import (
	"strconv"
	"strings"
)

// Owner order 2026-11-14: the calculator on the SCANNER page. It asks for the
// price and the quantity, and shows the money those shares need. C opens it
// and ESC leaves it.
func (a *App) openCalc() {
	a.pctOpen = false
	a.calcOpen, a.calcField = true, 0
	a.priceEdit, a.priceMsg = -1, ""
}

// openPct gives the keys to the PRICE DIFFERENCE tile beside the POSITION
// CALCULATOR. It is the same two box shape, so TAB or ENTER moves between the
// first and the second price.
func (a *App) openPct() {
	a.calcOpen = false
	a.pctOpen, a.pctField = true, 0
	a.priceEdit, a.priceMsg = -1, ""
}

// calcBuf is the field the keys are in.
func (a *App) calcBuf() *string {
	if a.calcField == 0 {
		return &a.calcPrice
	}
	return &a.calcQty
}

func (a *App) pctBuf() *string {
	if a.pctField == 0 {
		return &a.pctFirst
	}
	return &a.pctSecond
}

// keyPct handles the two price boxes of the difference tile.
func (a *App) keyPct(k Key) {
	if k.Kind == KRune && (k.R == 'c' || k.R == 'C') {
		a.openCalc()
		return
	}
	switch k.Kind {
	case KEsc:
		a.pctOpen = false
	case KEnter:
		if a.pctField == 0 {
			a.pctField = 1
		} else {
			a.pctOpen = false
		}
	case KTab, KDown, KUp:
		a.pctField = 1 - a.pctField
	case KBackspace:
		if r := []rune(*a.pctBuf()); len(r) > 0 {
			*a.pctBuf() = string(r[:len(r)-1])
		}
	case KDel:
		*a.pctBuf() = ""
	case KRune:
		r := k.R
		if (r >= '0' && r <= '9') || r == '.' {
			if b := a.pctBuf(); runeLen(*b) < 14 {
				*b += string(r)
			}
		}
	}
}

// keyCalc handles the two boxes: digits and one dot, TAB or ENTER to the next
// box, ESC closes.
func (a *App) keyCalc(k Key) {
	if k.Kind == KF6 || (k.Kind == KRune && (k.R == 'd' || k.R == 'D')) {
		a.openPct()
		return
	}
	switch k.Kind {
	case KEsc:
		a.calcOpen = false
	case KEnter:
		if a.calcField == 0 {
			a.calcField = 1
		} else {
			a.calcOpen = false
		}
	case KTab, KDown, KUp:
		a.calcField = 1 - a.calcField
	case KBackspace:
		if r := []rune(*a.calcBuf()); len(r) > 0 {
			*a.calcBuf() = string(r[:len(r)-1])
		}
	case KDel:
		*a.calcBuf() = ""
	case KRune:
		r := k.R
		if (r >= '0' && r <= '9') || r == '.' {
			if b := a.calcBuf(); runeLen(*b) < 14 {
				*b += string(r)
			}
		}
	}
}

// calcAmount is the one sum the calculator does, and the only place it can go
// wrong: either box missing or not a number above zero gives no total.
func calcAmount(priceText, qtyText string) (float64, bool) {
	p, err := strconv.ParseFloat(strings.TrimSpace(priceText), 64)
	if err != nil || p <= 0 {
		return 0, false
	}
	q, err := strconv.ParseFloat(strings.TrimSpace(qtyText), 64)
	if err != nil || q <= 0 {
		return 0, false
	}
	return p * q, true
}

// drawCalcPair puts the owner's two SCANNER tiles on one row: POSITION
// CALCULATOR on the left, PRICE DIFFERENCE on the right. The pair uses the
// same one cell gutter as every other gap on the SCANNER page. It always
// stands with its last values, whether or not it has the keys.
func (a *App) drawCalcPair(c *Canvas, x, y, w, h int) {
	if w < 48 {
		return
	}
	const gap = 1
	left := (w - gap) / 2
	a.drawCalculatorTile(c, x, y, left, h)
	a.drawPercentTile(c, x+left+gap, y, w-gap-left, h)
}

// drawPercentTile is the second of the two SCANNER tiles: two prices, and the
// percentage move from the first to the second. D gives it the keys, or a
// click on the tile does.
func (a *App) drawPercentTile(c *Canvas, x, y, w, h int) {
	th := a.th
	if w < 24 || h < 4 {
		return
	}
	hint := "Press \"D\" to calculate"
	if w < 56 {
		hint = "D"
	}
	if a.pctOpen {
		hint = "TAB next, ESC leaves"
		if w < 56 {
			hint = "TAB"
		}
	}
	ix, iy, iw, _ := a.panel(c, x, y, w, h, "PRICE DIFFERENCE", hint)
	a.addHit(x, y, w, h, func() { a.openPct() })
	// Owner order 2026-11-17: both fields read Enter price with one blank cell
	// before and after the words, and their labels are the full field names.
	firstLabel, secondLabel := "FIRST PRICE", "SECOND PRICE"
	bw := 13
	if firstLabelLen, secondLabelLen := runeLen(firstLabel), runeLen(secondLabel); firstLabelLen+secondLabelLen+3+2*bw > iw {
		// Keep both fields on the row on a narrower window, with short labels.
		firstLabel, secondLabel = "1", "2"
		bw = min(13, max(6, (iw-6)/2))
	}
	if bw < 6 {
		return
	}
	fx := ix + runeLen(firstLabel) + 1
	sx := fx + bw + 1 + runeLen(secondLabel) + 1
	if sx+bw > ix+iw {
		return
	}
	c.Text(ix, iy, runeLen(firstLabel), firstLabel, th.Soft, true)
	c.Text(fx+bw+1, iy, runeLen(secondLabel), secondLabel, th.Soft, true)
	a.drawInputBox(c, fx, iy, bw, a.pctFirst, "Enter price", a.pctOpen && a.pctField == 0)
	a.drawInputBox(c, sx, iy, bw, a.pctSecond, "Enter price", a.pctOpen && a.pctField == 1)
	label, col := "DIFF  --", th.Soft
	if pct, ok := pctChange(a.pctFirst, a.pctSecond); ok {
		label = "DIFF  " + signedPercent(pct)
		switch {
		case pct > 0:
			col = th.Good
		case pct < 0:
			col = th.Bad
		}
	}
	c.Text(ix, iy+1, iw, label, col, true)
}

// pctChange is the move from the first price to the second, in percent. Both
// prices must be numbers above zero; anything else gives no answer.
func pctChange(firstText, secondText string) (float64, bool) {
	first, err := strconv.ParseFloat(strings.TrimSpace(firstText), 64)
	if err != nil || first <= 0 {
		return 0, false
	}
	second, err := strconv.ParseFloat(strings.TrimSpace(secondText), 64)
	if err != nil || second <= 0 {
		return 0, false
	}
	return (second - first) / first * 100, true
}

func signedPercent(pct float64) string {
	s := strconv.FormatFloat(pct, 'f', 2, 64)
	if pct > 0 {
		s = "+" + s
	}
	return s + "%"
}

// drawInputBox draws one filled field without its own label, so the compact
// calculator pair can keep two boxes on one row.
func (a *App) drawInputBox(c *Canvas, bx, y, bw int, text, placeholder string, active bool) {
	th := a.th
	field := mix(th.Panel, th.Accent, 0.14)
	if active {
		field = mix(th.Panel, th.Accent, 0.3)
	}
	for k := 0; k < bw; k++ {
		c.Set(bx+k, y, ' ', th.Text, field, false)
	}
	if text == "" {
		c.Text(bx+1, y, bw-2, placeholder, mix(th.Soft, th.Panel, 0.25), false)
	} else {
		c.Text(bx+1, y, bw-2, fit(text, bw-2), th.Hot, true)
	}
	if active && text != "" && int(a.animSeconds()*2)%2 == 0 {
		c.Set(bx+1+min(runeLen(text), bw-3), y, '█', th.Accent, field, false)
	}
}

// drawCalculatorTile draws POSITION CALCULATOR in its half of the bottom row:
// the price and the quantity side by side, the total under them. At the full
// width it keeps the owner's six blank cells after the PRICE box; on the
// squeezed pair the same labels and equal boxes keep the one alignment.
func (a *App) drawCalculatorTile(c *Canvas, x, y, w, h int) {
	th := a.th
	if w < 24 || h < 4 {
		return
	}
	hint := "Press \"C\" to calculate"
	if w < 56 {
		hint = "C"
	}
	if a.calcOpen {
		hint = "TAB next, ESC leaves"
		if w < 56 {
			hint = "TAB"
		}
	}
	ix, iy, iw, _ := a.panel(c, x, y, w, h, "POSITION CALCULATOR", hint)
	a.addHit(x, y, w, h, func() { a.openCalc() })
	const (
		priceLabel = 5
		qtyLabel   = 8
		labelGap   = 1
	)
	body := iw - priceLabel - qtyLabel - 2*labelGap
	between := 1
	bw := (body - between) / 2
	if bw > 13 {
		bw = 13
		between = min(6, body-2*bw)
	}
	if bw < 6 || between < 1 {
		return
	}
	pBox := ix + priceLabel + labelGap
	qLabel := pBox + bw + between
	qBox := qLabel + qtyLabel + labelGap
	if qBox+bw > ix+iw {
		return
	}
	c.Text(ix, iy, priceLabel, "PRICE", th.Soft, true)
	c.Text(qLabel, iy, qtyLabel, "QUANTITY", th.Soft, true)
	a.drawInputBox(c, pBox, iy, bw, a.calcPrice, "Enter price", a.calcOpen && a.calcField == 0)
	a.drawInputBox(c, qBox, iy, bw, a.calcQty, "Enter qty", a.calcOpen && a.calcField == 1)
	total, ok := calcAmount(a.calcPrice, a.calcQty)
	c.Text(ix, iy+1, priceLabel+labelGap, "TOTAL", th.Soft, true)
	if ok {
		c.Text(pBox, iy+1, max(1, iw-(pBox-ix)), "PKR "+commaFloat(total, 2), th.Good, true)
	} else {
		// Owner order 2026-11-17: with nothing to calculate the dash stands in
		// front of PKR, in the same soft ink as the TOTAL label.
		c.Text(pBox, iy+1, 1, "-", th.Soft, true)
		c.Text(pBox+2, iy+1, max(1, iw-(pBox-ix)-2), "PKR", th.Good, true)
	}
}

// inputRow draws one labelled field of an overlay form: a filled box, the text
// in it and, while it has the keys, the blinking block at its end.
func (a *App) inputRow(c *Canvas, x, y, w int, label, text, placeholder string, active bool, fitWords bool) {
	a.inputRowSized(c, x, y, w, label, text, placeholder, active, fitWords, 0)
}

// inputRowSized is inputRow with an optional fixed box width. The calculator
// uses it so PRICE and QUANTITY have exactly the same box width while the
// other forms keep fitting their own words.
func (a *App) inputRowSized(c *Canvas, x, y, w int, label, text, placeholder string, active bool, fitWords bool, fixedW int) {
	th := a.th
	c.Text(x, y, 10, label, th.Soft, false)
	bx := x + 12
	bw := max(6, min(w-12, 28))
	if fixedW > 0 {
		bw = max(6, min(w-12, fixedW))
	} else if fitWords {
		// Owner order 2026-11-16: the calculator's boxes fit their words with
		// exactly one blank cell on either side.
		bw = max(6, min(w-12, runeLen(placeholder)+2))
	}
	field := mix(th.Panel, th.Accent, 0.14)
	if active {
		field = mix(th.Panel, th.Accent, 0.3)
	}
	for k := 0; k < bw; k++ {
		c.Set(bx+k, y, ' ', th.Text, field, false)
	}
	if text == "" {
		c.Text(bx+1, y, bw-2, placeholder, mix(th.Soft, th.Panel, 0.25), false)
	} else {
		c.Text(bx+1, y, bw-2, fit(text, bw-2), th.Hot, true)
	}
	// The cursor waits until something is typed, so it never covers the first
	// letter of the placeholder.
	if active && text != "" && int(a.animSeconds()*2)%2 == 0 {
		c.Set(bx+1+min(runeLen(text), bw-3), y, '█', th.Accent, field, false)
	}
}
