package main

import (
	"regexp"
	"strings"
	"testing"
)

// Owner order 2026-11-17: every KSE100 leader volume keeps nine digit
// positions, commas not counted, so S, U and T stand on the same cells on all
// three rows.
func TestKSE100VolumesKeepNineDigits(t *testing.T) {
	a := busyApp(t, 158, 41, 3)
	rows := rowsOf(a)
	inside := false
	field := regexp.MustCompile(`(?:B|S|U|T)=([\d,]+)`)
	var sAt, uAt, tAt []int
	checked := 0
	for _, row := range rows {
		switch {
		case strings.Contains(row, "KSE100 INDEX & THE TOP 3 SCRIPS OF VOLUME"):
			inside = true
			continue
		case strings.Contains(row, "BUYING NOW"):
			inside = false
		}
		if !inside || !strings.Contains(row, "B=") || !strings.Contains(row, "&  T=") {
			continue
		}
		matches := field.FindAllStringSubmatch(row, -1)
		if len(matches) != 4 {
			t.Fatalf("a leader row carries %d volume fields, want four: %q", len(matches), row)
		}
		for _, m := range matches {
			digits := 0
			for _, r := range m[1] {
				if r >= '0' && r <= '9' {
					digits++
				}
			}
			if digits > leaderVolDigits {
				t.Fatalf("a volume field has %d digits, more than the fixed %d: %q", digits, leaderVolDigits, row)
			}
		}
		for _, label := range []string{"S", "U"} {
			at := strings.Index(row, label+"=")
			v := row[at+2:]
			end := strings.IndexByte(v, ' ')
			if label == "S" {
				if end < 0 || end == 0 || v[end-1] != ',' {
					t.Fatalf("S value does not end with a comma: %q", row)
				}
				continue
			}
			if end < 0 || end == 0 || v[end-1] < '0' || v[end-1] > '9' {
				t.Fatalf("U value does not end on a digit: %q", row)
			}
		}
		sAt = append(sAt, col(row, "S="))
		uAt = append(uAt, col(row, "U="))
		tAt = append(tAt, col(row, "T="))
		checked++
	}
	if checked < 3 {
		t.Fatalf("only %d leader rows carried volumes, want three:\n%s", checked, strings.Join(rows, "\n"))
	}
	for i := 1; i < checked; i++ {
		if sAt[i] != sAt[0] || uAt[i] != uAt[0] || tAt[i] != tAt[0] {
			t.Fatalf("leader %d puts S/U/T on %d/%d/%d, the first row on %d/%d/%d",
				i+1, sAt[i], uAt[i], tAt[i], sAt[0], uAt[0], tAt[0])
		}
	}
}

// Owner order 2026-11-17: one blank row stands between CUSTOM SCRIPS OF VOLUME
// and the calculator pair.
func TestCalculatorPairHasOneBlankRowAboveIt(t *testing.T) {
	a := demoApp(t, 158, 41)
	a.screen = scrScanner
	rows := rowsOf(a)
	at := -1
	for i, row := range rows {
		if strings.Contains(row, "POSITION CALCULATOR") {
			at = i
			break
		}
	}
	if at < 1 {
		t.Fatalf("the scanner did not draw POSITION CALCULATOR:\n%s", strings.Join(rows, "\n"))
	}
	if strings.TrimSpace(rows[at-1]) != "" {
		t.Fatalf("the row above POSITION CALCULATOR is not blank: %q", rows[at-1])
	}
}
