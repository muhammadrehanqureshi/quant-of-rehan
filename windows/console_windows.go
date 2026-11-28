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
//
// Owner order 2026-11-22: the handoff through Windows Terminal's default
// terminal setting is withdrawn. Build 156 borrowed that registry pair for one
// launch, and the build then closed as soon as it started; the pair is not this
// program's to change, so the console this exe is given is the one it uses. A
// console hosted by Windows Terminal keeps Terminal's own tab and taskbar icons,
// and the one-time Windows setting that moves every console to the classic host
// is the owner's to make, in Settings, System, For developers, Terminal.
const createNewConsole = 0x00000010

var (
	pGetConsoleWindow      = kernel32.NewProc("GetConsoleWindow")
	pGetConsoleProcessList = kernel32.NewProc("GetConsoleProcessList")
	pCreateProcessW        = kernel32.NewProc("CreateProcessW")
)

// The two structures CreateProcessW fills. Their field order and types are the
// Windows ones, so the size this program passes is the size Windows expects.
type startupInfo struct {
	cb             uint32
	reserved       *uint16
	desktop        *uint16
	title          *uint16
	x, y           uint32
	xSize, ySize   uint32
	xChars, yChars uint32
	fillAttribute  uint32
	flags          uint32
	showWindow     uint16
	cbReserved2    uint16
	reserved2      *byte
	stdInput       syscall.Handle
	stdOutput      syscall.Handle
	stdErr         syscall.Handle
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

// The build's console window, placed on the middle of its monitor.
//
// Owner order 2026-11-28 (build 188): "right now the build screen little to the
// top and little to the left, is there any way you can get my build screen on
// the exact center on the console it's running on whether on CMD or
// POWERSHELL". The console the system made for this exe is a window of its own,
// so it is measured and moved as one: the middle of its monitor's work area,
// its size and its place in the window order left alone. A console with no
// window, a monitor that will not answer and a window that will not move all
// leave the build where Windows put it.
const swpNoZOrder = 0x0004

const monitorDefaultToNearest = 2

var (
	pMonitorFromWindow = user32.NewProc("MonitorFromWindow")
	pGetMonitorInfoW   = user32.NewProc("GetMonitorInfoW")
	pGetWindowRect     = user32.NewProc("GetWindowRect")
)

// consoleRect is RECT.
type consoleRect struct {
	left, top, right, bottom int32
}

// consoleMonitorInfo is MONITORINFO.
type consoleMonitorInfo struct {
	cbSize    uint32
	rcMonitor consoleRect
	rcWork    consoleRect
	dwFlags   uint32
}

// centerOwnConsole moves this build's console window to the middle of the
// monitor it stands on, and says whether it did.
func centerOwnConsole() bool {
	hwnd, _, _ := pGetConsoleWindow.Call()
	if hwnd == 0 {
		return false
	}
	mon, _, _ := pMonitorFromWindow.Call(hwnd, monitorDefaultToNearest)
	if mon == 0 {
		return false
	}
	var mi consoleMonitorInfo
	mi.cbSize = uint32(unsafe.Sizeof(mi))
	if ok, _, _ := pGetMonitorInfoW.Call(mon, uintptr(unsafe.Pointer(&mi))); ok == 0 {
		return false
	}
	var wr consoleRect
	if ok, _, _ := pGetWindowRect.Call(hwnd, uintptr(unsafe.Pointer(&wr))); ok == 0 {
		return false
	}
	w, h := int(wr.right-wr.left), int(wr.bottom-wr.top)
	if w <= 0 || h <= 0 {
		return false
	}
	x := int(mi.rcWork.left) + (int(mi.rcWork.right)-int(mi.rcWork.left)-w)/2
	y := int(mi.rcWork.top) + (int(mi.rcWork.bottom)-int(mi.rcWork.top)-h)/2
	ok, _, _ := pSetWindowPos.Call(hwnd, 0, uintptr(x), uintptr(y), 0, 0,
		uintptr(swpNoSize|swpNoZOrder|swpNoActivate))
	return ok != 0
}
