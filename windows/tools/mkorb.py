#!/usr/bin/env python3
"""Sample the owner's orb GIF into windows/orbpattern.go.

Owner order 2026-11-09: the HUD orb must be the attached GIF itself, not a
drawing of it. Every frame of assets/orb-online-green-refined.gif is sampled
onto the same 55 by 50 dot grid, every dot keeps one of the GIF's own two
green shades, and the console plays the frames at each frame's own delay. That
is why this file writes the data instead of a hand-drawn animation: the
rotation and the shading both come from the source pixels.

The script also writes orb-preview.png, an enlargement of the first and a
quarter-turn frame, so the build artifact can be looked at without launching
the console.

Run from the windows directory: python tools/mkorb.py
"""

from __future__ import annotations

import base64
from pathlib import Path

import numpy as np
from PIL import Image

COLS, ROWS = 55, 50

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


def sample_grid(frame):
    """Max luminance per cell: a dot lights its cell wherever it sits in it."""
    lum = luminance(frame)
    height, width = lum.shape
    xs = np.arange(COLS + 1) * width // COLS
    ys = np.arange(ROWS + 1) * height // ROWS
    row_max = np.maximum.reduceat(lum, xs[:-1], axis=1)[:, :COLS]
    cells = np.maximum.reduceat(row_max, ys[:-1], axis=0)[:ROWS, :]
    return cells.ravel().tolist()


def two_means(values):
    """Two luminance centroids; the GIF has exactly two green shades."""
    low, high = float(values.min()), float(values.max())
    if high - low < 1e-6:
        return low, high
    for _ in range(32):
        mid = (low + high) / 2
        below = values[values <= mid]
        above = values[values > mid]
        if below.size == 0 or above.size == 0:
            break
        new_low, new_high = float(below.mean()), float(above.mean())
        done = abs(new_low - low) < 0.05 and abs(new_high - high) < 0.05
        low, high = new_low, new_high
        if done:
            break
    return low, high


def palette_colours(frame):
    """The two greens: the mean colour of each luminance cluster."""
    arr = np.asarray(frame, dtype=np.float32)
    flat = arr.reshape(-1, 3)
    lum = luminance(frame).reshape(-1)
    background = float(np.percentile(lum, 30))
    mask = lum > background + (float(lum.max()) - background) * 0.30
    if not mask.any():
        raise SystemExit("the GIF has no lit pixels above its background")
    lit = lum[mask]
    dim_lum, bright_lum = two_means(lit)
    mid = (dim_lum + bright_lum) / 2
    dim_pixels = flat[mask][lit <= mid]
    bright_pixels = flat[mask][lit > mid]
    dim = tuple(int(round(value)) for value in dim_pixels.mean(axis=0))
    bright = tuple(int(round(value)) for value in bright_pixels.mean(axis=0))
    return background, dim_lum, bright_lum, dim, bright


def quantise(cells, background, dim_lum, bright_lum):
    """0 for no dot, 1 for the dim green, 2 for the bright green."""
    lit_at = (background + dim_lum) / 2
    bright_at = (dim_lum + bright_lum) / 2
    levels = []
    for value in cells:
        if value <= lit_at:
            levels.append(0)
        elif value < bright_at:
            levels.append(1)
        else:
            levels.append(2)
    return levels


def pack(levels):
    raw = bytearray((len(levels) + 3) // 4)
    for index, value in enumerate(levels):
        raw[index // 4] |= (value & 0x3) << (2 * (index % 4))
    return base64.b64encode(bytes(raw)).decode("ascii")


def wrap(text, width=96):
    return "\n".join(text[i:i + width] for i in range(0, len(text), width))


def draw_preview(level_frames, dim, bright, path):
    scale = 8
    count = len(level_frames)
    showcase = [0, count // 4] if count > 1 else [0]
    strip = Image.new(
        "RGB",
        (COLS * scale * len(showcase) + 8 * (len(showcase) - 1), ROWS * scale),
        (7, 18, 28),
    )
    for slot, index in enumerate(showcase):
        frame = Image.new("RGB", (COLS * scale, ROWS * scale), (7, 18, 28))
        pixels = frame.load()
        levels = level_frames[index]
        for row in range(ROWS):
            for col in range(COLS):
                value = levels[row * COLS + col]
                if value == 0:
                    continue
                colour = bright if value >= 2 else dim
                for y in range(row * scale, (row + 1) * scale - 2):
                    for x in range(col * scale, (col + 1) * scale - 2):
                        pixels[x, y] = colour
        strip.paste(frame, (slot * (COLS * scale + 8), 0))
    strip.save(path)


def main():
    frames, delays = load_frames()
    if not frames:
        raise SystemExit("the GIF has no frames")
    background, dim_lum, bright_lum, dim, bright = palette_colours(frames[0])
    level_frames = [quantise(sample_grid(frame), background,
                             dim_lum, bright_lum) for frame in frames]
    payload = "|".join(pack(levels) for levels in level_frames)
    delays_go = ", ".join(str(value) for value in delays)
    hexed = lambda colour: f"0x{colour[0]:02x}{colour[1]:02x}{colour[2]:02x}"
    source = f'''package main

import (
\t"encoding/base64"
\t"strings"
)

// Generated by tools/mkorb.py from
// assets/orb-online-green-refined.gif. Do not edit by hand: the Windows
// workflow regenerates this file before it tests and builds, so the shipped
// dots, shades and frame timing are the GIF's own pixels.
//
// {len(frames)} frames, a {COLS} by {ROWS} dot grid. Each dot is 0 (no dot),
// 1 (the dim green) or 2 (the bright green), four dots to a byte, frames
// separated by a bar. orbDelays is each frame's own display time in
// milliseconds, as the GIF declares it.
const (
\torbCols = {COLS}
\torbRows = {ROWS}

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
\tsize := orbCols * orbRows
\tframes := make([][]uint8, 0, 32)
\tfor _, part := range strings.Split(joined, "|") {{
\t\traw, err := base64.StdEncoding.DecodeString(part)
\t\tif err != nil || len(raw) < (size+3)/4 {{
\t\t\treturn nil
\t\t}}
\t\tlevels := make([]uint8, size)
\t\tfor index := 0; index < size; index++ {{
\t\t\tlevels[index] = (raw[index/4] >> (2 * uint(index%4))) & 0x3
\t\t}}
\t\tframes = append(frames, levels)
\t}}
\treturn frames
}}
'''
    OUT.write_text(source, encoding="utf-8", newline="\n")
    draw_preview(level_frames, dim, bright, PREVIEW)
    lit = sum(1 for value in level_frames[0] if value)
    print(f"orb: {len(frames)} frames, {lit} lit dots, "
          f"{max(delays)} ms longest frame")
    print(f"greens: dim #{dim[0]:02x}{dim[1]:02x}{dim[2]:02x}, "
          f"bright #{bright[0]:02x}{bright[1]:02x}{bright[2]:02x}")
    print(f"wrote {OUT.name} and {PREVIEW.name}")


if __name__ == "__main__":
    main()
