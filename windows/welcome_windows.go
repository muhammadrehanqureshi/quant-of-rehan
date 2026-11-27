//go:build windows

package main

import (
	"image"
	"runtime"
	"sync"
	"syscall"
	"unsafe"
)

// The gate's banner as a window.
//
// Owner order 2026-11-27 (build 184): the welcome image is the picture itself,
// not a block version of it. The gate draws cells, so the picture is given a
// window of its own: borderless, always on top, never taking the focus and
// never taking a click, laid over the console's middle while the welcome lasts.
// It is painted once from the file's own pixels, at their own size, and hidden
// again when the HUD takes the screen.
//
// The window lives on a thread of its own that answers its messages, because a
// window whose thread never pumps makes Windows call the programme hung and put
// its "is not responding" panel over the picture. The thread paints the picture,
// pumps until the gate asks for it back, and is gone with the window. If any
// step here fails the gate draws its cell banner instead, so this file can never
// be the reason the gate does not open.

var user32 = syscall.NewLazyDLL("user32.dll")

var (
	pRegisterClassExW     = user32.NewProc("RegisterClassExW")
	pCreateWindowExW      = user32.NewProc("CreateWindowExW")
	pDefWindowProcW       = user32.NewProc("DefWindowProcW")
	pDestroyWindow        = user32.NewProc("DestroyWindow")
	pGetMessageW          = user32.NewProc("GetMessageW")
	pTranslateMessage     = user32.NewProc("TranslateMessage")
	pDispatchMessageW     = user32.NewProc("DispatchMessageW")
	pPostMessageW         = user32.NewProc("PostMessageW")
	pSetDpiAwareness      = user32.NewProc("SetProcessDpiAwarenessContext")
	pSetDPIAware          = user32.NewProc("SetProcessDPIAware")
	pSetWindowPos         = user32.NewProc("SetWindowPos")
	pShowWindow           = user32.NewProc("ShowWindow")
	pGetDC                = user32.NewProc("GetDC")
	pReleaseDC            = user32.NewProc("ReleaseDC")
	pGetClientRect        = user32.NewProc("GetClientRect")
	pClientToScreen       = user32.NewProc("ClientToScreen")
	pIsWindowVisible      = user32.NewProc("IsWindowVisible")
	pGetForegroundWindow  = user32.NewProc("GetForegroundWindow")
	pSystemParametersInfo = user32.NewProc("SystemParametersInfoW")
	pGetModuleHandleW     = kernel32.NewProc("GetModuleHandleW")

	pStretchDIBits     = gdi32.NewProc("StretchDIBits")
	pSetStretchBltMode = gdi32.NewProc("SetStretchBltMode")
)

const (
	welcomeClassName = "QuantOfRehanWelcome"

	wsPopup         = 0x80000000
	wsExTopmost     = 0x00000008
	wsExTransparent = 0x00000020
	wsExToolWindow  = 0x00000080
	wsExNoActivate  = 0x08000000

	swpNoMove     = 0x0002
	swpNoSize     = 0x0001
	swpNoActivate = 0x0010
	swpShowWindow = 0x0040
	swHide        = 0
	hwndTopmost   = ^uintptr(0)

	spiGetWorkArea = 0x0030
	halftoneMode   = 4

	// Owner order 2026-11-27 (build 185): the window answers its messages.
	// build 184 never pumped them, so Windows took the programme for a hung one
	// and put its "is not responding" panel over the picture.
	wmWelcomeHide = 0x8001 // WM_APP + 1: take the picture down

	// DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2, so the picture is measured and
	// drawn in screen pixels. build 184 showed it through Windows' 125% scaling
	// and the picture came out a fifth wider than the file's own width.
	dpiPerMonitorV2 = ^uintptr(3)
	dibRGBColors   = 0
	srcCopyRop     = 0x00cc0020
)

// wndClassEx is WNDCLASSEXW.
type wndClassEx struct {
	cbSize        uint32
	style         uint32
	wndProc       uintptr
	clsExtra      int32
	wndExtra      int32
	instance      uintptr
	icon          uintptr
	cursor        uintptr
	background    uintptr
	menuName      *uint16
	className     *uint16
	iconSm        uintptr
}

type welcomeWinRect struct {
	left, top, right, bottom int32
}

type welcomeWinPoint struct {
	x, y int32
}

// welcomeMsg is MSG.
type welcomeMsg struct {
	hwnd     uintptr
	message  uint32
	wParam   uintptr
	lParam   uintptr
	time     uint32
	pt       welcomeWinPoint
	lPrivate uint32
}

// welcomeWindow is the window the gate makes for the welcome, held while it is
// up so the gate can ask after it. Its thread closes and frees it when the HUD
// opens, so a second welcome makes a fresh one.
type welcomeWindow struct {
	hwnd  uintptr
	shown bool
	bits  []uint8
	w, h  int
}

