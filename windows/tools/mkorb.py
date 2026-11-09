#!/usr/bin/env python3
"""Copy the owner's orb GIF into windows/orbpattern.go.

Owner order 2026-11-09: the HUD orb must be the GIF, not a drawing of it. The
earlier sampler quantised the artwork onto a 55 by 50 dot lattice, which moved
dots and closed the gaps between them, so the console never matched the file.
This one keeps the picture: every frame is sampled onto a square dot raster at
152 by 152, each dot keeping one of the GIF's own two greens, every frame plays
at its own declared delay, and the whole raster set is zlib compressed so 160
frames fit in a source file instead of eight hundred kilobytes of base64.

Run from the windows directory: python tools/mkorb.py
"""

from __future__ import annotations

import base64
import math
import zlib
from pathlib import Path

import numpy as np
from PIL import Image

RASTER = 152

HERE = Path(__file__).resolve().parent
ASSET = HERE.parent / "assets" / "orb-online-green-refined.gif"
OUT = HERE.parent / "orbpattern.go"
PREVIEW = HERE.parent / "orb-preview.png"


def load_frames():
    im = Image.open(ASSET)
    count = getattr(im, "n_frames", 1)
    frames, delays = [], []
    for index in range(count):
        im.seek(index)
        frames.append(im.convert("RGB").copy())
        delays.append(max(10, int(im.info.get("duration", 80) or 80)))
    return frames, delays


def luminance(frame):
    arr = np.asarray(frame, dtype=np.float32)
    return 0.2126 * arr[..., 0] + 0.7152 * arr[..., 1] + 0.0722 * arr[..., 2]


def sample(frame):
    """Max luminance per raster cell: a dot lights every cell it covers."""
    lum = luminance(frame)
    height, width = lum.shape
    xs = np.arange(RASTER + 1) * width // RASTER
    ys = np.arange(RASTER + 1) * height // RASTER
    row_max = np.maximum.reduceat(lum, xs[:-1], axis=1)[:, :RASTER]
    return np.maximum.reduceat(row_max, ys[:-1], axis=0)[:RASTER, :]


def two_means(values):
    """Two luminance centroids; the GIF has exactly two shades."""
    low, high = float(values.min()), float(values.max())
    if high - low < 1e-6:
        return low, high
    for _ in range(32):
        mid = (low + high) / 2
        below, above = values[values <= mid], values[values > mid]
        if below.size == 0 or above.size == 0:
            break
        new_low, new_high = float(below.mean()), float(above.mean())
        done = abs(new_low - low) < 0.05 and abs(new_high - high) < 0.05
        low, high = new_low, new_high
        if done:
            break
    return low, high


def palette(first):
    arr = np.asarray(first, dtype=np.float32)
    flat, lum = arr.reshape(-1, 3), luminance(first).reshape(-1)
    background = float(np.percentile(lum, 30))
    mask = lum > background + (float(lum.max()) - background) * 0.30
    if not mask.any():
        raise SystemExit("the GIF has no lit pixels above its background")
    dim_lum, bright_lum = two_means(lum[mask])
    mid = (dim_lum + bright_lum) / 2
    lit = lum[mask]
    dim_px, bright_px = flat[mask][lit <= mid], flat[mask][lit > mid]
    dim = tuple(int(round(v)) for v in dim_px.mean(axis=0))
    bright = tuple(int(round(v)) for v in bright_px.mean(axis=0))
    return background, dim_lum, bright_lum, dim, bright


def quantise(cells, background, dim_lum, bright_lum):
    """0 for no dot, 1 for the dim green, 2 for the bright green."""
    lit_at = (background + dim_lum) / 2
    bright_at = (dim_lum + bright_lum) / 2
    levels = np.zeros(cells.shape, dtype=np.uint8)
    levels[cells > lit_at] = 1
    levels[cells > bright_at] = 2
    return levels


