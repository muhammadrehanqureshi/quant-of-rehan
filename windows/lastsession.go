package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// The desktop window is usually opened while the exchange is shut, and the
// relay only carries a live table while a session feeds it. Build 26 therefore
// keeps the last good answers on disk and starts from them, so the last market
// day is always on screen, labelled with the day it belongs to. Nothing is
// invented: the file holds answers the relay really sent.

// sessionSnapshot is the state of a market day, as the window last saw it.
type sessionSnapshot struct {
	Ver     int              `json:"ver"`
	SavedAt time.Time        `json:"saved_at"`
	Session string           `json:"session"` // the relay's own trading date
	Market  *Market          `json:"market,omitempty"`
	Quotes  *Quotes          `json:"quotes,omitempty"`
	Prices  map[string]Quote `json:"prices,omitempty"`
	Signals   string           `json:"signals,omitempty"`
	Sectors   *Sectors         `json:"sectors,omitempty"`
	OrderFlow *OrderFlow       `json:"order_flow,omitempty"`
}

// sessionVer is bumped when an old file must not be read any more.
const sessionVer = 1

// sessionPath sits beside settings.json, in the user's own config folder, so a
// new build reads the day the previous one stored.
func sessionPath(cfgPath string) string {
	return filepath.Join(filepath.Dir(cfgPath), "last-session.json")
}

// sessionDayLabel turns the stored session date into 06 NOV 2026. A form it
// does not recognise is returned as it stands, never guessed.
func sessionDayLabel(s string) string {
	s = strings.TrimSpace(s)
	for _, layout := range []string{"2006-01-02", "02 Jan 2006", "02 Jan 06", "2006/01/02"} {
		if t, err := time.ParseInLocation(layout, s, pkt); err == nil {
			return strings.ToUpper(t.Format("02 Jan 2006"))
		}
	}
	return strings.ToUpper(s)
}

func loadSession(path string) *sessionSnapshot {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	var s sessionSnapshot
	if err := json.Unmarshal(b, &s); err != nil || s.Ver != sessionVer {
		return nil
	}
	if s.Market == nil && s.Quotes == nil && len(s.Prices) == 0 && s.Sectors == nil && s.OrderFlow == nil && strings.TrimSpace(s.Signals) == "" {
		return nil
	}
	return &s
}

func saveSession(path string, s *sessionSnapshot) error {
	if s == nil {
		return nil
	}
	b, err := json.Marshal(s)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, b, 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

// restoreSession puts the stored answers in place. The stored quotes are not
// fed to the tape: they carry no fresh tick, so the feed light keeps saying
// STALE and no alert is raised from yesterday's prices.
func (a *App) restoreSession(s *sessionSnapshot) {
	if s == nil {
		return
	}
	if s.Market != nil {
		a.market, a.marketOpen = s.Market, s.Market.Open
	}
	if s.Quotes != nil && len(s.Quotes.Items) > 0 {
		a.quotes = s.Quotes
	}
	if len(s.Prices) > 0 {
		a.prices = s.Prices
	}
	if s.Sectors != nil && len(s.Sectors.Items) > 0 {
		a.sectors = s.Sectors
	}
	if strings.TrimSpace(s.Signals) != "" {
		a.signals = s.Signals
	}
	if s.OrderFlow != nil {
		a.of = s.OrderFlow
	}
	a.sessionAt, a.sessionDate = s.SavedAt, s.Session
	a.rebuildSymbols()
	// Build 26 stored the prices and quotes but not the ORDER FLOW answer. A
	// build 29 window can still show that day's volume table by rebuilding the
	// rows from the stored quotes, with T only because the old snapshot did not
	// carry the relay's split method. It is the relay's own stored data, never an
	// invented row.
	a.rebuildOrderFlowFromSession()
}

// rebuildOrderFlowFromSession gives an old stored day an ORDER FLOW table when
// the snapshot has prices or quotes but no order-flow answer. Only the stored
// total volume is used; B and S stay absent because the old file did not keep a
// measured split method. This is why the table shows T only.
func (a *App) rebuildOrderFlowFromSession() {
	if a.of != nil && len(a.of.Rows) > 0 {
		return
	}
	if len(a.prices) == 0 && (a.quotes == nil || len(a.quotes.Items) == 0) {
		return
	}
	of := &OrderFlow{
		OK:        true,
		Day:       a.sessionDate,
		AsOf:      a.sessionAt.In(pkt).Format("2006-01-02 15:04:05"),
		AsOfTime:  a.sessionAt,
		FetchedAt: a.sessionAt,
		Universe:  len(a.symbols),
		Path:      "last-session",
		Basis:     "last stored session",
	}
	for _, sym := range a.symbols {
		price, chg := 0.0, (*float64)(nil)
		if q, ok := a.prices[sym]; ok && q.Price > 0 {
			price, chg = q.Price, q.ChangePct
		}
		if price <= 0 && a.quotes != nil {
			if lq, ok := a.quotes.Items[sym]; ok && lq.Price > 0 {
				price, chg = lq.Price, lq.ChangePct
			}
		}
		if price <= 0 {
			continue
		}
		row := FlowRow{Symbol: sym, Price: price, ChangePct: chg, Method: methodNone, Source: "last stored session"}
		if a.quotes != nil {
			if lq, ok := a.quotes.Items[sym]; ok && lq.Volume > 0 {
				v := lq.Volume
				row.Volume = &v
				row.ObservedAt = lq.ObservedAt
			}
		}
		of.Rows = append(of.Rows, row)
	}
	if len(of.Rows) == 0 {
		return
	}
	of.Included = len(of.Rows)
	a.of = of
}

// saveSession writes what the window has now. A demo run, or a run pointed at
// another relay, never touches the real file.
func (a *App) saveSession() {
	if a.cacheOff() {
		return
	}
	s := &sessionSnapshot{
		Ver:     sessionVer,
		SavedAt: a.now,
		Session: a.sessionDate,
		Market:  a.market,
		Quotes:  a.quotes,
		Prices:  a.prices,
		Signals:   a.signals,
		Sectors:   a.sectors,
		OrderFlow: a.of,
	}
	if s.Market == nil && s.Quotes == nil && len(s.Prices) == 0 && s.Sectors == nil && s.OrderFlow == nil && strings.TrimSpace(s.Signals) == "" {
		return
	}
	if err := saveSession(sessionPath(a.cfgPath), s); err != nil {
		return
	}
	a.sessionAt, a.sessionDirty, a.lastSessionSave = a.now, false, a.now
}

func (a *App) cacheOff() bool {
	return a.demo || a.ephemeral || a.relay == nil
}

// sameSessionDay says whether the stored date is the Karachi day of now.
func sameSessionDay(stored string, now time.Time) bool {
	stored = strings.TrimSpace(stored)
	if stored == "" {
		return false
	}
	for _, layout := range []string{"2006-01-02", "02 Jan 2006", "02 Jan 06", "2006/01/02"} {
		if t, err := time.ParseInLocation(layout, stored, pkt); err == nil {
			return t.In(pkt).Format("2006-01-02") == now.In(pkt).Format("2006-01-02")
		}
	}
	return false
}

// storedSessionDay words the day the data on screen belongs to.
func (a *App) storedSessionDay() string {
	if s := strings.TrimSpace(a.sessionDate); s != "" {
		return sessionDayLabel(s)
	}
	return strings.ToUpper(a.sessionAt.In(pkt).Format("02 Jan 2006"))
}
