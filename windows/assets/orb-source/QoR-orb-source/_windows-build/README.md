Files for the Windows HUD source. Copy them into the folder that holds `orb.go`.

    ring.go             replaces the app's ring.go (adds the ringRadius hook, nothing else changes)
    orb_big.go          new: drawOrbBig, the orb 10% bigger
    orb_big_test.go     new: size, nothing cut off, fallback, red is still
    screens.go.diff     patch: the Quant Core tile draws drawOrbBig in all 14 rows (the caption row goes)
    render_test.go.diff patch: removes the three caption words from the old tests

Apply the two patches from the HUD source folder, with `git apply` (it also works
outside a git repository) or with `patch` (Git for Windows ships it):

    git apply path\to\_windows-build\screens.go.diff
    git apply path\to\_windows-build\render_test.go.diff

Or make the edit by hand, it is small. In `drawLeft` in screens.go, replace everything
between the `a.panel(... "QUANT CORE", "")` line and the blank line before the
`TELEMETRY` panel (the `mode :=` line, the `drawOrb(...)` call, the `cap` switch and
the `centerText` caption) with this one line:

    drawOrbBig(c, ix, iy, iw, ih, a.animSeconds(), a.orbMode())

In render_test.go, delete the strings "ONLINE  ◆  SCANNING", "OFFLINE  ◆  PARKED" and
"RELAY UNREACHABLE" from the three lists that expect them.

Then: go vet ./... && go test ./... and build as usual. The full steps are in the main README.
