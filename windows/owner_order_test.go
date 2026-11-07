package main

import (
	"crypto/sha256"
	"encoding/hex"
	"os"
	"strings"
	"testing"
)

// ownerIconSHA256 is the exact picture the owner chose, committed as
// assets/icon-source.png, byte for byte his logo2.png. Owner order 2026-11-07:
// "make sure you never change that unless I tell you." If this fails, restore
// his picture; never update the hash to match a replacement.
const ownerIconSHA256 = "4298b15cff8e08ca1da1b986df1c3fe0ebf6e0dbdb3db2fe03c3767f93a623e4"

func TestIconIsTheOwnersExactPicture(t *testing.T) {
	raw, err := os.ReadFile("assets/icon-source.png")
	if err != nil {
		t.Fatalf("the owner's icon picture is missing: %v", err)
	}
	sum := sha256.Sum256(raw)
	if got := hex.EncodeToString(sum[:]); got != ownerIconSHA256 {
		t.Fatalf("assets/icon-source.png is %s, want the owner's picture %s", got, ownerIconSHA256)
	}
}

// TestIconGeneratorNeverRedraws guards the other half of the order: the build
// must use the picture, not a drawn stand-in.
func TestIconGeneratorNeverRedraws(t *testing.T) {
	raw, err := os.ReadFile("tools/mkicon_hud.py")
	if err != nil {
		t.Fatalf("the icon generator is missing: %v", err)
	}
	src := string(raw)
	if !strings.Contains(src, "source_art()") && !strings.Contains(src, "Image.open(SOURCE)") {
		t.Fatal("mkicon_hud.py no longer reads the owner's picture")
	}
	if strings.Contains(src, "def dial(") {
		t.Fatal("mkicon_hud.py draws its own dial again; the icon must be the owner's picture")
	}
}

// TestHeaderCarriesNoIndex pins the owner's line at the top centre.
func TestHeaderCarriesNoIndex(t *testing.T) {
	if headerTag != "PSX'S KMIALL" {
		t.Fatalf("headerTag is %q, want %q", headerTag, "PSX'S KMIALL")
	}
	if strings.Contains(strings.ToUpper(headerTag), "INDEX") {
		t.Fatalf("headerTag %q still carries INDEX", headerTag)
	}
}
