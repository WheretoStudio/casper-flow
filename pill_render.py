"""
Frame rendering for the Casper Flow status overlay.

Pure drawing, no windowing: every function takes state and returns an RGBA PIL
image, so the look can be tweaked or tested in isolation.

Smooth edges and the halos need per-pixel alpha, which is why pill.py composites
these frames through a layered window rather than with tkinter primitives.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ---------------------------------------------------------------- palette

RECORDING = {
    "hot": (255, 122, 78),      # highlight, upper-left
    "core": (250, 46, 46),      # main body
    "deep": (214, 28, 40),      # lower-right shading
    "halo": (255, 90, 70),
    "bars": (176, 30, 30),      # waveform inside the blob
}
TRANSCRIBING = {
    "hot": (255, 196, 92),
    "core": (245, 148, 42),
    "deep": (214, 110, 24),
    "halo": (255, 170, 70),
    "bars": (168, 92, 12),
}
ERROR = {
    "hot": (170, 178, 190),
    "core": (122, 132, 146),
    "deep": (92, 100, 112),
    "halo": (130, 140, 155),
    "bars": (70, 76, 86),
}

OUTER_BAR = (196, 200, 206)     # grey side waveform

PALETTES = {"recording": RECORDING, "transcribing": TRANSCRIBING, "error": ERROR}

# Supersampling factor. 2 is smooth enough and still renders every frame on a
# laptop CPU.
SS = 2


@dataclass
class FrameState:
    """Everything the renderer needs for one frame."""
    state: str = "recording"
    t: float = 0.0                              # seconds since shown
    level: float = 0.0                          # current input level 0-1
    history: list[float] = field(default_factory=list)   # recent levels, oldest first
    elapsed: float = 0.0                        # recording duration in seconds
    text: str = ""                              # live partial transcript


# ------------------------------------------------------------------ helpers

_grad_cache: dict[tuple, Image.Image] = {}


def _gradient(size: tuple[int, int], pal: dict) -> Image.Image:
    """Diagonal three-stop gradient used to fill the blob (cached)."""
    ckey = (size, pal["core"])
    hit = _grad_cache.get(ckey)
    if hit is not None:
        return hit
    # RGBA so callers can .copy() instead of paying a convert().
    img = _build_gradient(size, pal).convert("RGBA")
    _grad_cache[ckey] = img
    return img


def _build_gradient(size: tuple[int, int], pal: dict) -> Image.Image:
    w, h = size
    # Build it small and upscale; the blob hides any banding.
    gw, gh = 32, 32
    xs = np.linspace(0.0, 1.0, gw, dtype=np.float32)[None, :]
    ys = np.linspace(0.0, 1.0, gh, dtype=np.float32)[:, None]
    d = np.clip(xs * 0.55 + ys * 0.45, 0.0, 1.0)

    hot = np.array(pal["hot"], dtype=np.float32)
    core = np.array(pal["core"], dtype=np.float32)
    deep = np.array(pal["deep"], dtype=np.float32)

    # 0 -> hot, 0.5 -> core, 1 -> deep
    first = d[..., None] * 2.0
    second = (d[..., None] - 0.5) * 2.0
    grad = np.where(
        d[..., None] < 0.5,
        hot + (core - hot) * np.clip(first, 0, 1),
        core + (deep - core) * np.clip(second, 0, 1),
    ).astype(np.uint8)

    return Image.fromarray(grad, "RGB").resize((w, h), Image.BICUBIC)


def _blob_points(cx: float, cy: float, r: float, t: float,
                 harmonics, n: int = 132) -> list[tuple[float, float]]:
    """
    Organic closed outline: a circle whose radius is modulated by sine harmonics
    drifting at different speeds, so the shape never repeats exactly.
    """
    pts = []
    for i in range(n):
        a = (i / n) * math.tau
        rr = 1.0
        for amp, k, speed, phase in harmonics:
            rr += amp * math.sin(k * a + speed * t + phase)
        rad = r * rr
        pts.append((cx + math.cos(a) * rad, cy + math.sin(a) * rad))
    return pts


_HARMONICS_MAIN = (
    (0.048, 3, 0.9, 0.0),
    (0.030, 5, -0.7, 1.2),
    (0.018, 7, 1.3, 2.6),
)
_HARMONICS_ALT = (
    (0.070, 2, -0.6, 0.8),
    (0.042, 4, 0.8, 2.1),
    (0.024, 6, -1.1, 0.4),
)
_HARMONICS_ALT2 = (
    (0.060, 3, 0.5, 2.9),
    (0.048, 5, 1.0, 0.6),
)


def _rounded_bar(d: ImageDraw.ImageDraw, cx: float, cy: float,
                 w: float, h: float, fill):
    """Vertical capsule bar centred on (cx, cy)."""
    h = max(h, w)
    x0, x1 = cx - w / 2.0, cx + w / 2.0
    y0, y1 = cy - h / 2.0, cy + h / 2.0
    try:
        d.rounded_rectangle([x0, y0, x1, y1], radius=w / 2.0, fill=fill)
    except AttributeError:      # very old Pillow
        d.rectangle([x0, y0, x1, y1], fill=fill)


def _bar_heights(fs: FrameState, count: int, seed_phase: float) -> list[float]:
    """
    Per-bar 0-1 heights, driven by the live input level with a small per-bar
    oscillation so quiet passages do not collapse to a flat line.
    """
    lvl = max(0.0, min(1.0, fs.level))
    out = []
    for i in range(count):
        # centre bars taller than the edges
        centre = 1.0 - abs((i - (count - 1) / 2.0) / max(1.0, (count - 1) / 2.0))
        shape = 0.45 + 0.55 * centre
        wobble = 0.5 + 0.5 * math.sin(fs.t * 7.0 + i * 1.7 + seed_phase)
        h = shape * (0.22 + 0.95 * lvl) * (0.65 + 0.35 * wobble)
        out.append(max(0.06, min(1.0, h)))
    return out


# -------------------------------------------------------------- blob style

def render_blob(size: tuple[int, int], fs: FrameState) -> Image.Image:
    """The organic blob with inner waveform and grey side waveform."""
    W, H = size
    w, h = W * SS, H * SS
    pal = PALETTES.get(fs.state, RECORDING)

    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))

    cx, cy = w * 0.5, h * 0.52
    base_r = min(w, h) * 0.335
    # Breathing, plus a nudge from the live level
    pulse = 1.0 + 0.030 * math.sin(fs.t * 2.4) + 0.070 * max(0.0, min(1.0, fs.level))
    r = base_r * pulse

    # ---- grey side waveform (behind everything) -----------------------
    _draw_side_waveform(img, fs, cx, cy, r, w, h)

    # ---- glow + translucent companion shapes, in one mask -------------
    # Compositing full-size RGBA layers dominates frame time, so everything
    # tinted with the halo colour accumulates into one L mask, blurred at half
    # resolution and scaled up. The output is soft by design, so the loss of
    # detail is free and the blur costs a quarter of the pixels.
    QW, QH = w // 2, h // 2
    soft = Image.new("L", (QW, QH), 0)
    sd = ImageDraw.Draw(soft)
    sd.polygon(
        _blob_points(cx / 2.0, cy / 2.0, r * 1.06 / 2.0, fs.t, _HARMONICS_MAIN),
        fill=125,
    )
    for harm, scale, alpha, off in (
        (_HARMONICS_ALT, 1.14, 52, (0.055, 0.030)),
        (_HARMONICS_ALT2, 1.08, 44, (-0.050, -0.025)),
    ):
        sd.polygon(
            _blob_points((cx + r * off[0]) / 2.0, (cy + r * off[1]) / 2.0,
                         r * scale / 2.0, fs.t, harm),
            fill=alpha,
        )
    soft = soft.filter(ImageFilter.GaussianBlur(radius=max(1.5, r * 0.045)))
    halo_rgb = Image.new("RGBA", (w, h), pal["halo"] + (0,))
    halo_rgb.putalpha(soft.resize((w, h), Image.BILINEAR))
    img = Image.alpha_composite(img, halo_rgb)

    # ---- main body: crisp edge ----------------------------------------
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).polygon(
        _blob_points(cx, cy, r, fs.t, _HARMONICS_MAIN), fill=255
    )
    # Enough blur to antialias the polygon and soften the facets between lobes.
    mask = mask.filter(ImageFilter.GaussianBlur(radius=1.1 * SS))

    # Sheen and inner waveform go straight onto the gradient, so the body is
    # composited once through the blob mask.
    body = _gradient((w, h), pal).copy()

    sheen = Image.new("L", (QW, QH), 0)
    ImageDraw.Draw(sheen).ellipse(
        [(cx - r * 0.80) / 2, (cy - r * 0.95) / 2,
         (cx + r * 0.05) / 2, (cy - r * 0.12) / 2], fill=52
    )
    sheen = sheen.filter(ImageFilter.GaussianBlur(radius=r * 0.075))
    body.paste((255, 255, 255, 255), (0, 0), sheen.resize((w, h), Image.BILINEAR))

    bd = ImageDraw.Draw(body)
    count = 7
    bw = r * 0.125
    gap = bw * 2.0
    hs = _bar_heights(fs, count, 0.0)
    start = cx - gap * (count - 1) / 2.0
    for i, bh in enumerate(hs):
        if fs.state == "transcribing":
            # a travelling wave rather than a level meter
            ph = math.sin(fs.t * 5.0 - i * 0.9)
            bh = 0.34 + 0.60 * (0.5 + 0.5 * ph)
        # Capped at 1.20r so a loud passage cannot push bars past the blob edge,
        # where the mask would clip them into a flat line.
        _rounded_bar(bd, start + i * gap, cy, bw, r * 1.20 * bh,
                     pal["bars"] + (225,))

    body.putalpha(mask)
    img = Image.alpha_composite(img, body)

    _draw_dots(img, fs, cx, cy, r, pal)

    # BOX is an exact area average at integer downscale factors: as clean as
    # LANCZOS here and faster.
    return img.resize((W, H), Image.BOX)


def _draw_side_waveform(img: Image.Image, fs: FrameState,
                        cx: float, cy: float, r: float, w: int, h: int):
    """Grey bars marching outward from behind the blob on both sides."""
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    hist = fs.history or [0.0]
    bw = r * 0.075
    gap = bw * 2.5
    inner_edge = r * 0.88
    max_h = h * 0.46
    # Fills the width available on each side rather than a fixed count.
    n = max(4, int(((w * 0.5) - inner_edge) / gap))

    for i in range(n):
        # newest nearest the blob, so the waveform marches outward
        idx = len(hist) - 1 - i
        lvl = hist[idx] if 0 <= idx < len(hist) else 0.0
        fade = 1.0 - (i / n)
        # Reaches zero before the frame edge, so the waveform dissolves rather
        # than being cut off.
        alpha = int(235 * (fade ** 1.7))
        if alpha <= 3:
            continue
        # idle motion so it is not dead flat when silent
        idle = 0.16 + 0.10 * (0.5 + 0.5 * math.sin(fs.t * 3.0 + i * 0.9))
        bh = max_h * (idle + 0.85 * lvl) * (0.55 + 0.45 * fade)
        off = inner_edge + gap * i
        for sx in (cx - off, cx + off):
            _rounded_bar(d, sx, cy, bw, bh, OUTER_BAR + (alpha,))

    img.alpha_composite(layer)


def _draw_dots(img: Image.Image, fs: FrameState,
               cx: float, cy: float, r: float, pal: dict):
    """Two small dots drifting up above the blob and fading out."""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for k, (period, offset, rad) in enumerate(
        ((2.6, 0.0, r * 0.055), (3.4, 1.3, r * 0.038))
    ):
        p = ((fs.t + offset) % period) / period
        y = cy - r * (1.05 + p * 0.85)
        a = int(215 * (1.0 - p) ** 1.4)
        if a <= 4:
            continue
        x = cx + math.sin((fs.t + offset) * 1.7 + k) * r * 0.10
        d.ellipse([x - rad, y - rad, x + rad, y + rad], fill=pal["core"] + (a,))
    img.alpha_composite(layer)


# ----------------------------------------------------------- capsule style

# Nirmala UI first: it covers Devanagari as well as Latin, so Hinglish renders in
# one font. Segoe UI has no Devanagari coverage and draws .notdef boxes instead.
# Pillow here is built without Raqm/HarfBuzz, so there is no complex shaping;
# ordinary Devanagari is fine, unusual conjuncts may not be.
_FONT_CANDIDATES = (
    ("Nirmala.ttc", 1),        # semibold
    ("Nirmala.ttc", 0),
    ("seguisb.ttf", 0),
    ("segoeui.ttf", 0),
    ("arialbd.ttf", 0),
)
_font_cache: dict[int, ImageFont.FreeTypeFont] = {}


def _font(px: int):
    if px in _font_cache:
        return _font_cache[px]
    f = None
    for name, index in _FONT_CANDIDATES:
        try:
            f = ImageFont.truetype(name, px, index=index)
            break
        except Exception:
            continue
    if f is None:
        f = ImageFont.load_default()
    _font_cache[px] = f
    return f


def _wrap(text: str, font, max_px: float) -> list[str]:
    """Greedy word wrap measured in pixels."""
    lines, line = [], ""
    for word in text.split():
        probe = f"{line} {word}".strip()
        try:
            width = font.getlength(probe)
        except Exception:
            width = len(probe) * 8.0        # crude fallback
        if width <= max_px or not line:
            line = probe
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


LABELS = {"recording": "Recording", "transcribing": "Transcribing",
          "error": "Mic error"}


def render_capsule(size: tuple[int, int], fs: FrameState) -> Image.Image:
    """Compact dark capsule: pulsing dot, label, live meter, timer."""
    W, H = size
    w, h = W * SS, H * SS
    pal = PALETTES.get(fs.state, RECORDING)

    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    pad = int(10 * SS)
    card = [pad, pad, w - pad, h - pad]
    radius = (card[3] - card[1]) / 2.0

    sh = Image.new("L", (w // 2, h // 2), 0)
    ImageDraw.Draw(sh).rounded_rectangle(
        [card[0] / 2, (card[1] + 5 * SS) / 2, card[2] / 2, (card[3] + 6 * SS) / 2],
        radius=radius / 2, fill=120,
    )
    sh = sh.filter(ImageFilter.GaussianBlur(radius=5)).resize((w, h), Image.BILINEAR)
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    shadow.putalpha(sh)
    img = Image.alpha_composite(img, shadow)

    d = ImageDraw.Draw(img)
    d.rounded_rectangle(card, radius=radius, fill=(24, 27, 34, 242))
    d.rounded_rectangle(card, radius=radius, outline=(255, 255, 255, 34),
                        width=max(1, SS))

    cy = (card[1] + card[3]) / 2.0

    # pulsing indicator
    dot_x = card[0] + 26 * SS
    base = 5.5 * SS
    pulse = 1.0 + 0.30 * math.sin(fs.t * 4.0) + 0.5 * fs.level
    glow = Image.new("L", (w, h), 0)
    gr = base * 2.6 * (1.0 + 0.2 * math.sin(fs.t * 4.0))
    ImageDraw.Draw(glow).ellipse(
        [dot_x - gr, cy - gr, dot_x + gr, cy + gr], fill=110
    )
    glow = glow.filter(ImageFilter.GaussianBlur(radius=4 * SS))
    gl = Image.new("RGBA", (w, h), pal["halo"] + (0,))
    gl.putalpha(glow)
    img = Image.alpha_composite(img, gl)
    d = ImageDraw.Draw(img)
    rr = base * pulse
    d.ellipse([dot_x - rr, cy - rr, dot_x + rr, cy + rr], fill=pal["core"] + (255,))

    label = LABELS.get(fs.state, fs.state.title())
    f = _font(int(12.5 * SS))
    d.text((card[0] + 44 * SS, cy), label, font=f, fill=(238, 240, 245, 255),
           anchor="lm")

    # meter bars
    try:
        tw = d.textlength(label, font=f)
    except Exception:
        tw = 70 * SS
    mx = card[0] + 44 * SS + tw + 16 * SS
    right = card[2] - 58 * SS
    count = 14
    if right > mx + 10 * SS:
        gap = (right - mx) / count
        bw = min(3.0 * SS, gap * 0.55)
        for i, bh in enumerate(_bar_heights(fs, count, 1.1)):
            if fs.state == "transcribing":
                bh = 0.25 + 0.6 * (0.5 + 0.5 * math.sin(fs.t * 6.0 - i * 0.7))
            _rounded_bar(d, mx + gap * i, cy, bw, (h * 0.30) * bh,
                         pal["hot"] + (225,))

    secs = int(fs.elapsed)
    d.text((card[2] - 20 * SS, cy), f"{secs // 60}:{secs % 60:02d}",
           font=_font(int(11 * SS)), fill=(150, 156, 168, 255), anchor="rm")

    return img.resize((W, H), Image.LANCZOS)


# ----------------------------------------------------------- caption style

CAPTION_BG = (12, 14, 18, 240)
CAPTION_EDGE = (255, 255, 255, 26)
CAPTION_TEXT = (240, 242, 246, 255)
CAPTION_DIM = (128, 136, 150, 255)
MAX_LINES = 3


def _vertical_gradient(size, top, bottom):
    """Cheap vertical gradient as an RGB image."""
    w, h = size
    col = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None]
    top_a = np.array(top, dtype=np.float32)
    bot_a = np.array(bottom, dtype=np.float32)
    ramp = (top_a + (bot_a - top_a) * col).astype(np.uint8)      # h x 3
    return Image.fromarray(np.repeat(ramp[:, None, :], w, axis=1), "RGB")


_sprite_cache: dict[tuple, Image.Image] = {}

# Margin around the pill inside its sprite, for the shadow and glow to live in.
_MARGIN = 26


def _pill_sprite(pw: int, ph: int, state: str) -> Image.Image:
    """
    Glow, shadow, gradient body, top highlight and hairline border. All static,
    and 27 ms to build, so it is cached per (size, state).
    """
    key = (pw, ph, state)
    hit = _sprite_cache.get(key)
    if hit is not None:
        return hit

    pal = PALETTES.get(state, RECORDING)
    m = _MARGIN * SS
    W, H = pw + m * 2, ph + m * 2
    box = [m, m, m + pw, m + ph]
    r = ph // 2                     # fully rounded ends

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=r, fill=255)

    # Tight coloured glow: a wider, stronger blur reads as a smudge on a dark
    # desktop rather than as light.
    gw, gh = max(1, W // 4), max(1, H // 4)
    glow = Image.new("L", (gw, gh), 0)
    ImageDraw.Draw(glow).rounded_rectangle(
        [box[0] / 4, box[1] / 4, box[2] / 4, box[3] / 4], radius=r / 4, fill=78,
    )
    glow = glow.filter(ImageFilter.GaussianBlur(radius=4))
    g = Image.new("RGBA", (W, H), pal["halo"] + (0,))
    g.putalpha(glow.resize((W, H), Image.BILINEAR))
    img = Image.alpha_composite(img, g)

    # Neutral drop shadow, for separation from the desktop.
    sw, sh_ = max(1, W // 3), max(1, H // 3)
    sh = Image.new("L", (sw, sh_), 0)
    ImageDraw.Draw(sh).rounded_rectangle(
        [box[0] / 3, (box[1] + 7 * SS) / 3, box[2] / 3, (box[3] + 9 * SS) / 3],
        radius=r / 3, fill=165,
    )
    sh = sh.filter(ImageFilter.GaussianBlur(radius=5))
    s = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    s.putalpha(sh.resize((W, H), Image.BILINEAR))
    img = Image.alpha_composite(img, s)

    # Body: near-black with a cool cast, lighter at the top.
    body = _vertical_gradient((W, H), (37, 41, 51), (13, 15, 20)).convert("RGBA")
    body.putalpha(mask)
    img = Image.alpha_composite(img, body)

    # Specular highlight hugging the top edge, and a soft floor at the bottom.
    shade = Image.new("L", (W, H), 0)
    sd = ImageDraw.Draw(shade)
    top_span = int(10 * SS)
    for i in range(top_span):
        a = int(70 * (1.0 - i / top_span) ** 1.5)
        if a > 0:
            sd.rectangle([box[0], box[1] + i, box[2], box[1] + i + 1], fill=a)
    shade = Image.fromarray(np.minimum(np.asarray(shade), np.asarray(mask)), "L")
    hi = Image.new("RGBA", (W, H), (255, 255, 255, 0))
    hi.putalpha(shade)
    img = Image.alpha_composite(img, hi)

    d = ImageDraw.Draw(img)
    d.rounded_rectangle(box, radius=r, outline=(255, 255, 255, 26), width=max(1, SS))

    _sprite_cache[key] = img
    return img


def render_caption(size: tuple[int, int], fs: FrameState) -> Image.Image:
    """
    Live-caption pill.

    The pill is sized to its contents and centred in the frame, so it starts
    compact and grows as you speak. A fixed-width panel looked cheap: one short
    word floating in a large empty slab.

    Layout is a single horizontal row - waveform, text, elapsed time - inside one
    fully rounded shape. An earlier version floated the waveform in a separate
    badge above the card, which read as two disconnected pieces.
    """
    CW, CH = size
    w, h = CW * SS, CH * SS
    pal = PALETTES.get(fs.state, RECORDING)
    lvl = max(0.0, min(1.0, fs.level))

    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))

    fsize = int(15.5 * SS)
    font = _font(fsize)
    line_h = fsize * 1.44

    pad_l = int(20 * SS)          # left inset to the waveform
    wave_w = int(46 * SS)
    gap = int(15 * SS)
    pad_r = int(18 * SS)
    timer_w = int(38 * SS) if fs.elapsed >= 1.0 else 0

    min_pw = int(238 * SS)
    max_pw = min(int(600 * SS), w - _MARGIN * SS * 2)
    text_left = pad_l + wave_w + gap
    avail = max_pw - text_left - timer_w - pad_r

    body = (fs.text or "").strip()
    if body:
        lines = _wrap(body, font, avail)
        if len(lines) > MAX_LINES:
            lines = lines[-MAX_LINES:]
    else:
        lines = ["Listening" if fs.state == "recording" else
                 ("Transcribing" if fs.state == "transcribing"
                  else "Microphone error")]

    def measure(s):
        try:
            return font.getlength(s)
        except Exception:
            return len(s) * 8.0 * SS

    text_w = max((measure(ln) for ln in lines), default=0)
    caret_w = int(8 * SS)

    # Quantised so the sprite cache actually hits while text grows.
    want = text_left + text_w + caret_w + timer_w + pad_r
    pw = int(max(min_pw, min(max_pw, want)))
    pw = min(max_pw, ((pw + 23 * SS) // (24 * SS)) * (24 * SS))

    single = int(52 * SS)
    ph = single if len(lines) <= 1 else int(single + line_h * (len(lines) - 1))

    sprite = _pill_sprite(pw, ph, fs.state)
    ox = (w - sprite.width) // 2
    oy = (h - sprite.height) // 2
    img.alpha_composite(sprite, (ox, oy))

    # Pill origin inside the frame
    bx = ox + _MARGIN * SS
    by = oy + _MARGIN * SS
    cy = by + ph / 2.0
    d = ImageDraw.Draw(img)

    # ---- inline waveform ----------------------------------------------
    n = 7
    bar_w = 2.6 * SS
    bgap = (wave_w - bar_w) / (n - 1)
    wx = bx + pad_l
    for i, bh in enumerate(_bar_heights(fs, n, 0.4)):
        if fs.state == "transcribing":
            bh = 0.30 + 0.58 * (0.5 + 0.5 * math.sin(fs.t * 6.0 - i * 0.85))
        centre = 1.0 - abs((i - (n - 1) / 2.0) / ((n - 1) / 2.0))
        colour = pal["hot"] if centre > 0.6 else pal["core"]
        _rounded_bar(d, wx + i * bgap, cy, bar_w,
                     (22 * SS) * (0.30 + 0.70 * bh), colour + (252,))

    # ---- text ---------------------------------------------------------
    tx = bx + text_left
    ty = cy - (line_h * len(lines)) / 2.0 + (line_h - fsize) * 0.22

    for i, line in enumerate(lines):
        y = ty + i * line_h
        if not body:
            d.text((tx, y), line, font=font, fill=(150, 158, 172, 255))
            continue
        # Older lines recede so the eye lands on the newest words.
        age = (len(lines) - 1) - i
        alpha = 255 if age == 0 else (180 if age == 1 else 125)
        d.text((tx, y), line, font=font, fill=CAPTION_TEXT[:3] + (alpha,))

    # ---- caret --------------------------------------------------------
    if fs.state == "recording" and (body or (fs.t % 1.0) < 0.6):
        cx0 = tx + measure(lines[-1] if lines else "") + int(4 * SS)
        cy0 = ty + (len(lines) - 1) * line_h
        # Two translucent passes rather than a Gaussian blur: the same soft
        # edge for a fraction of the cost, on a layer redrawn 24x a second.
        for grow, alpha in ((2.4 * SS, 48), (1.2 * SS, 96)):
            d.rounded_rectangle(
                [cx0 - grow, cy0 + 2 * SS - grow,
                 cx0 + 2.0 * SS + grow, cy0 + fsize + 1 * SS + grow],
                radius=2 * SS, fill=pal["hot"] + (alpha,),
            )
        d.rounded_rectangle(
            [cx0, cy0 + 2 * SS, cx0 + 2.0 * SS, cy0 + fsize + 1 * SS],
            radius=SS, fill=(248, 250, 253, 245),
        )

    # ---- elapsed time -------------------------------------------------
    if timer_w:
        secs = int(fs.elapsed)
        d.text((bx + pw - pad_r, cy), f"{secs // 60}:{secs % 60:02d}",
               font=_font(int(11.5 * SS)), fill=(122, 130, 145, 225), anchor="rm")

    return img.resize((CW, CH), Image.BOX)


RENDERERS = {"blob": render_blob, "capsule": render_capsule,
             "caption": render_caption}
# Deliberately compact: this sits over whatever you are typing into, so it needs
# to be readable at a glance without dominating the screen. Scale it with the
# pill_scale setting. Smaller frames also render faster.
# The caption frame is a canvas, not the visible size: the pill is drawn to fit
# its contents and centred inside it, so the frame only needs to be big enough
# for the widest case plus room for the glow and shadow.
DEFAULT_SIZES = {"blob": (216, 108), "capsule": (264, 56),
                 "caption": (660, 150)}


def render(style: str, size: tuple[int, int], fs: FrameState) -> Image.Image:
    return RENDERERS.get(style, render_blob)(size, fs)
