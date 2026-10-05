"""Generate the Sentinels of Rehan launcher assets from the owner's logo.

Usage:
    python scripts/make_brand_assets.py "path/to/logo.jpg"

Reads the brand image (the WhatsApp logo: near-black purple field, gold
rounded border, gradient SENTINELS wordmark, ascending candles), then
writes, under android/app/src/main/res:

  * mipmap-{m,h,xh,xxh,xxxh}dpi/ic_launcher.png        (legacy, square)
  * mipmap-{m,h,xh,xxh,xxxh}dpi/ic_launcher_foreground.png
                                                       (adaptive layer)
  * drawable-nodpi/brand_header.jpg                    (in-app header)

The adaptive foreground keeps the art inside the 66/108 safe zone
(scaled to 56% of the canvas, centered, transparent padding) so every
launcher mask keeps the gold border visible. The background layer is a
flat color sampled from the logo's own field - the script prints it
for colors.xml.

One-off generator, kept in the repo so the icons stay reproducible.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

RES = Path(__file__).resolve().parents[1] / "android" / "app" / "src" / "main" / "res"

LEGACY = {
    "mipmap-mdpi": 48,
    "mipmap-hdpi": 72,
    "mipmap-xhdpi": 96,
    "mipmap-xxhdpi": 144,
    "mipmap-xxxhdpi": 192,
}
FOREGROUND = {
    "mipmap-mdpi": 108,
    "mipmap-hdpi": 162,
    "mipmap-xhdpi": 216,
    "mipmap-xxhdpi": 324,
    "mipmap-xxxhdpi": 432,
}
# Visible adaptive area is 72 of 108 dp; 56% keeps a comfortable margin.
FOREGROUND_ART_SHARE = 0.56
HEADER_WIDTH = 1000


def square_fit(img: Image.Image) -> Image.Image:
    """Letterbox the full logo into a square, padded with its own
    corner color. A center CROP of the 1600x1152 original would slice
    the wordmark's S and the gold frame's sides - the owner asked for
    THIS image, so the whole art survives.
    """
    w, h = img.size
    side = max(w, h)
    pad = img.getpixel((2, 2))
    canvas = Image.new("RGB", (side, side), pad)
    canvas.paste(img, ((side - w) // 2, (side - h) // 2))
    return canvas


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: make_brand_assets.py <logo-image>")
        return 2
    logo = Image.open(Path(sys.argv[1])).convert("RGB")
    print("source:", logo.size)
    sq = square_fit(logo)
    # The logo carries a black outer margin around its gold frame, so
    # sample INSIDE the purple panel (lower-left, clear of the candles
    # and the wordmark) for the adaptive background color.
    w, h = sq.size
    art_top = (h - logo.height) // 2
    px = sq.getpixel((int(w * 0.12), art_top + int(logo.height * 0.90)))
    print("sampled background: #%02X%02X%02X" % px)

    for folder, size in LEGACY.items():
        out = RES / folder
        out.mkdir(parents=True, exist_ok=True)
        sq.resize((size, size), Image.LANCZOS).save(out / "ic_launcher.png")
        print(f"wrote {folder}/ic_launcher.png {size}x{size}")

    for folder, size in FOREGROUND.items():
        out = RES / folder
        out.mkdir(parents=True, exist_ok=True)
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        art_side = round(size * FOREGROUND_ART_SHARE)
        art = sq.resize((art_side, art_side), Image.LANCZOS)
        off = (size - art_side) // 2
        canvas.paste(art, (off, off))
        canvas.save(out / "ic_launcher_foreground.png")
        print(f"wrote {folder}/ic_launcher_foreground.png {size}x{size}")

    header_dir = RES / "drawable-nodpi"
    header_dir.mkdir(parents=True, exist_ok=True)
    header_h = round(logo.height * HEADER_WIDTH / logo.width)
    logo.resize((HEADER_WIDTH, header_h), Image.LANCZOS).save(
        header_dir / "brand_header.jpg", quality=82, optimize=True
    )
    print("wrote drawable-nodpi/brand_header.jpg", f"{HEADER_WIDTH}x{header_h}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
