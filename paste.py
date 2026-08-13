"""
Text insertion at the caret, via the Windows clipboard.

  1. Snapshot the existing clipboard (all formats we can round-trip)
  2. Put our text on the clipboard
  3. Release the hotkey's own modifiers, then send Ctrl+V
  4. After a short delay, restore the snapshot

The user's clipboard has to survive this, and EmptyClipboard() destroys every
format rather than just text, so the snapshot covers the common binary formats
too. Step 3 is for combo hotkeys: with ctrl+shift+space Shift may still be down,
and the target app reads Ctrl+Shift+V.
"""

import logging
import time
import threading
from contextlib import contextmanager

log = logging.getLogger("casper.paste")

# Readable as str/bytes and writable straight back. CF_HDROP (copied files) is
# excluded: pywin32 returns a tuple of paths, re-setting it needs a DROPFILES struct.
_BINARY_FORMAT_NAMES = ("HTML Format", "Rich Text Format", "PNG", "image/png")

_MODIFIERS = ("ctrl", "shift", "alt", "windows")

# Held across snapshot -> set -> paste -> restore. The clipboard is one global
# resource and the restore is deferred, so ownership passes to the restore thread.
_sequence_lock = threading.Lock()

# Seconds. If hit, something is wedged; typing beats refusing for the session.
_LOCK_TIMEOUT = 8.0


@contextmanager
def _clipboard(timeout: float = 1.5):
    """
    Open the clipboard with retries. One global resource: Office, browsers and
    clipboard managers hold it open in bursts and OpenClipboard then fails with
    "Access is denied".
    """
    import win32clipboard

    deadline = time.monotonic() + timeout
    last_err = None
    while time.monotonic() < deadline:
        try:
            win32clipboard.OpenClipboard()
            break
        except Exception as e:      # pywin32 raises pywintypes.error
            last_err = e
            time.sleep(0.02)
    else:
        raise RuntimeError(f"clipboard stayed locked for {timeout}s: {last_err}")

    try:
        yield win32clipboard
    finally:
        try:
            win32clipboard.CloseClipboard()
        except Exception as e:
            # A clipboard left open blocks every other app on the machine.
            log.warning(f"Could not close the clipboard: {e}")


def _snapshot_formats(wc, win32con):
    """Return {format_id: str|bytes} for everything we can restore."""
    saved = {}
    candidates = [win32con.CF_UNICODETEXT, win32con.CF_DIB, win32con.CF_DIBV5]
    for name in _BINARY_FORMAT_NAMES:
        try:
            candidates.append(wc.RegisterClipboardFormat(name))
        except Exception:
            pass

    for fmt in candidates:
        try:
            if not wc.IsClipboardFormatAvailable(fmt):
                continue
            data = wc.GetClipboardData(fmt)
            if isinstance(data, (str, bytes)) and data:
                saved[fmt] = data
        except Exception as e:
            log.debug(f"Could not snapshot clipboard format {fmt}: {e}")

    try:
        if wc.IsClipboardFormatAvailable(win32con.CF_HDROP):
            log.info("Clipboard held copied files; those cannot be restored after paste")
    except Exception:
        pass

    return saved


def paste_text(text: str, cfg: dict | None = None, hotkey_mods=None) -> bool:
    """
    Insert `text` at the caret in the focused window. True if Ctrl+V was sent.
    """
    if not text:
        return False
    cfg = cfg or {}
    try:
        return _paste_win32(text, cfg, hotkey_mods or [])
    except Exception as e:
        log.exception(f"Paste failed: {e}")
        return False


def _paste_win32(text: str, cfg: dict, hotkey_mods) -> bool:
    try:
        import win32clipboard  # noqa: F401  (imported for the clear error message)
        import win32con
    except ImportError:
        raise RuntimeError("pywin32 not installed. Run: pip install pywin32")

    try:
        import keyboard
    except ImportError:
        raise RuntimeError("'keyboard' not installed. Run: pip install keyboard")

    settle = float(cfg.get("paste_settle_seconds", 0.06))
    restore_after = float(cfg.get("clipboard_restore_seconds", 0.4))

    if not _sequence_lock.acquire(timeout=_LOCK_TIMEOUT):
        log.error(
            f"Another paste has held the clipboard for over {_LOCK_TIMEOUT:g}s; "
            f"typing this dictation instead of using the clipboard"
        )
        return _type_fallback(text)

    # The restore thread releases the lock. Anything that returns before the
    # restore is scheduled has to release it here instead.
    handed_off = False
    try:
        # -- 1. snapshot ---------------------------------------------
        saved: dict = {}
        try:
            with _clipboard() as wc:
                saved = _snapshot_formats(wc, win32con)
            log.debug(f"Snapshotted {len(saved)} clipboard format(s)")
        except Exception as e:
            # Never fall through to EmptyClipboard(): with nothing read there is
            # nothing to put back, and restore would leave our text there.
            log.warning(
                f"Could not snapshot clipboard ({e}); typing this dictation "
                f"instead, so nothing on the clipboard is lost"
            )
            return _type_fallback(text)

        # -- 2. put our text on the clipboard ------------------------
        try:
            with _clipboard() as wc:
                wc.EmptyClipboard()
                wc.SetClipboardData(win32con.CF_UNICODETEXT, text)
        except Exception as e:
            log.error(f"Could not set clipboard, falling back to typing: {e}")
            return _type_fallback(text)

        # -- 3. release the hotkey's modifiers, then Ctrl+V ----------
        _release_modifiers(keyboard, hotkey_mods)
        time.sleep(settle)
        try:
            keyboard.send("ctrl+v")
        except Exception as e:
            # No restore: the user is told the text is on the clipboard.
            log.error(
                f"Could not send Ctrl+V ({e}); leaving the text on the clipboard "
                f"so it can be pasted manually. The previous clipboard contents "
                f"are lost."
            )
            return False

        log.info(f"Ctrl+V sent ({len(text)} chars)")
        if _foreground_looks_elevated():
            log.warning(
                "The focused window belongs to a program running as "
                "administrator. Windows blocks synthetic keystrokes to those, so "
                "the text may not have appeared - it is on the clipboard, so "
                "Ctrl+V by hand will work. Running Casper Flow as administrator "
                "too would also fix it."
            )

        # -- 4. restore -----------------------------------------------
        _schedule_restore(saved, win32con, restore_after)
        handed_off = True
        return True
    finally:
        if not handed_off:
            _sequence_lock.release()


