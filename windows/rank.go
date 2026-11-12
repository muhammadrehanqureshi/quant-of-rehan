package main

import "sort"

// cappedMoveMark is the APK's CAPPED_MOVE_MARK: a move at or above this is
// treated as a circuit capped print and is not "rising fast".
const cappedMoveMark = 4.9

// volumeOf is the traded total a scrip is ranked by: the relay's own total when
// it carries one, otherwise the measured buy and sell pair.
func volumeOf(q Quote) (int64, bool) {
	if q.Volume != nil {
		return *q.Volume, true
	}
	if q.Buy != nil && q.Sell != nil {
		return *q.Buy + *q.Sell, true
	}
	return 0, false
}

// top3 keeps the three scrips a CUSTOM SCRIPS OF VOLUME sort names.
func top3(out []string) []string {
	if len(out) > 3 {
		out = out[:3]
	}
	return out
}

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
	return top3(out)
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
	return top3(out)
}

// rankedSellerSymbols: MORE SELLERS & LESS BUYERS. Only rows with both sides
// reported and sell above buy, the heaviest sell side first, ties by symbol,
// top three. Owner order 2026-11-12: the three names are decided by volume, so
// the biggest seller prints lead.
func rankedSellerSymbols(q map[string]Quote) []string {
	var out []string
	for s, v := range q {
		if v.Buy != nil && v.Sell != nil && *v.Sell > *v.Buy {
			out = append(out, s)
		}
	}
	sort.Slice(out, func(i, j int) bool {
		a, b := *q[out[i]].Sell, *q[out[j]].Sell
		if a != b {
			return a > b
		}
		return out[i] < out[j]
	})
	return top3(out)
}

// rankedQuietSymbols: ALMOST NO VOLUME AT ALL. The lightest traded volume
// first, ties by symbol, top three. A scrip with no volume at all carries no
// pair to show, so it is left out.
func rankedQuietSymbols(q map[string]Quote) []string {
	var out []string
	for s, v := range q {
		if n, ok := volumeOf(v); ok && n > 0 {
			out = append(out, s)
		}
	}
	sort.Slice(out, func(i, j int) bool {
		a, _ := volumeOf(q[out[i]])
		b, _ := volumeOf(q[out[j]])
		if a != b {
			return a < b
		}
		return out[i] < out[j]
	})
	return top3(out)
}

// rankedLockSymbols ranks one side's locked prints. Owner order 2026-11-12: a
// scrip is at its lock when its move is at or beyond the app's own capped move
// mark in that direction, which is the same 4.9 percent the APK calls a circuit
// capped print, and the three named are the heaviest by volume.
func rankedLockSymbols(q map[string]Quote, down bool) []string {
	var out []string
	for s, v := range q {
		if v.ChangePct == nil {
			continue
		}
		ch := *v.ChangePct
		if down {
			if ch > -cappedMoveMark {
				continue
			}
		} else if ch < cappedMoveMark {
			continue
		}
		out = append(out, s)
	}
	sort.Slice(out, func(i, j int) bool {
		a, _ := volumeOf(q[out[i]])
		b, _ := volumeOf(q[out[j]])
		if a != b {
			return a > b
		}
		return out[i] < out[j]
	})
	return top3(out)
}

// rankedLowerLockSymbols: SCRIPS WITH LOWER LOCK.
func rankedLowerLockSymbols(q map[string]Quote) []string { return rankedLockSymbols(q, true) }

// rankedUpperLockSymbols: SCRIPS WITH UPPER LOCK.
func rankedUpperLockSymbols(q map[string]Quote) []string { return rankedLockSymbols(q, false) }
