"""Draw the Quant of Rehan mark: a HUD dial in the owner's blue.

Inspired by the owner's HUD picture, not a copy of it. A blue gradient glass
tile carries concentric segmented rings, tick rings, a thin outer arc with end
caps and a pale centre. Usage:
    python mkicon_hud.py assets/QuantOfRehan.ico assets/icon-1024.png
"""
import math
import sys

from PIL import Image, ImageDraw

OUT_ICO, OUT_PNG = sys.argv[1], sys.argv[2]
S = 1024
K = 2
N = S * K
CX = CY = N / 2

TOP_LEFT = (0, 124, 176)
BOTTOM_RIGHT = (0, 66, 102)
PALE = (232, 244, 248)
MID = (168, 208, 224)
DIM = (96, 150, 176)


def rgba(c, a=255):
    return (c[0], c[1], c[2], a)


def arc_block(d, r0, r1, a0, a1, fill):
    """A filled arc segment between two radii, angles in degrees."""
    steps = max(4, int(abs(a1 - a0) / 1.5))
    pts = []
    for i in range(steps + 1):
        a = math.radians(a0 + (a1 - a0) * i / steps)
        pts.append((CX + math.cos(a) * r1 * N, CY + math.sin(a) * r1 * N))
    for i in range(steps, -1, -1):
        a = math.radians(a0 + (a1 - a0) * i / steps)
        pts.append((CX + math.cos(a) * r0 * N, CY + math.sin(a) * r0 * N))
    d.polygon(pts, fill=fill)


def tick(d, r0, r1, a, fill, width):
    a = math.radians(a)
    d.line([CX + math.cos(a) * r0 * N, CY + math.sin(a) * r0 * N,
            CX + math.cos(a) * r1 * N, CY + math.sin(a) * r1 * N],
           fill=fill, width=width)


def background():
    # A 2x2 corner grid stretched smoothly gives a diagonal gradient cheaply.
    small = Image.new("RGB", (2, 2))
    small.putpixel((0, 0), TOP_LEFT)
    small.putpixel((1, 1), BOTTOM_RIGHT)
    mid = tuple((TOP_LEFT[i] + BOTTOM_RIGHT[i]) // 2 for i in range(3))
    small.putpixel((1, 0), mid)
    small.putpixel((0, 1), mid)
    return small.resize((N, N), Image.BILINEAR).convert("RGBA")


def dial():
    layer = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    # Outer ring of heavy blocks, twelve of them.
    for k in range(12):
        a0 = k * 30 + 4
        arc_block(d, 0.352, 0.384, a0, a0 + 20, rgba(PALE, 240))

    # Thin outer arc with two end caps, over the top-left quarter.
    arc_block(d, 0.405, 0.410, 196, 292, rgba(MID, 210))
    for ang in (196, 292):
        a = math.radians(ang)
        x, y = CX + math.cos(a) * 0.4075 * N, CY + math.sin(a) * 0.4075 * N
        d.rectangle([x - N * 0.008, y - N * 0.008, x + N * 0.008, y + N * 0.008], fill=rgba(PALE, 230))

    # Segmented middle ring, with one brighter section.
    for a0, a1, c, al in ((-150, -40, MID, 200), (-30, 50, PALE, 235), (70, 150, MID, 200)):
        arc_block(d, 0.292, 0.310, a0, a1, rgba(c, al))

    # Dense tick ring, long tick every fifteen degrees.
    for i in range(120):
        a = i * 3
        length = 0.022 if i % 5 == 0 else 0.011
        tick(d, 0.258 - length * 0.4, 0.258 + length, a, rgba(PALE, 220), max(2, int(N * 0.0025)))

    # Inner segmented ring with a dim gap.
    for a0, a1, c, al in ((-120, 30, PALE, 225), (40, 110, MID, 190), (120, 230, PALE, 225)):
        arc_block(d, 0.205, 0.226, a0, a1, rgba(c, al))

    # Small inner tick ring and a pale centre.
    for i in range(60):
        tick(d, 0.150, 0.162 if i % 5 else 0.170, i * 6, rgba(MID, 200), max(2, int(N * 0.002)))
    r = N * 0.075
    for i in range(16, 0, -1):
        f = i / 16
        rr = r * f
        col = tuple(int(PALE[k] * (1 - f) + MID[k] * f) for k in range(3))
        d.ellipse([CX - rr, CY - rr, CX + rr, CY + rr], fill=rgba(col, 255))
    return layer


def main():
    pad = int(N * 0.035)
    radius = int(N * 0.16)
    mask = Image.new("L", (N, N), 0)
    ImageDraw.Draw(mask).rounded_rectangle([pad, pad, N - pad, N - pad], radius=radius, fill=255)
    base = background()
    base.putalpha(mask)
    base = Image.alpha_composite(base, dial())
    out = base.resize((S, S), Image.LANCZOS)
    out.save(OUT_PNG)
    out.save(OUT_ICO, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote", OUT_PNG, "and", OUT_ICO)


if __name__ == "__main__":
    main()
