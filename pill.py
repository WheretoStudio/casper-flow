"""
Floating status overlay, shown while the mic is live and while transcription runs.

Frames come from pill_render.py and reach the screen through a Win32 layered
window (UpdateLayeredWindow), the only route to per-pixel alpha for the halos and
antialiased edges. tkinter owns the window for its message loop and lifecycle but
does none of the painting. The window is click-through and never takes focus, so
it cannot steal the caret from the app being dictated into. If the layered window
fails, a plain tkinter capsule takes over.
"""

from __future__ import annotations

import ctypes
import logging
import threading
import time
import tkinter as tk
from ctypes import wintypes

from paths import apply_window_icon

log = logging.getLogger("casper.pill")

FPS = 24
HISTORY = 24            # level samples kept for the trailing waveform

# ------------------------------------------------------------------ win32

try:
    _u32 = ctypes.WinDLL("user32", use_last_error=True)
    _g32 = ctypes.WinDLL("gdi32", use_last_error=True)
except Exception:                                    # pragma: no cover
    _u32 = _g32 = None

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020      # click-through
WS_EX_NOACTIVATE = 0x08000000       # never take focus
WS_EX_TOOLWINDOW = 0x00000080       # keep out of Alt-Tab
ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte),
                ("AlphaFormat", ctypes.c_ubyte)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


def _declare_signatures():
    """
    Declare argtypes/restypes for every Win32 call made here. Otherwise ctypes
    marshals Python ints as 32-bit C int, and 64-bit window and GDI handles
    exceed that range ("OverflowError: int too long to convert").
    """
    HWND, HDC = wintypes.HWND, wintypes.HDC
    HBITMAP, HGDIOBJ = wintypes.HBITMAP, wintypes.HGDIOBJ
    BOOL, DWORD, UINT = wintypes.BOOL, wintypes.DWORD, wintypes.UINT
    c_int, c_long = ctypes.c_int, ctypes.c_long

    _u32.GetDC.argtypes = (HWND,)
    _u32.GetDC.restype = HDC
    _u32.ReleaseDC.argtypes = (HWND, HDC)
    _u32.ReleaseDC.restype = c_int
    _u32.GetParent.argtypes = (HWND,)
    _u32.GetParent.restype = HWND
    _u32.GetWindowLongW.argtypes = (HWND, c_int)
    _u32.GetWindowLongW.restype = c_long
    _u32.SetWindowLongW.argtypes = (HWND, c_int, c_long)
    _u32.SetWindowLongW.restype = c_long
    _u32.UpdateLayeredWindow.argtypes = (
        HWND, HDC, ctypes.POINTER(POINT), ctypes.POINTER(SIZE), HDC,
        ctypes.POINTER(POINT), DWORD, ctypes.POINTER(BLENDFUNCTION), DWORD,
    )
    _u32.UpdateLayeredWindow.restype = BOOL

    _g32.CreateCompatibleDC.argtypes = (HDC,)
    _g32.CreateCompatibleDC.restype = HDC
    _g32.CreateDIBSection.argtypes = (
        HDC, ctypes.POINTER(BITMAPINFO), UINT,
        ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, DWORD,
    )
    _g32.CreateDIBSection.restype = HBITMAP
    _g32.SelectObject.argtypes = (HDC, HGDIOBJ)
    _g32.SelectObject.restype = HGDIOBJ
    _g32.DeleteObject.argtypes = (HGDIOBJ,)
    _g32.DeleteObject.restype = BOOL
    _g32.DeleteDC.argtypes = (HDC,)
    _g32.DeleteDC.restype = BOOL


if _u32 and _g32:
    try:
        _declare_signatures()
    except Exception as _e:                      # pragma: no cover
        log.warning(f"Could not declare Win32 signatures: {_e}")
        _u32 = _g32 = None


def _as_long(value: int) -> int:
    """Wrap a 32-bit style bitmask into the signed range c_long expects."""
    value &= 0xFFFFFFFF
    return value - 0x100000000 if value >= 0x80000000 else value


