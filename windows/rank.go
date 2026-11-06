package main

import "sort"

// cappedMoveMark is the APK's CAPPED_MOVE_MARK: a move at or above this is
// treated as a circuit capped print and is not "rising fast".
const cappedMoveMark = 4.9

// rankedSpeedSymbols: PRICES RISING FAST. Positive move below the cap, biggest
// first, ties by symbol, top three.
func rankedSpeedSymbols(q map[string]Quote) []string {
	var out []string
	for s, v := range q {
		if v.ChangePct != nil && *v.ChangePct > 0 && *v.ChangePct < cappedMoveMark {
			out = append(out, s)
		}
	}
	sort.Slice(out, func(i, j int) bool {
		a, b := *q[out[i]].ChangePct, *q[out[j]].ChangePct
		if a != b {
			return a > b
		}
		return out[i] < out[j]
	})
	if len(out) > 3 {
		out = out[:3]
	}
	return out
}

// rankedSplitSymbols: MORE BUYERS & LESS SELLERS. Only rows with both sides
// reported and buy above sell, widest gap first, ties by symbol, top three.
func rankedSplitSymbols(q map[string]Quote) []string {
	var out []string
	for s, v := range q {
		if v.Buy != nil && v.Sell != nil && *v.Buy > *v.Sell {
			out = append(out, s)
		}
	}
	sort.Slice(out, func(i, j int) bool {
		a := *q[out[i]].Buy - *q[out[i]].Sell
		b := *q[out[j]].Buy - *q[out[j]].Sell
		if a != b {
			return a > b
		}
		return out[i] < out[j]
	})
	if len(out) > 3 {
		out = out[:3]
	}
	return out
}
