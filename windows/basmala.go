package main

// The sign in banner's own words.
//
// Owner order 2026-11-26: the banner carries his words, بسم الله الرحمن الرحيم,
// and nothing after them, and the HUD takes the screen once they have stood.
//
// Owner order 2026-11-27: "write these words exactly in the one dotted line ...
// make it written in only one single continuous line." The dotted render was a
// picture sampled into cells, and at banner size it read as speckle: dots in
// the wrong places, letters with more dots than the Arabic carries, four words
// stacked into a block. The banner is the phrase itself now, typed once, on one
// line, in the terminal's own Arabic face. Nothing is sampled, nothing is
// approximated, and no mark stands beside the words.
const basmalaWords = "بسم الله الرحمن الرحيم"