class _LayeredSurface:
    """Owns the GDI objects needed to blit an RGBA image to a layered window."""

    def __init__(self, hwnd: int, w: int, h: int):
        self.hwnd = hwnd
        self.w, self.h = w, h
        self.apply_style()

        self.screen_dc = _u32.GetDC(0)
        self.mem_dc = _g32.CreateCompatibleDC(self.screen_dc)

        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h        # negative = top-down rows
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0    # BI_RGB

        self.bits = ctypes.c_void_p()
        _g32.CreateDIBSection.restype = wintypes.HBITMAP
        self.bitmap = _g32.CreateDIBSection(
            self.screen_dc, ctypes.byref(bmi), 0,
            ctypes.byref(self.bits), None, 0,
        )
        if not self.bitmap or not self.bits:
            raise OSError("CreateDIBSection failed")
        self.old = _g32.SelectObject(self.mem_dc, self.bitmap)

        self.blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        self.nbytes = w * h * 4
        self._warned = False
        self.blank = bytes(self.nbytes)      # fully transparent frame

    def apply_style(self):
        """
        (Re-)apply the extended window styles. Idempotent, and called before each
        show: tkinter can recreate the underlying window, dropping WS_EX_LAYERED
        and failing UpdateLayeredWindow with ERROR_INVALID_PARAMETER (87).
        """
        style = _u32.GetWindowLongW(self.hwnd, GWL_EXSTYLE)
        _u32.SetWindowLongW(
            self.hwnd, GWL_EXSTYLE,
            _as_long(style | WS_EX_LAYERED | WS_EX_TRANSPARENT
                     | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW),
        )

    def blit(self, bgra: bytes, x: int, y: int) -> bool:
        ctypes.memmove(self.bits, bgra, min(len(bgra), self.nbytes))
        ok = _u32.UpdateLayeredWindow(
            self.hwnd, self.screen_dc,
            ctypes.byref(POINT(x, y)), ctypes.byref(SIZE(self.w, self.h)),
            self.mem_dc, ctypes.byref(POINT(0, 0)), 0,
            ctypes.byref(self.blend), ULW_ALPHA,
        )
        if not ok and not self._warned:
            self._warned = True
            log.warning(
                f"UpdateLayeredWindow failed (err={ctypes.get_last_error()}); "
                f"the overlay may not be visible"
            )
        return bool(ok)

    def close(self):
        try:
            _g32.SelectObject(self.mem_dc, self.old)
            _g32.DeleteObject(self.bitmap)
            _g32.DeleteDC(self.mem_dc)
            _u32.ReleaseDC(0, self.screen_dc)
        except Exception:
            pass


