"""
Text insertion at the current cursor position, via the Windows clipboard.

Strategy:
  1. Snapshot the existing clipboard (all formats we can round-trip)
  2. Put our text on the clipboard
  3. Release the hotkey's own modifier keys, then send Ctrl+V
  4. After a short delay, restore the snapshot

**The user's clipboard is not ours to lose.** Someone dictating a reply has very
likely got something they copied a minute ago sitting on the clipboard, and
destroying it is a bug they will notice long after they could connect it to this
app. Three rules follow, and each one is here because the code broke it:

* EmptyClipboard() destroys *every* format, not just text. Snapshotting only
  CF_UNICODETEXT means a copied image is silently lost, so we snapshot the
  common binary formats too.
* If the snapshot fails, we do not paste via the clipboard at all. Emptying a
  clipboard we could not read is unrecoverable, and the code used to log a
  warning and then do exactly that.
* The whole sequence is serialised, restore included. The restore runs on a
  timer, so two dictations in quick succession used to interleave - the second
  snapshotting the first one's text and then "restoring" it over the user's
  original data.

If the hotkey is a combo (e.g. ctrl+shift+space), Shift may still be physically
down when we send Ctrl+V - which the target app reads as Ctrl+Shift+V ("paste
without formatting", or nothing at all). We release the hotkey's modifiers, and
only those.
"""

import logging
import time
import threading
from contextlib import contextmanager

log = logging.getLogger("casper.paste")

# Formats we can reliably read as str/bytes and write straight back.
# CF_HDROP (copied files) is deliberately excluded: pywin32 hands it back as a
# tuple of paths which cannot be re-set without building a DROPFILES struct.
_BINARY_FORMAT_NAMES = ("HTML Format", "Rich Text Format", "PNG", "image/png")

_MODIFIERS = ("ctrl", "shift", "alt", "windows")

# Held for the whole snapshot -> set -> paste -> restore sequence, which means it
# is handed to the restore thread rather than released by the caller. The
# clipboard is one global resource and the restore is deferred, so without this a
# second dictation starting inside that window corrupts both.
_sequence_lock = threading.Lock()

# If this is ever hit, something is wedged; typing the text is better than
# refusing to paste for the rest of the session.
_LOCK_TIMEOUT = 8.0


@contextmanager
def _clipboard(timeout: float = 1.5):
    """
    Open the clipboard with retries.

    The clipboard is a single global resource; other apps (Office, browsers,
    clipboard managers) hold it open for short bursts and OpenClipboard fails
    with "Access is denied" if you don't retry.
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
            # Worth a line: a clipboard left open blocks every other app on the
            # machine from using it, so this is never merely cosmetic.
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
    Insert `text` at the caret in whatever window has focus.

    Returns True if the paste keystroke was sent.
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
            # Do NOT continue to EmptyClipboard(). We could not read what is on
            # the clipboard, so emptying it destroys it with nothing to put back,
            # and the restore step would find an empty snapshot and leave our own
            # text sitting there instead. Typing is slower and completely safe.
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
            # Leave our text on the clipboard and do not restore. The caller
            # tells the user the text is on the clipboard so they can paste it
            # themselves, and scheduling a restore here made that a lie - it
            # wiped the text a fraction of a second later.
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
    Send key-up for the hotkey's own modifiers, if they are still held.

    Without this, a combo hotkey turns our Ctrl+V into Ctrl+Shift+V / Ctrl+Alt+V.

    Only the hotkey's modifiers, and this matters. Releasing every modifier that
    happened to be down took keys away from the user: a held Shift is how you
    extend a selection, a held Ctrl or Alt may be part of something the user is
    doing in the target app, and for a modifier-based hotkey a forced release is
    itself a key-up - which ends the dictation that is in progress. We only have a
    reason to touch keys the hotkey put down.
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

    User Interface Privilege Isolation silently discards synthetic input sent to a
    higher-integrity process, so `keyboard.send` succeeds and nothing appears.
    There is no way to ask whether the keystroke arrived, so this infers it: if we
    cannot even open the foreground window's process for a limited-information
    query, it is at a higher integrity level than we are.

    Only ever used to explain a failure, never to decide whether to paste, so a
    wrong answer costs at most one unnecessary log line.
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
    Put the original clipboard back, on a background thread.

    Takes ownership of `_sequence_lock` from the caller and releases it when the
    restore is done, so the next dictation cannot start snapshotting until the
    clipboard is back to what the user had.
    """

    def _restore():
        try:
            time.sleep(delay)
            if not saved:
                # The clipboard was genuinely empty before we wrote to it, so
                # there is nothing to put back and our text can stay. (A *failed*
                # snapshot never reaches here - that path types instead.)
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


# Typing is roughly 200 characters a second, so a long dictation would hold the
# keyboard for an uninterruptible age and land in whatever window gains focus
# meanwhile. Past this we type a prefix and leave the rest on the clipboard.
_MAX_TYPED_CHARS = 2000


def _type_fallback(text: str) -> bool:
    """
    Last resort: synthesise the keystrokes directly.

    Used when the clipboard cannot be read or written. Slower and more fragile
    than pasting, but it never destroys clipboard data, which is why the snapshot
    failure path comes here rather than pressing on.
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
