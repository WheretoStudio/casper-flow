"""
Where files live, whether running from source or from a frozen build.

  DATA_DIR      user-writable, survives an update: settings.json, casper.log,
                settings.local.json, .env
  RESOURCE_DIR  read-only, shipped with the build: assets, bundled models,
                the default settings.json

From source both are this directory. Frozen, DATA_DIR is the folder holding the
executable (writable without admin under a per-user install) and RESOURCE_DIR is
the bundle. Never use `Path(__file__).parent` for data: frozen, it points inside
`_internal`, which an update overwrites.
"""

import sys
from pathlib import Path

__all__ = [
    "FROZEN", "DATA_DIR", "RESOURCE_DIR",
    "resource_file", "icon_file", "apply_window_icon",
]

FROZEN = getattr(sys, "frozen", False)

if FROZEN:
    DATA_DIR = Path(sys.executable).resolve().parent
    # _MEIPASS is where PyInstaller unpacked the bundle; for --onedir that is the
    # _internal folder beside the executable.
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", DATA_DIR)).resolve()
else:
    DATA_DIR = Path(__file__).resolve().parent
    RESOURCE_DIR = DATA_DIR


def icon_file() -> Path:
    """
    The application icon, wherever it lives for this build.

    The tray, overlay, settings window and setup wizard all need it, and it has to
    resolve through RESOURCE_DIR to be found in a frozen build.
    """
    return resource_file("assets/casper.ico")


_icon_cache: dict = {}


def _load_sized_icon(cx: int, cy: int):
    """
    An HICON holding the .ico frame drawn for exactly cx x cy.

    LoadImage picks the closest frame in the file before scaling, so asking for
    32 px gets the 32 px frame, not a blown-up 16 px one. Cached: these live for
    the life of the process and every window wants the same two.
    """
    key = (cx, cy)
    if key in _icon_cache:
        return _icon_cache[key]

    import ctypes

    IMAGE_ICON = 1
    LR_LOADFROMFILE = 0x0010

    u32 = ctypes.WinDLL("user32", use_last_error=True)
    u32.LoadImageW.restype = ctypes.c_void_p
    u32.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint,
                               ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    handle = u32.LoadImageW(None, str(icon_file()), IMAGE_ICON, cx, cy,
                            LR_LOADFROMFILE)
    _icon_cache[key] = handle
    return handle


def _set_win32_icons(window) -> bool:
    """
    Put the right-sized frame in each of the window's two icon slots.

    Tk's `iconbitmap(default=)` reuses one handle (the 32 px frame) for both the
    small and big class slot, so the title bar squeezes 32 px into 16 and discards
    the simplified 16 px frame. Both slots are therefore set explicitly: WM_SETICON
    for this window, and the class slots so later windows inherit the same pair.
    """
    try:
        import ctypes

        u32 = ctypes.WinDLL("user32", use_last_error=True)
        SM_CXICON, SM_CYICON = 11, 12
        SM_CXSMICON, SM_CYSMICON = 49, 50
        WM_SETICON = 0x0080
        ICON_SMALL, ICON_BIG = 0, 1
        GCLP_HICON, GCLP_HICONSM = -14, -34

        big = _load_sized_icon(u32.GetSystemMetrics(SM_CXICON),
                               u32.GetSystemMetrics(SM_CYICON))
        small = _load_sized_icon(u32.GetSystemMetrics(SM_CXSMICON),
                                 u32.GetSystemMetrics(SM_CYSMICON))
        if not big or not small:
            return False

        # winfo_id() can be a child handle; the icon belongs on the top level.
        hwnd = window.winfo_id()
        while True:
            parent = u32.GetParent(hwnd)
            if not parent:
                break
            hwnd = parent

        u32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                     ctypes.c_void_p, ctypes.c_void_p]
        u32.SendMessageW.restype = ctypes.c_size_t
        u32.SendMessageW(ctypes.c_void_p(hwnd), WM_SETICON,
                         ctypes.c_void_p(ICON_BIG), ctypes.c_void_p(big))
        u32.SendMessageW(ctypes.c_void_p(hwnd), WM_SETICON,
                         ctypes.c_void_p(ICON_SMALL), ctypes.c_void_p(small))

        setter = getattr(u32, "SetClassLongPtrW", None) or u32.SetClassLongW
        setter.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        setter.restype = ctypes.c_size_t
        setter(ctypes.c_void_p(hwnd), GCLP_HICON, ctypes.c_void_p(big))
        setter(ctypes.c_void_p(hwnd), GCLP_HICONSM, ctypes.c_void_p(small))
        return True
    except Exception:
        return False


def apply_window_icon(window) -> bool:
    """
    Give a Tk window the application icon, for the title bar and the taskbar.

    `iconbitmap(default=)` makes the .ico the default for later windows;
    _set_win32_icons() supplies the correctly-sized frame per slot, which Tk will
    not do. Both are needed. Returns whether the icon was applied, and never
    raises: a missing icon should not stop a window opening.
    """
    if not icon_file().exists():
        return False
    applied = False
    try:
        window.iconbitmap(default=str(icon_file()))
        applied = True
    except Exception:
        try:
            window.iconbitmap(str(icon_file()))
            applied = True
        except Exception:
            pass
    # Runs even if iconbitmap failed; this is what decides what the taskbar draws.
    return _set_win32_icons(window) or applied


def resource_file(name: str) -> Path:
    """
    A file shipped with the build.

    DATA_DIR is checked first, so a replacement dropped beside the executable wins
    over the bundled copy - useful for swapping an icon or model without a rebuild.
    """
    candidate = DATA_DIR / name
    if candidate.exists():
        return candidate
    return RESOURCE_DIR / name
