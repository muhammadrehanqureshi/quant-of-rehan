package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-08: the index line is a size below the title. A console
// has one font size, so the line is set in Unicode small capitals: the same
// words and the same eighteen cells, with smaller letterforms.
func TestTaglineIsSmallCapped(t *testing.T) {
	if runeLen(headerTagSmall) != runeLen(headerTag) {
		t.Errorf("the small-caps line is %d cells, want the plain line's %d",
			runeLen(headerTagSmall), runeLen(headerTag))
	}
	if headerTagSmall == headerTag {
		t.Error("the tagline is still set at the title's size")
	}
	if !strings.HasSuffix(headerTagSmall, "ɪɴᴅᴇx") {
		t.Errorf("the small-caps line lost INDEX: %q", headerTagSmall)
	}
}
