"""Generate the viidaa app icon (dark-orange theme).

Tile: deep charcoal rounded square (#242424, border #3A3A3A)
Glyph: rich dark-orange (#E67E22 / #D35400) disc + white play triangle
       with a small download-tray bar underneath for the "downloader" cue.

Outputs: assets/viidaa.png (512) + assets/viidaa.ico (multi-size)
Run: python assets/make_icon.py
"""

from pathlib import Path
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent
SIZE = 512

TILE_FILL = (36, 36, 36, 255)       # #242424 — between #1E1E1E and #2D2D2D
TILE_EDGE = (58, 58, 58, 255)       # #3A3A3A
ORANGE = (230, 126, 34, 255)        # #E67E22
ORANGE_DARK = (211, 84, 0, 255)     # #D35400
WHITE = (255, 255, 255, 255)


def draw_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 512.0  # scale factor

    # Charcoal tile
    d.rounded_rectangle([8 * s, 8 * s, 504 * s, 504 * s],
                        radius=112 * s, fill=TILE_FILL,
                        outline=TILE_EDGE, width=max(1, int(6 * s)))

    # Orange disc with darker-orange rim
    d.ellipse([106 * s, 96 * s, 406 * s, 396 * s],
              fill=ORANGE, outline=ORANGE_DARK, width=max(1, int(12 * s)))

    # White play triangle (optically centered: nudged right)
    d.polygon([(218 * s, 178 * s), (218 * s, 316 * s), (342 * s, 247 * s)],
              fill=WHITE)

    # Download-tray cue: small white bar under the disc
    d.rounded_rectangle([206 * s, 404 * s, 306 * s, 422 * s],
                        radius=9 * s, fill=WHITE)
    return img


def main() -> None:
    icon = draw_icon(SIZE)
    icon.save(OUT / "viidaa.png", "PNG")
    icon.save(OUT / "viidaa.ico", "ICO",
              sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                     (64, 64), (128, 128), (256, 256)])
    print(f"wrote {OUT / 'viidaa.png'} + {OUT / 'viidaa.ico'}")


if __name__ == "__main__":
    main()
