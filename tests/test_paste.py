"""
Clipboard insertion.

**The user's clipboard is not ours to lose.** Somebody dictating a reply has very
likely got something they copied a minute ago sitting on the clipboard, and
destroying it is a bug they will notice long after they could connect it to this
app. Every test here is about that, not about whether the paste worked.

Driven through fakes rather than the real Win32 clipboard. The real thing is a
single global resource that other applications hold open in short bursts, so a test
suite that used it would be flaky for reasons that have nothing to do with this
code - and the paths that matter most are the failure paths, which are the hardest
to provoke for real.
"""

import sys
import types

import pytest

import paste


class FakeClipboard:
    """
    Enough of win32clipboard to exercise the logic.

    `fail_open_until` makes the first N opens raise, which is how a clipboard held
    by another application behaves, and is the case that used to destroy data.
    """

    CF_UNICODETEXT = 13
    CF_DIB = 8
    CF_DIBV5 = 17
    CF_HDROP = 15

    def __init__(self, contents=None, locked=False):
        self.contents = dict(contents or {})
        # A count would not do: _clipboard retries until a wall-clock deadline, so
        # "fail the first N opens" is satisfied by spinning and the clipboard then
        # appears to unlock. Locked means locked.
        self.locked = locked
        self.opens = 0
        self.emptied = 0
        self.closed = 0

    # -- the win32clipboard surface ------------------------------------
    def OpenClipboard(self):
        self.opens += 1
        if self.locked:
            raise OSError("Access is denied")

    def CloseClipboard(self):
        self.closed += 1

    def EmptyClipboard(self):
        self.emptied += 1
        self.contents.clear()

    def IsClipboardFormatAvailable(self, fmt):
        return fmt in self.contents

    def GetClipboardData(self, fmt):
        return self.contents[fmt]

    def SetClipboardData(self, fmt, data):
        self.contents[fmt] = data

    def RegisterClipboardFormat(self, name):
        return 1000 + len(name)


class FakeKeyboard:
    def __init__(self, send_fails=False, pressed=()):
        self.send_fails = send_fails
        self.pressed = set(pressed)
        self.sent = []
        self.released = []
        self.written = []

    def send(self, combo):
        if self.send_fails:
            raise OSError("SendInput failed")
        self.sent.append(combo)

    def is_pressed(self, key):
        return key in self.pressed

    def release(self, key):
        self.released.append(key)
        self.pressed.discard(key)

    def write(self, text, delay=0):
        self.written.append(text)


@pytest.fixture
def wired(monkeypatch):
    """
    Install the fakes as the modules paste.py imports, and make the deferred
    clipboard restore run inline so a test can assert on the final state.
    """
    clip = FakeClipboard()
    kb = FakeKeyboard()

    win32con = types.SimpleNamespace(
        CF_UNICODETEXT=FakeClipboard.CF_UNICODETEXT,
        CF_DIB=FakeClipboard.CF_DIB,
        CF_DIBV5=FakeClipboard.CF_DIBV5,
        CF_HDROP=FakeClipboard.CF_HDROP,
    )
    monkeypatch.setitem(sys.modules, "win32clipboard", clip)
    monkeypatch.setitem(sys.modules, "win32con", win32con)
    monkeypatch.setitem(sys.modules, "keyboard", kb)

    # No sleeping, and no elevation probe - the latter calls into user32.
    monkeypatch.setattr(paste.time, "sleep", lambda _s: None)
    monkeypatch.setattr(paste, "_foreground_looks_elevated", lambda: False)

    # The restore normally runs on a timer thread and takes ownership of the
    # sequence lock. Run it inline so its effect on the clipboard is visible to the
    # assertions, keeping the same lock hand-off.
    monkeypatch.setattr(
        paste, "_schedule_restore",
        lambda saved, _win32con, _delay: _run_restore_inline(saved, clip))
    return clip, kb


