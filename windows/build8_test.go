package main

import (
	"os"
	"strings"
	"testing"
)

// readWindowSource reads one of the HUD's own source files, so a test can pin
// the one place a law is applied instead of a copy of it.
func readWindowSource(t *testing.T, name string) string {
	t.Helper()
	b, err := os.ReadFile(name)
	if err != nil {
		t.Fatalf("read %s: %v", name, err)
	}
	return string(b)
}

// Owner order 2026-11-11: the green and red bars keep their length and height
// and carry ten boxes instead of sixteen, each box growing to fill the same
// span. The status note is awake from the 08:55 scan start.

func TestShareBarHoldsTenBoxesOverTheSameCells(t *testing.T) {
	if shareBarBoxes != 10 {
		t.Fatalf("the bar holds %d boxes, want ten", shareBarBoxes)
	}
	if shareBarSpan != 16 {
		t.Fatalf("the bar is %d cells, want its 16 cells untouched", shareBarSpan)
	}
	widths := shareBarBoxWidths(shareBarSpan)
	if len(widths) != 10 {
		t.Fatalf("the bar drew %d boxes", len(widths))
	}
	sum := 0
	for _, w := range widths {
		if w < 1 {
			t.Fatalf("a box is %d cells long: %v", w, widths)
		}
		sum += w
	}
	if sum != shareBarSpan {
		t.Fatalf("the ten boxes cover %d cells of the bar's %d: %v",
			sum, shareBarSpan, widths)
	}
	if widths[0] != 2 || widths[len(widths)-1] != 1 {
		t.Fatalf("the remainder is not on the leading boxes: %v", widths)
	}
	for _, span := range []int{10, 8, 21} {
		w := shareBarBoxWidths(span)
		n := 0
		for _, v := range w {
			n += v
		}
		if n != span {
			t.Fatalf("span %d: the boxes cover %d cells", span, n)
		}
	}
}

func TestShareBarStillDrawsItsSixteenCells(t *testing.T) {
	a := demoApp(t, 100, 30)
	c := NewCanvas(40, 1, RGB{})
	a.shareBar(c, 2, 0, shareBarWidth, 0.5)
	row := c.PlainRows()[0]
	if n := strings.Count(row, string(barBlock)); n != shareBarSpan {
		t.Fatalf("the bar draws %d cells of its %d, so its length moved: %q",
			n, shareBarSpan, row)
	}
}

func TestStatusIsAwakeFromTheScanStart(t *testing.T) {
	source := readWindowSource(t, "app.go")
	if !strings.Contains(source, "Market is closed but the quant is online now.") {
		t.Fatal("the status note has no sentence for the 08:55 gap")
	}
	if !strings.Contains(source, "sec >= scanOpen*60") {
		t.Fatal("the sentence is not bounded by the scan start")
	}
	if !strings.Contains(source, "preOpen = 9 * 60") {
		t.Fatal("the Friday pre-open boundary is not 09:00")
	}
}
