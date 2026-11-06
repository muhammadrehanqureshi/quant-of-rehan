package main

import (
	"fmt"
	"strings"
	"testing"
	"time"
)

func quotesWith(ages map[string]int, obs map[string]string) *Quotes {
	q := &Quotes{OK: true, Items: map[string]LiveQuote{}}
	for s, a := range ages {
		q.Items[s] = LiveQuote{Price: 10, Fresh: true, AgeSeconds: a, ObservedAt: obs[s]}
	}
	return q
}

func TestQuoteAges(t *testing.T) {
	q := quotesWith(map[string]int{"A": 0, "B": 3, "C": 9, "D": 12, "E": 20}, nil)
	q.Items["X"] = LiveQuote{Price: 5, Fresh: false, AgeSeconds: 99} // not fresh: ignored
	q.Items["Y"] = LiveQuote{Price: 0, Fresh: true, AgeSeconds: 1}   // no price: ignored
	q.Items["Z"] = LiveQuote{Price: 5, Fresh: true, AgeSeconds: -1}  // no age: ignored
	st := quoteAges(q)
	if st.N != 5 || st.Min != 0 || st.Median != 9 || st.Fresh5 != 2 || st.P90 != 20 {
		t.Fatalf("stats: %+v", st)
	}
	if e := quoteAges(nil); e.Min != -1 || e.N != 0 {
		t.Fatalf("empty: %+v", e)
	}
	if e := quoteAges(&Quotes{Items: map[string]LiveQuote{}}); e.Min != -1 {
		t.Fatalf("no items: %+v", e)
	}
}

// A feed where each stock repeats every 24 seconds but the sweep as a whole
// never stops: the freshest tick is seconds old, so the verdict is WIRE.
func TestFeedWatchSaysWire(t *testing.T) {
	w := newFeedWatcher()
	t0 := time.Date(2026, 11, 3, 11, 0, 0, 0, pkt)
	syms := []string{"A", "B", "C", "D", "E", "F", "G", "H"}
	for s := 0; s < 120; s++ {
		ages, obs := map[string]int{}, map[string]string{}
		for i, sym := range syms {
			phase := (s + i*3) % 24 // each stock is offset inside the 24 s cycle
			ages[sym] = phase
			obs[sym] = fmt.Sprintf("%s@%d", sym, (s+i*3)/24)
		}
		w.add(t0.Add(time.Duration(s)*time.Second), 120*time.Millisecond, quotesWith(ages, obs))
	}
	rep := strings.Join(w.report(), "\n")
	if !strings.Contains(rep, "VERDICT: WIRE") || !strings.Contains(rep, "every 24 s") {
		t.Fatalf("expected WIRE at 24 s:\n%s", rep)
	}
}

// The whole feed freezing for 25 seconds is a STALL, not the wire.
func TestFeedWatchSaysStall(t *testing.T) {
	w := newFeedWatcher()
	t0 := time.Date(2026, 11, 3, 11, 0, 0, 0, pkt)
	for s := 0; s < 90; s++ {
		age := s % 3
		if s >= 30 && s < 55 {
			age = 5 + (s - 30) // nothing new for 25 seconds
		}
		w.add(t0.Add(time.Duration(s)*time.Second), 100*time.Millisecond,
			quotesWith(map[string]int{"A": age, "B": age + 2}, map[string]string{"A": fmt.Sprint(s / 3), "B": fmt.Sprint(s / 3)}))
	}
	rep := strings.Join(w.report(), "\n")
	if !strings.Contains(rep, "VERDICT: STALL") {
		t.Fatalf("expected STALL:\n%s", rep)
	}
}

func TestFeedWatchSaysNetwork(t *testing.T) {
	w := newFeedWatcher()
	t0 := time.Date(2026, 11, 3, 11, 0, 0, 0, pkt)
	for s := 0; s < 20; s++ {
		var q *Quotes
		if s%4 != 0 {
			q = quotesWith(map[string]int{"A": 1}, map[string]string{"A": fmt.Sprint(s)})
		}
		w.add(t0.Add(time.Duration(s)*time.Second), 900*time.Millisecond, q)
	}
	if rep := strings.Join(w.report(), "\n"); !strings.Contains(rep, "VERDICT: NETWORK") {
		t.Fatalf("expected NETWORK:\n%s", rep)
	}
	empty := newFeedWatcher()
	if r := empty.report(); len(r) != 1 {
		t.Fatalf("empty report: %v", r)
	}
	for _, l := range append(w.report(), w.samples[0].line()) {
		if strings.ContainsAny(l, "\u2014\u2013") {
			t.Fatalf("no long dashes: %q", l)
		}
	}
}

// Every stock arriving in the same instant every 24 seconds is BURSTS, the
// sawtooth the LAGGING light shows, and not a one off stall.
func TestFeedWatchSaysBursts(t *testing.T) {
	w := newFeedWatcher()
	t0 := time.Date(2026, 11, 3, 11, 0, 0, 0, pkt)
	for s := 0; s < 130; s++ {
		age := s % 24
		w.add(t0.Add(time.Duration(s)*time.Second), 120*time.Millisecond,
			quotesWith(map[string]int{"A": age, "B": age, "C": age}, map[string]string{"A": fmt.Sprint(s / 24), "B": fmt.Sprint(s / 24), "C": fmt.Sprint(s / 24)}))
	}
	rep := strings.Join(w.report(), "\n")
	if !strings.Contains(rep, "VERDICT: BURSTS") {
		t.Fatalf("expected BURSTS:\n%s", rep)
	}
}
