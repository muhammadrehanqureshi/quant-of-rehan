package main

import (
	"encoding/json"
	"os"
	"path/filepath"
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
	BigBuy          bool   `json:"big_buy"`       // flag large buying on the broker feed
	BigSell         bool   `json:"big_sell"`      // flag large selling on the broker feed
	Sound           bool   `json:"sound"`         // play a tone with each flag and alert
	BigBuyValue     int64  `json:"big_buy_value"` // PKR bought in a minute to count as big
	CellShape       int    `json:"cell_shape"`    // terminal cell height over width, in hundredths (222 is 2.22)
}

// settingsVer is bumped when a stored default must be replaced. Version 2 is
// the first with one second polling and the big buying flag. Version 3 adds the
// big selling flag and the 2.22 cell shape of a Windows Terminal cell (9 by 20
// pixels), which replaces the 1.90 that builds 4 and 5 wrote on their own.
const settingsVer = 3

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

// bigBuyChoices are the thresholds the Settings screen steps through.
var bigBuyChoices = []int64{5_000_000, 10_000_000, 25_000_000, 50_000_000, 100_000_000}

func defaultSettings() Settings {
	return Settings{Ver: settingsVer, Theme: 0, Notify: true, PollMS: 1000, BigBuy: true, Sound: true, BigBuyValue: 10_000_000, CellShape: defaultCellShape, BigSell: true}
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
		if s.BigBuyValue == 0 {
			s.BigBuy, s.Sound, s.BigBuyValue = true, true, 10_000_000
		}
		s.Ver = settingsVer
	}
	if ver < 3 {
		// Builds 4 and 5 stored 1.90 without being asked. A Windows Terminal cell
		// is 20 by 9 pixels, so the ring was drawn too wide.
		s.BigSell = true
		s.CellShape = defaultCellShape
	}
	if s.BigBuyValue <= 0 {
		s.BigBuyValue = 10_000_000
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
