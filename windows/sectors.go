package main

import (
	"context"
	"strings"
	"time"
)

// Sector is one group of KMIALL scrips as the relay's /sectors answer words it.
type Sector struct {
	Name    string
	Symbols []string
}

// Sectors is the parsed /sectors answer. The relay builds it from the same
// KMIALL membership list the Android app uses, and it is read only.
type Sectors struct {
	OK        bool
	Source    string
	AsOf      string
	Items     []Sector
	Err       string
	FetchedAt time.Time
}

// ParseSectors reads the relay answer:
// {ok, source, as_of, sectors:[{name, symbols:[...]}]}.
func ParseSectors(o J) *Sectors {
	s := &Sectors{OK: o.boolean("ok", false), Source: o.str("source", ""), AsOf: o.str("as_of", "")}
	if !s.OK {
		s.Err = o.str("error", "The relay did not return a sector list.")
		return s
	}
	for _, row := range o.arr("sectors") {
		obj := objOf(row)
		if obj == nil {
			continue
		}
		name := strings.ToUpper(strings.TrimSpace(obj.str("name", "")))
		if name == "" {
			continue
		}
		seen := map[string]bool{}
		var syms []string
		for _, raw := range obj.arr("symbols") {
			sym, ok := raw.(string)
			if !ok {
				continue
			}
			sym = strings.ToUpper(strings.TrimSpace(sym))
			if sym == "" || seen[sym] {
				continue
			}
			seen[sym] = true
			syms = append(syms, sym)
		}
		if len(syms) == 0 {
			continue
		}
		s.Items = append(s.Items, Sector{Name: name, Symbols: syms})
	}
	if len(s.Items) == 0 {
		s.Err = "The relay returned no sectors."
	}
	return s
}

// FetchSectors reads the sector groups. A refusal is returned with the parsed
// answer, so the screen can say what the relay said rather than pretend there
// are no sectors.
func (r *Relay) FetchSectors(ctx context.Context) (*Sectors, error) {
	o, _, err := r.get(ctx, "/sectors")
	if err != nil {
		return nil, err
	}
	s := ParseSectors(o)
	s.FetchedAt = time.Now()
	if !s.OK {
		return s, &sectorError{s.Err}
	}
	return s, nil
}

type sectorError struct{ text string }

func (e *sectorError) Error() string { return e.text }
