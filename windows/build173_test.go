package main

import (
	"strings"
	"testing"
)

// figureCell is the cell the first digit of a drawn percentage stands on.
func figureCell(row string) int {
	for i, r := range []rune(row) {
		if r >= '0' && r <= '9' {
			return i
		}
	}
	return -1
}

// Owner order 2026-11-25 (build 173): every percentage starts its figure on the
// same cell, so a move of 10% and above stands on the column a 9% move stands
// on. The arrow holds its own cell and the figure follows it.
func TestBuild173ThePercentageFigureStartsOnOneCell(t *testing.T) {
	a := demoApp(t, 40, 4)
	c := NewCanvas(40, 4, a.th.Panel)
	for i, pct := range []float64{9.99, 10.53} {
		a.drawQuotePct(c, 2, i, pct)
	}
	rows := c.PlainRows()
	small, big := figureCell(rows[0]), figureCell(rows[1])
	if small < 0 || big < 0 {
		t.Fatalf("a percentage drew no figure: %q %q", rows[0], rows[1])
	}
	if small != big {
		t.Fatalf("9.99%% starts on cell %d and 10.53%% on cell %d: %q %q",
			small, big, rows[0], rows[1])
	}
	if !strings.ContainsRune(rows[1], '▲') {
		t.Fatalf("the percentage lost its direction arrow: %q", rows[1])
	}
}

// Owner order 2026-11-25 (build 173): on the boards the arrow and the figure
// stand on the cells a two digit move already stood on, so a one digit move no
// longer reads one cell to its right.
func TestBuild173BoardPercentagesStartOnOneCell(t *testing.T) {
	a := demoApp(t, 120, 20)
	for _, side := range []int{sideBuy, sideSell} {
		c := NewCanvas(79, 20, a.th.Panel)
		a.drawBoardPanel(c, 0, 0, 79, 20, side)
		figures := map[int]bool{}
		for _, row := range c.PlainRows()[1:] {
			if !strings.ContainsRune(row, '▲') && !strings.ContainsRune(row, '▼') {
				continue
			}
			at := strings.IndexFunc(row, func(r rune) bool { return r == '▲' || r == '▼' })
			figures[at] = true
		}
		if len(figures) > 1 {
			t.Fatalf("side %d: the board's arrows stand on %d cells, want one",
				side, len(figures))
		}
	}
}

// Owner order 2026-11-25 (build 173): the WATCH LIST page keeps one more cell
// between its CHANGE column and HIGH, so a change of 10% and above reads apart
// from the high that follows it.
func TestBuild173WatchListKeepsASpaceBeforeHigh(t *testing.T) {
	ten := 10.53
	rows := []FlowRow{{Symbol: "OGDC", ChangePct: &ten}}
	cols, barX := watchColumns(rows)
	chg, high := cols[1], cols[2]
	if chg.w != runeLen(changeText(ten)) {
		t.Fatalf("the CHANGE column holds %d cells, want %d",
			chg.w, runeLen(changeText(ten)))
	}
	if gap := high.x - (chg.x + chg.w); gap != 2 {
		t.Fatalf("CHANGE and HIGH stand %d cells apart, want two", gap)
	}
	if want := high.x + high.w + 2; barX < want {
		t.Fatalf("the tail starts on cell %d, want %d or later", barX, want)
	}
}

// Owner order 2026-11-25 (build 173): the ALERTS LOG and the boards no longer
// right align the whole move, which is what pushed a two digit percentage one
// cell left of a one digit one.
func TestBuild173TheMoveIsNotRightAligned(t *testing.T) {
	for _, pct := range []float64{-12.34, -9.99, 0.5, 9.99, 10.53, 25.0} {
		txt := changeText(pct)
		if !strings.HasPrefix(txt, "▲ ") && !strings.HasPrefix(txt, "▼ ") {
			t.Fatalf("%.2f%% reads %q, want the arrow and one space first",
				pct, txt)
		}
	}
	if strings.HasPrefix(padLeft(changeText(9.99), 8), "  ") == false {
		t.Fatal("the padded form no longer differs from the plain one")
	}
}
