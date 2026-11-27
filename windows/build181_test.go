package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-27 (the joined banner): the phrase reached the screen as
// separate letters with air between them, because a console hands the terminal
// one cell at a time and the terminal never joins a run it is not given whole.
// The banner therefore draws the Arabic PRESENTATION FORMS, where every letter
// already carries the shape its own neighbours give it.
func TestBuild181TheBannerIsThePhraseInJoinedForms(t *testing.T) {
	// Every form the banner may use, mapped back to the letter it shapes.
	formBase := map[rune]rune{
		0xFE91: 'ب', // BEH INITIAL
		0xFEB4: 'س', // SEEN MEDIAL
		0xFEE2: 'م', // MEEM FINAL
		0xFEE4: 'م', // MEEM MEDIAL
		0xFE8D: 'ا', // ALEF ISOLATED
		0xFEDF: 'ل', // LAM INITIAL
		0xFEE0: 'ل', // LAM MEDIAL
		0xFEEA: 'ه', // HEH FINAL
		0xFEAE: 'ر', // REH FINAL
		0xFEA3: 'ح', // HAH INITIAL
		0xFEE6: 'ن', // NOON FINAL
		0xFEF4: 'ي', // YEH MEDIAL
	}
	letters := make([]rune, 0, len(basmalaBanner))
	for _, r := range basmalaBanner {
		if r == ' ' {
			continue
		}
		base, ok := formBase[r]
		if !ok {
			t.Fatalf("the banner carries U+%04X, which is not one of the phrase's joined forms", r)
		}
		letters = append(letters, base)
	}
	said := string(letters)
	want := strings.ReplaceAll(basmalaWords, " ", "")
	if said != want {
		t.Fatalf("the banner spells %q, want %q", said, want)
	}
}

// No letter may wear its isolated shape where a neighbour joins it: an isolated
// glyph carries no join stroke, which is the gap he reported.
func TestBuild181NoJoinedLetterKeepsItsIsolatedShape(t *testing.T) {
	isolated := []rune{
		0xFE8F, // BEH ISOLATED
		0xFEB1, // SEEN ISOLATED
		0xFEE1, // MEEM ISOLATED
		0xFEDD, // LAM ISOLATED
		0xFEE9, // HEH ISOLATED
		0xFEA1, // HAH ISOLATED
		0xFEE5, // NOON ISOLATED
		0xFEF1, // YEH ISOLATED
	}
	for _, r := range isolated {
		if strings.ContainsRune(basmalaBanner, r) {
			t.Fatalf("the banner carries the isolated form U+%04X", r)
		}
	}
	// The joins the phrase really has, spelled out, so a later edit cannot
	// quietly swap one for another.
	for _, want := range []rune{
		0xFE91, // ب joins its neighbour
		0xFEB4, // س joins both neighbours
		0xFEE2, // م closes its word
		0xFEDF, // ل opens
		0xFEE0, // ل joins
		0xFEAE, // ر closes after ل
		0xFEA3, // ح opens after ر
		0xFEE6, // ن closes
		0xFEF4, // ي joins
	} {
		if !strings.ContainsRune(basmalaBanner, want) {
			t.Fatalf("the banner lost the joined form U+%04X", want)
		}
	}
}

// The banner is one line: the words are drawn once, centred, and nothing else
// stands on the gate with them.
func TestBuild181TheBannerIsOneCentredLine(t *testing.T) {
	a := lockedApp(t, 100, 30)
	typeRunes(a, wantUnlockPassword)
	a.onKey(Key{Kind: KEnter})
	rows := a.render().PlainRows()
	hits := 0
	for _, row := range rows {
		if strings.Contains(row, basmalaBanner) {
			hits++
		}
		if strings.Contains(row, basmalaWords) {
			t.Fatalf("the gate still draws the unjoined letters:\n%s",
				strings.Join(rows, "\n"))
		}
	}
	if hits != 1 {
		t.Fatalf("the banner stands on %d rows, want one", hits)
	}
}
