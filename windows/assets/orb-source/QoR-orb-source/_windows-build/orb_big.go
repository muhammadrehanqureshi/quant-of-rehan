package main

// The quant core orb, 10% bigger than the first dot version.
//
// The app fits the ring to the room it is given. In the tile at 122 by 30 that
// room was 13 rows (the 14th row held the ONLINE caption), so the ring had a
// radius of 13 * cellAspect / 2 - 0.5 = 13.93 columns. This draws the ring at
// orbGrow times that radius, which needs the whole 14 rows of the tile.
//
// orbGrow is 1.11 and not 1.10 on purpose. The ring is scaled smoothly, but it is
// drawn in dots about 2% of its width apart, so the outline you see grows in steps
// of that size. At 1.10 the outline measures +9% wide and +8% high; at 1.11 it
// measures +11% wide and +10% high (averaged over the 16 second loop), which is
// the one that looks 10% bigger.

const (
	orbGrow     = 1.11 // ring radius against the first dot version
	orbBaseRows = 13   // the rows the first dot version had
	orbBigRows  = 14   // the rows a ring of orbGrow needs
	orbBigCols  = 32   // and the columns
)

// drawOrbBig paints the 10% bigger orb into (x0,y0,w,h). It needs at least
// orbBigCols by orbBigRows cells. With less room, or when [ and ] have changed
// cellAspect so the 14 rows are no longer tall enough, it draws the ring at the
// size that fits, exactly as drawOrb does, so it never draws outside its
// rectangle and the ring stays round.
func drawOrbBig(c *Canvas, x0, y0, w, h int, t float64, mode OrbMode) {
	room := minF(float64(w)/2, float64(h)*cellAspect/2) // the biggest radius the rectangle holds, in columns
	want := (float64(orbBaseRows)*cellAspect/2 - 0.5) * orbGrow
	if w >= orbBigCols && h >= orbBigRows && want <= room {
		ringRadius = want
		defer func() { ringRadius = 0 }()
	}
	drawOrb(c, x0, y0, w, h, t, mode, nil)
}

func minF(a, b float64) float64 {
	if a < b {
		return a
	}
	return b
}
