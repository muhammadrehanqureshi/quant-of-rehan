package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-27 (build 187): on TELEMETRY's FLOW row only the three
// values keep a colour, green for B, red for S and yellow for U. The letters,
// both equals signs, the ampersand and the commas wear FLOW's own soft ink.
func TestBuild187TelemetryFlowColoursOnlyTheValues(t *testing.T) {
	a := demoApp(t, 140, 40)
	buy, sell, un, vol := int64(600), int64(300), int64(100), int64(1000)
	a.flow = nil
	a.of = &OrderFlow{Rows: []FlowRow{{
		Symbol: "AAA", Buy: &buy, Sell: &sell, Unclassified: &un, Volume: &vol,
		Method: methodMeasured,
	}}}
	c := NewCanvas(70, 40, a.th.Panel)
	a.drawLeft(c, 0, 0, 70, 40)
	rows := c.PlainRows()
	y, _ := findCells(c, "FLOW")
	if y < 0 {
		t.Fatalf("the TELEMETRY tile has no FLOW row:\n%s", strings.Join(rows, "\n"))
	}
	line := rows[y]
	soft := a.th.Soft
	check := func(what string, x int, want RGB) {
		t.Helper()
		if x < 0 {
			t.Fatalf("the FLOW row has no %s: %q", what, line)
		}
		if got := c.Cells[y*c.W+x].FG; got != want {
			t.Errorf("%s on the FLOW row wears %v, want %v: %q", what, got, want, line)
		}
	}
	// The three letters and their equals signs wear the label's own ink.
	for _, k := range []string{"B=", "S="} {
		x := runeAt(line, k)
		check(k[:1], x, soft)
		check(k, x+1, soft)
	}
	ux := runeAt(line, "& U=")
	check("&", ux, soft)
	check("U", ux+2, soft)
	check("U's equals", ux+3, soft)
	// Only the figures carry the inks.
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
			check(fig.text, x+k, fig.ink)
		}
	}
	// The commas stand in the same soft ink as the letters.
	for _, v := range []string{"600,", "300,"} {
		x := runeAt(line, v)
		check("the comma after a figure", x+len(v)-1, soft)
	}
}

// Owner order 2026-11-27 (build 187): the WATCH LIST writes the average change
// of its scrips under the last of them, the arrow and the figure in the
// direction's own green or red and the sentence soft. Owner order 2026-11-28
// (build 188) moved that line two rows up and took the quotes off the figure.
func TestBuild187WatchAverageStandsUnderTheList(t *testing.T) {
	a := demoApp(t, 210, 44)
	a.cfg.Watch = []string{"AAA", "BBB", "CCC"}
	p2, p4, p6 := 2.0, 4.0, 6.0
	v := int64(10)
	row := func(sym string, pct *float64) FlowRow {
		return FlowRow{Symbol: sym, Price: 10, ChangePct: pct, Buy: &v, Sell: &v,
			Unclassified: &v, Volume: &v, Method: methodMeasured}
	}
	a.of = &OrderFlow{Rows: []FlowRow{row("AAA", &p2), row("BBB", &p4), row("CCC", &p6)}}
	a.screen = scrWatch
	sorted := a.watchSorted()
	lastSym := sorted[len(sorted)-1].Symbol
	c := a.render()
	rows := c.PlainRows()
	last, avg := -1, -1
	for i, r := range rows {
		if strings.Contains(r, lastSym) {
			last = i
		}
		if strings.Contains(r, "The average change of the above scrips is") {
			avg = i
		}
	}
	if last < 0 || avg < 0 {
		t.Fatalf("the page has no average under %s:\n%s", lastSym, strings.Join(rows, "\n"))
	}
	if avg != last+3 {
		t.Fatalf("the average stands on row %d, %d rows under %s on row %d; want two blank rows between",
			avg, avg-last, lastSym, last)
	}
	if want := "▲ 4.00%"; !strings.Contains(rows[avg], want) {
		t.Fatalf("the average does not read %q: %q", want, rows[avg])
	}
	if got := c.Cells[avg*c.W+runeAt(rows[avg], "The average")].FG; got != a.th.Soft {
		t.Errorf("the sentence wears %v, want the page's soft ink %v", got, a.th.Soft)
	}
	for _, part := range []string{"▲", "4.00%"} {
		if got := c.Cells[avg*c.W+runeAt(rows[avg], part)].FG; got != a.th.Good {
			t.Errorf("%q wears %v, want the rise's green %v", part, got, a.th.Good)
		}
	}
}

// Owner order 2026-11-27 (build 187): the average is taken over the scrips the
// relay has a percentage for, and the page writes it only for a list of two
// scrips or more.
func TestBuild187WatchAverageNeedsTwoScrips(t *testing.T) {
	p5 := 5.0
	p2, p4 := 2.0, 4.0
	rows := []FlowRow{{Symbol: "AAA", ChangePct: &p2}, {Symbol: "BBB"}, {Symbol: "CCC", ChangePct: &p4}}
	if avg, ok := watchAverage(rows); !ok || avg != 3 {
		t.Fatalf("the average is %v, %v; want 3 over the two scrips that have a change", avg, ok)
	}
	if _, ok := watchAverage([]FlowRow{{Symbol: "AAA"}}); ok {
		t.Fatal("a list with no change still answers an average")
	}
	a := demoApp(t, 158, 41)
	a.cfg.Watch = []string{"AAA"}
	a.of = &OrderFlow{Rows: []FlowRow{{Symbol: "AAA", ChangePct: &p5}}}
	a.screen = scrWatch
	if s := plain(a); strings.Contains(s, "The average change") {
		t.Fatalf("a list of one scrip still writes the average:\n%s", s)
	}
}

// Owner order 2026-11-27 (build 187): a row with no figure shows one dash in
// NET DELTA and one in NET DELTA %, not two in one and none in the other.
func TestBuild187WatchKeepsOneDashInBothNetDeltaColumns(t *testing.T) {
	a := demoApp(t, 210, 44)
	a.cfg.Watch = []string{"AAA"}
	a.of = nil
	a.screen = scrWatch
	c := a.render()
	rows := c.PlainRows()
	// The offsets are read off the table's own heading row, because the ORDER
	// line of chips above it carries a NET DELTA chip of its own.
	hy, _ := findCells(c, "SCRIP")
	ry, _ := findCells(c, "AAA")
	if hy < 0 || ry <= hy {
		t.Fatalf("the page is missing the table heading or the scrip: heading %d, row %d\n%s",
			hy, ry, strings.Join(rows, "\n"))
	}
	hx := runeAt(rows[hy], "NET DELTA")
	px := runeAt(rows[hy], "NET DELTA %")
	if hx < 0 || px < 0 {
		t.Fatalf("the heading carries no NET DELTA columns: %q", rows[hy])
	}
	if strings.Contains(rows[ry], "--") {
		t.Fatalf("the row still writes two dashes together: %q", rows[ry])
	}
	r := []rune(rows[ry])
	one := func(at int) bool {
		if at < 0 || at >= len(r) || r[at] != '-' {
			return false
		}
		return at+1 >= len(r) || r[at+1] != '-'
	}
	if !one(hx) {
		t.Fatalf("NET DELTA carries no single dash in its column %d: %q", hx, rows[ry])
	}
	if !one(px) {
		t.Fatalf("NET DELTA %% carries no single dash in its column %d: %q", px, rows[ry])
	}
}
