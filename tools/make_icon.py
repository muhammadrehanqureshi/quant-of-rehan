"""Draw the Charts of Rehan icon: a black plate with teal PSX candles.

The shortcut used to wear Windows' own generic document icon, which on this
machine renders as the old Internet Explorer page. This wrote a real icon once
and the build keeps the .ico in assets/ so the shortcut always has one.

Run it again only if the mark changes:

    python tools/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
NAME = "charts-of-rehan.ico"

UP = (8, 153, 129)
DOWN = (242, 54, 69)
PLATE = (10, 10, 10)
EDGE = (31, 31, 31)


def draw(size: int) -> Image.Image:
    """One square icon at `size` pixels, drawn from the same proportions."""
    scale = size / 256
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    radius = max(2, int(52 * scale))
    draw.rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=radius, fill=PLATE, outline=EDGE,
        width=max(1, int(4 * scale)),
    )

    # Four candles walking up, in TV's own teal and red, on a grid line.
    baseline = int(196 * scale)
    grid = (26, 26, 26)
    draw.line((int(40 * scale), baseline, int(216 * scale), baseline),
              fill=grid, width=max(1, int(4 * scale)))

    candles = [
        (56, 150, 96, 196, DOWN),
        (104, 128, 82, 196, UP),
        (152, 104, 60, 196, UP),
        (200, 74, 40, 196, UP),
    ]
    body = max(2, int(26 * scale))
    for centre, top, bottom, close, colour in candles:
        x = int(centre * scale)
        top_y = int(top * scale)
        low_y = int(bottom * scale)
        close_y = int(close * scale)
        draw.line((x, top_y, x, low_y), fill=colour,
                  width=max(1, int(6 * scale)))
        left = x - body // 2
        right = x + body // 2
        upper = min(close_y, max(top_y, int(top * scale)))
        draw.rounded_rectangle(
            (left, min(upper, low_y), right, max(upper, low_y)),
            radius=max(1, int(6 * scale)), fill=colour,
        )

    return image


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [draw(size) for size in sizes]
    target = ASSETS / NAME
    images[-1].save(target, format="ICO",
                    sizes=[(size, size) for size in sizes])
    print(f"wrote {target} ({target.stat().st_size} bytes) at "
          f"{', '.join(f'{size}x{size}' for size in sizes)}")


if __name__ == "__main__":
    main()
