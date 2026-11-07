"""Make the Windows icon from the owner's own picture.

Owner order 2026-11-07: the icon is the owner's `logo2.png`, committed as
`assets/icon-source.png` (sha256 4298b15c...e4). It is never redrawn,
recoloured, masked or replaced. The only transformation here is a square crop
and a resize, because an .ico needs square sizes. A Go test pins the source
hash, so a later session cannot swap the picture unless the owner says so.

Usage:
    python mkicon_hud.py assets/QuantOfRehan.ico assets/icon-1024.png
"""
import sys

from PIL import Image

OUT_ICO, OUT_PNG = sys.argv[1], sys.argv[2]
SOURCE = "assets/icon-source.png"
S = 1024


def square(im):
    """The largest centred square, so the dial is never stretched."""
    w, h = im.size
    side = min(w, h)
    return im.crop(((w - side) // 2, (h - side) // 2, (w + side) // 2, (h + side) // 2))


def main():
    im = Image.open(SOURCE).convert("RGBA")
    out = square(im).resize((S, S), Image.LANCZOS)
    out.save(OUT_PNG)
    out.save(
        OUT_ICO,
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print("wrote", OUT_PNG, "and", OUT_ICO, "from the owner's picture", SOURCE)


if __name__ == "__main__":
    main()