def _release_modifiers(keyboard, hotkey_mods):
    """
    Send key-up for the hotkey's own modifiers, if still held. Without this a combo
    hotkey turns our Ctrl+V into Ctrl+Shift+V.

    Only the hotkey's own: a held Shift extends a selection, a held Ctrl or Alt may
    belong to the target app, and for a modifier-based hotkey a forced release is a
    key-up that ends the dictation in progress.
    """
    wanted = [m for m in dict.fromkeys(hotkey_mods) if m in _MODIFIERS]
    for mod in wanted:
        try:
            if keyboard.is_pressed(mod):
                keyboard.release(mod)
                log.debug(f"Released held hotkey modifier: {mod}")
        except Exception as e:
            log.debug(f"Could not release {mod}: {e}")


def _foreground_looks_elevated() -> bool:
    """
    True if the focused window is probably a process we cannot send keys to.

    UIPI discards synthetic input sent to a higher-integrity process: keyboard.send
    succeeds and nothing appears, with no way to ask. Inferred from failing to open
    the process even for a limited-information query. Only used to explain a
    failure, so a wrong answer costs one log line.
    """
    try:
        import ctypes
        from ctypes import wintypes

        u32 = ctypes.WinDLL("user32", use_last_error=True)
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)

        hwnd = u32.GetForegroundWindow()
        if not hwnd:
            return False
        pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return False

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False,
                                 pid.value)
        if handle:
            k32.CloseHandle(handle)
            return False
        ERROR_ACCESS_DENIED = 5
        return ctypes.get_last_error() == ERROR_ACCESS_DENIED
    except Exception:
        return False


def _schedule_restore(saved: dict, win32con, delay: float):
    """
    Put the original clipboard back, on a background thread. Takes ownership of
    _sequence_lock and releases it when done, so the next dictation cannot snapshot
    a clipboard that is still ours.
    """

    def _restore():
        try:
            time.sleep(delay)
            if not saved:
                # Genuinely empty before we wrote, so our text can stay.
                log.debug("Clipboard was empty before pasting; leaving our text")
                return
            try:
                with _clipboard() as wc:
                    wc.EmptyClipboard()
                    for fmt, data in saved.items():
                        try:
                            wc.SetClipboardData(fmt, data)
                        except Exception as e:
                            log.debug(
                                f"Could not restore clipboard format {fmt}: {e}")
                log.debug(f"Clipboard restored ({len(saved)} format(s))")
            except Exception as e:
                log.warning(f"Could not restore clipboard: {e}")
        finally:
            _sequence_lock.release()

    threading.Thread(target=_restore, daemon=True, name="clipboard-restore").start()


# Typing runs ~200 chars/sec, so a long dictation holds the keyboard for seconds
# and spills into whatever window takes focus. Past this, type a prefix only.
_MAX_TYPED_CHARS = 2000


def _type_fallback(text: str) -> bool:
    """
    Last resort: synthesise the keystrokes, when the clipboard cannot be read or
    written. Slower and more fragile, but it never destroys clipboard data.
    """
    try:
        import keyboard
        if "\n" in text:
            log.warning(
                "Typing a multi-line dictation: each line break is an Enter "
                "keypress, which some chat apps treat as send."
            )
        if len(text) > _MAX_TYPED_CHARS:
            log.warning(
                f"Dictation is {len(text)} chars; typing the first "
                f"{_MAX_TYPED_CHARS} only."
            )
            text = text[:_MAX_TYPED_CHARS]
        keyboard.write(text, delay=0.005)
        log.info(f"Typed {len(text)} chars directly (clipboard unavailable)")
        return True
    except Exception as e:
        log.error(f"Typing fallback failed: {e}")
        return False