def _run_restore_inline(saved, clip):
    """What _schedule_restore's worker does, minus the thread and the delay."""
    try:
        if saved:
            clip.OpenClipboard()
            clip.EmptyClipboard()
            for fmt, data in saved.items():
                clip.SetClipboardData(fmt, data)
            clip.CloseClipboard()
    finally:
        paste._sequence_lock.release()


TEXT = FakeClipboard.CF_UNICODETEXT


class TestTheHappyPath:
    def test_the_text_is_pasted_and_the_clipboard_restored(self, wired):
        clip, kb = wired
        clip.contents = {TEXT: "something the user copied"}

        assert paste.paste_text("kal meeting hai", {}) is True
        assert kb.sent == ["ctrl+v"]
        assert clip.contents == {TEXT: "something the user copied"}, (
            "the user's clipboard was not put back")

    def test_an_empty_clipboard_keeps_our_text_rather_than_being_emptied(self, wired):
        clip, _kb = wired
        clip.contents = {}
        assert paste.paste_text("kal meeting hai", {}) is True
        assert clip.contents == {TEXT: "kal meeting hai"}

    def test_empty_text_is_refused(self, wired):
        assert paste.paste_text("", {}) is False


class TestAFailedSnapshotNeverDestroysTheClipboard:
    """
    The defect this class exists for: the snapshot failing was logged as a warning
    and then EmptyClipboard() ran anyway. The user's clipboard was gone, with
    nothing saved to put back, and the restore step then found an empty snapshot
    and left our dictation sitting there instead.
    """

    def test_typing_is_used_instead_of_emptying(self, monkeypatch):
        clip = FakeClipboard({TEXT: "irreplaceable"}, locked=True)
        kb = FakeKeyboard()
        win32con = types.SimpleNamespace(
            CF_UNICODETEXT=TEXT, CF_DIB=8, CF_DIBV5=17, CF_HDROP=15)
        monkeypatch.setitem(sys.modules, "win32clipboard", clip)
        monkeypatch.setitem(sys.modules, "win32con", win32con)
        monkeypatch.setitem(sys.modules, "keyboard", kb)

        assert paste.paste_text("kal meeting hai", {}) is True
        assert clip.emptied == 0, "emptied a clipboard it could not read"
        assert clip.contents == {TEXT: "irreplaceable"}
        assert kb.written == ["kal meeting hai"], "did not fall back to typing"
        assert kb.sent == [], "sent Ctrl+V without putting anything on the clipboard"


class TestPasteFailureLeavesTheTextReachable:
    """
    On a failed Ctrl+V the caller tells the user the text is on the clipboard so
    they can paste it themselves. Scheduling a restore made that a lie: it wiped
    the text a fraction of a second later.
    """

    def test_the_text_stays_on_the_clipboard(self, monkeypatch):
        clip = FakeClipboard({TEXT: "previous"})
        kb = FakeKeyboard(send_fails=True)
        win32con = types.SimpleNamespace(
            CF_UNICODETEXT=TEXT, CF_DIB=8, CF_DIBV5=17, CF_HDROP=15)
        monkeypatch.setitem(sys.modules, "win32clipboard", clip)
        monkeypatch.setitem(sys.modules, "win32con", win32con)
        monkeypatch.setitem(sys.modules, "keyboard", kb)
        monkeypatch.setattr(paste.time, "sleep", lambda _s: None)

        assert paste.paste_text("kal meeting hai", {}) is False
        assert clip.contents == {TEXT: "kal meeting hai"}, (
            "the text the user was told to paste by hand is not there")


