package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-28 (build 191): "on the TELEMETRY tile, make the values of
// B, S and U bold that are in front of FLOW". Each figure keeps its own colour
// and is bold like the letters before it.
func TestBuild191TelemetryFlowValuesAreBold(t *testing.T) {
	a := demoApp(t, 140, 40)
	buy, sell, un, vol := int64(600), int64(300), int64(100), int64(1000)
	a.flow = nil
	a.of = &OrderFlow{Rows: []FlowRow{{
		Symbol: "AAA", Buy: &buy, Sell: &sell, Unclassified: &un, Volume: &vol,
		Method: methodMeasured,
	}}}
	c := NewCanvas(70, 40, a.th.Panel)
	a.drawLeft(c, 0, 0, 70, 40)
	y, _ := findCells(c, "FLOW")
	if y < 0 {
		t.Fatalf("the TELEMETRY tile has no FLOW row:\n%s", strings.Join(c.PlainRows(), "\n"))
	}
	line := c.PlainRows()[y]
	for _, fig := range []struct {
		text string
		ink  RGB
	}{
		{"600", a.th.Good},
		{"300", a.th.Bad},
		{"100", a.th.Warn},
	} {
		x := runeAt(line, fig.text)
		if x < 0 {
			t.Fatalf("the FLOW row does not carry %q: %q", fig.text, line)
		}
		for k := 0; k < len(fig.text); k++ {
			cell := c.Cells[y*c.W+x+k]
			if cell.Ch != rune(fig.text[k]) {
				t.Fatalf("the FLOW row holds %q where %q belongs: %q", cell.Ch, fig.text[k], line)
			}
			if !cell.Bold {
				t.Fatalf("%q on the FLOW row is not bold: %q", fig.text, line)
			}
			if cell.FG != fig.ink {
				t.Fatalf("%q on the FLOW row wears %v, want %v: %q", fig.text, cell.FG, fig.ink, line)
			}
		}
	}
	// The letters, the equals signs and the commas were bold on build 187 and
	// keep that weight, so the row reads as one bold line of three figures.
	for _, k := range []string{"B=", "S=", "  & U="} {
		x := runeAt(line, k)
		if !c.Cells[y*c.W+x].Bold {
			t.Fatalf("%q on the FLOW row lost the weight build 187 gave it: %q", k, line)
		}
	}
	// The figures keep the soft ink of the punctuation; only their weight moved.
	if x := runeAt(line, "600,"); x >= 0 {
		if c.Cells[y*c.W+x+3].FG != a.th.Soft {
			t.Fatalf("the comma after a figure lost FLOW's soft ink: %q", line)
		}
	}
}

// Owner order 2026-11-28 (build 191): "also make the value of U bold on KSE100
// tile". U's figure is bold in all three forms the tile writes its leaders in,
// whether or not it has a volume to show: his screenshot carried U=0.
func TestBuild191Kse100LeadersMakeUBold(t *testing.T) {
	a := demoApp(t, 120, 40)
	buy, sell, total := int64(500000), int64(500000), int64(1000000)
	cols := bstLeaderCols([]Leader{{Buy: &buy, Sell: &sell, Volume: &total}})
	forms := []struct {
		name string
		draw func(c *Canvas)
	}{
		{"wide", func(c *Canvas) { a.putBSTWide(c, 0, 0, &buy, &sell, &total) }},
		{"packed", func(c *Canvas) { a.putBSTPacked(c, 0, 0, &buy, &sell, &total, cols) }},
		{"bare", func(c *Canvas) { a.putBSTBare(c, 0, 0, &buy, &sell, &total) }},
	}
	for _, f := range forms {
		t.Run(f.name, func(t *testing.T) {
			c := NewCanvas(70, 1, a.th.Panel)
			f.draw(c)
			line := c.PlainRows()[0]
			x := runeAt(line, "U=")
			if x < 0 {
				t.Fatalf("the %s form carries no U: %q", f.name, line)
			}
			if c.Cells[x].Bold || c.Cells[x+1].Bold {
				t.Fatalf("the U label is bold in the %s form: %q", f.name, line)
			}
			fig := c.Cells[x+2]
			if fig.Ch != '0' {
				t.Fatalf("the %s form holds %q where U's 0 belongs: %q", f.name, fig.Ch, line)
			}
			if !fig.Bold {
				t.Fatalf("U's figure is not bold in the %s form: %q", f.name, line)
			}
			if fig.FG != a.th.Warn {
				t.Fatalf("U's figure wears %v in the %s form, want %v: %q", fig.FG, f.name, a.th.Warn, line)
			}
		})
	}
}

