package main

import (
	"compress/gzip"
	"encoding/csv"
	"fmt"
	"io"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

// Owner order 2026-11-08: the CHARTS page opens on a full year, 08 Nov 2025 to
// 08 Nov 2026. The relay began storing bars on 2026-11-07, so it cannot answer
// a year. The repository's EOD crawl can: data/eod_history.csv.gz holds each
// session's own OHLCV. This file reads that local history when it is present
// and never invents a bar when it is not.
const (
	eodWindowStart = "2025-11-08"
	eodWindowEnd   = "2026-11-08"
)

var (
	eodMu    sync.Mutex
	eodCache = map[string][]ChartBar{}
	eodPath  string
	eodTried bool
)

// findEODFile looks beside the program and up the tree, because the built exe
// may sit in windows/, in windows/package/, or in the repository root.
func findEODFile() string {
	cands := []string{
		filepath.Join("data", "eod_history.csv.gz"),
		filepath.Join("..", "data", "eod_history.csv.gz"),
		filepath.Join("..", "..", "data", "eod_history.csv.gz"),
	}
	if exe, err := os.Executable(); err == nil {
		dir := filepath.Dir(exe)
		cands = append(cands,
			filepath.Join(dir, "data", "eod_history.csv.gz"),
			filepath.Join(dir, "..", "data", "eod_history.csv.gz"))
	}
	seen := map[string]bool{}
	for _, p := range cands {
		if seen[p] {
			continue
		}
		seen[p] = true
		if st, err := os.Stat(p); err == nil && !st.IsDir() {
			return p
		}
	}
	return ""
}

// localEODHistory returns the daily bars in the owner's year, or nil when the
// local file has nothing for this symbol. A nil answer is not an error: the
// caller falls back to the relay, whose own note explains an empty store.
func localEODHistory(sym string) *ChartHistory {
	sym = strings.ToUpper(strings.TrimSpace(sym))
	if sym == "" {
		return nil
	}
	bars := eodBarsFor(sym)
	if len(bars) == 0 {
		return nil
	}
	return &ChartHistory{
		Symbol: sym,
		TF:     "1D",
		Days:   365,
		Bars:   bars,
		Day:    bars[len(bars)-1].At.Format("2006-01-02"),
	}
}

// eodBarsFor reads one symbol once and keeps it. The file is a long frame in
// date order, so a symbol change costs one pass; reopening it for the same
// symbol on the next poll would be waste.
func eodBarsFor(sym string) []ChartBar {
	eodMu.Lock()
	defer eodMu.Unlock()
	if bars, ok := eodCache[sym]; ok {
		return bars
	}
	if !eodTried {
		eodTried, eodPath = true, findEODFile()
	}
	if eodPath == "" {
		eodCache[sym] = nil
		return nil
	}
	f, err := os.Open(eodPath)
	if err != nil {
		eodCache[sym] = nil
		return nil
	}
	defer f.Close()
	zr, err := gzip.NewReader(f)
	if err != nil {
		eodCache[sym] = nil
		return nil
	}
	defer zr.Close()
	bars, err := readEODBars(zr, sym)
	if err != nil {
		bars = nil
	}
	eodCache[sym] = bars
	return bars
}

// readEODBars parses the long frame [date, symbol, open, high, low, close,
// volume], keeps the owner's window and the named symbol, and repairs a ragged
// envelope by widening high and low to the row's own open and close. A row
// with a zero price or zero volume is an untraded session, not a candle, and is
// dropped rather than drawn as a flat bar.
func readEODBars(r io.Reader, sym string) ([]ChartBar, error) {
	cr := csv.NewReader(r)
	cr.FieldsPerRecord = -1
	cr.LazyQuotes = true
	head, err := cr.Read()
	if err != nil {
		return nil, err
	}
	col := make(map[string]int, len(head))
	for i, name := range head {
		name = strings.TrimPrefix(name, "\ufeff")
		col[strings.ToLower(strings.TrimSpace(name))] = i
	}
	for _, need := range []string{"date", "symbol", "open", "high", "low", "close", "volume"} {
		if _, ok := col[need]; !ok {
			return nil, fmt.Errorf("eod: missing %s column", need)
		}
	}
	var out []ChartBar
	for {
		rec, err := cr.Read()
		if err == io.EOF {
			break
		}
		if err != nil {
			continue
		}
		field := func(name string) string {
			i := col[name]
			if i < 0 || i >= len(rec) {
				return ""
			}
			return strings.TrimSpace(rec[i])
		}
		d := field("date")
		if len(d) > 10 {
			d = d[:10]
		}
		if d < eodWindowStart || d > eodWindowEnd {
			continue
		}
		if !strings.EqualFold(field("symbol"), sym) {
			continue
		}
		open, e1 := strconv.ParseFloat(field("open"), 64)
		high, e2 := strconv.ParseFloat(field("high"), 64)
		low, e3 := strconv.ParseFloat(field("low"), 64)
		close, e4 := strconv.ParseFloat(field("close"), 64)
		vol, e5 := strconv.ParseFloat(field("volume"), 64)
		if e1 != nil || e2 != nil || e3 != nil || e4 != nil || e5 != nil {
			continue
		}
		if open <= 0 || high <= 0 || low <= 0 || close <= 0 || vol <= 0 {
			continue
		}
		hi := math.Max(open, math.Max(high, close))
		lo := math.Min(open, math.Min(low, close))
		at, err := time.ParseInLocation("2006-01-02", d, pkt)
		if err != nil {
			continue
		}
		out = append(out, ChartBar{
			At:     at,
			Minute: at.Format("02 Jan 06"),
			Open:   open,
			High:   hi,
			Low:    lo,
			Close:  close,
			Volume: int64(math.Round(vol)),
		})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].At.Before(out[j].At) })
	if len(out) > 400 {
		out = out[len(out)-400:]
	}
	return out, nil
}
