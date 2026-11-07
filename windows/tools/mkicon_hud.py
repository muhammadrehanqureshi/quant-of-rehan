"""Draw the owner's teal dial artwork as the Windows icon: a square teal tile
under concentric pale ice blue rings, with the thin outer arc, twelve heavy
blocks, a smooth ring, two tick rings, the bright inner ring and the small inner
ring, and an empty centre.

Usage:
    python mkicon_hud.py assets/QuantOfRehan.ico assets/icon-1024.png
"""
import math
import sys

from PIL import Image, ImageDraw, ImageFilter

OUT_ICO, OUT_PNG = sys.argv[1], sys.argv[2]
S = 1024
K = 2
N = S * K
CX = CY = N / 2

TOP_LEFT = (14, 112, 143)
TOP_RIGHT = (10, 93, 122)
BOTTOM_LEFT = (8, 82, 109)
BOTTOM_RIGHT = (5, 60, 82)
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


def background():
    # The picture's teal, lighter at the top left and deeper at the bottom right.
    small = Image.new("RGB", (2, 2))
    small.putpixel((0, 0), TOP_LEFT)
    small.putpixel((1, 0), TOP_RIGHT)
    small.putpixel((0, 1), BOTTOM_LEFT)
    small.putpixel((1, 1), BOTTOM_RIGHT)
    return small.resize((N, N), Image.BILINEAR).convert("RGBA")


def cap(d, ang, r, size, fill):
    a = math.radians(ang)
    x, y = CX + math.cos(a) * r * N, CY + math.sin(a) * r * N
    h = N * size
    d.rectangle([x - h, y - h, x + h, y + h], fill=fill)


def dial():
    layer = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    # The thin outer arc, almost a full circle, with a small gap at the top and
    # the picture's four square caps on the diagonals.
    arc_block(d, 0.955, 0.990, 12, 348, rgba(ink(0.55), 215))
    cap(d, 12, 0.9725, 0.0085, rgba(ink(0.85), 235))
    cap(d, 348, 0.9725, 0.0085, rgba(ink(0.85), 235))
    for ang in (45, 135, 225, 315):
        cap(d, ang, 0.9725, 0.0075, rgba(ink(0.90), 240))

    # The ring of twelve heavy blocks, the picture's most visible band.
    for k in range(12):
        a0 = k * 30 + 4
        arc_block(d, 0.805, 0.930, a0, a0 + 22, rgba(ink(0.94), 245))

    # The smooth pale ring under the blocks, in four long segments.
    for k in range(4):
        a0 = k * 90 + 2
        arc_block(d, 0.700, 0.770, a0, a0 + 86, rgba(ink(0.72), 225))

    # The first tick ring.
    for i in range(64):
        a = i * (360 / 64)
        arc_block(d, 0.610, 0.685, a + 0.4, a + 1.5, rgba(ink(0.88), 225))

    # The bright inner ring, in six long segments.
    for k in range(6):
        a0 = k * 60 + 5
        arc_block(d, 0.450, 0.545, a0, a0 + 47, rgba(ink(1.0), 250))

    # The second tick ring.
    for i in range(48):
        a = i * (360 / 48)
        arc_block(d, 0.350, 0.435, a + 0.4, a + 1.6, rgba(ink(0.76), 225))

    # The small inner ring, in twelve short segments around an empty centre.
    for i in range(12):
        a0 = i * 30 + 7
        arc_block(d, 0.235, 0.295, a0, a0 + 16, rgba(ink(0.80), 235))
    return layer


def main():
    art = dial()
    # A soft halo under the pale segments, like the glow in the picture.
    halo = art.filter(ImageFilter.GaussianBlur(N * 0.010))
    halo.putalpha(halo.getchannel("A").point(lambda v: int(v * 0.55)))
    out = Image.alpha_composite(background(), halo)
    out = Image.alpha_composite(out, art)
    out = out.resize((S, S), Image.LANCZOS)
    out.save(OUT_PNG)
    out.save(OUT_ICO, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote", OUT_PNG, "and", OUT_ICO)


if __name__ == "__main__":
    main()
