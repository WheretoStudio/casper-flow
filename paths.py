"""
Where files live, whether running from source or from a frozen build.

`Path(__file__).parent` is correct when running from source and wrong once
PyInstaller has bundled the app: `__file__` then points inside `_internal`, so
settings, the log and the `.env` all end up in a directory the user cannot
reasonably find and that an update would overwrite. The first frozen build did
exactly that.

Two directories, because they have different requirements:

  DATA_DIR      user-writable, survives an update: settings.json, casper.log,
                settings.local.json, .env
  RESOURCE_DIR  read-only, shipped with the build: assets, bundled models,
                the default settings.json

Running from source they are the same directory, which is what makes development
straightforward. Frozen, DATA_DIR is the folder containing the executable - which
under a per-user install is `%LOCALAPPDATA%\\Programs\\CasperFlow` and therefore
writable without administrator rights - and RESOURCE_DIR is the bundle.
"""

import sys
from pathlib import Path

__all__ = [
    "FROZEN", "DATA_DIR", "RESOURCE_DIR",
    "resource_file", "icon_file", "apply_window_icon",
]

FROZEN = getattr(sys, "frozen", False)

if FROZEN:
    # sys.executable is the .exe; its parent is the install directory.
    DATA_DIR = Path(sys.executable).resolve().parent
    # _MEIPASS is where PyInstaller unpacked the bundle. For a --onedir build
    # that is the _internal folder beside the executable.
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", DATA_DIR)).resolve()
else:
    DATA_DIR = Path(__file__).resolve().parent
    RESOURCE_DIR = DATA_DIR


# There is deliberately no data_file() helper. It existed, was exported, and was
# never called once: every caller writes `DATA_DIR / name` directly, which is
# shorter than the import. Kept as a note so it does not get reinvented.


def icon_file() -> Path:
    """
    The application icon, wherever it lives for this build.

    One place, because it is needed by the tray, the overlay, the settings window
    and the setup wizard, and three of those had their own copy of the path - one
    of which pointed at DATA_DIR and would therefore have failed to find it in a
    frozen build, silently, inside a try/except.
    """
    return resource_file("assets/casper.ico")


_icon_cache: dict = {}


def _load_sized_icon(cx: int, cy: int):
    """
    An HICON holding the .ico frame drawn for exactly cx x cy.

    LoadImage picks the closest frame in the file and only then scales, so asking
    for 32 px gets the 32 px frame rather than a blown-up 16 px one. Cached
    because these live for the life of the process and every window wants the
    same two.
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

    Tk's `iconbitmap(default=)` loads one icon and assigns that single handle to
    both the small and the big class slot. Measured, it picks the big one (32 px),
    so the title bar then shows a 32 px frame squeezed into 16 - which throws away
    the simplified 16 px frame that make_icon.py draws specifically to stay legible
    at that size.

    So set both slots explicitly: WM_SETICON for this window, and the class slots
    so windows created later inherit the same pair.
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

    Two steps, because neither alone is enough:

      iconbitmap(default=)  makes Tk treat the .ico as the default for windows
                            created later. Plain `iconbitmap(path)` - what this
                            code used to do - sets only the small icon, leaving
                            the taskbar to upscale a 16 px frame, which is why the
                            mark looked soft and blobby.
      _set_win32_icons()    puts the correctly-sized frame in each slot, which Tk
                            does not do; it reuses one handle for both.

    Returns whether the icon was applied. Never raises - a missing icon is not
    worth failing to open a window over.
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
    # Runs even if iconbitmap failed; it is the part that actually decides what
    # the taskbar draws.
    return _set_win32_icons(window) or applied


def resource_file(name: str) -> Path:
    """
    A file shipped with the build.

    Falls back to DATA_DIR when the resource is not in the bundle, so a user who
    drops a replacement next to the executable wins - useful for swapping an icon
    or adding a model without rebuilding.
    """
    candidate = DATA_DIR / name
    if candidate.exists():
        return candidate
    return RESOURCE_DIR / name
