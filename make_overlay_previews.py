"""
Render the real overlay to PNGs for the website.

    venv\\Scripts\\python.exe make_overlay_previews.py

Writes transparent PNGs into website/public/overlay/.

**These are not illustrations of the overlay. They are the overlay.** The website
had a hand-drawn SVG approximation, and it was wrong in every particular: burnt
sienna instead of red, a wide flat ellipse instead of a round organic shape, no
waveform bars inside the blob, no grey waveform marching out to the sides, no
rising dots, and a black box behind something that is actually transparent.

Importing `pill_render` and calling the same function `pill.py` calls at 24 fps
removes that entire class of error. If the overlay is redesigned, re-run this and
the site is correct again.

Rendered at 2x the shipped size so they stay sharp on a high-DPI display, and left
transparent so the page can place them on any background.
"""

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pill_render import DEFAULT_SIZES, FrameState, render

ROOT = Path(__file__).parent
OUT = ROOT / "website" / "public" / "overlay"

SCALE = 2

# A frame is a moment in an animation, so the moment has to be chosen. These
# values were picked to show the overlay doing something rather than idling:
# mid-level input so the inner bars have height and the side waveform has shape,
# and a `t` where the organic outline is visibly off-round.
LEVEL = 0.62
T = 1.35

# Oldest first, newest last - the side waveform marches outward from the newest
# sample, so this decides the shape of the trailing wave. Shaped like someone
# mid-sentence rather than a flat line or a tidy ramp.
HISTORY = [
    0.05, 0.09, 0.18, 0.34, 0.52, 0.61, 0.48, 0.33, 0.22, 0.31,
    0.46, 0.58, 0.67, 0.71, 0.62, 0.44, 0.29, 0.36, 0.51, 0.64,
    0.58, 0.47, 0.55, 0.62,
]

SHOTS = [
    # name,      style,     state,       text
    #
    # One shot per overlay style, in its recording state. The "transcribing"
    # state renders in amber and is a genuinely different look, but nothing on the
    # site shows it, and an asset nobody references is an asset nobody notices has
    # broken. Add it back here the day a page needs it.
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

        # The caption frame is a canvas with the pill centred in it, so most of it
        # is empty. Cropping to the drawn content stops the page from reserving a
        # 1320x300 box for a pill that occupies a third of it.
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