var (
	welcomeMu        sync.Mutex
	welcomeWin       *welcomeWindow
	welcomeTried     bool // a window has been asked for in this run
	welcomeDead      bool // no window can be made: the gate keeps its cells
	welcomeClassOnce sync.Once
	welcomeClassOK   bool
)

// showWelcomePicture paints the picture and shows it over the console. It
// reports whether the picture is on the screen.
func showWelcomePicture(img image.Image, bg RGB) bool {
	welcomeMu.Lock()
	if win := welcomeWin; win != nil && win.shown {
		welcomeMu.Unlock()
		return true
	}
	if welcomeDead || welcomeTried {
		welcomeMu.Unlock()
		return false
	}
	welcomeTried = true
	welcomeMu.Unlock()

	bits, w, h := welcomePicturePixels(img, bg)
	console, work := welcomeScreenRects()
	rect := welcomePictureRect(console, work, w, h)
	if w < 8 || h < 8 || len(bits) == 0 || rect.Empty() || !registerWelcomeClass() {
		markWelcomeDead()
		return false
	}
	// The window is made and painted on its own thread, which then answers its
	// messages; the answer arrives once the picture is on the screen, so the
	// gate holds its cell banner back only when the picture is really there.
	ready := make(chan uintptr, 1)
	go runWelcomeWindow(bits, w, h, rect, ready)
	hwnd := <-ready
	if hwnd == 0 {
		markWelcomeDead()
		return false
	}
	welcomeMu.Lock()
	welcomeWin = &welcomeWindow{hwnd: hwnd, shown: true, bits: bits, w: w, h: h}
	welcomeMu.Unlock()
	return true
}

func markWelcomeDead() {
	welcomeMu.Lock()
	welcomeDead = true
	welcomeMu.Unlock()
}

// hideWelcomePicture takes the picture off the screen when the HUD opens. The
// window's own thread closes it and ends with it, so nothing of the picture is
// left behind to answer for.
func hideWelcomePicture() {
	welcomeMu.Lock()
	win := welcomeWin
	if win == nil || !win.shown {
		welcomeMu.Unlock()
		return
	}
	win.shown = false
	welcomeMu.Unlock()
	pPostMessageW.Call(win.hwnd, wmWelcomeHide, 0, 0)
}

// enableWelcomeDPI makes this programme measure its own windows in screen
// pixels, so the picture is drawn at the file's own width instead of being
// scaled by Windows' display setting. It must stand before the first window is
// made; the processes that do not answer it keep the system's own choice.
func enableWelcomeDPI() {
	if ok, _, _ := pSetDpiAwareness.Call(dpiPerMonitorV2); ok != 0 {
		return
	}
	pSetDPIAware.Call()
}

// runWelcomeWindow makes the window on a thread of its own, paints the picture
// into it, shows it, and answers its messages until the gate asks for it back.
func runWelcomeWindow(bits []uint8, w, h int, rect image.Rectangle, ready chan<- uintptr) {
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()
	hwnd := createWelcomeWindow(rect)
	if hwnd == 0 {
		ready <- 0
		return
	}
	win := &welcomeWindow{hwnd: hwnd, bits: bits, w: w, h: h}
	// Shown first and painted right after, because a surface painted while the
	// window is hidden is not the surface the screen composites.
	if ok, _, _ := pSetWindowPos.Call(hwnd, hwndTopmost, 0, 0, 0, 0,
		swpNoMove|swpNoSize|swpNoActivate|swpShowWindow); ok == 0 {
		pDestroyWindow.Call(hwnd)
		ready <- 0
		return
	}
	if !paintWelcome(win, rect.Dx(), rect.Dy()) {
		pDestroyWindow.Call(hwnd)
		ready <- 0
		return
	}
	ready <- hwnd
	welcomePump()
	pDestroyWindow.Call(hwnd)
}

// welcomePump answers the window's messages, which is what keeps Windows from
// calling the programme hung, until the gate posts the word to take it down.
func welcomePump() {
	var msg welcomeMsg
	for {
		r, _, _ := pGetMessageW.Call(uintptr(unsafe.Pointer(&msg)), 0, 0, 0)
		if int32(r) <= 0 {
			return
		}
		if msg.message == wmWelcomeHide {
			return
		}
		pTranslateMessage.Call(uintptr(unsafe.Pointer(&msg)))
		pDispatchMessageW.Call(uintptr(unsafe.Pointer(&msg)))
	}
}

// registerWelcomeClass names the window's class once for the run. The system's
// own window procedure answers every message, so no Go callback is involved.
func registerWelcomeClass() bool {
	welcomeClassOnce.Do(func() {
		name, err := syscall.UTF16PtrFromString(welcomeClassName)
		if err != nil {
			return
		}
		instance, _, _ := pGetModuleHandleW.Call(0)
		wc := wndClassEx{
			cbSize:    uint32(unsafe.Sizeof(wndClassEx{})),
			wndProc:   pDefWindowProcW.Addr(),
			instance:  instance,
			className: name,
		}
		if atom, _, _ := pRegisterClassExW.Call(uintptr(unsafe.Pointer(&wc))); atom != 0 {
			welcomeClassOK = true
		}
	})
	return welcomeClassOK
}

