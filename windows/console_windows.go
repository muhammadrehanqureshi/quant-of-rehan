//go:build windows

package main

import (
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

// Owner order 2026-11-21: the build runs in a console window of its own. Windows
// takes a console window's icon from the program the console was made for, so a
// build started from a PowerShell or Command Prompt window wears that shell's
// icon on the taskbar, in Alt+Tab and on the title bar, never the icon this exe
// carries. The shell keeps its window and its prompt; the build gets one taskbar
// button with its own logo.
//
// Owner order 2026-11-22: Windows Terminal, the default host on Windows 11,
// draws its own tab icon and its own taskbar icon, and Microsoft's own answer is
// that no program can change them. So when this build finds its console inside
// Windows Terminal, it borrows the pair of delegation values Microsoft documents
// for the classic console host, starts itself again in a console that host makes,
// and puts the owner's pair back the moment the new console exists. The classic
// host draws the icon the exe carries, so both the title bar and the taskbar
// wear the Quant of Rehan logo, and the owner's default terminal is left as it
// was found.
const createNewConsole = 0x00000010

// The registry and process constants the delegation pair needs.
const (
	hkeyCurrentUser         = 0x80000001
	keyQueryValue           = 0x0001
	keySetValue             = 0x0002
	regSZ                   = 1
	processQueryLimitedInfo = 0x1000
	delegationConsoleName   = "DelegationConsole"
	delegationTerminalName  = "DelegationTerminal"
)

var (
	advapi32                    = syscall.NewLazyDLL("advapi32.dll")
	pGetConsoleWindow           = kernel32.NewProc("GetConsoleWindow")
	pGetConsoleProcessList      = kernel32.NewProc("GetConsoleProcessList")
	pCreateProcessW             = kernel32.NewProc("CreateProcessW")
	pGetWindowThreadProcessID   = kernel32.NewProc("GetWindowThreadProcessId")
	pOpenProcess                = kernel32.NewProc("OpenProcess")
	pQueryFullProcessImageNameW = kernel32.NewProc("QueryFullProcessImageNameW")

	pRegOpenKeyExW    = advapi32.NewProc("RegOpenKeyExW")
	pRegQueryValueExW = advapi32.NewProc("RegQueryValueExW")
	pRegSetValueExW   = advapi32.NewProc("RegSetValueExW")
	pRegDeleteValueW  = advapi32.NewProc("RegDeleteValueW")
	pRegCloseKey      = advapi32.NewProc("RegCloseKey")
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

// repairDelegation puts back a pair a killed run left parked, before this run
// looks at the console or touches the registry. The child of a handoff skips it:
// its console is already made, and its parent is about to put the pair back.
func repairDelegation() {
	if os.Getenv(consoleChildEnv) != "" {
		return
	}
	found, ok := parkedDelegation()
	if !ok {
		return
	}
	writeDelegation(found)
	unparkDelegation()
}

// openOwnConsole starts this build again in a console when the console it is
// attached to belongs to a shell, and says whether it did. A console made for
// this exe, and a console held only as a pipe, are left alone.
func openOwnConsole() bool {
	if os.Getenv(consoleChildEnv) != "" {
		return false
	}
	hwnd, _, _ := pGetConsoleWindow.Call()
	if hwnd == 0 {
		return false
	}
	var pids [16]uint32
	n, _, _ := pGetConsoleProcessList.Call(uintptr(unsafe.Pointer(&pids[0])), uintptr(len(pids)))
	shared := sharedConsole(uint32(n))
	inTerminal := inTerminalConsole(hwnd)
	if !shared && !inTerminal {
		return false
	}
	exe, err := os.Executable()
	if err != nil {
		return false
	}
	if inTerminal {
		return startInClassicConsole(exe, os.Args[1:])
	}
	return startInNewConsole(exe, os.Args[1:])
}

// terminalHosted reports whether the window that hosts this console belongs to a
// program other than conhost.exe. Windows Terminal hands the console to
// OpenConsole.exe inside its own package, so the window, its icon and its tab
// are Terminal's.
func terminalHosted(hwnd uintptr) bool {
	var pid uint32
	pGetWindowThreadProcessID.Call(hwnd, uintptr(unsafe.Pointer(&pid)))
	if pid == 0 {
		return false
	}
	h, _, _ := pOpenProcess.Call(processQueryLimitedInfo, 0, uintptr(pid))
	if h == 0 {
		return false
	}
	defer syscall.CloseHandle(syscall.Handle(h))
	buf := make([]uint16, 512)
	size := uint32(len(buf))
	ok, _, _ := pQueryFullProcessImageNameW.Call(h, 0, uintptr(unsafe.Pointer(&buf[0])), uintptr(unsafe.Pointer(&size)))
	if ok == 0 {
		return false
	}
	return !strings.EqualFold(filepath.Base(syscall.UTF16ToString(buf[:size])), "conhost.exe")
}

// inTerminalConsole reports whether this console is Windows Terminal's. The
// window that hosts it says so first; when that window belongs to a program
// this build cannot name, the delegation pair says it instead, so a handoff
// covered by Terminal is never mistaken for the classic host.
func inTerminalConsole(hwnd uintptr) bool {
	if terminalHosted(hwnd) {
		return true
	}
	d, ok := readDelegation()
	if !ok {
		return false
	}
	return d.HasConsole && d.HasTerminal &&
		!strings.EqualFold(d.Console, classicConsoleCLSID) &&
		!strings.EqualFold(d.Terminal, classicConsoleCLSID)
}

// startInClassicConsole asks Windows for a console from the classic host, starts
// this exe in it, and puts the owner's delegation pair back. The pair is parked
// on disk first, so a run killed at the wrong moment is repaired by the next
// start instead of leaving the default terminal changed.
func startInClassicConsole(exe string, args []string) bool {
	found, ok := readDelegation()
	if !ok {
		return false
	}
	if err := parkDelegation(found); err != nil {
		return false
	}
	if !writeDelegation(classicDelegation()) {
		unparkDelegation()
		return false
	}
	started := startInNewConsole(exe, args)
	// Windows picks the host while CreateProcessW is still running, so the pair
	// can go back as soon as it returns; the wait covers a busy machine.
	time.Sleep(600 * time.Millisecond)
	writeDelegation(found)
	unparkDelegation()
	return started
}

// readDelegation reads the pair as Windows has it now.
func readDelegation() (delegation, bool) {
	h, ok := openStartupKey(keyQueryValue)
	if !ok {
		return delegation{}, false
	}
	defer pRegCloseKey.Call(uintptr(h))
	var d delegation
	d.Console, d.HasConsole = queryDelegation(h, delegationConsoleName)
	d.Terminal, d.HasTerminal = queryDelegation(h, delegationTerminalName)
	return d, true
}

// writeDelegation puts a pair back exactly: a value that was found is written,
// and a value that was absent is deleted.
func writeDelegation(d delegation) bool {
	h, ok := openStartupKey(keySetValue | keyQueryValue)
	if !ok {
		return false
	}
	defer pRegCloseKey.Call(uintptr(h))
	console := writeDelegationValue(h, delegationConsoleName, d.Console, d.HasConsole)
	terminal := writeDelegationValue(h, delegationTerminalName, d.Terminal, d.HasTerminal)
	return console && terminal
}

func openStartupKey(access uintptr) (syscall.Handle, bool) {
	name, err := syscall.UTF16PtrFromString(startupKey)
	if err != nil {
		return 0, false
	}
	var h syscall.Handle
	r, _, _ := pRegOpenKeyExW.Call(hkeyCurrentUser, uintptr(unsafe.Pointer(name)),
		0, access, uintptr(unsafe.Pointer(&h)))
	if r != 0 {
		return 0, false
	}
	return h, true
}

func queryDelegation(h syscall.Handle, name string) (string, bool) {
	n, err := syscall.UTF16PtrFromString(name)
	if err != nil {
		return "", false
	}
	var size uint32
	r, _, _ := pRegQueryValueExW.Call(uintptr(h), uintptr(unsafe.Pointer(n)), 0,
		0, 0, uintptr(unsafe.Pointer(&size)))
	if r != 0 || size < 2 {
		return "", false
	}
	buf := make([]uint16, size/2+1)
	r, _, _ = pRegQueryValueExW.Call(uintptr(h), uintptr(unsafe.Pointer(n)), 0,
		0, uintptr(unsafe.Pointer(&buf[0])), uintptr(unsafe.Pointer(&size)))
	if r != 0 {
		return "", false
	}
	return syscall.UTF16ToString(buf), true
}

func writeDelegationValue(h syscall.Handle, name, value string, present bool) bool {
	n, err := syscall.UTF16PtrFromString(name)
	if err != nil {
		return false
	}
	if !present {
		// ERROR_FILE_NOT_FOUND is the answer when it was already absent, which
		// is the state being restored.
		r, _, _ := pRegDeleteValueW.Call(uintptr(h), uintptr(unsafe.Pointer(n)))
		return r == 0 || r == 2
	}
	v, err := syscall.UTF16FromString(value)
	if err != nil {
		return false
	}
	r, _, _ := pRegSetValueExW.Call(uintptr(h), uintptr(unsafe.Pointer(n)), 0, regSZ,
		uintptr(unsafe.Pointer(&v[0])), uintptr(len(v)*2))
	return r == 0
}

// startInNewConsole creates this exe in a console the system makes for it. The
// child is given no standard handles of its own, so Windows gives it the new
// console's, which is what an interactive build needs. It carries the child
// marker in its own environment, so it never starts a third console.
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
	env := envBlock(append(os.Environ(), consoleChildEnv+"=1"))
	var si startupInfo
	si.cb = uint32(unsafe.Sizeof(si))
	var pi processInfo
	ok, _, _ := pCreateProcessW.Call(
		uintptr(unsafe.Pointer(app)),
		uintptr(unsafe.Pointer(&cmdline[0])),
		0, 0, // no inherited handles
		0,
		createNewConsole,
		uintptr(unsafe.Pointer(&env[0])),
		0, // this folder
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
