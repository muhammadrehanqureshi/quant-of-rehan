package main

import (
	"math"
	"strconv"
)

// RGB is a 24 bit colour.
type RGB struct{ R, G, B uint8 }

func hexc(s string) RGB {
	if len(s) == 7 && s[0] == '#' {
		r, _ := strconv.ParseUint(s[1:3], 16, 8)
		g, _ := strconv.ParseUint(s[3:5], 16, 8)
		b, _ := strconv.ParseUint(s[5:7], 16, 8)
		return RGB{uint8(r), uint8(g), uint8(b)}
	}
	return RGB{}
}

func mix(a, b RGB, t float64) RGB {
	if t <= 0 {
		return a
	}
	if t >= 1 {
		return b
	}
	f := func(x, y uint8) uint8 { return uint8(math.Round(float64(x) + (float64(y)-float64(x))*t)) }
	return RGB{f(a.R, b.R), f(a.G, b.G), f(a.B, b.B)}
}

func scale(c RGB, k float64) RGB {
	f := func(x uint8) uint8 {
		v := float64(x) * k
		if v > 255 {
			v = 255
		}
		if v < 0 {
			v = 0
		}
		return uint8(v)
	}
	return RGB{f(c.R), f(c.G), f(c.B)}
}

// Theme is one palette. Index 0 is the JARVIS look this port ships with; the
// other five are the themes from the Android app, keeping their names.
type Theme struct {
	Name   string
	BG     RGB // screen
	Panel  RGB // panel fill
	Field  RGB // input fill
	Line   RGB // panel outlines
	Accent RGB // headings, main ink
	Hot    RGB // brightest highlight
	Text   RGB
	Soft   RGB
	Good   RGB
	Bad    RGB
	Warn   RGB
	// pill colours
	OnGood, OnBad, GoodFill, BadFill RGB
}

var themes = []Theme{
	{
		Name: "JARVIS CYAN",
		BG:   hexc("#01060c"), Panel: hexc("#04121b"), Field: hexc("#03101a"), Line: hexc("#0e6a8c"),
		Accent: hexc("#00d4ff"), Hot: hexc("#cffaff"), Text: hexc("#d4f4ff"), Soft: hexc("#6aa6ba"),
		Good: hexc("#27f2a3"), Bad: hexc("#ff4a5c"), Warn: hexc("#ffb830"),
		OnGood: hexc("#eafff6"), OnBad: hexc("#fff0f0"), GoodFill: hexc("#0a5c3f"), BadFill: hexc("#7a1424"),
	},
	{
		Name: "PURPLE & YELLOW",
		BG:   hexc("#0b070d"), Panel: hexc("#170d1c"), Field: hexc("#120a16"), Line: hexc("#6b4577"),
		Accent: hexc("#d9a441"), Hot: hexc("#f8ce66"), Text: hexc("#f0eaf4"), Soft: hexc("#b9a6c2"),
		Good: hexc("#2fae6f"), Bad: hexc("#c14a52"), Warn: hexc("#f8ce66"),
		OnGood: hexc("#f2fbf6"), OnBad: hexc("#fdf3f3"), GoodFill: hexc("#1b6b45"), BadFill: hexc("#8e1f1f"),
	},
	{
		Name: "BLACK & WHITE",
		BG:   hexc("#000000"), Panel: hexc("#141414"), Field: hexc("#262626"), Line: hexc("#5e5e5e"),
		Accent: hexc("#ffffff"), Hot: hexc("#ffffff"), Text: hexc("#f0f0f0"), Soft: hexc("#a0a0a0"),
		Good: hexc("#2fae6f"), Bad: hexc("#c14a52"), Warn: hexc("#d9d9d9"),
		OnGood: hexc("#f2fbf6"), OnBad: hexc("#fdf3f3"), GoodFill: hexc("#1b6b45"), BadFill: hexc("#8e1f1f"),
	},
	{
		Name: "GREEN & YELLOW",
		BG:   hexc("#0b2417"), Panel: hexc("#143220"), Field: hexc("#1f4a2e"), Line: hexc("#4a8a63"),
		Accent: hexc("#d9a441"), Hot: hexc("#f8ce66"), Text: hexc("#eaf6ee"), Soft: hexc("#9cc4ac"),
		Good: hexc("#43c98a"), Bad: hexc("#d65f66"), Warn: hexc("#f8ce66"),
		OnGood: hexc("#f2fbf6"), OnBad: hexc("#fdf3f3"), GoodFill: hexc("#1b6b45"), BadFill: hexc("#8e1f1f"),
	},
	{
		Name: "NAVY BLUE & WHITE",
		BG:   hexc("#0a1330"), Panel: hexc("#131c3d"), Field: hexc("#1e2a55"), Line: hexc("#4458a8"),
		Accent: hexc("#ffffff"), Hot: hexc("#ffffff"), Text: hexc("#e8ecff"), Soft: hexc("#9aa6d6"),
		Good: hexc("#43c98a"), Bad: hexc("#d65f66"), Warn: hexc("#f8ce66"),
		OnGood: hexc("#f2fbf6"), OnBad: hexc("#fdf3f3"), GoodFill: hexc("#1b6b45"), BadFill: hexc("#8e1f1f"),
	},
	{
		Name: "ORANGE & WHITE",
		BG:   hexc("#2f1307"), Panel: hexc("#3f1b0c"), Field: hexc("#592812"), Line: hexc("#b3612a"),
		Accent: hexc("#ffffff"), Hot: hexc("#ffe3cf"), Text: hexc("#fff1e8"), Soft: hexc("#e0b9a0"),
		Good: hexc("#43c98a"), Bad: hexc("#ff6a6a"), Warn: hexc("#ffb830"),
		OnGood: hexc("#f2fbf6"), OnBad: hexc("#fdf3f3"), GoodFill: hexc("#1b6b45"), BadFill: hexc("#8e1f1f"),
	},
}

func themeAt(i int) *Theme {
	if i < 0 || i >= len(themes) {
		i = 0
	}
	return &themes[i]
}

// PanelHi is the lighter end of a panel's glass: the fill runs from it at the
// top edge to Panel at the bottom edge.
func (t *Theme) PanelHi() RGB { return mix(t.Panel, t.Accent, 0.07) }
