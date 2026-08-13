"""Caps Lock must still work as Caps Lock.

Reported symptom: "i holded caps lock key but its blinking, and even i just
clicked and caps lock is not getting on ... my caps lock key as well isnt
working". The hook swallowed every press unconditionally, so binding the key
removed it from the system for as long as the app ran.

Two things are verified: a press shorter than the threshold is handed back so the
key toggles, and a longer press dictates without touching the toggle.

The injected keystroke must come from keybd_event with a REAL scan code. The
keyboard package flags its own send()/press() events and its hook skips them, so
using that API here would silently test nothing - which it did on the first
attempt. And bScan=0 makes the package fall back to -vk, which does not match
the scan code the suppression hook is registered under.
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

    These tests inject real keystrokes and then check what the OS did with them,
    which is not instantaneous: the replay happens on a worker thread after a
    grace period, and the whole suite runs on two cores alongside tests that open
    Tk windows. A fixed sleep long enough to be reliable there is a guess, and the
    guess failed intermittently. Waiting for the condition asserts exactly the same
    thing without the guess.

    The timeout is generous on purpose. It is not a performance assertion - these
    tests are about whether Caps Lock still works, not how fast. A tight deadline
    turns a slow machine into a red build: this suite ran in 47 s early in a session
    and 310 s at the end of one, on the same two cores, and a 3 s deadline started
    failing at the slow end while the behaviour was unchanged.
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
        """
        The replayed keystroke can come back through our own hook. If it were
        mistaken for a real press, _held would stick True and every later
        dictation would be ignored as auto-repeat until restart.
        """
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
    """
    Suppressing a key means the app has to hand back the taps it swallows, or
    binding Caps Lock removes Caps Lock from the machine. The replay guard exists
    so the app does not then mistake its own injected tap for a real keypress.

    Driven directly rather than by injecting keystrokes, because the guard's
    semantics are what matter here and injection is what makes the tests above
    slow and desktop-dependent.
    Driven directly rather than by injecting keystrokes: the integration tests
    above inject, which makes them sensitive to everything else happening on the
    desktop, and timing logic is exactly what a busy desktop tests least reliably.
    """

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
        """
        The guard passes our own events to the app and swallows nothing else. A
        guard that consumed too many would eat the user's next real press; one that
        consumed too few would let a replayed tap start a dictation, which is the
        failure mode that killed two attempts to shorten this window - see the
        comment on _REPLAY_GRACE in hotkey.py.
        """
        hk = self._listener()
        hk._replay_pending = 2
        hk._replay_deadline = time.monotonic() + 10
        consumed = [hk._consume_replay() for _ in range(5)]
        assert consumed == [True, True, False, False, False]
        assert hk._replay_pending == 0
