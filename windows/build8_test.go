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

// Owner order 2026-11-11 (third pass): the green and red bars keep their 16
// cells and height, with ten cells on a compact bar. Owner order 2026-11-13:
// the split follows those cells, not the ten boxes, so the bar carries the
// buyers' exact share. The status note is awake from the 08:55 scan start.

func TestShareBarHoldsTenBoxesOverTheSameCells(t *testing.T) {
	if shareBarBoxes != 10 {
		t.Fatalf("the compact bar holds %d boxes, want ten", shareBarBoxes)
	}
	if shareBarSpan != 16 {
		t.Fatalf("the bar is %d cells, want its 16 cells untouched", shareBarSpan)
	}
	for _, c := range []struct {
		buy, sell int64
		span, want int
	}{
		{5, 5, shareBarSpan, 8},
		{884017, 1376954, shareBarSpan, 6},
		{1376954, 884017, shareBarSpan, 10},
		{0, 100, shareBarSpan, 0},
		{100, 0, shareBarSpan, 16},
		{5, 5, 10, 5},
	} {
		if got := shareGreenCells(c.buy, c.sell, c.span); got != c.want {
			t.Fatalf("%d buys and %d sells on %d cells drew %d green, want %d",
				c.buy, c.sell, c.span, got, c.want)
		}
	}
}

func TestShareBarStillDrawsItsSixteenCells(t *testing.T) {
	a := demoApp(t, 100, 30)
	c := NewCanvas(40, 1, RGB{})
	a.shareBar(c, 2, 0, shareBarWidth, 5, 5)
	row := c.PlainRows()[0]
	if n := strings.Count(row, string(barBlock)); n != shareBarSpan {
		t.Fatalf("the bar draws %d cells of its %d, so its length moved: %q",
			n, shareBarSpan, row)
	}
}

// Owner order 2026-11-11: one measured pair for every scrip, the same one the
// Android app reads from the relay. No Windows display may derive a split from
// the day's price range again.
func TestNoWindowsDisplayUsesTheRangeEstimate(t *testing.T) {
	for _, name := range []string{"screens_lists.go", "app.go", "screens.go", "screens_orderflow.go"} {
		if strings.Contains(readWindowSource(t, name), "RangeSplit(") {
			t.Errorf("%s splits volume from the day range; the relay's measured pair is the only source", name)
		}
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
