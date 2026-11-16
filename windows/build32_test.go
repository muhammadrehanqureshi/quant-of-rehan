package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-16: a shortened ORDER FLOW bar must put its NET DELTA on
// the same cell as the NET DELTA heading, never one or more cells to the right.
func TestCompressedBarEndsOnItsNetDeltaColumn(t *testing.T) {
	a := demoApp(t, 140, 34)
	for _, fieldW := range []int{shareBarWidth, 23, 21} {
		c := NewCanvas(40, 1, a.th.Panel)
		a.shareBar(c, 0, 0, fieldW, 60, 40)
		row := []rune(c.PlainRows()[0])
		span := fieldW - shareNetW - shareBarGap
		if span > shareBarSpan {
			span = shareBarSpan
		}
		netAt := -1
		for i := span + shareBarGap; i < len(row); i++ {
			if row[i] != ' ' {
				netAt = i
				break
			}
		}
		want := span + shareBarGap
		if netAt != want {
			t.Errorf("field %d: NET DELTA starts on cell %d, want %d: %q", fieldW, netAt, want, string(row))
		}
	}
}

// Owner order 2026-11-16: the SECTORS direction arrow keeps one fixed column,
// so a 10.00% row does not push its arrow one cell left of the others.
func TestSectorArrowsShareOneColumn(t *testing.T) {
	a := demoApp(t, 158, 41)
	a.screen = scrScanner
	inside, count, want := false, 0, -1
	for _, row := range rowsOf(a) {
		switch {
		case strings.Contains(row, "SECTORS"):
			inside = true
			continue
		case strings.Contains(row, "CUSTOM SCRIPS OF VOLUME"):
			inside = false
		}
		if !inside {
			continue
		}
		at := strings.IndexAny(row, "▲▼")
		if at < 0 || !strings.Contains(row, "%") {
			continue
		}
		if want < 0 {
			want = at
		} else if at != want {
			t.Errorf("a sector arrow starts on cell %d, want %d: %q", at, want, row)
		}
		count++
	}
	if count < 5 {
		t.Fatalf("only %d sector percentages were found", count)
	}
}

// Owner order 2026-11-16: both ALERTS boards are equal and fill the same right
// edge as PRICE ALERTS and ALERTS LOG.
func TestAlertBoardsFillThePageWidth(t *testing.T) {
	a := demoApp(t, 158, 41)
	a.screen = scrAlerts
	var boardRow, logRow string
	for _, row := range rowsOf(a) {
		if strings.Contains(row, "BIG BUYING NOW") && strings.Contains(row, "BIG SELLING NOW") {
			boardRow = row
		}
		if strings.Contains(row, "ALERTS LOG") {
			logRow = row
		}
	}
	if boardRow == "" || logRow == "" {
		t.Fatalf("missing board or log frame:\n%s", strings.Join(rowsOf(a), "\n"))
	}
	var opens, closes []int
	for i, r := range []rune(boardRow) {
		switch r {
		case '┏':
			opens = append(opens, i)
		case '┓':
			closes = append(closes, i)
		}
	}
	if len(opens) != 2 || len(closes) != 2 {
		t.Fatalf("cannot measure the two board frames: %q", boardRow)
	}
	buyW, sellW := closes[0]-opens[0], closes[1]-opens[1]
	if buyW != sellW {
		t.Errorf("the selling board spans %d cells, the buying board %d", sellW, buyW)
	}
	logClose := -1
	for i, r := range []rune(logRow) {
		if r == '┓' {
			logClose = i
		}
	}
	if logClose != closes[1] {
		t.Errorf("the boards end on cell %d, the ALERTS LOG on %d", closes[1], logClose)
	}
}
