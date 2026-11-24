package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// Settings is the small state file, the desktop twin of the app's "qor"
// SharedPreferences. It never holds a secret: the relay is read only and
// nothing here needs a token.
type Settings struct {
	Ver             int    `json:"ver"`
	Theme           int    `json:"theme"`
	RelayURL        string `json:"relay_url"`
	Notify          bool   `json:"notify"`
	PollMS          int    `json:"poll_ms"`
	LastMarketEvent string `json:"last_market_event"`
	LastSignal      string `json:"last_signal"`
	ReqDay          string `json:"req_day"`
	ReqCount        int64  `json:"req_count"`
	BigBuy          bool   `json:"big_buy"`      // flag large buying on the broker feed
	BigSell         bool   `json:"big_sell"`     // flag large selling on the broker feed
	Sound           bool   `json:"sound"`        // play a tone with each flag and alert
	BigOrderQty     int64  `json:"big_order_qty"` // shares in one second to count as a big order
	CellShape       int    `json:"cell_shape"`    // terminal cell height over width, in hundredths (222 is 2.22)
	// Owner order 2026-11-13: the three PRICE ALERT slots live here, so they
	// survive a restart. They are the owner's own numbers, never a secret.
	PriceAlerts [priceAlertSlots]PriceAlert `json:"price_alerts"`
	// Owner order 2026-11-24: the WATCH LIST is the owner's own scrips, in his
	// own order, written here so they survive a restart.
	Watch []string `json:"watch"`
}

// watchMax is how many scrips the WATCH LIST keeps. It is more than any screen
// holds at once and small enough that the page always reads.
const watchMax = 40

// settingsVer is bumped when a stored default must be replaced. Version 2 is
// the first with one second polling and the big buying flag. Version 3 adds the
// big selling flag and the 2.22 cell shape of a Windows Terminal cell (9 by 20
// pixels), which replaces the 1.90 that builds 4 and 5 wrote on their own.
// Version 4 replaces the PKR big-buy value with a share quantity, because the
// owner's 2026-11-16 order measures a big order in shares.
const settingsVer = 4

// defaultCellShape is the height over width of a Windows Terminal cell at its
// stock font, 20 pixels over 9.
const defaultCellShape = 222

// The ring's roundness steps by 0.05 between these. [ and ] change it on the
// home and scanner screens, where the ring is.
const (
	cellShapeMin  = 150
	cellShapeMax  = 280
	cellShapeStep = 5
)

// alertFloorShares is the smallest one-second step the ALERTS LOG announces.
// Owner order 2026-11-16: the boards list 50k and above, while the log and its
// pop-ups start at 100k and above.
const alertFloorShares int64 = 100_000

// bigOrderChoices are the share thresholds the Settings screen steps through.
// The 50k board floor is not an alert threshold, so the choices start at 100k.
var bigOrderChoices = []int64{alertFloorShares, 250_000, 500_000, 1_000_000}

func defaultSettings() Settings {
	return Settings{Ver: settingsVer, Theme: 0, Notify: true, PollMS: 1000, BigBuy: true, Sound: true, BigOrderQty: alertFloorShares, CellShape: defaultCellShape, BigSell: true}
}

func settingsPath() string {
	dir, err := os.UserConfigDir()
	if err != nil || dir == "" {
		dir = "."
	}
	return filepath.Join(dir, "QuantOfRehan", "settings.json")
}

func loadSettings(path string) Settings {
	s := defaultSettings()
	b, err := os.ReadFile(path)
	if err != nil {
		return s
	}
	s.Ver = 0 // a file without a version is from build 1
	_ = json.Unmarshal(b, &s)
	ver := s.Ver
	if s.Ver < settingsVer {
		// A file written by build 1 holds the old two second default, and has no
		// big buying fields. Replace what the old build set on its own.
		s.PollMS = 1000
		if s.BigOrderQty == 0 {
			s.BigBuy, s.Sound, s.BigOrderQty = true, true, 100_000
		}
		s.Ver = settingsVer
	}
	if ver < 3 {
		// Builds 4 and 5 stored 1.90 without being asked. A Windows Terminal cell
		// is 20 by 9 pixels, so the ring was drawn too wide.
		s.BigSell = true
		s.CellShape = defaultCellShape
	}
	if s.BigOrderQty < alertFloorShares {
		// A file written by build 115 may carry the 50k board floor as its
		// alert threshold. The log never goes below the ordered 100k.
		s.BigOrderQty = alertFloorShares
	}
	if s.CellShape == 0 {
		s.CellShape = defaultCellShape
	}
	s.CellShape = min(max(s.CellShape, cellShapeMin), cellShapeMax)
	if s.Theme < 0 || s.Theme >= len(themes) {
		s.Theme = 0
	}
	if s.PollMS < 1000 {
		s.PollMS = 1000
	}
	if s.PollMS > 60000 {
		s.PollMS = 60000
	}
	// Owner order 2026-11-24: every watched scrip is read back as an upper case
	// ticker, one of each, in the order the owner put them in.
	seen := map[string]bool{}
	kept := s.Watch[:0]
	for _, sym := range s.Watch {
		sym = strings.ToUpper(strings.TrimSpace(sym))
		if sym == "" || seen[sym] || runeLen(sym) > 12 {
			continue
		}
		if len(kept) >= watchMax {
			break
		}
		seen[sym] = true
		kept = append(kept, sym)
	}
	s.Watch = kept
	for i := range s.PriceAlerts {
		p := &s.PriceAlerts[i]
		p.Symbol = strings.ToUpper(strings.TrimSpace(p.Symbol))
		if p.Symbol == "" || p.Target <= 0 || p.Target > 1_000_000 {
			*p = PriceAlert{}
		}
	}
	return s
}

func saveSettings(path string, s Settings) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	b, err := json.MarshalIndent(s, "", "  ")
	if err != nil {
		return err
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, b, 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

// utcDay is the day Cloudflare counts requests against (it resets at 00:00 UTC).
func utcDay(t time.Time) string { return t.UTC().Format("2006-01-02") }
