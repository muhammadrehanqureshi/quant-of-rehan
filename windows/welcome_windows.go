//go:build windows

package main

import (
	"image"
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
// The window needs no message loop: it has the system's own window procedure,
// it is painted directly into its device context, and hiding it is all the
// handling it ever asks for. If any step here fails the gate draws its cell
// banner instead, so this file can never be the reason the gate does not open.

var user32 = syscall.NewLazyDLL("user32.dll")

var (
	pRegisterClassExW     = user32.NewProc("RegisterClassExW")
	pCreateWindowExW      = user32.NewProc("CreateWindowExW")
	pDefWindowProcW       = user32.NewProc("DefWindowProcW")
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

// welcomeWindow is the one window the gate makes, kept for the whole run so a
// second welcome reuses it rather than making another.
type welcomeWindow struct {
	hwnd  uintptr
	shown bool
	bits  []uint8
	w, h  int
}

var (
	welcomeMu        sync.Mutex
	welcomeWin       *welcomeWindow
	welcomeClassOnce sync.Once
	welcomeClassOK   bool
)

// showWelcomePicture paints the picture and shows it over the console. It
// reports whether the picture is on the screen.
func showWelcomePicture(img image.Image, bg RGB) bool {
	welcomeMu.Lock()
	defer welcomeMu.Unlock()

	// The gate asks on every frame of the welcome, and the picture is already
	// the file's own pixels at the right place, so there is nothing to redo.
	if win := welcomeWin; win != nil && win.shown {
		return true
	}

	bits, w, h := welcomePicturePixels(img, bg)
	if w < 8 || h < 8 || len(bits) == 0 {
		return false
	}
	console, work := welcomeScreenRects()
	rect := welcomePictureRect(console, work, w, h)
	if rect.Empty() {
		return false
	}

	if win := welcomeWin; win != nil {
		win.bits, win.w, win.h = bits, w, h
		pSetWindowPos.Call(win.hwnd, hwndTopmost,
			uintptr(rect.Min.X), uintptr(rect.Min.Y),
			uintptr(rect.Dx()), uintptr(rect.Dy()),
			swpNoActivate|swpShowWindow)
		if !paintWelcome(win, rect.Dx(), rect.Dy()) {
			return false
		}
		win.shown = true
		return true
	}

	if !registerWelcomeClass() {
		return false
	}
	hwnd := createWelcomeWindow(rect)
	if hwnd == 0 {
		return false
	}
	win := &welcomeWindow{hwnd: hwnd, bits: bits, w: w, h: h}
	welcomeWin = win
	// Shown first and painted right after, because a surface painted while the
	// window is hidden is not the surface the screen composites.
	if ok, _, _ := pSetWindowPos.Call(hwnd, hwndTopmost, 0, 0, 0, 0,
		swpNoMove|swpNoSize|swpNoActivate|swpShowWindow); ok == 0 {
		return false
	}
	if !paintWelcome(win, rect.Dx(), rect.Dy()) {
		return false
	}
	win.shown = true
	return true
}

// hideWelcomePicture takes the picture off the screen when the HUD opens. The
// window itself is kept, hidden, until the process ends.
func hideWelcomePicture() {
	welcomeMu.Lock()
	defer welcomeMu.Unlock()
	if welcomeWin == nil || !welcomeWin.shown {
		return
	}
	pShowWindow.Call(welcomeWin.hwnd, swHide)
	welcomeWin.shown = false
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