// Owner order 2026-11-28 (build 191): "Make the T value bold that is written
// after MEASURED on the top of ORDER FLOW page". B's and S's figures on that
// line were already bold; T's now is too, and its label keeps the soft ink.
func TestBuild191OrderFlowMeasuredTotalIsBold(t *testing.T) {
	a := orderFlowApp(t, 160, 45, sampleOrderFlow)
	c := a.render()
	y, x := findCells(c, "MEASURED")
	if y < 0 {
		t.Fatalf("ORDER FLOW carries no MEASURED line:\n%s", strings.Join(c.PlainRows(), "\n"))
	}
	line := []rune(c.PlainRows()[y])
	at := -1
	for k := x; k+2 <= len(line); k++ {
		if string(line[k:k+2]) == "T=" {
			at = k
			break
		}
	}
	if at < 0 {
		t.Fatalf("the MEASURED line carries no T: %q", string(line))
	}
	cell := func(i int) Cell { return c.Cells[y*c.W+i] }
	if cell(at).Bold || cell(at+1).Bold {
		t.Fatalf("the T label on the MEASURED line is bold: %q", string(line))
	}
	digits := 0
	for k := at + 2; k < len(line) && line[k] != ' '; k++ {
		if line[k] >= '0' && line[k] <= '9' {
			digits++
			if !cell(k).Bold {
				t.Fatalf("T's figure is not bold: %q", string(line))
			}
			if cell(k).FG != totalBlue {
				t.Fatalf("T's figure wears %v, want %v: %q", cell(k).FG, totalBlue, string(line))
			}
		}
	}
	if digits == 0 {
		t.Fatalf("the MEASURED line carries no T figure: %q", string(line))
	}
}

// Owner order 2026-11-28 (build 191): "the build's screen is not on the exact
// center on the console, make it on the absolute center." The window's text
// area, the part that carries the build, is what is put in the middle; the
// frame follows it by its own inset, so the title bar and the borders no longer
// pull the build up and to the left.
func TestBuild191ConsoleCentresItsTextArea(t *testing.T) {
	work := consoleRect{left: 0, top: 0, right: 1000, bottom: 600}
	frame := consoleRect{left: 0, top: 0, right: 100, bottom: 60}
	client := consoleRect{left: 30, top: 25, right: 100, bottom: 60}
	x, y := consoleClientCentre(work, frame, client, true)
	if x != 435 || y != 257 {
		t.Fatalf("the frame lands on %d,%d, want 435,257 for its 70 by 35 text area", x, y)
	}
	// The frame's own middle is still the answer when there is no text area to
	// measure, so a window that will not answer stays centred as build 189 left
	// it rather than jumping.
	if x, y := consoleClientCentre(work, frame, consoleRect{}, false); x != 450 || y != 270 {
		t.Fatalf("a window with no text area lands on %d,%d, want 450,270", x, y)
	}
	if x, y := consoleClientCentre(work, frame, consoleRect{}, true); x != 450 || y != 270 {
		t.Fatalf("an empty text area lands on %d,%d, want 450,270", x, y)
	}
	// A window whose frame is its text area, as a borderless console is, is
	// centred exactly as before.
	same := consoleRect{left: 0, top: 0, right: 100, bottom: 60}
	if x, y := consoleClientCentre(work, same, same, true); x != 450 || y != 270 {
		t.Fatalf("a borderless console lands on %d,%d, want 450,270", x, y)
	}
}