class TestModifierHandling:
    """
    A combo hotkey can still be physically held when Ctrl+V is sent, turning it
    into Ctrl+Shift+V. Only the hotkey's own modifiers may be released: a held
    Shift is how a user extends a selection, and for a modifier-based hotkey a
    forced release is itself a key-up, which ends the dictation in progress.
    """

    def test_the_hotkeys_own_modifiers_are_released(self, monkeypatch):
        clip = FakeClipboard()
        kb = FakeKeyboard(pressed={"ctrl", "shift"})
        win32con = types.SimpleNamespace(
            CF_UNICODETEXT=TEXT, CF_DIB=8, CF_DIBV5=17, CF_HDROP=15)
        monkeypatch.setitem(sys.modules, "win32clipboard", clip)
        monkeypatch.setitem(sys.modules, "win32con", win32con)
        monkeypatch.setitem(sys.modules, "keyboard", kb)
        monkeypatch.setattr(paste.time, "sleep", lambda _s: None)
        monkeypatch.setattr(paste, "_foreground_looks_elevated", lambda: False)

        paste.paste_text("hi", {}, hotkey_mods=["ctrl", "shift"])
        assert set(kb.released) == {"ctrl", "shift"}

    def test_modifiers_the_hotkey_does_not_use_are_left_alone(self, monkeypatch):
        clip = FakeClipboard()
        kb = FakeKeyboard(pressed={"shift", "alt", "windows"})
        win32con = types.SimpleNamespace(
            CF_UNICODETEXT=TEXT, CF_DIB=8, CF_DIBV5=17, CF_HDROP=15)
        monkeypatch.setitem(sys.modules, "win32clipboard", clip)
        monkeypatch.setitem(sys.modules, "win32con", win32con)
        monkeypatch.setitem(sys.modules, "keyboard", kb)
        monkeypatch.setattr(paste.time, "sleep", lambda _s: None)
        monkeypatch.setattr(paste, "_foreground_looks_elevated", lambda: False)

        # Caps Lock is the default hotkey and has no modifiers at all.
        paste.paste_text("hi", {}, hotkey_mods=[])
        assert kb.released == [], (
            "released a modifier the user was holding for their own reasons")


class TestTheSequenceLockIsAlwaysReleased:
    """
    The lock is handed to the restore worker rather than released by the caller, so
    every early return has to release it instead. A leak here would make the next
    dictation wait _LOCK_TIMEOUT and then type instead of pasting.
    """

    def test_after_a_successful_paste(self, wired):
        paste.paste_text("hi", {})
        assert paste._sequence_lock.acquire(blocking=False)
        paste._sequence_lock.release()

    def test_after_a_failed_snapshot(self, monkeypatch):
        clip = FakeClipboard({TEXT: "x"}, locked=True)
        kb = FakeKeyboard()
        win32con = types.SimpleNamespace(
            CF_UNICODETEXT=TEXT, CF_DIB=8, CF_DIBV5=17, CF_HDROP=15)
        monkeypatch.setitem(sys.modules, "win32clipboard", clip)
        monkeypatch.setitem(sys.modules, "win32con", win32con)
        monkeypatch.setitem(sys.modules, "keyboard", kb)
        monkeypatch.setattr(paste.time, "sleep", lambda _s: None)

        paste.paste_text("hi", {})
        assert paste._sequence_lock.acquire(blocking=False)
        paste._sequence_lock.release()

    def test_after_a_failed_ctrl_v(self, monkeypatch):
        clip = FakeClipboard()
        kb = FakeKeyboard(send_fails=True)
        win32con = types.SimpleNamespace(
            CF_UNICODETEXT=TEXT, CF_DIB=8, CF_DIBV5=17, CF_HDROP=15)
        monkeypatch.setitem(sys.modules, "win32clipboard", clip)
        monkeypatch.setitem(sys.modules, "win32con", win32con)
        monkeypatch.setitem(sys.modules, "keyboard", kb)
        monkeypatch.setattr(paste.time, "sleep", lambda _s: None)

        paste.paste_text("hi", {})
        assert paste._sequence_lock.acquire(blocking=False)
        paste._sequence_lock.release()


class TestTypingFallbackGuards:
    def test_a_very_long_dictation_is_truncated_rather_than_held(self, monkeypatch):
        kb = FakeKeyboard()
        monkeypatch.setitem(sys.modules, "keyboard", kb)
        assert paste._type_fallback("x" * (paste._MAX_TYPED_CHARS + 500)) is True
        assert len(kb.written[0]) == paste._MAX_TYPED_CHARS
