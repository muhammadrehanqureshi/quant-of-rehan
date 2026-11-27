//go:build windows

package main

import (
	"sync"
	"syscall"
	"unsafe"
)

// The ligature's ink, from Windows' own text engine.
//
// Retyping the ligature's letters would be a different thing from the character
// the owner named, and a console cell cannot scale one glyph, so the shape is
// taken from the system: the character 0xFDFD is drawn with GDI into a memory
// bitmap, cut to its ink, and handed to the gate as a coverage mask. If any
// step of this fails the gate draws the character itself instead, so this file
// can never be the reason the gate does not open.

var gdi32 = syscall.NewLazyDLL("gdi32.dll")

var (
	pCreateCompatibleDC = gdi32.NewProc("CreateCompatibleDC")
	pCreateDIBSection   = gdi32.NewProc("CreateDIBSection")
	pSelectObject       = gdi32.NewProc("SelectObject")
	pDeleteObject       = gdi32.NewProc("DeleteObject")
	pDeleteDC           = gdi32.NewProc("DeleteDC")
	pCreateFontW        = gdi32.NewProc("CreateFontW")
	pGetGlyphIndicesW   = gdi32.NewProc("GetGlyphIndicesW")
	pSetBkMode          = gdi32.NewProc("SetBkMode")
	pSetTextColor       = gdi32.NewProc("SetTextColor")
	pTextOutW           = gdi32.NewProc("TextOutW")
)

const (
	ggrMarkNonExistingGlyphs = 0x0001
	transparentBkMode        = 1

	// The surface the glyph is drawn into. It is far larger than any console
	// needs, so the letterforms are sampled down rather than up, and it is wide
	// because the ligature is one long joined mark: a narrower page would cut
	// its end off and the sample would keep the cut.
	ligatureTileW = 2048
	ligatureTileH = 512
)

// ligatureFaces are the faces Windows sets Arabic in, the calligraphic ones
// first, because the ligature should look like the inscription it is. The first
// face that actually carries the character is the one used.
var ligatureFaces = []string{
	"Traditional Arabic",
	"Arabic Typesetting",
	"Sakkal Majalla",
	"Aldhabi",
	"Simplified Arabic",
	"Urdu Typesetting",
	"Segoe UI",
	"Arial",
	"Tahoma",
	"Times New Roman",
	"Microsoft Sans Serif",
}

type bitmapInfoHeader struct {
	Size          uint32
	Width         int32
	Height        int32
	Planes        uint16
	BitCount      uint16
	Compression   uint32
	SizeImage     uint32
	XPelsPerMetre int32
	YPelsPerMetre int32
	ClrUsed       uint32
	ClrImportant  uint32
}

type bitmapInfo struct {
	Header bitmapInfoHeader
	Colors [1]uint32
}

var (
	ligatureOnce sync.Once
	ligatureInk  ligatureMask
	ligatureOK   bool
)

// platformLigatureGlyph draws U+FDFD once and keeps its ink.
func platformLigatureGlyph() (ligatureMask, bool) {
	ligatureOnce.Do(func() {
		ligatureInk, ligatureOK = drawLigatureGlyph()
	})
	return ligatureInk, ligatureOK
}

