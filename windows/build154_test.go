package main

import (
	"fmt"
	"strings"
	"testing"
)

// Owner order 2026-11-21: NAVY BLUE & WHITE is deleted from the Windows palette,
// so the console shows the same three themes the phone already shows.
func TestBuild154NavyThemeIsGone(t *testing.T) {
	if len(themes) != 3 {
		t.Fatalf("the palette carries %d themes, want 3", len(themes))
	}
	for i, th := range themes {
		if strings.Contains(strings.ToUpper(th.Name), "NAVY") {
			t.Errorf("theme %d is still %q", i, th.Name)
		}
	}
	a := demoApp(t, 122, 36)
	a.screen = scrSettings
	if s := plain(a); strings.Contains(s, "NAVY BLUE & WHITE") {
		t.Errorf("SETTINGS still lists the deleted theme:\n%s", s)
	}
	// A saved navy choice (theme index 3) clamps to the first theme the way any
	// out of range theme does, so the app still opens on a real palette.
	p := t.TempDir() + "/settings.json"
	if err := saveSettings(p, Settings{Ver: settingsVer, Theme: 3, PollMS: 1000}); err != nil {
		t.Fatal(err)
	}
	if got := loadSettings(p); got.Theme != 0 {
		t.Errorf("a stored theme 3 reads %d, want the first theme 0", got.Theme)
	}
}

// flowSample154 is a twelve stock answer with a frame the relay has not
// refreshed, so ORDER FLOW's numbering and its STALE words can be read.
func flowSample154() string {
	var rows []string
	for i := 0; i < 12; i++ {
		fresh := "true"
		if i == 0 {
			fresh = "false"
		}
		rows = append(rows, fmt.Sprintf(`{"symbol":"S%02d","price":10.5,"high":10.5,"low":10.5,"bid":10.5,"ask":10.5,"change_pct":1.2,"volume":1000,"buy_volume":600,"sell_volume":300,"classified_volume":900,"unclassified_volume":100,"split_method":"quote_rule","fresh":%s}`, i, fresh))
	}
	return `{"ok":true,"day":"2026-11-20","as_of":"2026-11-20T10:15:04.000Z",` +
		`"counts":{"universe":12,"included":12,"missing":0,"fresh":11},"rows":[` + strings.Join(rows, ",") + `]}`
}

// Owner order 2026-11-21 (second pass): every number starts on the "#"'s own
// cell, so 1. and 10. line up under the heading, and a full stop follows each.
func TestBuild154OrderFlowNumbersLineUpUnderTheHash(t *testing.T) {
	a := orderFlowApp(t, 200, 50, flowSample154())
	rows := rowsOf(a)
	head, first, tenth := -1, "", ""
	for i, row := range rows {
		if strings.Contains(row, "SCRIP") && strings.Contains(row, "BUYING (B)") {
			head = i
		}
		if strings.Contains(row, "S00") {
			first = row
		}
		if strings.Contains(row, "S09") {
			tenth = row
		}
	}
	if head < 0 || first == "" || tenth == "" {
		t.Fatalf("the heading or the rows are missing:\n%s", strings.Join(rows, "\n"))
	}
	// The page starts on cell 1 and the panel's frame and one cell of pad come
	// before its inner rectangle, so the table starts on rune 3.
	const ix = 3
	h := []rune(rows[head])
	if got := string(h[ix : ix+flowNumW]); !strings.HasPrefix(got, "#") {
		t.Fatalf("the heading reads %q, want # on the table's first cell", got)
	}
	f, tn := []rune(first), []rune(tenth)
	if got := string(f[ix : ix+2]); got != "1." {
		t.Errorf("the first row reads %q, want 1. on the # cell: %q", got, first)
	}
	if got := string(tn[ix : ix+3]); got != "10." {
		t.Errorf("the tenth row reads %q, want 10. starting on the # cell: %q", got, tenth)
	}
	if got := string(f[ix : ix+flowNumW]); got != "1. " {
		t.Errorf("the first number field reads %q, want the full stop beside the digit", got)
	}
	// The digits themselves start on one cell, so 1. and 10. line up under the
	// # instead of each figure ending on one cell.
	if f[ix] == ' ' || tn[ix] == ' ' {
		t.Errorf("a number does not start on the # cell: %q / %q", first, tenth)
	}
}

// Owner order 2026-11-21 (second pass): ORDER FLOW no longer writes STALE after
// its NET DELTA values. A row the relay has not refreshed keeps its soft symbol.
func TestBuild154OrderFlowWritesNoStale(t *testing.T) {
	a := orderFlowApp(t, 200, 50, flowSample154())
	s := plain(a)
	if strings.Contains(s, "STALE") {
		t.Fatalf("ORDER FLOW still writes STALE:\n%s", s)
	}
	if !strings.Contains(s, "S00") {
		t.Fatalf("the stale row is missing from the table:\n%s", s)
	}
}
