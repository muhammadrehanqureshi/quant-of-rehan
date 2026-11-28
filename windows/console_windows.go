//go:build windows

package main

import (
	"os"
	"syscall"
	"time"
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
//
// Owner order 2026-11-28 (build 189): "the build's screen/interface is still not
// in the center of the console". One move was not enough. A console is made at
// a default size and given its own size a moment later, and Windows grows a
// window from its top left corner, so the window kept its corner and its middle
// drifted up and to the left after the build had moved it. The window is now
// watched for the first seconds of the run and put back in the middle of its
// monitor every time it changes under the build, so the last size Windows
// gives it is centred too.
//
// A console held by Windows Terminal has no window of its own: the console's
// handle belongs to a hidden window and moving it changes nothing on the
// screen. The terminal's own window is the one the build is seen in, so that
// window is the one moved, and only when it is Windows Terminal's window.
const swpNoZOrder = 0x0004

const monitorDefaultToNearest = 2

// windowsTerminalClass is the window class Windows Terminal gives its window.
const windowsTerminalClass = "CASCADIA_HOSTING_WINDOW_CLASS"

// consoleSettleFor is how long the window is watched after it opens, and
// consoleSettleEvery how often it is looked at: often enough to catch the size
// Windows gives the console a moment late, few enough to cost nothing.
const (
	consoleSettleFor   = 3 * time.Second
	consoleSettleEvery = 80 * time.Millisecond
)

var (
	pMonitorFromWindow = user32.NewProc("MonitorFromWindow")
	pGetMonitorInfoW   = user32.NewProc("GetMonitorInfoW")
	pGetWindowRect     = user32.NewProc("GetWindowRect")
	pConsoleIsVisible  = user32.NewProc("IsWindowVisible")
	pConsoleIsZoomed   = user32.NewProc("IsZoomed")
	pConsoleForeground = user32.NewProc("GetForegroundWindow")
	pGetClassNameW     = user32.NewProc("GetClassNameW")
)

// consoleRect is RECT.
type consoleRect struct {
	left, top, right, bottom int32
}

// consolePoint is POINT, in screen pixels.
type consolePoint struct {
	x, y int32
}

// consoleMonitorInfo is MONITORINFO.
type consoleMonitorInfo struct {
	cbSize    uint32
	rcMonitor consoleRect
	rcWork    consoleRect
	dwFlags   uint32
}

// centerOwnConsole moves the window this build is seen in to the middle of the
// monitor it stands on, and says whether it did.
func centerOwnConsole() bool {
	return centreConsoleWindow(consolePlacementWindow())
}

// settleOwnConsole watches the window this build is seen in for d and puts it
// back in the middle of its monitor every time Windows changes it: the size the
// console is given a moment after it opens, and the place Windows puts it when
// it hands the window over, both land on the middle of the screen instead of
// leaving the build up and to the left. The window is looked at every
// consoleSettleEvery; a window that never changes is never moved twice.
// It returns at once and does its watching in the background, so the gate is up
// while the window settles.
func settleOwnConsole(d time.Duration) {
	hwnd := consolePlacementWindow()
	if hwnd == 0 {
		return
	}
	go func() {
		last, ok := consoleWindowRect(hwnd)
		if !ok {
			return
		}
		for spent := time.Duration(0); spent < d; spent += consoleSettleEvery {
			time.Sleep(consoleSettleEvery)
			r, ok := consoleWindowRect(hwnd)
			if !ok {
				return
			}
			if r == last {
				continue
			}
			last = r
			if centreConsoleWindow(hwnd) {
				if r, ok := consoleWindowRect(hwnd); ok {
					last = r
				}
			}
		}
	}()
}

// consolePlacementWindow is the window this build is seen in: its own console
// window when Windows gave the console a visible one, and the default
// terminal's window when the console is held behind a hidden one, so the thing
// on the screen is the thing that is centred. Zero means no such window could
// be found, and the build is left where Windows put it.
func consolePlacementWindow() uintptr {
	if hwnd, _, _ := pGetConsoleWindow.Call(); hwnd != 0 {
		if v, _, _ := pConsoleIsVisible.Call(hwnd); v != 0 {
			return hwnd
		}
	}
	fg, _, _ := pConsoleForeground.Call()
	if fg != 0 && consoleWindowClassIs(fg, windowsTerminalClass) {
		return fg
	}
	return 0
}

// consoleWindowClassIs says whether a window is of the named class, as when the
// window in front is Windows Terminal's own and not another programme's.
func consoleWindowClassIs(hwnd uintptr, want string) bool {
	if hwnd == 0 || want == "" {
		return false
	}
	var buf [128]uint16
	n, _, _ := pGetClassNameW.Call(hwnd, uintptr(unsafe.Pointer(&buf[0])), uintptr(len(buf)))
	if n == 0 {
		return false
	}
	return syscall.UTF16ToString(buf[:]) == want
}

// centreConsoleWindow moves a window to the middle of its monitor's work area,
// the space the taskbar leaves, and says whether it is there. The window's size
// and its place in the window order are left alone, and a maximised window is
// never moved, so a window he has snapped or filled stays where it is.
func centreConsoleWindow(hwnd uintptr) bool {
	if hwnd == 0 {
		return false
	}
	if z, _, _ := pConsoleIsZoomed.Call(hwnd); z != 0 {
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
	wr, ok := consoleWindowRect(hwnd)
	if !ok {
		return false
	}
	w, h := int(wr.right-wr.left), int(wr.bottom-wr.top)
	if w <= 0 || h <= 0 {
		return false
	}
	// Owner order 2026-11-28 (build 191): "the build's screen is not on the exact
	// center on the console, make it on the absolute center." The title bar and
	// the window's borders do not carry any of the build, so it is the text area
	// that is put in the middle of the work area; the frame follows it by its own
	// inset. A window that will not answer keeps the frame's own middle.
	cr, clientOK := consoleClientRect(hwnd)
	x, y := consoleClientCentre(mi.rcWork, wr, cr, clientOK)
	if int(wr.left) == x && int(wr.top) == y {
		return true
	}
	moved, _, _ := pSetWindowPos.Call(hwnd, 0, uintptr(x), uintptr(y), 0, 0,
		uintptr(swpNoSize|swpNoZOrder|swpNoActivate))
	return moved != 0
}

// consoleClientCentre is the frame's top left corner that puts the window's text
// area, the part that carries the build, in the middle of work. The frame stands
// around the text area by its own inset, so the corner moves back by that inset
// after the text area's own middle is found. A window with no text area, or one
// that would not answer, is centred by its frame instead.
func consoleClientCentre(work, frame, client consoleRect, haveClient bool) (int, int) {
	cw, ch := int(client.right-client.left), int(client.bottom-client.top)
	if !haveClient || cw <= 0 || ch <= 0 {
		return consoleCentreTarget(work, int(frame.right-frame.left), int(frame.bottom-frame.top))
	}
	cx, cy := consoleCentreTarget(work, cw, ch)
	return cx - int(client.left-frame.left), cy - int(client.top-frame.top)
}

// consoleCentreTarget is the top left corner that puts a w by h window in the
// middle of work, in screen pixels. The air left over is split in two, so a
// window whose size differs from the work area's by an odd number of pixels is
// one pixel from the exact middle and never rounded away from it.
func consoleCentreTarget(work consoleRect, w, h int) (int, int) {
	x := int(work.left) + (int(work.right)-int(work.left)-w)/2
	y := int(work.top) + (int(work.bottom)-int(work.top)-h)/2
	return x, y
}

// consoleClientRect is a window's text area in screen pixels: its client
// rectangle, whose own corner is asked for on the screen because GetClientRect
// answers in the window's own coordinates. Owner order 2026-11-28 (build 191):
// the client rectangle and its corner are measured here so the frame can be
// centred by the text area; their two procedures are declared once, in
// welcome_windows.go, and read from there.
func consoleClientRect(hwnd uintptr) (consoleRect, bool) {
	var cr consoleRect
	if hwnd == 0 {
		return cr, false
	}
	if ok, _, _ := pGetClientRect.Call(hwnd, uintptr(unsafe.Pointer(&cr))); ok == 0 {
		return cr, false
	}
	if cr.right <= cr.left || cr.bottom <= cr.top {
		return cr, false
	}
	pt := consolePoint{cr.left, cr.top}
	if ok, _, _ := pClientToScreen.Call(hwnd, uintptr(unsafe.Pointer(&pt))); ok == 0 {
		return cr, false
	}
	w, h := cr.right-cr.left, cr.bottom-cr.top
	return consoleRect{left: pt.x, top: pt.y, right: pt.x + w, bottom: pt.y + h}, true
}

// consoleWindowRect is a window's rectangle in screen pixels.
func consoleWindowRect(hwnd uintptr) (consoleRect, bool) {
	var wr consoleRect
	if hwnd == 0 {
		return wr, false
	}
	if ok, _, _ := pGetWindowRect.Call(hwnd, uintptr(unsafe.Pointer(&wr))); ok == 0 {
		return wr, false
	}
	return wr, true
}
