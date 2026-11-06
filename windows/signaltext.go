package main

import (
	"math"
	"regexp"
	"strconv"
	"strings"
)

// This file is a line for line port of the Android SignalText and the signal
// helpers in Watcher, so the card shows exactly what the phone shows.

const (
	notReported = "Not reported"
	noTradeText = "NO TRADE"
	unavailable = "Signal unavailable"
	signalNone  = "NO SIGNAL AVAILABLE RIGHT NOW"
)

var (
	reEntered  = regexp.MustCompile(`(?i)([A-Z0-9]{2,12})\s+entered\s+at\s+(-?[0-9]+(?:\.[0-9]+)?)`)
	reCardDate = regexp.MustCompile(`\b(\d{4}-\d{2}-\d{2})\b`)
	reTarget   = regexp.MustCompile(`(?i)\btarget\s+(-?[0-9]+(?:\.[0-9]+)?)`)
	reStop     = regexp.MustCompile(`(?i)\b(?:stop\s*loss|stop|sl)\b\s*(?:at\s+)?(-?[0-9]+(?:\.[0-9]+)?)`)
	reSymbol   = regexp.MustCompile(`(?im)^\s*symbol:\s*([A-Za-z0-9]{2,12})\b`)
	reEntryAt  = regexp.MustCompile(`(?i)\bentry\s+time:?\s*([0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?)`)
)

// cardDate returns the first yyyy-mm-dd in the text, or "".
func cardDate(s string) string {
	m := reCardDate.FindStringSubmatch(s)
	if m == nil {
		return ""
	}
	return m[1]
}

func known(s string) (string, bool) {
	t := strings.TrimSpace(s)
	if t == "" || strings.EqualFold(t, "null") || strings.EqualFold(t, "undefined") {
		return "", false
	}
	return t, true
}

func afterLabel(line, label string) (string, bool) {
	if len(line) < len(label) || !strings.EqualFold(line[:len(label)], label) {
		return "", false
	}
	return known(line[len(label):])
}

func leadingPrice(s string) (string, bool) {
	k, ok := known(s)
	if !ok {
		return "", false
	}
	tok := strings.Fields(k)
	if len(tok) == 0 {
		return "", false
	}
	f, err := strconv.ParseFloat(tok[0], 64)
	if err != nil || f <= 0 || math.IsNaN(f) || math.IsInf(f, 0) {
		return "", false
	}
	return tok[0], true
}

// SignalFields is the structured result of reading a relay signal text.
type SignalFields struct {
	Symbol string
	Entry  string
	Exit   string
	Stop   string
	// Time is when the entry happened, as the card words it ("10:12:34 PKT"), or
	// notReported when the card carries no entry time.
	Time string
	// State is "trade" when any price field was found, else "none" or "unavailable".
	State string
}

// parseSignal ports SignalText.compact. The symbol line is a small addition:
// the phone card never shows which stock a labelled signal is for, and a trade
// card without its symbol is not much use on a desktop screen.
func parseSignal(raw string) SignalFields {
	trim := strings.TrimSpace(raw)
	if trim == "" {
		return SignalFields{State: "unavailable"}
	}
	var symbol, entry, exit, stop string
	var haveEntry, haveExit, haveStop bool
	for _, line := range regexp.MustCompile(`\r?\n`).Split(trim, -1) {
		if v, ok := afterLabel(line, "Entry price:"); ok {
			entry, haveEntry = v, true
			continue
		}
		if v, ok := afterLabel(line, "Exit price:"); ok {
			exit, haveExit = v, true
			continue
		}
		if v, ok := afterLabel(line, "Exit reference:"); ok {
			exit, haveExit = v, true
			continue
		}
		if v, ok := afterLabel(line, "Exit:"); ok {
			exit, haveExit = v, true
			continue
		}
		if v, ok := afterLabel(line, "Stop Loss:"); ok {
			stop, haveStop = v, true
			continue
		}
		if v, ok := afterLabel(line, "SL:"); ok {
			stop, haveStop = v, true
			continue
		}
		if v, ok := afterLabel(line, "Target:"); ok {
			if lp, ok2 := leadingPrice(v); ok2 {
				exit, haveExit = lp, true
			}
		}
	}
	if !haveEntry && !haveExit && !haveStop {
		if m := reEntered.FindStringSubmatch(trim); m != nil {
			symbol = strings.ToUpper(m[1])
			entry, haveEntry = m[2], true
			if t := reTarget.FindStringSubmatch(trim); t != nil {
				exit, haveExit = t[1], true
			}
			if s := reStop.FindStringSubmatch(trim); s != nil {
				stop, haveStop = s[1], true
			}
		}
	}
	if !haveEntry && !haveExit && !haveStop {
		if strings.Contains(strings.ToUpper(trim), noTradeText) {
			return SignalFields{State: "none"}
		}
		return SignalFields{State: "unavailable"}
	}
	if symbol == "" {
		if m := reSymbol.FindStringSubmatch(trim); m != nil {
			symbol = strings.ToUpper(m[1])
		}
	}
	or := func(v string, ok bool) string {
		if !ok {
			return notReported
		}
		return v
	}
	entryTime := notReported
	if m := reEntryAt.FindStringSubmatch(trim); m != nil {
		entryTime = m[1] + " PKT"
	}
	return SignalFields{
		Symbol: symbol,
		Entry:  or(entry, haveEntry),
		Exit:   or(exit, haveExit),
		Stop:   or(stop, haveStop),
		Time:   entryTime,
		State:  "trade",
	}
}

