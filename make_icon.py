"""
Generate the application icon set from one definition.

    venv\\Scripts\\python.exe make_icon.py

Writes assets/casper.ico, assets/casper.png and website/public/favicon.ico from
the same frames, so the tray icon, the installer and the website cannot show three
different logos.

Drawn in code so it stays reviewable in a diff, and so every size is rendered at
its own resolution: a 16 px icon downscaled from 256 px turns to mush, and 16 px
is the size most users see. The mark is a soft-edged speech shape with a vertical
dictation caret cut out of it, burnt sienna on transparent, matching the website's
accent colour.
"""

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).parent
ASSETS = ROOT / "assets"

# The website's --accent, oklch(0.52 0.13 45), converted to sRGB.
ACCENT = (177, 78, 42)
ACCENT_DEEP = (138, 57, 30)
CARET = (255, 250, 246)

# 16 and 32 for the tray, title bar and Explorer list view, 48 in Explorer, 256
# for the large tile and the installer header. 20 and 40 are what Windows asks for
# when notification icons are scaled to 125% and 250%; without those frames it
# squashes the nearest larger one.
SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]

# Render at size * SS and reduce, so curves antialias properly at every size.
SS = 8

# Below this the three-bar mark becomes a single bold bar. Windows draws tray icons
# at 16 px (100% scaling) and 20 px (125%), where three bars are mush.
SIMPLE_BELOW = 32


def draw_mark(size: int) -> Image.Image:
    """
    Render the mark at `size` pixels, supersampled then reduced.

    Detail is chosen per size, not scaled. The three-bar mark measures 1.25 px per
    side bar at 16 px and 1.56 px at 20 px, thin enough to antialias into grey, so
    below SIMPLE_BELOW the mark is a single bold bar and above it three.
    """
    n = size * SS
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # A squircle-ish rounded square, still readable when reduced to 16 px. The
    # padding keeps it from looking oversized next to other tray icons.
    pad = n * 0.09
    radius = n * 0.28
    box = (pad, pad, n - pad, n - pad)

    # Vertical gradient as a clipped band stack; it survives reduction unbanded.
    grad = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for y in range(n):
        t = y / max(1, n - 1)
        gd.line(
            [(0, y), (n, y)],
            fill=(
                int(ACCENT[0] + (ACCENT_DEEP[0] - ACCENT[0]) * t),
                int(ACCENT[1] + (ACCENT_DEEP[1] - ACCENT[1]) * t),
                int(ACCENT[2] + (ACCENT_DEEP[2] - ACCENT[2]) * t),
                255,
            ),
        )

    mask = Image.new("L", (n, n), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=radius, fill=255)
    img.paste(grad, (0, 0), mask)

    cx, cy = n / 2, n / 2

    if size < SIMPLE_BELOW:
        # A solid 3.5 px of white at 16 px, which survives Windows rescaling it.
        bar_w = n * 0.22
        bar_h = n * 0.46
        d.rounded_rectangle(
            (cx - bar_w / 2, cy - bar_h / 2, cx + bar_w / 2, cy + bar_h / 2),
            radius=bar_w / 2, fill=CARET + (255,))
        return img.resize((size, size), Image.LANCZOS)

    # Three bars: a caret with a level meter either side. Widths are set so the
    # thinnest is still over 2 px at 32 px.
    bar_w = n * 0.145
    bar_h = n * 0.44
    d.rounded_rectangle(
        (cx - bar_w / 2, cy - bar_h / 2, cx + bar_w / 2, cy + bar_h / 2),
        radius=bar_w / 2, fill=CARET + (255,))

    side_w = n * 0.095
    for dx, h in ((-n * 0.215, 0.24), (n * 0.215, 0.30)):
        bh = n * h
        d.rounded_rectangle(
            (cx + dx - side_w / 2, cy - bh / 2, cx + dx + side_w / 2, cy + bh / 2),
            radius=side_w / 2,
            fill=CARET + (190,),
        )

    if size >= 48:
        # Faint top-edge highlight for depth. Skipped small, where it just muddies.
        hl = Image.new("RGBA", (n, n), (0, 0, 0, 0))
        ImageDraw.Draw(hl).rounded_rectangle(
            (pad, pad, n - pad, n - pad), radius=radius,
            outline=(255, 255, 255, 46), width=int(n * 0.012),
        )
        img = Image.alpha_composite(img, hl.filter(ImageFilter.GaussianBlur(n * 0.004)))

    return img.resize((size, size), Image.LANCZOS)


def main() -> int:
    ASSETS.mkdir(exist_ok=True)

    frames = [draw_mark(s) for s in SIZES]

    ico = ASSETS / "casper.ico"
    # Given explicit sizes, Pillow writes each supplied image as its own frame, so
    # every resolution is the one drawn for it rather than a downscale.
    frames[-1].save(ico, format="ICO",
                    sizes=[(s, s) for s in SIZES],
                    append_images=frames[:-1])

    png = ASSETS / "casper.png"
    frames[-1].save(png, format="PNG")

    print(f"{ico.name:16} {ico.stat().st_size / 1024:6.1f} KB  "
          f"{len(SIZES)} sizes: {SIZES}")
    print(f"{png.name:16} {png.stat().st_size / 1024:6.1f} KB  256x256")

    # The favicon is written from the same frames, so the browser tab cannot drift
    # away from the tray icon.
    favicon = ROOT / "website" / "public" / "favicon.ico"
    if favicon.parent.exists():
        frames[-1].save(favicon, format="ICO",
                        sizes=[(s, s) for s in SIZES],
                        append_images=frames[:-1])
        print(f"{'favicon.ico':16} {favicon.stat().st_size / 1024:6.1f} KB  "
              f"-> website/public/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
