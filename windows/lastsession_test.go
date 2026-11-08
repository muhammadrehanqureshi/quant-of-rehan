package main

import (
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestSessionDayLabel(t *testing.T) {
	cases := map[string]string{
		"2026-11-06":  "06 NOV 2026",
		"06 Nov 2026": "06 NOV 2026",
		"":            "",
		"not a day":   "NOT A DAY",
	}
	for in, want := range cases {
		if got := sessionDayLabel(in); got != want {
			t.Errorf("sessionDayLabel(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestSessionFileRoundTrip(t *testing.T) {
	path := filepath.Join(t.TempDir(), "last-session.json")
	px := 5.79
	snap := &sessionSnapshot{
		Ver:     sessionVer,
		SavedAt: time.Date(2026, 11, 6, 15, 30, 0, 0, pkt),
		Session: "2026-11-06",
		Market:  &Market{Date: "2026-11-06"},
		Prices:  map[string]Quote{"KEL": {Price: 5.79, ChangePct: &px}},
		Signals: "KEL entered at 5.79",
	}
	if err := saveSession(path, snap); err != nil {
		t.Fatalf("save: %v", err)
	}
	got := loadSession(path)
	if got == nil {
		t.Fatal("the stored session did not load")
	}
	if got.Session != "2026-11-06" || got.Market == nil || len(got.Prices) != 1 {
		t.Fatalf("the file lost a field: %+v", got)
	}
	if q := got.Prices["KEL"]; q.Price != 5.79 || q.ChangePct == nil || *q.ChangePct != 5.79 {
		t.Fatalf("the price row changed: %+v", q)
	}
	if got.Signals != "KEL entered at 5.79" {
		t.Fatalf("the signal changed: %q", got.Signals)
	}
}

func TestStartRestoresTheLastSession(t *testing.T) {
	dir := t.TempDir()
	cfgPath := filepath.Join(dir, "settings.json")
	px := 5.79
	snap := &sessionSnapshot{
		Ver:     sessionVer,
		SavedAt: time.Date(2026, 11, 6, 15, 30, 0, 0, pkt),
		Session: "2026-11-06",
		Market:  &Market{Date: "2026-11-06"},
		Prices:  map[string]Quote{"KEL": {Price: 5.79, ChangePct: &px}},
	}
	if err := saveSession(sessionPath(cfgPath), snap); err != nil {
		t.Fatalf("save: %v", err)
	}
	cfg := defaultSettings()
	cfg.Notify = false
	a := NewApp(cfg, cfgPath, NewRelay(defaultRelay))
	a.now = time.Date(2026, 11, 8, 12, 0, 0, 0, pkt)
	if a.market == nil || len(a.prices) != 1 || a.sessionDate != "2026-11-06" {
		t.Fatalf("the stored day was not restored: market %v prices %d date %q", a.market, len(a.prices), a.sessionDate)
	}
	if len(a.symbols) == 0 {
		t.Fatal("the search list has no symbols after the restore")
	}
	if !strings.Contains(a.statusNote(), "06 NOV 2026") {
		t.Fatalf("the status note does not name the stored day: %q", a.statusNote())
	}
}

func TestEmptyRelayAnswersKeepTheStoredTable(t *testing.T) {
	a := newTestApp(t)
	a.now = time.Date(2026, 11, 8, 12, 0, 0, 0, pkt) // a Sunday
	px := 5.79
	a.quotes = &Quotes{OK: true, Items: map[string]LiveQuote{"KEL": {Price: 5.79, ChangePct: &px}}, FetchedAt: a.now.Add(-time.Hour)}
	a.prices = map[string]Quote{"KEL": {Price: 5.79, ChangePct: &px}}
	a.market = &Market{Date: "2026-11-06", Leaders: []Leader{{Symbol: "KEL"}}}
	a.sessionAt = time.Date(2026, 11, 6, 15, 30, 0, 0, pkt)
	a.sessionDate = "2026-11-06"

	a.onMsg(msgQuotes{q: &Quotes{OK: true, Items: map[string]LiveQuote{}}})
	if _, ok := a.quotes.Items["KEL"]; !ok {
		t.Fatal("an empty quotes answer erased the stored table")
	}
	if len(a.prices) != 1 {
		t.Fatal("an empty quotes answer erased the stored prices")
	}

	a.onMsg(msgMarket{m: NewMarket()})
	if a.market.Date != "2026-11-06" || len(a.market.Leaders) != 1 {
		t.Fatalf("an empty market card erased the stored day: %+v", a.market)
	}
}