// compact reproduces the exact text the Android card shows (without my symbol
// addition when the symbol came from a Symbol: line).
func compact(raw string) string {
	f := parseSignal(raw)
	switch f.State {
	case "none":
		return noTradeText
	case "unavailable":
		return unavailable
	}
	var b strings.Builder
	if f.Symbol != "" {
		b.WriteString(f.Symbol)
		b.WriteByte('\n')
	}
	b.WriteString("Entry Price: " + f.Entry + "\n")
	b.WriteString("Exit Price: " + f.Exit + "\n")
	b.WriteString("Stop Loss: " + f.Stop)
	return b.String()
}

// latestSignalDisplay ports MainActivity.latestSignalDisplay: a card dated on
// another day than the relay's own date is treated as no signal.
func latestSignalDisplay(raw, relayDate string) string {
	cd := cardDate(raw)
	if cd != "" && relayDate != "" && cd != relayDate {
		return signalNone
	}
	c := compact(raw)
	if c == noTradeText {
		return signalNone
	}
	return c
}

// signalBody drops the first (header) line, like Watcher.signalBody.
func signalBody(s string) string {
	if i := strings.IndexByte(s, '\n'); i >= 0 {
		s = s[i+1:]
	}
	return strings.TrimSpace(s)
}

// isTradeSignal ports Watcher.isTradeSignal.
func isTradeSignal(body string) bool {
	if body == "" {
		return false
	}
	u := strings.ToUpper(body)
	if strings.HasPrefix(u, "NO TRADE") || strings.HasPrefix(u, "NO SIGNAL") ||
		strings.HasPrefix(u, "NO CALL") || strings.Contains(u, "NO SIGNAL AVAILABLE") {
		return false
	}
	return strings.Contains(u, "SYMBOL:") || strings.Contains(u, "ENTERED AT")
}

// marketEvent ports Watcher.marketEvent. The switch table was recovered from
// the APK bytecode: OPEN is online, BREAK is break, CLOSED and POST_CLOSE are
// offline, every other phase (for example WARMUP) raises no event.
func marketEvent(m *Market) string {
	if m == nil || m.Phase == "" {
		return ""
	}
	switch m.Phase {
	case "OPEN":
		return "online"
	case "BREAK":
		return "break"
	case "CLOSED", "POST_CLOSE":
		return "offline"
	}
	return ""
}

// greetingFor ports MainActivity.refreshGreeting (Karachi clock).
func greetingFor(h, m int) string {
	night := "You have a wonderful night, Mr. Rehan!"
	if h == 5 && m == 0 {
		return night
	}
	switch {
	case (h >= 5 && h <= 11) || (h == 12 && m == 0):
		return "Good morning, Mr. Rehan!"
	case (h >= 12 && h <= 16) || (h == 17 && m == 0):
		return "Good afternoon, sir!"
	case (h >= 17 && h <= 18) || (h == 19 && m == 0):
		return "Good evening, sir!"
	}
	return night
}
