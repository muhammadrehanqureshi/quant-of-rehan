package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"unicode/utf16"
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

// consoleChildEnv marks the process this build started in a console of its own.
// A child never opens a second console, so a handoff that fails cannot loop.
const consoleChildEnv = "QOR_CONSOLE_CHILD"

// classicConsoleCLSID is Microsoft's CLSID for the classic Windows Console
// Host, the pair of values under HKCU\Console\%%Startup that means "no Windows
// Terminal". Windows Terminal draws its own tab and taskbar icons and lets no
// program change them; the classic host draws the icon the exe carries, which
// is the one the owner wants on this build.
const classicConsoleCLSID = "{B23D10C0-E52E-411E-9D5B-C09FDF709C7D}"

// startupKey is where Windows keeps the two delegation values. The key's name
// really does carry the two percent signs.
const startupKey = `Console\%%Startup`

// delegation is the pair of values Windows reads under startupKey when it
// decides which program hosts a new console window. An absent value is
// remembered as absent, so the pair goes back exactly as it was found.
type delegation struct {
	Console     string `json:"console"`
	Terminal    string `json:"terminal"`
	HasConsole  bool   `json:"has_console"`
	HasTerminal bool   `json:"has_terminal"`
}

// classicDelegation is the pair that makes the Windows Console Host the host.
func classicDelegation() delegation {
	return delegation{
		Console:     classicConsoleCLSID,
		Terminal:    classicConsoleCLSID,
		HasConsole:  true,
		HasTerminal: true,
	}
}

// envBlock is a CreateProcessW environment block: the entries sorted the way
// Windows expects them, each ending in a NUL, and the block ending in a second
// NUL. The child gets this block instead of the parent's environment, so it
// carries consoleChildEnv and knows it is already in its own console.
func envBlock(env []string) []uint16 {
	sorted := append([]string(nil), env...)
	sort.Slice(sorted, func(i, j int) bool {
		return strings.ToUpper(sorted[i]) < strings.ToUpper(sorted[j])
	})
	var u []uint16
	for _, e := range sorted {
		u = append(u, utf16.Encode([]rune(e))...)
		u = append(u, 0)
	}
	return append(u, 0)
}

// parkedDelegationPath is the file the found pair waits in while the build
// opens a console of its own. A run killed between the registry writes leaves
// it behind, and the next start puts the pair back before anything else. It
// stands beside the settings file, so one folder holds both.
func parkedDelegationPath() string {
	return filepath.Join(filepath.Dir(settingsPath()), "defterm.json")
}

// parkDelegation writes the found pair down before the registry is touched.
func parkDelegation(d delegation) error {
	p := parkedDelegationPath()
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		return err
	}
	b, err := json.Marshal(d)
	if err != nil {
		return err
	}
	return os.WriteFile(p, b, 0o644)
}

// parkedDelegation reads the pair a killed run left behind.
func parkedDelegation() (delegation, bool) {
	b, err := os.ReadFile(parkedDelegationPath())
	if err != nil {
		return delegation{}, false
	}
	var d delegation
	if json.Unmarshal(b, &d) != nil {
		return delegation{}, false
	}
	return d, true
}

// unparkDelegation forgets the found pair once it has been put back.
func unparkDelegation() { os.Remove(parkedDelegationPath()) }
