package main

import "strings"

// windowsCommandLine joins arguments the way Windows parses a command line: an
// argument is quoted only when it needs to be, and a backslash before a quote is
// doubled, so a path or a flag with a space in it reaches the new console whole.
func windowsCommandLine(args []string) string {
	var b strings.Builder
	for i, a := range args {
		if i > 0 {
			b.WriteByte(' ')
		}
		if a != "" && !strings.ContainsAny(a, " \t\n\v\"") {
			b.WriteString(a)
			continue
		}
		b.WriteByte('"')
		slashes := 0
		for _, r := range a {
			switch r {
			case '\\':
				slashes++
			case '"':
				b.WriteString(strings.Repeat(`\`, slashes*2+1))
				b.WriteRune(r)
				slashes = 0
				continue
			default:
				slashes = 0
			}
			b.WriteRune(r)
		}
		b.WriteString(strings.Repeat(`\`, slashes*2))
		b.WriteByte('"')
	}
	return b.String()
}

// sharedConsole reports whether a console is attached to more than one process.
// That is the case when the build was started from a shell's own console, whose
// window, title and icon belong to the shell. A console the build makes for
// itself carries exactly one process.
func sharedConsole(attached uint32) bool { return attached > 1 }
