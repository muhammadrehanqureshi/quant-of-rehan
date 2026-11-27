package main

import "image"

// The gate's banner, the picture itself.
//
// Owner order 2026-11-27 (build 184): "only use this image as the welcome
// image, DO NOT RENDER IT, just have this exact image as the welcome banner."
// A console lays one cell at a time and cannot put a picture on the screen, so
// the banner is no longer rebuilt from the picture's ink into blocks: the
// picture is shown in a window of its own, laid over the gate's middle for as
// long as the welcome lasts, every pixel the file's own and in the picture's
// own colours.
//
// The banner of cells stays as the fallback for a platform with no such window,
// and for a run whose window cannot be made, so the gate never opens without
// its mark. build183_test.go still covers that banner, because it is still what
// a snapshot and a test draw.
//
// welcomePictureAllowed is set by main for a real interactive run, so a
// snapshot, a self test and a test never open a window.
var welcomePictureAllowed bool

// welcomePictureUp puts the picture on the screen and says whether the gate may
// leave its cell banner out. It is asked on every frame of the welcome and
// answers at once: the picture's window belongs to the platform, and Windows
// does the picture's work away from the gate's own thread (build 186), so no
// frame of the gate waits for a decode or for a window.
func welcomePictureUp(bg RGB) bool {
	if !welcomePictureAllowed {
		return false
	}
	return showWelcomePicture(bg)
}

// welcomePicturePercent is the share of its 185 size the picture stands at.
//
// Owner order 2026-11-27 (build 186): "reduce the banner's image size by 35%
// from it's current size." The picture takes 65% of whichever size it stood at
// on 185, the size its own file, the console's width or the screen's work area
// decided.
const welcomePicturePercent = 65

// welcomePicturePixels lays the picture over the gate's own background colour
// and returns top down BGRA rows ready for the screen, one opaque pixel each.
// A picture's transparency takes the colour of the screen behind it, exactly as
// the picture looks on its own dark backdrop; its own pixels are left alone.
func welcomePicturePixels(img image.Image, bg RGB) ([]uint8, int, int) {
	if img == nil {
		return nil, 0, 0
	}
	b := img.Bounds()
	w, h := b.Dx(), b.Dy()
	if w <= 0 || h <= 0 {
		return nil, 0, 0
	}
	px := make([]uint8, w*h*4)
	for y := 0; y < h; y++ {
		for x := 0; x < w; x++ {
			// RGBA is already multiplied by the pixel's alpha.
			r, g, bl, a := img.At(b.Min.X+x, b.Min.Y+y).RGBA()
			ar := int(a >> 8)
			i := (y*w + x) * 4
			px[i+0] = uint8(int(bl>>8) + int(bg.B)*(255-ar)/255)
			px[i+1] = uint8(int(g>>8) + int(bg.G)*(255-ar)/255)
			px[i+2] = uint8(int(r>>8) + int(bg.R)*(255-ar)/255)
			px[i+3] = 0xff
		}
	}
	return px, w, h
}

// welcomePictureRect places the picture over the gate. It is shown at its own
// size whenever the screen holds it, so every pixel is the file's own; a screen
// too small for it shrinks it whole, keeping its shape; and what stands is 65%
// of that size, the owner's 35% off the banner (build 186). It is centred on the
// console the gate is drawn in, and kept inside the screen's work area so no
// part of it is ever cut off by an edge or by the taskbar. An empty rectangle
// means the picture cannot be placed at all.
func welcomePictureRect(console, work image.Rectangle, imgW, imgH int) image.Rectangle {
	if imgW < 8 || imgH < 8 {
		return image.Rectangle{}
	}
	maxW, maxH := work.Dx()*92/100, work.Dy()*92/100
	// Owner order 2026-11-27 (build 185): the picture is no wider than the
	// window the gate is drawn in, so it reads as that window's banner instead
	// of spilling across the screen.
	if !console.Empty() {
		maxW = min(maxW, console.Dx())
	}
	if maxW < 8 || maxH < 8 {
		return image.Rectangle{}
	}
	w, h := imgW, imgH
	if w > maxW {
		h = max(1, h*maxW/w)
		w = maxW
	}
	if h > maxH {
		w = max(1, w*maxH/h)
		h = maxH
	}
	// Owner order 2026-11-27 (build 186): the picture stands at 65% of the size
	// it stood at on 185, so the 35% comes off whatever that size was: a screen
	// that held it whole, a console narrower than it, or a work area too small
	// for it. It is still centred, still whole and still never cut.
	w = max(1, w*welcomePicturePercent/100)
	h = max(1, h*welcomePicturePercent/100)
	if w < 8 || h < 8 {
		return image.Rectangle{}
	}
	if console.Empty() {
		console = work
	}
	x := console.Min.X + console.Dx()/2 - w/2
	y := console.Min.Y + console.Dy()/2 - h/2
	x = min(x, work.Max.X-w)
	y = min(y, work.Max.Y-h)
	x = max(x, work.Min.X)
	y = max(y, work.Min.Y)
	return image.Rect(x, y, x+w, y+h)
}
