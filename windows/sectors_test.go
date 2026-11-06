package main

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestParseSectorsUppercasesAndDeduplicates(t *testing.T) {
	s := ParseSectors(flowJSON(t, `{"ok":true,"source":"kmiall","as_of":"2026-11-06 10:00 PKT",
	"sectors":[
		{"name":"Automobile","symbols":["ALFA","alfa","BRVO",""]},
		{"name":"Cement","symbols":["CHRL","ECHO"]},
		{"name":"","symbols":["NOPE"]},
		{"name":"Empty","symbols":[]}
	]}`))
	if !s.OK || len(s.Items) != 2 {
		t.Fatalf("sectors: %+v", s)
	}
	if s.Items[0].Name != "AUTOMOBILE" || len(s.Items[0].Symbols) != 2 || s.Items[0].Symbols[0] != "ALFA" {
		t.Errorf("first group: %+v", s.Items[0])
	}
	if s.Source != "kmiall" || s.AsOf == "" {
		t.Errorf("metadata: %+v", s)
	}
	if bad := ParseSectors(flowJSON(t, `{"ok":false,"error":"not ready"}`)); bad.OK || bad.Err != "not ready" {
		t.Errorf("refusal: %+v", bad)
	}
}

func TestFetchSectorsReadsTheRelayContract(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/sectors" {
			t.Errorf("path: %s", r.URL.Path)
		}
		_, _ = w.Write([]byte(`{"ok":true,"source":"relay","as_of":"2026-11-06 10:00 PKT",
			"sectors":[{"name":"CEMENT","symbols":["CHRL","ECHO"]}]}`))
	}))
	defer srv.Close()
	s, err := NewRelay(srv.URL).FetchSectors(context.Background())
	if err != nil || s == nil || len(s.Items) != 1 || s.Items[0].Symbols[1] != "ECHO" {
		t.Fatalf("fetch: %v %+v", err, s)
	}
}

func TestScannerShowsSectorsAndCyclesThem(t *testing.T) {
	a := demoApp(t, 122, 30)
	a.screen = scrScanner
	a.sectors = nil // the demo has its own invented groups
	s := plain(a)
	for _, want := range []string{"SECTORS", "AUTOMOBILE", "ALFA"} {
		if !strings.Contains(s, want) {
			t.Errorf("scanner is missing %q", want)
		}
	}
	clickText(t, a, "CEMENT")
	if a.sectorChoice != 1 {
		t.Errorf("clicking a row of the sector drop down must pick that group: %d", a.sectorChoice)
	}
	if s := plain(a); !strings.Contains(s, "CHRL") {
		t.Errorf("the chosen group's scrips must be shown:\n%s", s)
	}
}

func TestQuantOnlineInPreAndPostWithoutAlerts(t *testing.T) {
	a := newTestApp(t)
	a.w, a.h, a.animT = 120, 30, 3.2
	a.link, a.checking = true, false
	a.marketOpen = false
	a.market = marketIn("CLOSED")
	a.head = &Head{Reachable: true, MarketOpen: false, Phase: a.market}
	a.market.Phase, a.market.TradingDay = "CLOSED", true
	a.cfg.LastMarketEvent = "online"
	for _, at := range []time.Time{
		time.Date(2026, 11, 2, 9, 5, 0, 0, pkt),
		time.Date(2026, 11, 2, 15, 40, 0, 0, pkt),
	} {
		a.now = at
		a.bannerTitle, a.bannerBody = "", ""
		a.beat()
		if !a.online() {
			t.Errorf("%v: the quant must be online in pre and post", at)
		}
		if a.bannerTitle != "" {
			t.Errorf("%v: pre and post must not raise alerts: %q", at, a.bannerTitle)
		}
	}
}
