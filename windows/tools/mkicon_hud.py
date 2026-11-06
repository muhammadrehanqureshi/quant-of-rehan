"""Draw the Quant of Rehan mark exactly as the owner's HUD picture: a teal tile
under concentric pale ice blue rings, one ring of heavy blocks, ribbed and tick
rings and a bright inner ring, with an empty centre.

Usage:
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

TOP = (12, 106, 142)
BOTTOM = (6, 82, 116)
PALE = (230, 244, 250)
MID = (176, 212, 228)
DIM = (108, 160, 184)


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
    # The picture's teal, a touch deeper at the bottom.
    small = Image.new("RGB", (2, 2))
    small.putpixel((0, 0), TOP)
    small.putpixel((1, 1), BOTTOM)
    mid = tuple((TOP[i] + BOTTOM[i]) // 2 for i in range(3))
    small.putpixel((1, 0), mid)
    small.putpixel((0, 1), mid)
    return small.resize((N, N), Image.BILINEAR).convert("RGBA")


def dial():
    layer = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    # The thin outer arc, almost a full circle, with a small gap and two caps.
    arc_block(d, 0.955, 0.990, 10, 348, rgba(ink(0.50), 210))
    for ang in (10, 348):
        a = math.radians(ang)
        x, y = CX + math.cos(a) * 0.9725 * N, CY + math.sin(a) * 0.9725 * N
        d.rectangle([x - N * 0.009, y - N * 0.009, x + N * 0.009, y + N * 0.009],
                    fill=rgba(ink(0.80), 235))

    # The ring of heavy blocks, twelve of them.
    for k in range(12):
        a0 = k * 30 + 4
        arc_block(d, 0.800, 0.930, a0, a0 + 22, rgba(ink(0.92), 245))

    # The ribbed ring.
    for k in range(40):
        a0 = k * 9 + 1
        arc_block(d, 0.690, 0.760, a0, a0 + 7.0, rgba(ink(0.62), 220))

    # The first dense tick ring.
    for i in range(64):
        a = i * (360 / 64)
        arc_block(d, 0.615, 0.700, a + 0.4, a + 1.5, rgba(ink(0.88), 225))

    # The bright inner ring, in a few long segments.
    for k in range(6):
        a0 = k * 60 + 5
        arc_block(d, 0.455, 0.545, a0, a0 + 47, rgba(ink(1.0), 250))

    # The second tick ring.
    for i in range(48):
        a = i * (360 / 48)
        arc_block(d, 0.360, 0.440, a + 0.4, a + 1.6, rgba(ink(0.76), 225))

    # The small inner ring.
    for i in range(36):
        a = i * 10
        arc_block(d, 0.230, 0.290, a + 0.6, a + 2.6, rgba(ink(0.70), 220))
    return layer


def main():
    out = Image.alpha_composite(background(), dial())
    out = out.resize((S, S), Image.LANCZOS)
    out.save(OUT_PNG)
    out.save(OUT_ICO, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote", OUT_PNG, "and", OUT_ICO)


if __name__ == "__main__":
    main()
