//go:build !windows

package main

import "image"

// The banner's window belongs to Windows. Elsewhere the gate draws the picture
// as its cell banner, so the picture is never up and the banner is never left
// out: welcome.go's fallback carries the mark on every other platform.
func showWelcomePicture(img image.Image, bg RGB) bool { return false }

func hideWelcomePicture() {}
