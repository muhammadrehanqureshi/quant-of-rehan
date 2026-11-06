package main

import (
	"context"
	"fmt"
	"io"
	"os"
	"sort"
	"strings"
	"time"
)

// -feedwatch N asks the relay for /quotes once a second for N seconds and
// writes down what it sees: how old the freshest and the typical stock are,
// how often each stock repeats, and whether the whole feed ever stops. It
// answers one question with numbers instead of a feeling: when the lag shows,
// is it the broker's wire (every stock only repeats every 24 s), a stall
// somewhere upstream (nothing new for a while), or the network.

type watchSample struct {
	at      time.Time
	ok      bool
	rtt     time.Duration
	stats   feedStats
	changed int // stocks whose tick time moved since the last answer
}

type feedWatcher struct {
	samples    []watchSample
	lastObs    map[string]string
	lastChange map[string]time.Time
	repeats    []float64 // seconds between two ticks of the same stock
}

func newFeedWatcher() *feedWatcher {
	return &feedWatcher{lastObs: map[string]string{}, lastChange: map[string]time.Time{}}
}

// add records one answer, or one failure when q is nil.
func (w *feedWatcher) add(at time.Time, rtt time.Duration, q *Quotes) watchSample {
	s := watchSample{at: at, rtt: rtt}
	if q != nil {
		s.ok = true
		s.stats = quoteAges(q)
		for sym, lq := range q.Items {
			if lq.ObservedAt == "" {
				continue
			}
			prev, seen := w.lastObs[sym]
			if seen && prev != lq.ObservedAt {
				s.changed++
				if t, had := w.lastChange[sym]; had {
					w.repeats = append(w.repeats, at.Sub(t).Seconds())
				}
				w.lastChange[sym] = at
			} else if !seen {
				w.lastObs[sym] = lq.ObservedAt
				continue
			}
			w.lastObs[sym] = lq.ObservedAt
		}
	}
	w.samples = append(w.samples, s)
	return s
}

func median(v []float64) float64 {
	if len(v) == 0 {
		return 0
	}
	c := append([]float64(nil), v...)
	sort.Float64s(c)
	return c[len(c)/2]
}

// report is the summary and the plain verdict.
func (w *feedWatcher) report() []string {
	var out []string
	n := len(w.samples)
	if n == 0 {
		return []string{"No answers were recorded."}
	}
	var okN, fresh, worstMin int
	var rtts []float64
	stall, longest := 0, 0
	var slowest time.Duration
	for _, s := range w.samples {
		if !s.ok {
			stall++
			longest = max(longest, stall)
			continue
		}
		okN++
		rtts = append(rtts, float64(s.rtt.Milliseconds()))
		slowest = max(slowest, s.rtt)
		if s.stats.Min >= 0 && s.stats.Min <= 5 {
			fresh++
			stall = 0
		} else {
			stall++
			longest = max(longest, stall)
		}
		worstMin = max(worstMin, s.stats.Min)
	}
	out = append(out, fmt.Sprintf("Answers: %d of %d (%d failed)", okN, n, n-okN))
	if okN == 0 {
		return append(out, "VERDICT: NETWORK. The relay never answered. Check the connection and the relay address.")
	}
	out = append(out, fmt.Sprintf("Round trip: median %.0f ms, slowest %d ms", median(rtts), slowest.Milliseconds()))
	out = append(out, fmt.Sprintf("Freshest tick: 5 s or less in %d%% of answers, oldest seen %d s", fresh*100/okN, worstMin))
	out = append(out, fmt.Sprintf("Longest stretch with no stock newer than 5 s: %d s", longest))
	// A burst feed: the freshest tick ages 0, 1, 2 ... and then drops back to
	// 0 on a steady beat, because every stock arrives in the same instant.
	var resets []float64
	var lastReset time.Time
	for i := 1; i < n; i++ {
		p, c := w.samples[i-1], w.samples[i]
		if p.ok && c.ok && p.stats.Min >= 8 && c.stats.Min >= 0 && c.stats.Min <= 2 {
			if !lastReset.IsZero() {
				resets = append(resets, c.at.Sub(lastReset).Seconds())
			}
			lastReset = c.at
		}
	}
	burst := len(resets) >= 2 && median(resets) >= 10
	if burst {
		lo, hi := resets[0], resets[0]
		for _, v := range resets {
			lo, hi = min(lo, v), max(hi, v)
		}
		burst = hi-lo <= 0.4*median(resets)+2
	}
	if len(resets) > 0 {
		out = append(out, fmt.Sprintf("The freshest tick reset to new %d times, about every %.0f s", len(resets)+1, median(resets)))
	}
	rep := median(w.repeats)
	if len(w.repeats) > 0 {
		out = append(out, fmt.Sprintf("One stock repeats about every %.0f s (median of %d repeats)", rep, len(w.repeats)))
	} else {
		out = append(out, "One stock repeats: not enough answers to tell, run it longer")
	}
	switch {
	case (n-okN)*100/n >= 5 || median(rtts) > 1500:
		out = append(out, "VERDICT: NETWORK. Answers fail or crawl. That is the link between this PC and the relay.")
	case burst:
		out = append(out, fmt.Sprintf("VERDICT: BURSTS. Every stock arrives together about every %.0f s, and between bursts the freshest tick ages, which is the LAGGING light. That fits the broker's wire cycle in your own audit (about 24 s). This app cannot shorten it, and neither can the relay. Only a faster source than that wire could.", median(resets)))
	case longest >= 10:
		out = append(out, fmt.Sprintf("VERDICT: STALL. The whole feed went quiet for up to %d s, so no stock was newer than that. The cause is upstream of this app, in the feeder or the relay. Send this file to the agent.", longest))
	case len(w.repeats) > 0 && rep >= 10:
		out = append(out, fmt.Sprintf("VERDICT: WIRE. The feed as a whole is live, but each stock only repeats about every %.0f s. That is how the broker sends it. No setting in this app can make one stock tick faster than the wire.", rep))
	case len(w.repeats) > 0:
		out = append(out, "VERDICT: CLEAN. Stocks refreshed every few seconds and nothing stalled.")
	default:
		out = append(out, "VERDICT: NOT ENOUGH DATA. Run it for at least two minutes while the market is trading.")
	}
	return out
}

