//go:build !windows

package main

// brandConsoleWindow has nothing to brand here: the icon of a console window is
// a Windows console matter, and the Linux terminal draws whatever icon its own
// profile carries.
func brandConsoleWindow() func() { return func() {} }
