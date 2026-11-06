package main

import "sort"

// wireCycleSeconds is how often the broker's wire repeats one symbol. The
// owner's own audit (reports/2026-11-03-eclear-order-flow.md, section 1)
// measured a sweep of 23.98 seconds per symbol. The relay can pass on what the
// wire carries and no faster, so the freshest stock is almost always seconds
// old while a typical stock is about half a cycle old.
const wireCycleSeconds = 24

// feedStats describes how old the stocks in one /quotes answer are, at the
// moment the relay answered.
type feedStats struct {
	N      int // stocks with a fresh price
	Fresh5 int // of those, how many ticked within the last 5 seconds
	Min    int // the freshest tick, -1 when no stock has an age
	Median int // the typical stock
	P90    int // nine in ten stocks are this fresh or fresher
}

// quoteAges counts the stocks of one answer by age. Only stocks the relay calls
// fresh, with a price, and with a known age take part.
func quoteAges(q *Quotes) feedStats {
	st := feedStats{Min: -1, Median: -1, P90: -1}
	if q == nil {
		return st
	}
	ages := make([]int, 0, len(q.Items))
	for _, lq := range q.Items {
		if !lq.Fresh || lq.Price <= 0 || lq.AgeSeconds < 0 {
			continue
		}
		ages = append(ages, lq.AgeSeconds)
	}
	if len(ages) == 0 {
		return st
	}
	sort.Ints(ages)
	st.N = len(ages)
	st.Min = ages[0]
	st.Median = ages[len(ages)/2]
	st.P90 = ages[min(len(ages)-1, len(ages)*9/10)]
	for _, v := range ages {
		if v <= 5 {
			st.Fresh5++
		}
	}
	return st
}
