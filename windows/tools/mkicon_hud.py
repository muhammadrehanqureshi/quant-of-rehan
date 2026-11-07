"""Make the Windows icon. When the owner's exact picture is saved at
assets/icon-source.png, that bitmap is used unchanged apart from a square crop
and the rounded corners. Otherwise the red dial is drawn as before: a rounded
dark maroon tile
under concentric bright red rings, with the thin outer arc, twelve bright
blocks, a smooth ring, two tick rings, the bright inner ring and the small inner
ring, and an empty centre. The tile's corners are transparent, so Explorer
shows the rounded app tile the owner asked for.

Usage:
    python mkicon_hud.py assets/QuantOfRehan.ico assets/icon-1024.png
"""
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFilter

OUT_ICO, OUT_PNG = sys.argv[1], sys.argv[2]
SOURCE = "assets/icon-source.png"
S = 1024
K = 2
N = S * K
CX = CY = N / 2
# The dial's outer radius, as a fraction of the half canvas. The picture keeps
# a small margin of plain teal around its thin outer arc.
R = N * 0.48

# The tile's rounded corners, as a fraction of the full canvas, and the thin
# transparent margin that keeps the rounded shape off the exact edge.
CORNER_RADIUS = 0.18
CORNER_INSET = 0.012

# The HUD's own red (owner order 2026-11-07): the tile is the dark maroon of
# the panel and the rings run from deep red to the bright red of the ORB.
TOP_LEFT = (58, 8, 10)
TOP_RIGHT = (46, 6, 8)
BOTTOM_LEFT = (36, 4, 6)
BOTTOM_RIGHT = (28, 3, 4)
PALE = (255, 96, 96)
MID = (240, 48, 48)
DIM = (150, 18, 20)


def rgba(c, a=255):
    return (c[0], c[1], c[2], a)


def ink(tone):
    return tuple(int(DIM[i] + (PALE[i] - DIM[i]) * tone) for i in range(3))


def arc_block(d, r0, r1, a0, a1, fill):
    """A filled arc segment between two radii, angles in degrees."""
    steps = max(4, int(abs(a1 - a0) / 1.5))
    pts = []
    for i in range(steps + 1):
        a = math.radians(a0 + (a1 - a0) * i / steps)
        pts.append((CX + math.cos(a) * r1 * R, CY + math.sin(a) * r1 * R))
    for i in range(steps, -1, -1):
        a = math.radians(a0 + (a1 - a0) * i / steps)
        pts.append((CX + math.cos(a) * r0 * R, CY + math.sin(a) * r0 * R))
    d.polygon(pts, fill=fill)


def background():
    # The tile's maroon, lighter at the top left and deeper at the bottom right.
    small = Image.new("RGB", (2, 2))
    small.putpixel((0, 0), TOP_LEFT)
    small.putpixel((1, 0), TOP_RIGHT)
    small.putpixel((0, 1), BOTTOM_LEFT)
    small.putpixel((1, 1), BOTTOM_RIGHT)
    return small.resize((N, N), Image.BILINEAR).convert("RGBA")


def cap(d, ang, r, size, fill):
    a = math.radians(ang)
    x, y = CX + math.cos(a) * r * R, CY + math.sin(a) * r * R
    h = N * size
    d.rectangle([x - h, y - h, x + h, y + h], fill=fill)


def near(a, target, width):
    """True when angle a is within width degrees of target, across 0."""
    return abs(((a - target + 180) % 360) - 180) < width


def dial():
    layer = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    # The thin outer arc, almost a full circle, with a small gap at the top and
    # the picture's four square caps on the diagonals.
    arc_block(d, 0.962, 0.986, 12, 348, rgba(ink(0.78), 225))
    cap(d, 12, 0.974, 0.0078, rgba(ink(0.95), 240))
    cap(d, 348, 0.974, 0.0078, rgba(ink(0.95), 240))
    for ang in (45, 135, 225, 315):
        cap(d, ang, 0.974, 0.0068, rgba(ink(0.90), 240))

    # The ring of twelve pale blocks, the picture's most visible band. They
    # sit on the 12 o'clock marks, as in the picture, rather than between them.
    for k in range(12):
        a0 = k * 30 - 12
        arc_block(d, 0.815, 0.915, a0, a0 + 24, rgba(ink(0.94), 245))

    # The smooth pale ring under the blocks, in four long segments.
    for k in range(4):
        a0 = k * 90 + 2
        arc_block(d, 0.700, 0.765, a0, a0 + 86, rgba(ink(0.72), 225))

    # The first tick ring, dense like the picture's, with the four diagonal
    # breaks the picture has.
    for i in range(120):
        a = i * 3
        if any(near(a, t, 2.4) for t in (45, 135, 225, 315)):
            continue
        arc_block(d, 0.590, 0.670, a + 0.15, a + 0.60, rgba(ink(0.88), 225))

    # The bright inner ring, in six long segments.
    for k in range(6):
        a0 = k * 60 + 5
        arc_block(d, 0.455, 0.535, a0, a0 + 48, rgba(ink(1.0), 250))

    # The second tick ring, with the six breaks of the bright ring above it.
    for i in range(72):
        a = i * 5
        if any(near(a, t, 2.6) for t in (5, 65, 125, 185, 245, 305)):
            continue
        arc_block(d, 0.355, 0.430, a + 0.15, a + 0.65, rgba(ink(0.76), 225))

    # The small inner ring, thin dashes around an empty centre.
    for i in range(36):
        a = i * (360 / 36)
        arc_block(d, 0.240, 0.295, a + 0.4, a + 1.8, rgba(ink(0.80), 235))
    return layer


def source_art():
    """The owner's exact picture, square and at the working resolution."""
    im = Image.open(SOURCE).convert("RGBA")
    w, h = im.size
    side = min(w, h)
    im = im.crop(((w - side) // 2, (h - side) // 2, (w + side) // 2, (h + side) // 2))
    return im.resize((N, N), Image.LANCZOS)


def main():
    if os.path.exists(SOURCE):
        out = source_art()
        print("using the owner's exact picture", SOURCE)
    else:
        art = dial()
        # A soft halo under the pale segments, like the glow in the picture.
        halo = art.filter(ImageFilter.GaussianBlur(N * 0.011))
        halo.putalpha(halo.getchannel("A").point(lambda v: int(v * 0.55)))
        out = Image.alpha_composite(background(), halo)
        out = Image.alpha_composite(out, art)
    # Round the tile's corners. The mask is drawn at the supersampled size and
    # reduced with the artwork, so the edge stays smooth at 16 pixels too.
    mask = Image.new("L", (N, N), 0)
    m = ImageDraw.Draw(mask)
    inset = int(N * CORNER_INSET)
    m.rounded_rectangle(
        [inset, inset, N - 1 - inset, N - 1 - inset],
        radius=int(N * CORNER_RADIUS),
        fill=255,
    )
    out.putalpha(
        Image.composite(out.getchannel("A"), Image.new("L", (N, N), 0), mask)
    )
    out = out.resize((S, S), Image.LANCZOS)
    out.save(OUT_PNG)
    out.save(OUT_ICO, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote rounded", OUT_PNG, "and", OUT_ICO)


if __name__ == "__main__":
    main()
