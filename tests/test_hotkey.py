"""Caps Lock must still work as Caps Lock.

A press shorter than the threshold is handed back so the key toggles; a longer
press dictates without touching the toggle.

Keystrokes come from keybd_event with a real scan code. The keyboard package's
hook skips its own send() events, and bScan=0 misses the hook's scan code.
"""

import ctypes
import threading
import time

import pytest

from conftest import needs_app_not_running, needs_desktop
from hotkey import HotkeyListener, parse_hotkey

_user32 = ctypes.WinDLL("user32", use_last_error=True)
VK_CAPITAL = 0x14
KEYEVENTF_KEYUP = 0x0002

THRESHOLD = 0.4          # short, to keep the test quick
SETTLE = THRESHOLD + 0.9


def caps_on() -> bool:
    return bool(_user32.GetKeyState(VK_CAPITAL) & 1)


def wait_until(predicate, timeout: float = 10.0, poll: float = 0.05) -> bool:
    """
    True as soon as `predicate()` holds, or False at the deadline.

    The replay lands on a worker thread after a grace period, so a fixed sleep is
    a guess. The generous timeout is not a performance assertion: the same suite
    has run in 47 s and in 310 s on these two cores.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(poll)
    return predicate()


def press_caps(seconds: float):
    scan = _user32.MapVirtualKeyW(VK_CAPITAL, 0)
    _user32.keybd_event(VK_CAPITAL, scan, 0, 0)
    time.sleep(seconds)
    _user32.keybd_event(VK_CAPITAL, scan, KEYEVENTF_KEYUP, 0)


class TestHotkeyParsing:
    """Pure, so it runs everywhere including CI."""

    def test_single_key_has_no_modifiers(self):
        assert parse_hotkey("caps lock") == ([], "caps lock")

    def test_combo_splits_into_modifiers_and_trigger(self):
        assert parse_hotkey("ctrl+shift+space") == (["ctrl", "shift"], "space")

    def test_aliases_are_normalised(self):
        assert parse_hotkey("capslock") == ([], "caps lock")
        assert parse_hotkey("control+space") == (["ctrl"], "space")

    def test_empty_spec_falls_back(self):
        mods, trigger = parse_hotkey("")
        assert trigger == "caps lock"
        assert mods == []


@needs_desktop
@needs_app_not_running
class TestCapsLockSurvives:
    @pytest.fixture
    def listener(self):
        events: list[str] = []
        hk = HotkeyListener(
            {"hotkey": "caps lock", "suppress_hotkey": True,
             "min_hold_seconds": THRESHOLD, "max_hold_seconds": 120},
            on_press=lambda: events.append("press"),
            on_release=lambda discard=False: events.append(
                "discard" if discard else "dictate"),
        )
        hk.events = events
        threading.Thread(target=hk.run, daemon=True, name="hk-test").start()
        time.sleep(2.0)          # let the hook install

        original = caps_on()
        yield hk

        hk.stop()
        time.sleep(0.3)
        if caps_on() != original:      # never leave the user's key flipped
            import keyboard
            keyboard.send("caps lock")
            time.sleep(0.3)

    def test_short_tap_toggles_caps_lock(self, listener):
        before = caps_on()
        listener.events.clear()
        press_caps(0.08)

        assert wait_until(lambda: caps_on() != before), (
            "a tap did not toggle Caps Lock - the key has been taken away from "
            "the user, which is the reported bug"
        )
        time.sleep(SETTLE)      # a dictation, if one started, would land by now
        assert "dictate" not in listener.events, "a tap started a dictation"

    def test_long_hold_dictates_without_toggling(self, listener):
        before = caps_on()
        listener.events.clear()
        press_caps(THRESHOLD + 0.35)

        assert wait_until(lambda: "dictate" in listener.events), (
            "a long hold did not dictate")
        assert caps_on() == before, "dictation flipped Caps Lock"

    def test_hold_just_under_the_threshold_is_not_dictation(self, listener):
        """The threshold is the whole point of the setting."""
        before = caps_on()
        listener.events.clear()
        press_caps(THRESHOLD * 0.5)

        assert wait_until(lambda: caps_on() != before), (
            "a sub-threshold press must still toggle")
        time.sleep(SETTLE)
        assert "dictate" not in listener.events

    def test_repeated_taps_do_not_wedge_the_listener(self, listener):
        """A replayed keystroke read as a real press leaves _held stuck True, so
        every later dictation is ignored as auto-repeat."""
        for _ in range(3):
            press_caps(0.08)
            time.sleep(SETTLE)

        listener.events.clear()
        press_caps(THRESHOLD + 0.35)
        assert wait_until(lambda: "dictate" in listener.events), (
            "dictation stopped working after repeated taps - the replay guard "
            "leaked and left the listener wedged"
        )
        assert not listener._held, "_held stuck True after the hold ended"


class TestReplayGuard:
    """The app hands back the taps it swallows, and must not read its own injected
    tap as a real press. Driven directly, since a busy desktop is the least
    reliable way to test timing logic."""

    @staticmethod
    def _listener():
        return HotkeyListener(
            {"hotkey": "caps lock", "min_hold_seconds": 0.0,
             "suppress_hotkey": True},
            on_press=lambda: None,
            on_release=lambda held: None,
        )

    def test_the_guard_expects_one_down_and_one_up(self):
        hk = self._listener()
        hk._replay_pending = 2
        hk._replay_deadline = time.monotonic() + 10
        assert hk._consume_replay() is True
        assert hk._consume_replay() is True
        assert hk._consume_replay() is False, "consumed a third event"

    def test_the_guard_expires_so_it_cannot_stay_armed(self):
        """A replay that never arrives must not eat the next real press."""
        hk = self._listener()
        hk._replay_pending = 2
        hk._replay_deadline = time.monotonic() - 0.001
        assert hk._consume_replay() is False
        assert hk._replay_pending == 0

    def test_exactly_the_events_we_injected_are_let_through(self):
        """Consuming too many eats the user's next real press; too few lets a
        replayed tap start a dictation. See _REPLAY_GRACE in hotkey.py."""
        hk = self._listener()
        hk._replay_pending = 2
        hk._replay_deadline = time.monotonic() + 10
        consumed = [hk._consume_replay() for _ in range(5)]
        assert consumed == [True, True, False, False, False]
        assert hk._replay_pending == 0
