"""
Render the real overlay to PNGs for the website.

    venv\\Scripts\\python.exe make_overlay_previews.py

Writes transparent PNGs into website/public/overlay/. These are not illustrations
of the overlay: they come from `pill_render`, the same function `pill.py` calls at
24 fps, so a redesign only needs this re-running.

Rendered at 2x the shipped size for high-DPI displays, and left transparent so the
page can place them on any background.
"""

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pill_render import DEFAULT_SIZES, FrameState, render

ROOT = Path(__file__).parent
OUT = ROOT / "website" / "public" / "overlay"

SCALE = 2

# A frame is a moment in an animation, so the moment matters: mid-level input so
# the inner bars have height and the side waveform has shape, and a `t` where the
# organic outline is visibly off-round.
LEVEL = 0.62
T = 1.35

# Oldest first: the side waveform marches outward from the newest sample, so this
# array is the shape of the trailing wave.
HISTORY = [
    0.05, 0.09, 0.18, 0.34, 0.52, 0.61, 0.48, 0.33, 0.22, 0.31,
    0.46, 0.58, 0.67, 0.71, 0.62, 0.44, 0.29, 0.36, 0.51, 0.64,
    0.58, 0.47, 0.55, 0.62,
]

SHOTS = [
    # name,      style,     state,       text
    #
    # One shot per overlay style, in its recording state. Nothing on the site
    # shows the amber "transcribing" state, so it is not rendered.
    ("blob", "blob", "recording", ""),
    ("capsule", "capsule", "recording", ""),
    (
        "caption",
        "caption",
        "recording",
        "the deposition is scheduled for Thursday morning",
    ),
]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    for name, style, state, text in SHOTS:
        w, h = DEFAULT_SIZES[style]
        size = (w * SCALE, h * SCALE)

        fs = FrameState(
            state=state,
            t=T,
            level=LEVEL,
            history=list(HISTORY),
            elapsed=4.0,
            text=text,
        )
        img = render(style, size, fs)

        # The caption frame is a canvas with the pill centred in it, so cropping to
        # the drawn content stops the page reserving a 1320x300 box for a third of it.
        bbox = img.getbbox()
        if bbox:
            img = img.crop(bbox)

        path = OUT / f"{name}.png"
        img.save(path, format="PNG", optimize=True)
        print(
            f"{path.name:22} {img.width:>4}x{img.height:<4} "
            f"{path.stat().st_size / 1024:6.1f} KB"
        )

    print(f"\n-> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
