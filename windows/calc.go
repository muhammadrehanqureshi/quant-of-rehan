package main

import (
	"fmt"
	"strconv"
	"strings"
)

// Owner order 2026-11-13: the calculator on the SCANNER page. It asks for the
// price and the quantity, and shows the money those shares need. F6 opens and
// closes it, so the search box keeps every letter it had.
func (a *App) openCalc() {
	a.calcOpen, a.calcField = true, 0
	a.priceEdit, a.priceMsg = -1, ""
}

// calcBuf is the field the keys are in.
func (a *App) calcBuf() *string {
	if a.calcField == 0 {
		return &a.calcPrice
	}
	return &a.calcQty
}

// keyCalc handles the two boxes: digits and one dot, TAB or ENTER to the next
// box, ESC closes.
func (a *App) keyCalc(k Key) {
	switch k.Kind {
	case KEsc, KF6:
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

// drawCalculator is the form: the two boxes, the rule, the total.
func (a *App) drawCalculator(c *Canvas) {
	th := a.th
	w := min(52, a.w-4)
	h := 10
	if w < 24 || h > a.h-2 {
		return
	}
	x, y := (a.w-w)/2, (a.h-h)/2
	ix, iy, iw, _ := a.panel(c, x, y, w, h, "POSITION CALCULATOR", "F6 or ESC closes")
	a.inputRow(c, ix, iy, iw, "PRICE", a.calcPrice, a.calcField == 0)
	a.inputRow(c, ix, iy+2, iw, "QUANTITY", a.calcQty, a.calcField == 1)
	c.HLine(ix, iy+4, iw, '─', mix(th.Line, th.Panel, 0.3))
	total, ok := calcAmount(a.calcPrice, a.calcQty)
	c.Text(ix, iy+5, 12, "TOTAL", th.Soft, true)
	amount := "PKR -"
	if ok {
		amount = "PKR " + commaFloat(total, 2)
	}
	c.Text(ix+12, iy+5, max(1, iw-12), amount, th.Good, true)
	hint := "The total is the price times the quantity."
	if ok {
		if q, err := strconv.ParseFloat(strings.TrimSpace(a.calcQty), 64); err == nil {
			hint = fmt.Sprintf("%s shares at PKR %s", commaFloat(q, 0), commaFloat(total/q, 2))
		}
	}
	c.Text(ix, iy+7, iw, fit(hint, iw), th.Soft, false)
}

// inputRow draws one labelled field of an overlay form: a filled box, the text
// in it and, while it has the keys, the blinking block at its end.
func (a *App) inputRow(c *Canvas, x, y, w int, label, text string, active bool) {
	th := a.th
	c.Text(x, y, 10, label, th.Soft, false)
	bx := x + 12
	bw := max(6, min(w-12, 28))
	field := mix(th.Panel, th.Accent, 0.14)
	if active {
		field = mix(th.Panel, th.Accent, 0.3)
	}
	for k := 0; k < bw; k++ {
		c.Set(bx+k, y, ' ', th.Text, field, false)
	}
	if text == "" {
		c.Text(bx+1, y, bw-2, "type here", mix(th.Soft, th.Panel, 0.25), false)
	} else {
		c.Text(bx+1, y, bw-2, fit(text, bw-2), th.Hot, true)
	}
	if active && int(a.animSeconds()*2)%2 == 0 {
		c.Set(bx+1+min(runeLen(text), bw-3), y, '█', th.Accent, field, false)
	}
}
