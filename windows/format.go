package main

import (
	"fmt"
	"math"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"
)

// commaInt formats like Java's %,d.
func commaInt(n int64) string {
	neg := n < 0
	if neg {
		n = -n
	}
	s := strconv.FormatInt(n, 10)
	var b strings.Builder
	if neg {
		b.WriteByte('-')
	}
	for i := 0; i < len(s); i++ {
		if i > 0 && (len(s)-i)%3 == 0 {
			b.WriteByte(',')
		}
		b.WriteByte(s[i])
	}
	return b.String()
}

// commaFloat formats like Java's %,.Nf.
func commaFloat(f float64, dec int) string {
	neg := f < 0
	s := strconv.FormatFloat(math.Abs(f), 'f', dec, 64)
	ip, fp, hasFrac := strings.Cut(s, ".")
	var b strings.Builder
	if neg && strings.Trim(s, "0.") != "" {
		b.WriteByte('-')
	}
	for i := 0; i < len(ip); i++ {
		if i > 0 && (len(ip)-i)%3 == 0 {
			b.WriteByte(',')
		}
		b.WriteByte(ip[i])
	}
	if hasFrac {
		b.WriteByte('.')
		b.WriteString(fp)
	}
	return b.String()
}

// arrow returns the direction glyph used across the app.
func arrow(v float64) string {
	if v >= 0 {
		return "▲"
	}
	return "▼"
}

// changeText renders "▲ 0.47%" with the absolute value.
func changeText(pct float64) string {
	return arrow(pct) + " " + strconv.FormatFloat(math.Abs(pct), 'f', 2, 64) + "%"
}

// indexLine renders the KSE100 line exactly like the Android card.
func indexLine(value, change, pct float64) string {
	return "KSE100  " + commaFloat(value, 2) + " " + arrow(change) + " " +
		commaFloat(math.Abs(change), 2) + " (" + strconv.FormatFloat(math.Abs(pct), 'f', 2, 64) + "%)"
}

func runeLen(s string) int { return utf8.RuneCountInString(s) }

// fit truncates to w runes, ending with an ellipsis when cut.
func fit(s string, w int) string {
	if w <= 0 {
		return ""
	}
	if runeLen(s) <= w {
		return s
	}
	r := []rune(s)
	if w == 1 {
		return string(r[:1])
	}
	return string(r[:w-1]) + "…"
}

// padRight pads with spaces to w runes (no truncation).
func padRight(s string, w int) string {
	n := runeLen(s)
	if n >= w {
		return s
	}
	return s + strings.Repeat(" ", w-n)
}

// wrap breaks text into lines of at most w runes, on spaces where possible.
func wrap(s string, w int) []string {
	if w < 4 {
		return []string{fit(s, w)}
	}
	var out []string
	for _, para := range strings.Split(s, "\n") {
		para = strings.TrimRight(para, " \t\r")
		if para == "" {
			out = append(out, "")
			continue
		}
		words := strings.Fields(para)
		line := ""
		for _, wd := range words {
			for runeLen(wd) > w {
				if line != "" {
					out = append(out, line)
					line = ""
				}
				r := []rune(wd)
				out = append(out, string(r[:w]))
				wd = string(r[w:])
			}
			switch {
			case line == "":
				line = wd
			case runeLen(line)+1+runeLen(wd) <= w:
				line += " " + wd
			default:
				out = append(out, line)
				line = wd
			}
		}
		if line != "" {
			out = append(out, line)
		}
	}
	return out
}

// plural writes a count with its noun, adding an s when there is not exactly one.
func plural(n int, noun string) string {
	if n == 1 {
		return "1 " + noun
	}
	return strconv.Itoa(n) + " " + noun + "s"
}

// friendlyNext words the relay's next event, such as "OPEN 2026-11-02 09:32",
// the way a person would say it. An OPEN is the next scanning window, which
// starts at scanOpen (08:55), not the exchange's 09:32 opening bell, so the
// telemetry says "Mon 02 Nov, 08:55". A CLOSE keeps the relay's time.
// Anything it does not recognise is shown as the relay sent it.
func friendlyNext(s string) string {
	parts := strings.Fields(s)
	if len(parts) != 3 {
		return s
	}
	day, err := time.ParseInLocation("2006-01-02", parts[1], pkt)
	if err != nil {
		return s
	}
	switch strings.ToUpper(parts[0]) {
	case "OPEN":
		return fmt.Sprintf("%s, %02d:%02d", day.Format("Mon 02 Jan"), scanOpen/60, scanOpen%60)
	case "CLOSE":
		return "Closes " + day.Format("Mon 02 Jan") + ", " + parts[2]
	}
	return s
}

// sentence ends s with a full stop unless it already ends in a mark that
// closes a sentence, so a title and a body read as two proper sentences.
func sentence(s string) string {
	s = strings.TrimSpace(s)
	if s == "" {
		return s
	}
	switch s[len(s)-1] {
	case '.', '!', '?', ':':
		return s
	}
	return s + "."
}
