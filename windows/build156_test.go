package main

import (
	"testing"
	"unicode/utf16"
)

// Owner order 2026-11-22: a console hosted by Windows Terminal is moved to the
// classic host for the build's own window, which is the only host that draws the
// icon this exe carries. The pair used is Microsoft's documented one.
func TestBuild156ClassicConsolePair(t *testing.T) {
	d := classicDelegation()
	if d.Console != "{B23D10C0-E52E-411E-9D5B-C09FDF709C7D}" {
		t.Fatalf("console value = %q", d.Console)
	}
	if d.Terminal != d.Console {
		t.Fatalf("terminal value = %q, want the console value", d.Terminal)
	}
	if !d.HasConsole || !d.HasTerminal {
		t.Fatal("both values must be written, not deleted")
	}
}

// The pair lives under a key whose name really carries two percent signs.
func TestBuild156StartupKey(t *testing.T) {
	if startupKey != `Console\%%Startup` {
		t.Fatalf("startup key = %q", startupKey)
	}
}

// The child of a handoff is told so in its own environment, sorted the way
// Windows expects, and the block ends in the second NUL Windows reads.
func TestBuild156ChildEnvironmentBlock(t *testing.T) {
	block := envBlock([]string{"B=2", "A=1", consoleChildEnv + "=1"})
	got := string(utf16.Decode(block))
	want := "A=1\x00B=2\x00QOR_CONSOLE_CHILD=1\x00\x00"
	if got != want {
		t.Fatalf("environment block = %q, want %q", got, want)
	}
}

// A run killed between the two registry writes leaves the found pair parked, and
// the next start puts it back exactly: an absent value stays absent.
func TestBuild156ParkedPairKeepsAbsentValues(t *testing.T) {
	found := delegation{Console: "{11}", HasConsole: true}
	parkDelegation(found)
	defer unparkDelegation()
	back, ok := parkedDelegation()
	if !ok {
		t.Fatal("the parked pair was not read back")
	}
	if back.Console != "{11}" || !back.HasConsole {
		t.Fatalf("console = %q present %v", back.Console, back.HasConsole)
	}
	if back.HasTerminal {
		t.Fatal("a value that was absent came back present")
	}
}
