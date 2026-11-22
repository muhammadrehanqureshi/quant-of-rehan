//go:build !windows

package main

// openOwnConsole has nothing to do here: the window a terminal gives a program
// is the terminal's, and its icon belongs to that terminal's own profile.
func openOwnConsole() bool { return false }
