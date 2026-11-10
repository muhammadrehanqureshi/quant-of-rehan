# Quant of Rehan orbs: green and red, in Go

The quant core orb of the Windows HUD as a small, stand alone Go program. Green is
online and turning. Red is offline and completely still. Amber (still checking) is
there as a third colour. Both orbs are **10% bigger** than the first dot version.

Go 1.24, standard library only. No cgo, nothing to download.

    go run .                  # both orbs, animated in the terminal (Ctrl+C to stop)
    go run . -mode green      # only green (also: red, amber)
    go run . -ansi -t 3.7     # one frame as colour text
    go run . -out ./pictures  # write the GIFs and PNGs
    go test ./...

## What is in the folder

| File | What it is |
| --- | --- |
| `orb.go` | `DrawOrb`, the green, red and amber colours, the size rules. Read this one first. |
| `ring.go`, `ring_data.go`, `assets/ring/*.png` | The ring itself: six turning layers drawn as round Braille dots. Byte for byte the files the app uses. |
| `canvas.go` | A grid of character cells (`Canvas`) and the colour type. |
| `style.go` | Turns a canvas into a picture: round anti aliased dots on a flat background, as a full colour PNG or a GIF frame. |
| `main.go`, `vt_windows.go`, `vt_other.go` | The demo and the picture maker. `vt_windows.go` switches on colour text in an old style Windows console. |
| `orb_test.go`, `testdata/` | The checks (below). |
| `_windows-build/` | (The leading underscore keeps Go from compiling it here.) What to add to the Windows HUD source to put this orb in the Quant Core tile. |
| `tools/ring/` | How the six layers were cut from the reference picture. You do not need it to use the orb. |

## Using the orb in your own code

    c := NewCanvas(32, 14, RGB{4, 18, 27})        // 32 columns, 14 rows, the panel colour
    DrawOrb(c, 0, 0, 32, 14, seconds, OrbGreen)   // or OrbRed, OrbAmber
    fmt.Print(c.ANSI())                           // colour text for the terminal

`seconds` is the time of motion. Green turns and repeats exactly every 16 seconds.
Red ignores it, because nothing moves. The orb is centred in the rectangle you give
it and keeps its own size, so the rectangle must be at least `OrbCols(OrbGrow)` by
`OrbRows(OrbGrow)` cells, which is 32 by 14. Anything smaller cuts the ring off.

`cellAspect` is a cell's height over its width. It is 2.22 for Windows Terminal's
9 by 20 pixel cell, and it keeps the ring round. Change the variable if your font is
different.

## Why the size is 1.11 and not 1.10

The app's orb has a radius of 13.93 columns. The ring here is drawn at **1.11 times
that, 15.46 columns**, and it needs all 14 rows of the tile instead of 13.

The reason for 1.11 is the dots. They sit 4.5 by 5 pixels apart, about 2% of the
orb across, so the outline you see can only grow in steps of that size. At exactly
1.10 the outline lands just under a step and measures only 9% wider and 8% higher.
At 1.11 it lands on the next step and measures **11% wider and 10% higher**
(averaged over the 16 second loop), which is what looks 10% bigger. The GIFs show
the same: the lit orb is 820 by 821 pixels against 738 by 745 in the GIF you sent.
`OrbGrow` is one constant in `orb.go` if you want another size.

## Putting it in the Windows build

The `_windows-build` folder has everything. Copy the files into the HUD source
folder (next to `orb.go`), apply the two small diffs, then build as usual:

1. Copy `ring.go` over the app's `ring.go`. It is the same file plus one small hook, `ringRadius`, which lets the orb have a size of its own. With the hook at zero the app behaves exactly as before.
2. Copy `orb_big.go` and `orb_big_test.go` into the folder.
3. Apply `screens.go.diff`. The Quant Core tile then calls `drawOrbBig` and uses all 14 rows. The `ONLINE ◆ SCANNING` caption row goes, which is the order for build 7.
4. Apply `render_test.go.diff`. It removes the three caption words the old tests looked for.
5. `go vet ./... && go test ./...`, then build: `GOOS=windows GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -ldflags "-s -w -buildid="`.

If the tile is ever too small or `[` and `]` make the cells too short, `drawOrbBig`
falls back to the ring that fits, the way the app does today. It never draws outside
its rectangle.

## What was checked

* **Same as the app.** At the app's own size (scale 1.0, 38 by 13 cells) this code draws 251 of 251 cells identical to the app's own snapshot, with the same dots and the same colours, for green at 0 s and 3.7 s and for red. The golden files in `testdata/` were cut from the app's output.
* **Same in the app.** With the Windows build files applied to a copy of the app, the Quant Core tile shows the same 294 cells (green at 0 s, red) and 298 cells (green at 5.3 s) as this program, 0 differences.
* **10% bigger.** Measured on the lit dots over the whole 16 second loop: 11.0% wider and 10.1% higher here, 11.0% and 10.2% in the app tile.
* **Round, nothing cut off, red is still, green loops at 16 s, the GIFs have 241 colours and a 888 pixel square.** All in `orb_test.go`.
* `go vet` and `go test` pass, and `go vet` passes for `GOOS=windows`.

Not checked, because there is no Windows machine here: how big a Braille dot looks in
Cascadia Mono on your screen, and the colour mode of an old console (`vt_windows.go`
only has to compile). The GIFs draw the dots the way Windows Terminal's 9 by 20
cell does, which is why they are a fair picture of what you will see.

## How the orb is drawn, in short

Six layers (small dial, inner arcs, tick ring, thick glass ring, ring of blocks,
outer arcs) turn about their own centres at 22.5 or 45 degrees a second, in
alternating directions. Every dot is a pixel of the ring. A thin layer lights a dot
when its line covers a bit of it, so lines stay whole. A solid layer lights a dot
when the middle of the dot is inside the shape, so edges stay where the picture has
them. How bright a dot is follows how opaque its layer is. A cell has one ink for
all its dots, so a cell takes a mix of its brightest dot and the average.
Offline, nothing moves: every layer rests at the angle of the reference picture.