def _to_bgra(img) -> bytes:
    """RGBA PIL image -> premultiplied BGRA bytes, as UpdateLayeredWindow wants."""
    import numpy as np
    a = np.asarray(img.convert("RGBA"), dtype=np.uint8)
    alpha = a[:, :, 3].astype(np.uint16)
    # Premultiply; Windows composites with already-multiplied colour channels.
    rgb = (a[:, :, :3].astype(np.uint16) * alpha[:, :, None] // 255).astype(np.uint8)
    out = np.empty_like(a)
    out[:, :, 0] = rgb[:, :, 2]      # B
    out[:, :, 1] = rgb[:, :, 1]      # G
    out[:, :, 2] = rgb[:, :, 0]      # R
    out[:, :, 3] = a[:, :, 3]
    return out.tobytes()


# -------------------------------------------------------------------- pill

class RecordingPill:
    """
    Thread-safe status overlay. tkinter gets its own thread and mainloop in
    _tk_main; show()/set_state()/hide() may be called from any thread and are
    marshalled onto that loop with after().
    """

    def __init__(self, cfg: dict | None = None):
        cfg = cfg or {}
        import pill_render as pr

        self._pr = pr
        self.style = str(cfg.get("pill_style", "caption")).lower()
        if self.style not in pr.RENDERERS:
            log.warning(f"Unknown pill_style {self.style!r}; using 'caption'")
            self.style = "caption"

        scale = float(cfg.get("pill_scale", 1.0))
        scale = min(3.0, max(0.5, scale))
        bw, bh = pr.DEFAULT_SIZES[self.style]
        self.size = (int(bw * scale), int(bh * scale))
        self.position = str(cfg.get("pill_position", "bottom-center")).lower()
        self.enabled = bool(cfg.get("show_pill", True))

        self._root: tk.Tk | None = None
        self._surface: _LayeredSurface | None = None
        self._fallback: dict | None = None
        self._ready = threading.Event()
        self._failed = False

        self._state = "recording"
        self._visible = False
        self._t0 = 0.0
        self._anim_id = None
        self._history: list[float] = [0.0] * HISTORY
        self._level_source = None
        self._elapsed_source = None
        self._text = ""

        if not self.enabled:
            log.info("Status pill disabled (show_pill=false)")
            self._failed = True
            self._ready.set()
            return

        threading.Thread(target=self._tk_main, daemon=True, name="pill-ui").start()
        if not self._ready.wait(timeout=6):
            log.warning("Pill UI did not start within 6s; continuing without it")

    # -- wiring --------------------------------------------------------

    def set_sources(self, level=None, elapsed=None):
        """Provide callables for live input level (0-1) and elapsed seconds."""
        self._level_source = level
        self._elapsed_source = elapsed

    # -- public API ----------------------------------------------------

    def show(self, state: str = "recording"):
        def run():
            self._state = state
            self._t0 = time.monotonic()
            self._history = [0.0] * HISTORY
            self._text = ""
            self._do_show()
        self._schedule(run)

    def set_state(self, state: str):
        self._schedule(lambda: setattr(self, "_state", state))

    def set_text(self, text: str):
        """Update the live transcript shown in the caption style."""
        self._schedule(lambda: setattr(self, "_text", text or ""))

    def hide(self):
        self._schedule(self._do_hide)

    # -- internals -----------------------------------------------------

    def _schedule(self, fn):
        root = self._root
        if root is None or self._failed:
            return
        try:
            root.after(0, fn)
        except Exception as e:
            log.debug(f"Could not schedule pill update: {e}")

    def _origin(self) -> tuple[int, int]:
        assert self._root is not None
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        w, h = self.size
        if self.position == "bottom-right":
            return sw - w - 28, sh - h - 72
        if self.position == "top-center":
            return (sw - w) // 2, 40
        if self.position == "center":
            return (sw - w) // 2, (sh - h) // 2
        return (sw - w) // 2, sh - h - 96        # bottom-center (default)

    @staticmethod
    def _toplevel_hwnd(root: tk.Tk) -> int:
        """
        Real top-level HWND for a Tk window. winfo_id() can return a child
        handle, and UpdateLayeredWindow needs the top-level window.
        """
        hwnd = root.winfo_id()
        try:
            while True:
                parent = _u32.GetParent(hwnd)
                if not parent:
                    return hwnd
                hwnd = parent
        except Exception:
            return hwnd

    def _tk_main(self):
        try:
            root = tk.Tk()
        except Exception as e:
            log.error(f"Overlay unavailable (tkinter failed to start): {e}")
            self._failed = True
            self._ready.set()
            return

        # First and only Tk root in the process, so the icon set here is inherited
        # by the settings window, wizard and dialogs. This overlay is
        # overrideredirect and has no taskbar button of its own.
        apply_window_icon(root)

        try:
            w, h = self.size
            root.overrideredirect(True)
            root.attributes("-topmost", True)
            root.geometry(f"{w}x{h}+0+0")
            root.update_idletasks()

            if _u32 and _g32:
                try:
                    # The window must be mapped before UpdateLayeredWindow paints.
                    root.deiconify()
                    root.update()
                    self._surface = _LayeredSurface(self._toplevel_hwnd(root), w, h)
                    # Start invisible with a transparent frame, not withdraw():
                    # tkinter can recreate the window on withdraw/deiconify, which
                    # drops the layered style and breaks the blit.
                    self._surface.blit(self._surface.blank, -10000, -10000)
                    log.info(
                        f"Overlay ready: style={self.style} size={w}x{h} "
                        f"pos={self.position} (layered window, per-pixel alpha)"
                    )
                except Exception as e:
                    log.warning(f"Layered window unavailable ({e}); using simple overlay")
                    self._surface = None

            if self._surface is None:
                self._build_fallback(root)
                root.withdraw()

            self._root = root
        except Exception as e:
            log.exception(f"Overlay setup failed: {e}")
            self._failed = True
            self._ready.set()
            return

        self._ready.set()
        try:
            root.mainloop()
        except Exception as e:
            log.error(f"Overlay loop ended: {e}")

    # -- fallback (no layered window) ----------------------------------

    def _build_fallback(self, root: tk.Tk):
        key = "#ff00fe"
        try:
            root.attributes("-transparentcolor", key)
            root.configure(bg=key)
        except tk.TclError:
            key = "#1a1a1a"
            root.configure(bg=key)
        w, h = self.size
        h = min(h, 64)
        root.geometry(f"{w}x{h}+0+0")
        self.size = (w, h)
        canvas = tk.Canvas(root, width=w, height=h, bg=key,
                           highlightthickness=0, bd=0)
        canvas.pack()
        r = h // 2
        body = [
            canvas.create_oval(0, 0, 2 * r, h, fill="#fa2e2e", outline=""),
            canvas.create_oval(w - 2 * r, 0, w, h, fill="#fa2e2e", outline=""),
            canvas.create_rectangle(r, 0, w - r, h, fill="#fa2e2e", outline=""),
        ]
        label = canvas.create_text(w // 2, h // 2, text="Recording",
                                   fill="white", font=("Segoe UI", 11, "bold"))
        self._fallback = {"canvas": canvas, "body": body, "label": label}

    def _paint_fallback(self):
        fb = self._fallback
        if not fb:
            return
        colour = {"recording": "#fa2e2e", "transcribing": "#f5942a",
                  "error": "#7a8492"}.get(self._state, "#fa2e2e")
        text = self._pr.LABELS.get(self._state, self._state.title())
        try:
            for item in fb["body"]:
                fb["canvas"].itemconfigure(item, fill=colour)
            fb["canvas"].itemconfigure(fb["label"], text=text)
        except Exception:
            pass

    # -- show / hide / animate -----------------------------------------

    def _do_show(self):
        if not self._root:
            return
        if self._visible:
            self._state_changed()
            return
        try:
            if self._surface:
                # Layered path: the window stays mapped; just resume real frames.
                self._surface.apply_style()
                self._root.attributes("-topmost", True)
            else:
                x, y = self._origin()
                self._root.geometry(f"{self.size[0]}x{self.size[1]}+{x}+{y}")
                self._root.deiconify()
                self._root.attributes("-topmost", True)
            self._visible = True
            self._tick()
        except Exception as e:
            log.debug(f"Could not show overlay: {e}")

    def _state_changed(self):
        if self._fallback:
            self._paint_fallback()

    def _do_hide(self):
        if not self._root or not self._visible:
            return
        self._visible = False
        if self._anim_id is not None:
            try:
                self._root.after_cancel(self._anim_id)
            except Exception:
                pass
            self._anim_id = None
        try:
            if self._surface:
                # Transparent frame parked offscreen instead of withdraw(), so
                # tkinter never recreates the window and drops the layered style.
                self._surface.blit(self._surface.blank, -10000, -10000)
            else:
                self._root.withdraw()
        except Exception as e:
            log.debug(f"Could not hide overlay: {e}")

    def _tick(self):
        """One animation frame. Reschedules itself while visible."""
        if not self._visible or not self._root:
            return

        try:
            level = 0.0
            if self._level_source is not None:
                try:
                    level = float(self._level_source() or 0.0)
                except Exception:
                    level = 0.0
            elapsed = 0.0
            if self._elapsed_source is not None:
                try:
                    elapsed = float(self._elapsed_source() or 0.0)
                except Exception:
                    elapsed = 0.0

            self._history.append(level)
            if len(self._history) > HISTORY:
                del self._history[0]

            if self._surface:
                fs = self._pr.FrameState(
                    state=self._state,
                    t=time.monotonic() - self._t0,
                    level=level,
                    history=list(self._history),
                    elapsed=elapsed,
                    text=self._text,
                )
                img = self._pr.render(self.style, self.size, fs)
                x, y = self._origin()
                self._surface.blit(_to_bgra(img), x, y)
            else:
                self._paint_fallback()
        except Exception as e:
            log.debug(f"Overlay frame failed: {e}")

        try:
            self._anim_id = self._root.after(int(1000 / FPS), self._tick)
        except Exception:
            self._anim_id = None
