package main

import "testing"

// Owner order 2026-11-21: the console window wears this build's own icon, and
// the icons it had are put back when the build quits. The call must be safe on a
// window that has no icon of its own, and the restore it hands back must always
// be safe to run.
func TestBuild155ConsoleWindowBrandingIsSafe(t *testing.T) {
	restore := brandConsoleWindow()
	if restore == nil {
		t.Fatal("brandConsoleWindow handed back no restore function")
	}
	restore()
	restore()
}
