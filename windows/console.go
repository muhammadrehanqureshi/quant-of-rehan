package main

import (
	"fmt"
	"os"
	"path/filepath"
	"runtime/debug"
	"strings"
	"time"
)

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

// Owner order 2026-11-22: a build that closes before the HUD paints leaves a
// line in startup.log, so a window that flashes and vanishes is read from that
// file instead of guessed at. The log stands beside settings.json and holds one
// short line per run.
func startupLogPath() string {
	return filepath.Join(filepath.Dir(settingsPath()), "startup.log")
}

// noteStartup records this run before anything else touches the console.
func noteStartup() {
	noteStartupLine(fmt.Sprintf("start pid %d, %s, build %s", os.Getpid(), appVersion, hudBuild))
}

// noteCrash records what ended the run, with the stack that ended it.
func noteCrash(r any) {
	noteStartupLine(fmt.Sprintf("crash pid %d: %v\n%s", os.Getpid(), r, debug.Stack()))
}

func noteStartupLine(line string) {
	p := startupLogPath()
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		return
	}
	f, err := os.OpenFile(p, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return
	}
	fmt.Fprintf(f, "%s %s\n", time.Now().In(pkt).Format("2006-01-02 15:04:05"), line)
	f.Close()
}
