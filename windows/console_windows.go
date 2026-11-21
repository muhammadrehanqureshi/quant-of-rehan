//go:build windows

package main

import (
	"os"
	"syscall"
	"unsafe"
)

// Owner order 2026-11-21: the build runs in a console window of its own. Windows
// takes a console window's icon from the program the console was made for, so a
// build started from a PowerShell or Command Prompt window wears that shell's
// icon on the taskbar, in Alt+Tab and on the title bar, never the icon this exe
// carries. A console the system makes for this exe wears this exe's own icon, the
// same picture Explorer shows, so the build leaves a shared console and opens
// its own. The shell keeps its window and its prompt; the build gets one taskbar
// button with its own logo.
const createNewConsole = 0x00000010

var (
	pGetConsoleWindow      = kernel32.NewProc("GetConsoleWindow")
	pGetConsoleProcessList = kernel32.NewProc("GetConsoleProcessList")
	pCreateProcessW        = kernel32.NewProc("CreateProcessW")
)

// The two structures CreateProcessW fills. Their field order and types are the
// Windows ones, so the size this program passes is the size Windows expects.
type startupInfo struct {
	cb            uint32
	reserved      *uint16
	desktop       *uint16
	title         *uint16
	x, y          uint32
	xSize, ySize  uint32
	xChars, yChars uint32
	fillAttribute uint32
	flags         uint32
	showWindow    uint16
	cbReserved2   uint16
	reserved2     *byte
	stdInput      syscall.Handle
	stdOutput     syscall.Handle
	stdErr        syscall.Handle
}

type processInfo struct {
	process   syscall.Handle
	thread    syscall.Handle
	processID uint32
	threadID  uint32
}

// openOwnConsole starts this build again in a new console when the console it is
// attached to belongs to a shell, and says whether it did. A console made for
// this exe, and a console held only as a pipe, are left alone.
func openOwnConsole() bool {
	hwnd, _, _ := pGetConsoleWindow.Call()
	if hwnd == 0 {
		return false
	}
	var pids [16]uint32
	n, _, _ := pGetConsoleProcessList.Call(uintptr(unsafe.Pointer(&pids[0])), uintptr(len(pids)))
	if !sharedConsole(uint32(n)) {
		return false
	}
	exe, err := os.Executable()
	if err != nil {
		return false
	}
	return startInNewConsole(exe, os.Args[1:])
}

// startInNewConsole creates this exe in a console the system makes for it. The
// child is given no standard handles of its own, so Windows gives it the new
// console's, which is what an interactive build needs.
func startInNewConsole(exe string, args []string) bool {
	line := windowsCommandLine(append([]string{exe}, args...))
	app, err := syscall.UTF16PtrFromString(exe)
	if err != nil {
		return false
	}
	// CreateProcessW may write into the command line it is given, so it gets a
	// buffer of its own rather than the string's.
	cmdline, err := syscall.UTF16FromString(line)
	if err != nil {
		return false
	}
	var si startupInfo
	si.cb = uint32(unsafe.Sizeof(si))
	var pi processInfo
	ok, _, _ := pCreateProcessW.Call(
		0,
		uintptr(unsafe.Pointer(app)),
		uintptr(unsafe.Pointer(&cmdline[0])),
		0, 0, // no inherited handles
		0,
		createNewConsole,
		0, 0, // this environment and folder
		uintptr(unsafe.Pointer(&si)),
		uintptr(unsafe.Pointer(&pi)),
	)
	if ok == 0 {
		return false
	}
	syscall.CloseHandle(pi.thread)
	syscall.CloseHandle(pi.process)
	return true
}