func (s watchSample) line() string {
	t := s.at.In(pkt).Format("15:04:05")
	if !s.ok {
		return fmt.Sprintf("%s  FAILED after %d ms", t, s.rtt.Milliseconds())
	}
	return fmt.Sprintf("%s  %5d ms  %3d stocks  freshest %2d s  typical %2d s  nine in ten within %2d s  %2d new ticks",
		t, s.rtt.Milliseconds(), s.stats.N, s.stats.Min, s.stats.Median, s.stats.P90, s.changed)
}

// feedWatch runs the watch for the given seconds, printing to out and to
// qor-feedwatch.txt in the current folder, and returns the exit code.
func feedWatch(base string, seconds int, out io.Writer) int {
	seconds = max(10, min(seconds, 900))
	r := NewRelay(base)
	var w io.Writer = out
	if f, err := os.Create("qor-feedwatch.txt"); err == nil {
		defer f.Close()
		w = io.MultiWriter(out, f)
	}
	fmt.Fprintf(w, "Quant of Rehan feed watch, %d seconds, relay %s\n", seconds, r.Base)
	fmt.Fprintf(w, "Started %s. It costs %d of the free 100,000 daily relay requests.\n", time.Now().In(pkt).Format("2006-01-02 15:04:05 MST"), seconds)
	fmt.Fprintln(w, strings.Repeat("-", 100))
	fw := newFeedWatcher()
	start := time.Now()
	for i := 0; i < seconds; i++ {
		if d := time.Until(start.Add(time.Duration(i) * time.Second)); d > 0 {
			time.Sleep(d)
		}
		ctx, cancel := context.WithTimeout(context.Background(), 4*time.Second)
		t0 := time.Now()
		q, err := r.FetchQuotes(ctx)
		rtt := time.Since(t0)
		cancel()
		if err != nil || q == nil || !q.OK {
			q = nil
		}
		fmt.Fprintln(w, fw.add(t0, rtt, q).line())
	}
	fmt.Fprintln(w, strings.Repeat("-", 100))
	for _, l := range fw.report() {
		fmt.Fprintln(w, l)
	}
	fmt.Fprintln(w, "Saved as qor-feedwatch.txt in this folder.")
	return 0
}
