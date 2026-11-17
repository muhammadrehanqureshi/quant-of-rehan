package main

import (
	"crypto/sha256"
	"encoding/hex"
	"os"
	"strings"
	"testing"
)

// ownerIconSHA256 is the exact picture the owner chose, committed as
// assets/icon-source.png, byte for byte his QoR.png (owner order 2026-11-17,
// which replaces his QoR.png of 2026-11-12): "this is the new/updated image
// for the project... this image will be the new ICON of the windows build as
// well". If this fails, restore his picture; never update the hash to match a
// replacement.
const ownerIconSHA256 = "439acc880074f97215395225b626e6732c403c339fa833fefb3adf0499e9b781"

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

// TestHeaderCarriesTheIndex pins the owner's full line at the top centre.
func TestHeaderCarriesTheIndex(t *testing.T) {
	if headerTag != "PSX'S KMIALL INDEX" {
		t.Fatalf("headerTag is %q, want %q", headerTag, "PSX'S KMIALL INDEX")
	}
	if !strings.Contains(strings.ToUpper(headerTag), "INDEX") {
		t.Fatalf("headerTag %q must carry INDEX", headerTag)
	}
}