// drawLigatureGlyph renders the character into a memory bitmap and returns its
// ink, cut to its own edges. Every failure returns false and leaves the gate on
// its text fallback.
func drawLigatureGlyph() (ligatureMask, bool) {
	hdc, _, _ := pCreateCompatibleDC.Call(0)
	if hdc == 0 {
		return ligatureMask{}, false
	}
	defer pDeleteDC.Call(hdc)

	bmi := bitmapInfo{Header: bitmapInfoHeader{
		Size:     uint32(unsafe.Sizeof(bitmapInfoHeader{})),
		Width:    ligatureTileW,
		Height:   -ligatureTileH, // top down, so row 0 is the top row
		Planes:   1,
		BitCount: 32,
	}}
	var bits unsafe.Pointer
	hbm, _, _ := pCreateDIBSection.Call(hdc, uintptr(unsafe.Pointer(&bmi)), 0, uintptr(unsafe.Pointer(&bits)), 0, 0)
	if hbm == 0 || bits == nil {
		return ligatureMask{}, false
	}
	defer pDeleteObject.Call(hbm)
	oldBM, _, _ := pSelectObject.Call(hdc, hbm)
	if oldBM == 0 {
		return ligatureMask{}, false
	}
	defer pSelectObject.Call(hdc, oldBM)

	// A white page: ink is what is left dark afterwards.
	buf := unsafe.Slice((*byte)(bits), ligatureTileW*ligatureTileH*4)
	for i := 0; i+3 < len(buf); i += 4 {
		buf[i], buf[i+1], buf[i+2], buf[i+3] = 0xff, 0xff, 0xff, 0xff
	}

	pSetBkMode.Call(hdc, transparentBkMode)
	pSetTextColor.Call(hdc, 0)

	glyph := [1]uint16{0xFDFD}
	font := ligatureFont(hdc, &glyph[0])
	if font == 0 {
		return ligatureMask{}, false
	}
	oldFont, _, _ := pSelectObject.Call(hdc, font)
	defer func() {
		pSelectObject.Call(hdc, oldFont)
		pDeleteObject.Call(font)
	}()

	if r, _, _ := pTextOutW.Call(hdc, 0, 0, uintptr(unsafe.Pointer(&glyph[0])), 1); r == 0 {
		return ligatureMask{}, false
	}
	return inkFromTile(buf, ligatureTileW, ligatureTileH), true
}

// ligatureFont makes a font of the first face that carries the glyph. A face
// that does not have it is dropped rather than falling back silently to a box
// or to the plain letters, because a box is not the mark the owner named.
func ligatureFont(hdc uintptr, glyph *uint16) uintptr {
	height := uintptr(ligatureTileH * 3 / 4)
	for _, face := range ligatureFaces {
		name, err := syscall.UTF16PtrFromString(face)
		if err != nil {
			continue
		}
		h, _, _ := pCreateFontW.Call(
			height, 0, 0, 0,
			400, // FW_NORMAL
			0, 0, 0,
			1, // DEFAULT_CHARSET, so the face is taken as it is
			0, 0, 0, 0,
			uintptr(unsafe.Pointer(name)),
		)
		if h == 0 {
			continue
		}
		old, _, _ := pSelectObject.Call(hdc, h)
		var index uint16
		ok, _, _ := pGetGlyphIndicesW.Call(hdc, uintptr(unsafe.Pointer(glyph)), 1,
			uintptr(unsafe.Pointer(&index)), ggrMarkNonExistingGlyphs)
		pSelectObject.Call(hdc, old)
		if ok != 0 && index != 0xFFFF {
			return h
		}
		pDeleteObject.Call(h)
	}
	return 0
}

// inkFromTile reads the top-down 32 bit surface and keeps its dark pixels,
// cut to the box they occupy.
func inkFromTile(buf []byte, w, h int) ligatureMask {
	ink := make([]uint8, w*h)
	minX, minY, maxX, maxY := w, h, -1, -1
	for y := 0; y < h; y++ {
		row := buf[y*w*4:]
		for x := 0; x < w; x++ {
			px := row[x*4:]
			if px[0] >= 128 && px[1] >= 128 && px[2] >= 128 {
				continue
			}
			dark := 255 - int(px[0])
			if v := 255 - int(px[1]); v < dark {
				dark = v
			}
			if v := 255 - int(px[2]); v < dark {
				dark = v
			}
			ink[y*w+x] = uint8(dark)
			if x < minX {
				minX = x
			}
			if x > maxX {
				maxX = x
			}
			if y < minY {
				minY = y
			}
			if y > maxY {
				maxY = y
			}
		}
	}
	if maxX < minX || maxY < minY {
		return ligatureMask{}
	}
	cw, ch := maxX-minX+1, maxY-minY+1
	out := ligatureMask{W: cw, H: ch, Ink: make([]uint8, cw*ch)}
	for y := 0; y < ch; y++ {
		src := (minY+y)*w + minX
		copy(out.Ink[y*cw:(y+1)*cw], ink[src:src+cw])
	}
	return out
}
