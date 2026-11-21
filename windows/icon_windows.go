//go:build windows

package main

import (
	"os"
	"syscall"
	"unsafe"
)

// Owner order 2026-11-21: the console window wears this build's own icon. The
// window Windows makes for a console program carries the icon of the program
// that made the console, so an exe opened from a PowerShell window shows the
// PowerShell icon on the title bar, in Alt+Tab and on the taskbar. The icon
// here comes out of this exe's own resource, the same one Explorer shows, and
// the icons the window had are put back when the build quits.
const (
	wmGetIcon = 0x007F
	wmSetIcon = 0x0080
	iconSmall = 0
	iconBig   = 1
)

var (
	user32            = syscall.NewLazyDLL("user32.dll")
	shell32           = syscall.NewLazyDLL("shell32.dll")
	pGetConsoleWindow = kernel32.NewProc("GetConsoleWindow")
	pSendMessageW     = user32.NewProc("SendMessageW")
	pExtractIconExW   = shell32.NewProc("ExtractIconExW")
)

// brandIcons holds the two handles the window uses. They must stay alive for as
// long as the window draws them, so they are package variables and are never
// destroyed.
var brandIcons [2]uintptr

// brandConsoleWindow sets the console window's small and large icon from this
// exe. It returns the function that puts the window's own icons back; that
// function is always safe to call, on a window that never had one too.
func brandConsoleWindow() func() {
	hwnd, _, _ := pGetConsoleWindow.Call()
	if hwnd == 0 {
		return func() {}
	}
	oldSmall, _, _ := pSendMessageW.Call(hwnd, wmGetIcon, iconSmall, 0)
	oldBig, _, _ := pSendMessageW.Call(hwnd, wmGetIcon, iconBig, 0)

	exe, err := os.Executable()
	if err != nil {
		return func() {}
	}
	path, err := syscall.UTF16PtrFromString(exe)
	if err != nil {
		return func() {}
	}
	found, _, _ := pExtractIconExW.Call(uintptr(unsafe.Pointer(path)), 0,
		uintptr(unsafe.Pointer(&brandIcons[iconBig])), uintptr(unsafe.Pointer(&brandIcons[iconSmall])), 1)
	small, big := brandIcons[iconSmall], brandIcons[iconBig]
	if found == 0 || (small == 0 && big == 0) {
		return func() {}
	}
	if small == 0 {
		small = big
	}
	if big == 0 {
		big = small
	}
	pSendMessageW.Call(hwnd, wmSetIcon, iconSmall, small)
	pSendMessageW.Call(hwnd, wmSetIcon, iconBig, big)
	return func() {
		pSendMessageW.Call(hwnd, wmSetIcon, iconSmall, oldSmall)
		pSendMessageW.Call(hwnd, wmSetIcon, iconBig, oldBig)
	}
}