def pack(levels):
    flat = levels.reshape(-1)
    padded = np.zeros((len(flat) + 3) // 4 * 4, dtype=np.uint8)
    padded[:len(flat)] = flat
    return ((padded[0::4])
            | (padded[1::4] << 2)
            | (padded[2::4] << 4)
            | (padded[3::4] << 6)).astype(np.uint8).tobytes()


def wrap(text, width=96):
    return "\n".join(text[i:i + width] for i in range(0, len(text), width))


HUD_PITCH = 2      # one empty console dot between dots, so a dot stays a dot
HUD_ROWS = 28      # the 120 by 30 home panel offers 56 dots down, halved
HUD_ASPECT = 1.11  # cellAspect / 2: a square source stays square on screen
HUD_COVER = 0.25   # orbDotCover: how much of a point the GIF must fill
HUD_SCALE = 1.00   # orbScale: the mark fills its tile
HUD_BANDS = 8      # orbBands: rings of alternating shade from the middle out


def hud_grid(frame, rows=HUD_ROWS, aspect=HUD_ASPECT):
    """What orbGrid draws: one dot per lattice point, one empty dot between,
    and the two shades alternating ring by ring from the middle outward."""
    size = frame.shape[0]
    rows = max(1, round(rows * HUD_SCALE))
    cols = max(1, round(rows * aspect))
    band = max(2, round(cols / 2 / HUD_BANDS))
    cx, cy = (cols - 1) / 2, (rows - 1) / 2
    out = np.zeros((rows, cols), dtype=np.uint8)
    for j in range(rows):
        sy0 = j * size // rows
        sy1 = max(sy0 + 1, (j + 1) * size // rows)
        for i in range(cols):
            sx0 = i * size // cols
            sx1 = max(sx0 + 1, (i + 1) * size // cols)
            block = frame[sy0:sy1, sx0:sx1]
            if float(block.mean()) < HUD_COVER:
                continue
            out[j, i] = 2 if int(math.hypot(i - cx, j - cy) / band) % 2 == 0 else 1
    return out


def hud_tile(grid, dim, bright, cell=8, dot=4):
    """The console's own lattice: a dot of four pixels with four between."""
    rows, cols = grid.shape
    img = Image.new("RGB", (cols * HUD_PITCH * cell, rows * HUD_PITCH * cell), (7, 18, 28))
    pixels = img.load()
    for j in range(rows):
        for i in range(cols):
            value = grid[j, i]
            if value == 0:
                continue
            colour = bright if value >= 2 else dim
            x0, y0 = i * HUD_PITCH * cell, j * HUD_PITCH * cell
            for dy in range(dot):
                for dx in range(dot):
                    pixels[x0 + dx, y0 + dy] = colour
    return img


def tile(grid, dim, bright, scale):
    rows, cols = grid.shape
    img = Image.new("RGB", (cols * scale, rows * scale), (7, 18, 28))
    pixels = img.load()
    for y in range(rows):
        for x in range(cols):
            value = grid[y, x]
            if value == 0:
                continue
            colour = bright if value >= 2 else dim
            for dy in range(scale):
                for dx in range(scale):
                    pixels[x * scale + dx, y * scale + dy] = colour
    return img


WIDE_ROWS = 52  # a 60 cell wide column at a 180 column window


def shade(colour, factor):
    """darken() in orb.go: the panel's shades are the GIF's, taken down."""
    return tuple(int(round(v * factor)) for v in colour)


def draw_preview(levels, dim, bright, path):
    """The GIF's raster, then the console lattice at the home and wide panels."""
    showcase = [0, len(levels) // 4] if len(levels) > 1 else [0]
    hud_dim, hud_bright = shade(dim, 0.55), shade(bright, 0.82)
    rows = [
        [tile(levels[i], dim, bright, 2) for i in showcase],
        [hud_tile(hud_grid(levels[i], rows=HUD_ROWS), hud_dim, hud_bright) for i in showcase],
        [hud_tile(hud_grid(levels[i], rows=WIDE_ROWS), hud_dim, hud_bright) for i in showcase],
    ]
    gap = 12
    width = max(sum(t.width for t in row) + gap * (len(row) - 1) for row in rows)
    height = sum(row[0].height for row in rows) + gap * (len(rows) - 1)
    strip = Image.new("RGB", (width, height), (7, 18, 28))
    y = 0
    for row in rows:
        x = 0
        for t in row:
            strip.paste(t, (x, y))
            x += t.width + gap
        y += row[0].height + gap
    strip.save(path)


def main():
    frames, delays = load_frames()
    if not frames:
        raise SystemExit("the GIF has no frames")
    background, dim_lum, bright_lum, dim, bright = palette(frames[0])
    levels = [quantise(sample(f), background, dim_lum, bright_lum) for f in frames]
    blob = zlib.compress(b"".join(pack(frame) for frame in levels), 9)
    payload = base64.b64encode(blob).decode("ascii")
    delays_go = ", ".join(str(v) for v in delays)
    hexed = lambda colour: f"0x{colour[0]:02x}{colour[1]:02x}{colour[2]:02x}"
    source = f'''package main

import (
\t"bytes"
\t"compress/zlib"
\t"encoding/base64"
\t"io"
\t"strings"
)

// Generated by tools/mkorb.py from assets/orb-online-green-refined.gif. Do not
// edit by hand: the Windows workflow regenerates this file before it tests and
// builds. This is the owner's GIF itself, sampled onto a square dot raster at
// {RASTER} by {RASTER}; each cell is 0 (no dot), 1 (the dim green) or 2 (the
// bright green), four cells to a byte, every frame back to back, zlib
// compressed. orbDelays is each frame's own display time in milliseconds, as
// the GIF declares it.
const (
\torbRaster = {RASTER}

\torbGreenDim    = {hexed(dim)}
\torbGreenBright = {hexed(bright)}

\torbFramesB64 = `{wrap(payload)}`
)

var (
\torbDelays = []int{{{delays_go}}}

\torbFrames = decodeOrbFrames()
)

func decodeOrbFrames() [][]uint8 {{
\tjoined := strings.ReplaceAll(orbFramesB64, "\\n", "")
\tif joined == "" {{
\t\treturn nil
\t}}
\tpacked, err := base64.StdEncoding.DecodeString(joined)
\tif err != nil {{
\t\treturn nil
\t}}
\treader, err := zlib.NewReader(bytes.NewReader(packed))
\tif err != nil {{
\t\treturn nil
\t}}
\tdefer reader.Close()
\tall, err := io.ReadAll(reader)
\tif err != nil {{
\t\treturn nil
\t}}
\tsize := orbRaster * orbRaster
\tperFrame := (size + 3) / 4
\tif perFrame == 0 || len(all)%perFrame != 0 {{
\t\treturn nil
\t}}
\tframes := make([][]uint8, 0, len(all)/perFrame)
\tfor offset := 0; offset+perFrame <= len(all); offset += perFrame {{
\t\tlevels := make([]uint8, size)
\t\tfor index := 0; index < size; index++ {{
\t\t\tlevels[index] = (all[offset+index/4] >> (2 * uint(index%4))) & 0x3
\t\t}}
\t\tframes = append(frames, levels)
\t}}
\treturn frames
}}
'''
    OUT.write_text(source, encoding="utf-8", newline="\n")
    draw_preview(levels, dim, bright, PREVIEW)
    lit = int((levels[0] > 0).sum())
    print(f"orb: {len(frames)} frames, {lit} lit dots of {RASTER * RASTER}, "
          f"{max(delays)} ms longest frame")
    print(f"greens: dim #{dim[0]:02x}{dim[1]:02x}{dim[2]:02x}, "
          f"bright #{bright[0]:02x}{bright[1]:02x}{bright[2]:02x}")
    for name, count in (("home", HUD_ROWS), ("wide", WIDE_ROWS)):
        hud = hud_grid(levels[0], rows=count)
        rows, cols = hud.shape
        print(f"hud {name}: {int((hud > 0).sum())} of {cols * rows} dots lit at "
              f"{cols} by {rows}, one empty dot between (pitch {HUD_PITCH})")
    print(f"wrote {OUT.name} ({OUT.stat().st_size} bytes) and {PREVIEW.name}")


if __name__ == "__main__":
    main()
