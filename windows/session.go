package main

import "time"

// The PSX session law, in Karachi time. It follows the repository's own
// src/data/sessions.py, which was checked against the exchange's published
// trading hours:
//
//	Monday to Thursday  pre-market 09:00 to 09:15, trading 09:32 to 15:30,
//	                    post-market 15:32 to 15:49
//	Friday              pre-market 09:00 to 09:15, trading 09:17 to 12:00 and
//	                    14:32 to 16:30, post-market 16:32 to 16:49
//
// The quant reads the broker feed every second from 08:55, five minutes before
// the exchange's pre-open, until the post-market closes, so the gaps between
// those windows are scanned too. The 08:55 start is the owner's order of
// 2026-11-07: the day must never begin with volume the capture could not side.
// Each end is half open: 15:49:00 is already after the post-market, and a short
// grace period after it catches the final print.

type window struct{ from, to int } // minutes after midnight, half open

var (
	preWindow     = window{9*60 + 0, 9*60 + 15}
	weekdayTrade  = []window{{9*60 + 32, 15*60 + 30}}
	fridayTrade   = []window{{9*60 + 17, 12 * 60}, {14*60 + 32, 16*60 + 30}}
	weekdayPost   = window{15*60 + 32, 15*60 + 49}
	fridayPost    = window{16*60 + 32, 16*60 + 49}
	scanGraceSecs = 30

	// scanOpen is 08:55, five minutes before the exchange's pre-open. The scan
	// starts there on every trading day, not at 09:00, so the day never begins
	// with volume the capture could not side.
	scanOpen = 8*60 + 55
)

// PSX holidays, mirroring PSX_HOLIDAYS_2026 in src/data/sessions.py. The 9th
// of November and the 25th of December are closed every year by the owner's
// 2026-10-24 order, whatever the yearly list says.
var (
	psxHolidays2026 = map[string]bool{
		"2026-02-05": true, "2026-03-21": true, "2026-03-23": true,
		"2026-05-01": true, "2026-05-27": true, "2026-05-28": true,
		"2026-06-25": true, "2026-06-26": true, "2026-08-14": true,
		"2026-08-25": true, "2026-11-09": true, "2026-12-25": true,
	}
	alwaysClosedMonthDay = map[[2]int]bool{{11, 9}: true, {12, 25}: true}
)

// isPsxHoliday says whether this Karachi day is a PSX holiday. It matters to
// the orb: a holiday is not a market day, so the mark is red all day even
// inside the owner's green clock window (order 2026-11-09).
func isPsxHoliday(p time.Time) bool {
	if alwaysClosedMonthDay[[2]int{int(p.Month()), p.Day()}] {
		return true
	}
	return psxHolidays2026[p.Format("2006-01-02")]
}

func isFriday(p time.Time) bool { return p.Weekday() == time.Friday }

func isWeekend(p time.Time) bool {
	return p.Weekday() == time.Saturday || p.Weekday() == time.Sunday
}

func minuteOf(p time.Time) int { return p.Hour()*60 + p.Minute() }

func secondOf(p time.Time) int { return p.Hour()*3600 + p.Minute()*60 + p.Second() }

func (w window) has(m int) bool { return m >= w.from && m < w.to }

func tradeWindows(p time.Time) []window {
	if isFriday(p) {
		return fridayTrade
	}
	return weekdayTrade
}

func postWindow(p time.Time) window {
	if isFriday(p) {
		return fridayPost
	}
	return weekdayPost
}

// Session names. They are the words the HUD shows.
const (
	sesClosed  = "CLOSED"
	sesPre     = "PRE-MARKET"
	sesTrading = "MARKET OPEN"
	sesPost    = "POST-MARKET"
	sesBreak   = "MIDDAY BREAK"
	sesBetween = "BETWEEN SESSIONS"
)

// sessionAt names the part of the PSX day that Karachi time t falls in.
func sessionAt(t time.Time) string {
	p := t.In(pkt)
	if isWeekend(p) {
		return sesClosed
	}
	m := minuteOf(p)
	if preWindow.has(m) {
		return sesPre
	}
	for _, w := range tradeWindows(p) {
		if w.has(m) {
			return sesTrading
		}
	}
	if postWindow(p).has(m) {
		return sesPost
	}
	if isFriday(p) && m >= 12*60 && m < 14*60+32 {
		return sesBreak
	}
	if m >= preWindow.from && m < postWindow(p).to {
		return sesBetween
	}
	return sesClosed
}

// inScanWindow is true on a weekday from 08:55 until the post-market closes
// (15:49 Monday to Thursday, 16:49 on Friday), plus a short grace period.
func inScanWindow(t time.Time) bool {
	p := t.In(pkt)
	if isWeekend(p) {
		return false
	}
	s := secondOf(p)
	return s >= scanOpen*60 && s < postWindow(p).to*60+scanGraceSecs
}

// inTradingBand is true only while the exchange is trading, which is when the
// big buying detector counts volume.
func inTradingBand(t time.Time) bool {
	p := t.In(pkt)
	if isWeekend(p) {
		return false
	}
	m := minuteOf(p)
	for _, w := range tradeWindows(p) {
		if w.has(m) {
			return true
		}
	}
	return false
}

// untilScanStart is how long until the next scanning window opens, counted
// from t, or zero when one is open now. It is used so that the slow check
// outside the window never makes the first scan late.
func untilScanStart(t time.Time) time.Duration {
	if inScanWindow(t) {
		return 0
	}
	p := t.In(pkt)
	day := time.Date(p.Year(), p.Month(), p.Day(), 8, 55, 0, 0, pkt)
	if !day.After(p) {
		day = day.AddDate(0, 0, 1)
	}
	for isWeekend(day) {
		day = day.AddDate(0, 0, 1)
	}
	return day.Sub(p)
}

// phaseAt names the part of the day Karachi time t falls in, in the five words
// the status tile needs. The pre-market runs from 09:00 to the open (so the
// two minute matching gap is part of it), and the post-market from the close
// to its end (15:30 to 15:49 Monday to Thursday, 16:30 to 16:49 on Friday).
func phaseAt(t time.Time) string {
	p := t.In(pkt)
	if isWeekend(p) {
		return qsClosed
	}
	m := minuteOf(p)
	wins := tradeWindows(p)
	if m >= preWindow.from && m < wins[0].from {
		return qsPre
	}
	for _, w := range wins {
		if w.has(m) {
			return qsOpen
		}
	}
	if isFriday(p) && m >= 12*60 && m < 14*60+32 {
		return qsBreak
	}
	if last := wins[len(wins)-1]; m >= last.to && m < postWindow(p).to {
		return qsPost
	}
	return qsClosed
}
