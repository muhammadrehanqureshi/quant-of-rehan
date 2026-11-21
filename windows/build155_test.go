package main

import (
	"strings"
	"testing"
)

// Owner order 2026-11-21: the build opens a console of its own when it was
// started inside a shell's console, so the taskbar carries the build's icon
// instead of the shell's. A console the exe made for itself, or one held only as
// a pipe, is left alone.
func TestBuild155OnlyASharedConsoleIsLeft(t *testing.T) {
	for _, attached := range []uint32{0, 1} {
		if sharedConsole(attached) {
			t.Errorf("%d processes on the console: the build would leave a console of its own", attached)
		}
	}
	for _, attached := range []uint32{2, 3, 9} {
		if !sharedConsole(attached) {
			t.Errorf("%d processes on the console: the build would stay in the shell's window", attached)
		}
	}
}

// The new console is started with a command line Windows parses back into the
// same arguments, so a folder or a flag with a space in it still arrives whole.
func TestBuild155NewConsoleCommandLine(t *testing.T) {
	cases := []struct {
		args []string
		want string
	}{
		{[]string{`C:\QOR\QuantOfRehan.exe`}, `C:\QOR\QuantOfRehan.exe`},
		{[]string{`C:\QOR\QuantOfRehan.exe`, "-demo"}, `C:\QOR\QuantOfRehan.exe -demo`},
		{[]string{`C:\Quant of Rehan\QuantOfRehan.exe`, "-relay", "http://x/y"}, `"C:\Quant of Rehan\QuantOfRehan.exe" -relay http://x/y`},
		{[]string{`C:\a b\q.exe`, `C:\dir\`}, `"C:\a b\q.exe" C:\dir\`},
		{[]string{`C:\a b\q.exe`, `say "hi"`}, `"C:\a b\q.exe" "say \"hi\""`},
		{[]string{""}, `""`},
	}
	for _, c := range cases {
		if got := windowsCommandLine(c.args); got != c.want {
			t.Errorf("windowsCommandLine(%q) = %q, want %q", c.args, got, c.want)
		}
	}
}

// A flag that carries a quote is doubled inside the quotes, never left to end
// the argument early.
func TestBuild155QuotedArgumentKeepsItsQuotes(t *testing.T) {
	got := windowsCommandLine([]string{"a b", `c:\x"y`})
	if strings.Count(got, `"`) < 4 {
		t.Fatalf("the quoted argument lost its own quotes: %q", got)
	}
}