// createWelcomeWindow makes the picture's window at the given place and size,
// hidden: borderless, on top, out of the task bar's list, never focused, and
// see-through to the mouse so the console behind it keeps its clicks.
func createWelcomeWindow(r image.Rectangle) uintptr {
	name, err := syscall.UTF16PtrFromString(welcomeClassName)
	if err != nil {
		return 0
	}
	title, err := syscall.UTF16PtrFromString("")
	if err != nil {
		return 0
	}
	instance, _, _ := pGetModuleHandleW.Call(0)
	hwnd, _, _ := pCreateWindowExW.Call(
		uintptr(wsExTopmost|wsExToolWindow|wsExNoActivate|wsExTransparent),
		uintptr(unsafe.Pointer(name)),
		uintptr(unsafe.Pointer(title)),
		uintptr(wsPopup),
		uintptr(r.Min.X), uintptr(r.Min.Y),
		uintptr(r.Dx()), uintptr(r.Dy()),
		0, 0, instance, 0,
	)
	return hwnd
}

// paintWelcome puts the picture's pixels into the window: the rows are the
// file's, at the size the screen is given, with a smooth shrink when the screen
// holds the picture only scaled down.
func paintWelcome(win *welcomeWindow, w, h int) bool {
	if win == nil || win.hwnd == 0 || win.w <= 0 || win.h <= 0 || len(win.bits) == 0 || w <= 0 || h <= 0 {
		return false
	}
	bmi := bitmapInfo{Header: bitmapInfoHeader{
		Size:     uint32(unsafe.Sizeof(bitmapInfoHeader{})),
		Width:    int32(win.w),
		Height:   -int32(win.h), // top down: row 0 is the picture's own first row
		Planes:   1,
		BitCount: 32,
	}}
	hdc, _, _ := pGetDC.Call(win.hwnd)
	if hdc == 0 {
		return false
	}
	defer pReleaseDC.Call(win.hwnd, hdc)
	pSetStretchBltMode.Call(hdc, halftoneMode)
	lines, _, _ := pStretchDIBits.Call(hdc,
		0, 0, uintptr(w), uintptr(h),
		0, 0, uintptr(win.w), uintptr(win.h),
		uintptr(unsafe.Pointer(&win.bits[0])),
		uintptr(unsafe.Pointer(&bmi)),
		dibRGBColors, srcCopyRop,
	)
	return lines != 0 && lines != ^uintptr(0)
}

// welcomeScreenRects are where the gate's console is, and the work area of the
// screen it is on. Windows Terminal keeps the console behind a hidden window,
// so the window the user is looking at stands in for it when the console's own
// window cannot be seen.
func welcomeScreenRects() (image.Rectangle, image.Rectangle) {
	work := welcomeWorkArea()
	if work.Empty() {
		work = image.Rect(0, 0, 1280, 720)
	}
	console := image.Rectangle{}
	consoleHwnd, _, _ := pGetConsoleWindow.Call()
	foregroundHwnd, _, _ := pGetForegroundWindow.Call()
	for _, hwnd := range []uintptr{consoleHwnd, foregroundHwnd} {
		if r := welcomeClientRect(hwnd); !r.Empty() {
			console = r
			break
		}
	}
	return console, work
}

// welcomeWorkArea is the screen's own area, without the task bar.
func welcomeWorkArea() image.Rectangle {
	var r welcomeWinRect
	if ok, _, _ := pSystemParametersInfo.Call(spiGetWorkArea, 0, uintptr(unsafe.Pointer(&r)), 0); ok == 0 {
		return image.Rectangle{}
	}
	return image.Rect(int(r.left), int(r.top), int(r.right), int(r.bottom))
}

// welcomeClientRect is a window's visible client area in screen pixels.
func welcomeClientRect(hwnd uintptr) image.Rectangle {
	if hwnd == 0 {
		return image.Rectangle{}
	}
	if visible, _, _ := pIsWindowVisible.Call(hwnd); visible == 0 {
		return image.Rectangle{}
	}
	var cr welcomeWinRect
	if ok, _, _ := pGetClientRect.Call(hwnd, uintptr(unsafe.Pointer(&cr))); ok == 0 {
		return image.Rectangle{}
	}
	w, h := int(cr.right-cr.left), int(cr.bottom-cr.top)
	if w <= 0 || h <= 0 {
		return image.Rectangle{}
	}
	pt := welcomeWinPoint{}
	if ok, _, _ := pClientToScreen.Call(hwnd, uintptr(unsafe.Pointer(&pt))); ok == 0 {
		return image.Rectangle{}
	}
	return image.Rect(int(pt.x), int(pt.y), int(pt.x)+w, int(pt.y)+h)
}
