package main

// The sign in banner, and the mark it stands as.
//
// Owner order 2026-11-26: the banner carries his words, بسم الله الرحمن الرحيم,
// and nothing after them, and the HUD takes the screen once they have stood.
//
// Owner order 2026-11-27, after two rejected builds: "these are not even the
// words as I told you. do this type "chcp 65001" type "echo ﷽" ... make bigger,
// the banner should take about 40% of the screen." The words he means are not
// the phrase typed out, and not its joined presentation forms either: they are
// the one character he asked for, U+FDFD, the ligature itself, which is what
// his own chcp 65001 and Write-Output [char]0xFDFD put on the screen.
const basmalaBanner = "\uFDFD"

// basmalaWords is the phrase the ligature stands for, kept as the reading of
// the mark for the notes and the documentation. The gate never draws it: the
// banner is the ligature.
const basmalaWords = "بسم الله الرحمن الرحيم"

// A console cell draws one glyph at one size, so the ligature on one line can
// never be "about 40% of the screen". The gate therefore draws the ligature's
// own shape, taken from Windows' text engine, as the solid blocks a cell
// carries: see ligature.go. The character above stays the banner in its own
// right, and is what the gate shows when the shape cannot be drawn.
