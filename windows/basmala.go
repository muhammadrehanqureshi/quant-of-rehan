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

// Owner order 2026-11-27 (the joined banner): the plain phrase reached the
// screen as separate letters with air between them, because a console draws
// one cell per character and the terminal never joins a run it is handed cell
// by cell. The banner therefore carries the phrase in the Arabic PRESENTATION
// FORMS: every letter is already the shape it takes in its own place in the
// word (initial, medial or final), so the join strokes travel with the letter
// and neighbouring cells meet. The words, their order and their letters are
// his own; only the shapes are pre-joined, which is what an Arabic typesetter
// would hand to a press that cannot join type itself.
//
// The forms, letter by letter:
//   بسم      = BEH INITIAL, SEEN MEDIAL, MEEM FINAL
//   الله     = ALEF ISOLATED, LAM INITIAL, LAM MEDIAL, HEH FINAL
//   الرحمن   = ALEF ISOLATED, LAM INITIAL, REH FINAL, HAH INITIAL,
//              MEEM MEDIAL, NOON FINAL
//   الرحيم   = ALEF ISOLATED, LAM INITIAL, REH FINAL, HAH INITIAL,
//              YEH MEDIAL, MEEM FINAL
// ALEF is isolated because the alef never joins the letter after it, and REH
// is final for the same reason; every other letter keeps the shape its own
// neighbours give it.
const basmalaBanner = "\uFE91\uFEB4\uFEE2 \uFE8D\uFEDF\uFEE0\uFEEA \uFE8D\uFEDF\uFEAE\uFEA3\uFEE4\uFEE6 \uFE8D\uFEDF\uFEAE\uFEA3\uFEF4\uFEE2"
