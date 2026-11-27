package main

import (
	"bytes"
	"embed"
	"image"
	_ "image/jpeg"
	_ "image/png"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
)

// The gate's banner as a picture.
//
// Owner order 2026-11-27 (build 183): "can you display PNG/JPG/JPEG pictures as
// the display banner if I give you?" He gave windows/assets/banner/
// durood-ibrahimi-white.png, the mark as his own artwork, so the gate now shows
// the picture instead of rebuilding the mark from a font. Every .png, .jpg and
// .jpeg in that folder is embedded in the exe; a file named banner.png,
// banner.jpg or banner.jpeg beside the exe wins over it, so a new picture needs
// no rebuild.
//
//go:embed assets/banner
var bannerAssets embed.FS

// bannerFileNames are the names a picture must have to stand beside the exe.
var bannerFileNames = []string{"banner.png", "banner.jpg", "banner.jpeg"}

// pictureFromBytes decodes one picture and reads its ink.
func pictureFromBytes(data []byte) (ligatureMask, bool) {
	img, _, err := image.Decode(bytes.NewReader(data))
	if err != nil {
		return ligatureMask{}, false
	}
	return pictureMask(img)
}

// pictureFile decodes the picture at path.
func pictureFile(path string) (ligatureMask, bool) {
	data, err := os.ReadFile(path)
	if err != nil {
		return ligatureMask{}, false
	}
	return pictureFromBytes(data)
}

// pictureMask reads a decoded picture as coverage, 0 to 255, already cut to the
// ink's own edges so the banner fills the space it is given.
//
// The artwork may be white on a transparent field (his own file is) or white on
// a dark one, so the channel that carries the shape is chosen once: a picture
// with a clear field is read by its alpha, one without by its brightness. A
// sheet that is lit edge to edge is not artwork, and is refused, so a blank or a
// white page can never be printed as a solid block.
func pictureMask(img image.Image) (ligatureMask, bool) {
	bnd := img.Bounds()
	w, h := bnd.Dx(), bnd.Dy()
	if w < 16 || h < 16 {
		return ligatureMask{}, false
	}
	lum := make([]uint8, w*h)
	alpha := make([]uint8, w*h)
	faded := 0
	for y := 0; y < h; y++ {
		for x := 0; x < w; x++ {
			r, g, b, a := img.At(bnd.Min.X+x, bnd.Min.Y+y).RGBA()
			lum[y*w+x] = uint8((299*int(r) + 587*int(g) + 114*int(b)) / 1000 >> 8)
			alpha[y*w+x] = uint8(a >> 8)
			if a>>8 < 250 {
				faded++
			}
		}
	}
	ink := lum
	if faded > w*h/100 {
		ink = alpha
	}

	const edge = 24 // below this a pixel is field, not ink
	x0, y0, x1, y1 := w, h, -1, -1
	for y := 0; y < h; y++ {
		for x := 0; x < w; x++ {
			if ink[y*w+x] < edge {
				continue
			}
			if x < x0 {
				x0 = x
			}
			if x > x1 {
				x1 = x
			}
			if y < y0 {
				y0 = y
			}
			if y > y1 {
				y1 = y
			}
		}
	}
	if x1 < x0 || y1 < y0 {
		return ligatureMask{}, false
	}
	mw, mh := x1-x0+1, y1-y0+1
	out := make([]uint8, mw*mh)
	dense := 0
	for y := 0; y < mh; y++ {
		for x := 0; x < mw; x++ {
			v := ink[(y0+y)*w+x0+x]
			out[y*mw+x] = v
			if v >= 128 {
				dense++
			}
		}
	}
	if dense > mw*mh*9/10 {
		return ligatureMask{}, false
	}
	return ligatureMask{W: mw, H: mh, Ink: out}, true
}

// readBannerPicture finds the picture the gate should show: a file beside the
// exe first, then the artwork embedded from assets/banner. Its ink is what the
// cell banner is rebuilt from, and that is the fallback now.
func readBannerPicture() (ligatureMask, bool) {
	img, ok := bannerPictureImage()
	if !ok {
		return ligatureMask{}, false
	}
	return pictureMask(img)
}

// readBannerPictureImage decodes the picture itself, the same search order as
// the mask. The banner window shows this image as it is, so every pixel on the
// screen is the file's own rather than a sample of its ink.
func readBannerPictureImage() (image.Image, bool) {
	if exe, err := os.Executable(); err == nil {
		dir := filepath.Dir(exe)
		for _, name := range bannerFileNames {
			if img, ok := pictureFileImage(filepath.Join(dir, name)); ok {
				return img, true
			}
		}
	}
	names, err := fs.Glob(bannerAssets, "assets/banner/*")
	if err != nil {
		return nil, false
	}
	sort.Strings(names)
	for _, name := range names {
		switch strings.ToLower(filepath.Ext(name)) {
		case ".png", ".jpg", ".jpeg":
		default:
			continue
		}
		data, err := bannerAssets.ReadFile(name)
		if err != nil {
			continue
		}
		if img, ok := pictureImageFromBytes(data); ok {
			return img, true
		}
	}
	return nil, false
}

// pictureImageFromBytes decodes one picture, without reading its ink.
func pictureImageFromBytes(data []byte) (image.Image, bool) {
	img, _, err := image.Decode(bytes.NewReader(data))
	if err != nil {
		return nil, false
	}
	return img, true
}

// pictureFileImage reads a picture file as the picture itself.
func pictureFileImage(path string) (image.Image, bool) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, false
	}
	return pictureImageFromBytes(data)
}

// cachedPicture decodes a picture once and keeps it: the gate asks for the
// banner on every frame of the welcome, and decoding it per frame would stall
// the gate.
func cachedPicture(f func() (image.Image, bool)) func() (image.Image, bool) {
	var once sync.Once
	var img image.Image
	var ok bool
	return func() (image.Image, bool) {
		once.Do(func() { img, ok = f() })
		return img, ok
	}
}

// bannerPictureImage is the banner's picture, decoded once.
var bannerPictureImage = cachedPicture(readBannerPictureImage)

// cachedMark reads a mark once and keeps it: the gate asks for the banner on
// every frame of the welcome, and decoding a picture per frame would stall it.
func cachedMark(f func() (ligatureMask, bool)) func() (ligatureMask, bool) {
	var once sync.Once
	var m ligatureMask
	var ok bool
	return func() (ligatureMask, bool) {
		once.Do(func() { m, ok = f() })
		return m, ok
	}
}

// pictureGlyph is the banner's picture, read once.
var pictureGlyph = cachedMark(readBannerPicture)

// bannerMark is what main installs as the gate's mark: his picture when one is
// given, and otherwise the platform's own rendering of the ligature.
func bannerMark() (ligatureMask, bool) {
	if m, ok := pictureGlyph(); ok {
		return m, true
	}
	return platformLigatureGlyph()
}
