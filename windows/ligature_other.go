//go:build !windows

package main

// platformLigatureGlyph says this platform cannot draw the ligature's shape.
// The gate then draws the character itself, one line on its middle row, which
// is what the owner's own chcp and Write-Output commands show.
func platformLigatureGlyph() (ligatureMask, bool) { return ligatureMask{}, false }
