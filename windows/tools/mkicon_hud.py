"""Draw the Quant of Rehan mark: the gold sun inside a wireframe sphere.

It follows the owner's picture rather than the old radar. The icon has the dark
glass of the desktop HUD, a gold sun with short rays and a slowly implied mesh
of gold nodes. There is no antenna beam and no target. Usage:
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
R = N * 0.405

BG = (3, 7, 13, 255)
PANEL = (10, 21, 31, 255)
GOLD_DIM = (112, 69, 13, 255)
GOLD = (224, 157, 38, 255)
GOLD_HOT = (255, 240, 190, 255)


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def rgba(c, a=255):
    return (c[0], c[1], c[2], a)


def mark_layer():
    layer = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    # A soft gold halo.
    for k in range(20, 0, -1):
        r = R * 1.45 * k / 20
        d.ellipse([CX - r, CY - r, CX + r, CY + r], fill=rgba(GOLD_DIM, 3))

    # The sun, a still disc with a bright centre and a dark gold edge.
    sun = R * 0.29
    for i in range(24, 0, -1):
        f = i / 24
        r = sun * f
        col = lerp(GOLD_HOT, GOLD, f * 0.9)
        alpha = int(255 * (1 - 0.35 * f))
        d.ellipse([CX - r, CY - r, CX + r, CY + r], fill=rgba(col, alpha))
    # Short rays, part of the sun, not a sweep.
    for k in range(12):
        a = k * math.pi / 6
        x1, y1 = CX + math.cos(a) * sun * 1.35, CY + math.sin(a) * sun * 1.35
        x2, y2 = CX + math.cos(a) * sun * 1.72, CY + math.sin(a) * sun * 1.72
        d.line([x1, y1, x2, y2], fill=rgba(GOLD, 170), width=max(1, int(N * 0.003)))

    # A Fibonacci sphere, projected. The same shape as the screen mark.
    nodes = []
    n = 46
    ga = math.pi * (3 - math.sqrt(5))
    for i in range(n):
        y = 1 - 2 * (i + 0.5) / n
        rad = math.sqrt(max(0, 1 - y * y))
        a = ga * i
        nodes.append((math.cos(a) * rad, y, math.sin(a) * rad))
    # Nearest-neighbour constellation, two links per node.
    pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            dx, dy, dz = (nodes[i][k] - nodes[j][k] for k in range(3))
            pairs.append((dx * dx + dy * dy + dz * dz, i, j))
    pairs.sort()
    seen = [0] * n
    links = []
    for _, i, j in pairs:
        if seen[i] >= 2 and seen[j] >= 2:
            continue
        if seen[i] >= 3 or seen[j] >= 3:
            continue
        seen[i] += 1
        seen[j] += 1
        links.append((i, j))
    rot, tilt = 0.72, 0.36
    ca, sa = math.cos(rot), math.sin(rot)
    ct, st = math.cos(tilt), math.sin(tilt)

    def project(v):
        x, y, z = v
        x, z = ca * x + sa * z, -sa * x + ca * z
        y, z = ct * y - st * z, st * y + ct * z
        return CX + x * R, CY - y * R, z

    for i, j in links:
        ax, ay, az = project(nodes[i])
        bx, by, bz = project(nodes[j])
        depth = (az + bz) / 2
        col = lerp(GOLD_DIM, GOLD_HOT, max(0, min(1, depth * 0.5 + 0.5)))
        d.line([ax, ay, bx, by], fill=rgba(col, 210), width=max(1, int(N * 0.0035)))
    for v in nodes:
        x, y, z = project(v)
        rr = max(2, int(N * (0.004 + 0.002 * (z + 1) / 2)))
        d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=rgba(GOLD_HOT, 235))
    return layer


def main():
    base = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    d = ImageDraw.Draw(base)
    pad = int(N * 0.035)
    d.rounded_rectangle([pad, pad, N - pad, N - pad], radius=int(N * 0.16), fill=BG)
    d.rounded_rectangle([pad + int(N * 0.012), pad + int(N * 0.012), N - pad - int(N * 0.012), N - pad - int(N * 0.012)],
                        radius=int(N * 0.14), outline=rgba(PANEL), width=max(1, int(N * 0.012)))
    layer = mark_layer()
    # A soft bloom under the mark.
    glow = layer.filter(ImageFilter.GaussianBlur(N * 0.012))
    base = Image.alpha_composite(base, glow)
    base = Image.alpha_composite(base, layer)
    out = base.resize((S, S), Image.LANCZOS)
    out.save(OUT_PNG)
    out.save(OUT_ICO, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote", OUT_PNG, "and", OUT_ICO)


if __name__ == "__main__":
    main()
