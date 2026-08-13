"""
Generate the social share card.

    venv\\Scripts\\python.exe make_og_image.py

Writes website/public/og.png at 1200x630, the size Facebook, X, LinkedIn, Slack,
Discord and iMessage all read. `__root.tsx` declares
`twitter:card: summary_large_image`, so without this file every share renders as a
blank placeholder. Reuses `draw_mark` from make_icon.py rather than reimplementing
the logo, so the card cannot drift away from the tray icon.
"""

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PIL import Image, ImageDraw, ImageFont

from make_icon import ACCENT, draw_mark

ROOT = Path(__file__).parent
OUT = ROOT / "website" / "public" / "og.png"

W, H = 1200, 630

# The website's tokens from styles.css, converted from oklch to sRGB. Pillow cannot
# read CSS, so they are duplicated here; keep them in step with the page.
PAPER = (250, 248, 243)        # --background  oklch(0.982 0.006 85)
INK = (44, 40, 35)             # --foreground  oklch(0.19 0.008 60)
MUTED = (112, 106, 98)         # --muted-foreground oklch(0.46 0.01 65)
BORDER = (227, 223, 215)       # --border      oklch(0.9 0.008 75)

FONT_DIR = Path("C:/Windows/Fonts")


def font(candidates: tuple[str, ...], size: int) -> ImageFont.FreeTypeFont:
    """
    The first of `candidates` that exists on this machine, at `size`.

    Segoe UI rather than the site's Instrument Sans, which is loaded from Google
    Fonts at runtime and is not on disk. A list rather than one name because the
    weights are not all present everywhere - no semibold here - and asking for a
    missing face silently gives Pillow's bitmap default.
    """
    for name in candidates:
        path = FONT_DIR / name
        if path.exists():
            return ImageFont.truetype(str(path), size)
    print(f"    (none of {candidates} found, falling back to the default font)")
    return ImageFont.load_default(size)


def main() -> int:
    if not OUT.parent.exists():
        print(f"error: {OUT.parent} does not exist", file=sys.stderr)
        return 1

    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)

    bold = font(("segoeuib.ttf",), 92)
    semi = font(("segoeuisb.ttf", "segoeui.ttf"), 34)
    mono = font(("consola.ttf",), 23)

    pad = 76

    # Hairline frame: Slack and Discord render cards on their own backgrounds, and
    # a near-white card without an edge bleeds into a light theme.
    d.rectangle((0, 0, W - 1, H - 1), outline=BORDER, width=2)

    # The same device the page uses to mark the "Casper Flow" column.
    d.rectangle((0, 0, 7, H), fill=ACCENT)

    mark_size = 128
    mark = draw_mark(mark_size)
    img.paste(mark, (pad, pad), mark)

    # anchor="lm" centres the text on the mark. A baseline anchor ("ls") at a
    # hand-tuned y does not stay aligned when the font or size changes.
    d.text(
        (pad + mark_size + 28, pad + mark_size / 2),
        "Casper Flow", font=bold, fill=INK, anchor="lm",
    )

    d.text(
        (pad, 300),
        "Hold a key. Speak. The words land at your cursor.",
        font=semi, fill=INK, anchor="ls",
    )
    d.text(
        (pad, 352),
        "Speech recognition runs on your own CPU. No account, no upload,",
        font=semi, fill=MUTED, anchor="ls",
    )
    d.text((pad, 400), "no server to stream your voice to.", font=semi, fill=MUTED, anchor="ls")

    # Facts rather than adjectives, in the mono face the site uses for anything
    # measured. The separator width is measured to fill the line exactly; a fixed
    # run of spaces overflows and clips the last item at the right edge.
    d.line((pad, H - pad - 62, W - pad, H - pad - 62), fill=BORDER, width=2)
    items = ["WINDOWS 10 / 11", "OPEN SOURCE, MIT", "WORKS OFFLINE", "ENGLISH + HINGLISH"]
    avail = W - 2 * pad
    text_w = sum(d.textlength(s, font=mono) for s in items)
    dot_w = d.textlength("·", font=mono)
    gaps = len(items) - 1
    gap = max(dot_w * 2, (avail - text_w - gaps * dot_w) / gaps)

    x = float(pad)
    baseline = H - pad - 18
    for i, s in enumerate(items):
        d.text((x, baseline), s, font=mono, fill=MUTED, anchor="ls")
        x += d.textlength(s, font=mono)
        if i < gaps:
            d.text((x + gap / 2, baseline), "·", font=mono, fill=BORDER, anchor="ms")
            x += gap + dot_w

    img.save(OUT, format="PNG", optimize=True)
    print(f"{OUT.relative_to(ROOT)}  {OUT.stat().st_size / 1024:.1f} KB  {W}x{H}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
