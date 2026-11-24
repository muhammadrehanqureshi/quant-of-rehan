package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-23: the KSE100 leaders read as one table. LOADS's shorter
// S used to pull its U= and its & T= off the cells TREET and ENGROH used, so each
// leader now writes on the columns the widest one sets.
func TestTheLeadersHoldOneUTColumn(t *testing.T) {
	a := demoApp(t, 120, 30)
	b1, s1, t1 := int64(2786986), int64(2750043), int64(5537029)
	b2, s2, t2 := int64(1399572), int64(963526), int64(2363098)
	b3, s3, t3 := int64(3054665), int64(1539025), int64(4593690)
	leaders := []Leader{
		{Buy: &b1, Sell: &s1, Volume: &t1},
		{Buy: &b2, Sell: &s2, Volume: &t2},
		{Buy: &b3, Sell: &s3, Volume: &t3},
	}
	cols := bstLeaderCols(leaders)
	c := NewCanvas(70, 3, a.th.Panel)
	for i, l := range leaders {
		a.putBSTPacked(c, 3, i, l.Buy, l.Sell, l.Volume, cols)
	}
	rows := c.PlainRows()
	at := func(i int, s string) int { return strings.Index(rows[i], s) }
	for i := 1; i < len(rows); i++ {
		for _, label := range []string{"B=", "S=", "U=", "&", "T="} {
			if at(i, label) != at(0, label) {
				t.Fatalf("row %d puts %s on cell %d, the first row puts it on %d:\n%s",
					i+1, label, at(i, label), at(0, label), strings.Join(rows, "\n"))
			}
		}
	}
	// Every row still carries its own punctuation and its whole figures.
	for i := range rows {
		for _, want := range []string{"B=", ",", "S=", ",", "U=", "&", "T="} {
			if !strings.Contains(rows[i], want) {
				t.Fatalf("row %d lost %q: %q", i+1, want, rows[i])
			}
		}
	}
}

// Owner order 2026-11-23: the gate is one of the build's own tiles, drawn by
// the same panel frame as QUANT CORE and KSE100, not a bare box of its own.
func TestTheGateIsOneOfTheBuildsOwnTiles(t *testing.T) {
	a := lockedApp(t, 100, 30)
	rows := screenOf(a)
	var frame string
	for _, row := range strings.Split(rows, "\n") {
		if strings.Contains(row, "◆") {
			frame = row
		}
	}
	// Owner order 2026-11-24: the gate's tile is headed SIGN IN.
	if frame == "" || !strings.Contains(frame, "SIGN IN") {
		t.Fatalf("the gate has no diamond title on its frame:\n%s", rows)
	}
	if !strings.Contains(frame, "┏") || !strings.Contains(frame, "┓") || !strings.Contains(frame, "━") {
		t.Fatalf("the gate's frame is not the HUD's frame: %q", frame)
	}
	if !strings.Contains(rows, "PASSWORD") {
		t.Fatalf("the field carries no label:\n%s", rows)
	}
}

// Owner order 2026-11-23: a click takes the box, the placeholder goes, and the
// block cursor blinks on the frame clock the rest of the build uses.
func TestAClickGivesTheBoxTheBlinkingCursor(t *testing.T) {
	a := lockedApp(t, 100, 30)
	a.animT = 0 // the block is in its lit half
	if rows := screenOf(a); !strings.Contains(rows, wantUnlockPlaceholder) {
		t.Fatalf("the box does not offer the placeholder:\n%s", rows)
	}
	if strings.Contains(screenOf(a), "█") {
		t.Fatal("the block stands beside the placeholder before the box is taken")
	}
	a.onKey(Key{Kind: KMouse, Btn: MouseLeft, X: a.passX + 2, Y: a.passY})
	rows := screenOf(a)
	if strings.Contains(rows, wantUnlockPlaceholder) {
		t.Fatalf("the click did not clear the placeholder:\n%s", rows)
	}
	if !strings.Contains(rows, "█") {
		t.Fatalf("the box has no cursor after the click:\n%s", rows)
	}
	a.animT = 0.6 // the dark half, half a second later
	if strings.Contains(screenOf(a), "█") {
		t.Fatal("the cursor did not blink off")
	}
	a.animT = 1.0
	if !strings.Contains(screenOf(a), "█") {
		t.Fatal("the cursor did not blink back")
	}
	a.onKey(Key{Kind: KRune, R: '7'})
	rows = screenOf(a)
	if strings.Contains(rows, wantUnlockPlaceholder) || !strings.Contains(rows, "█") {
		t.Fatalf("the cursor or the placeholder changed on the first digit:\n%s", rows)
	}
}

// A click outside the box leaves it alone, so the placeholder stays.
func TestAClickBesideTheBoxLeavesThePlaceholder(t *testing.T) {
	a := lockedApp(t, 100, 30)
	a.animT = 0
	screenOf(a) // lays the box out and keeps its cells
	a.onKey(Key{Kind: KMouse, Btn: MouseLeft, X: a.passX + 2, Y: a.passY + 4})
	if rows := screenOf(a); !strings.Contains(rows, wantUnlockPlaceholder) {
		t.Fatalf("a click away from the box took it anyway:\n%s", rows)
	}
}
