"""
Global hold-to-talk hotkey listener.

Accepts a single key ("scroll lock", "f13") or a combo ("ctrl+shift+space").

keyboard.add_hotkey() fires once on press and gives no release event, so it
cannot express hold-to-talk. Instead the trigger key - the last element of the
combo - is bound on its own and the modifier state is checked here. This also
works around on_press_key() rejecting anything but a single key name.
"""

import ctypes
import queue
import time
import logging
import threading

log = logging.getLogger("casper.hotkey")

try:
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
    _user32.GetAsyncKeyState.restype = ctypes.c_short
    _user32.MapVirtualKeyW.restype = ctypes.c_uint
except Exception:      # pragma: no cover - non-Windows
    _user32 = None

# Virtual-key codes for the keys usable as a push-to-talk trigger. MapVirtualKey
# cannot translate the 0xE0-prefixed scan codes the keyboard library reports - it
# maps scroll lock's 0xE046 to VK_CANCEL - so the common ones are listed here.
_VK_TABLE = {
    "scroll lock": 0x91, "pause": 0x13, "caps lock": 0x14, "num lock": 0x90,
    "space": 0x20, "tab": 0x09, "enter": 0x0D, "backspace": 0x08,
    "insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23,
    "page up": 0x21, "page down": 0x22, "escape": 0x1B,
    "ctrl": 0x11, "shift": 0x10, "alt": 0x12, "windows": 0x5B,
    "right ctrl": 0xA3, "right shift": 0xA1, "right alt": 0xA5,
}
for _i in range(1, 25):
    _VK_TABLE[f"f{_i}"] = 0x6F + _i          # f1 = 0x70 ... f24 = 0x87


# Keys whose entry above names one side only. VK_CONTROL, VK_SHIFT and VK_MENU
# each report either side, but there is no combined code for Windows - only
# VK_LWIN and VK_RWIN - so the right key would otherwise always read as up.
_VK_EITHER_SIDE = {0x5B: (0x5B, 0x5C)}


def _physically_down(vk: int) -> bool:
    """
    True if the key is physically held, straight from the OS.

    Not keyboard.is_pressed(): that reads the library's own bookkeeping, which is
    what goes stale when a KEY-UP is dropped.
    """
    if not _user32 or not vk:
        return False
    return any(bool(_user32.GetAsyncKeyState(code) & 0x8000)
               for code in _VK_EITHER_SIDE.get(vk, (vk,)))

# Normalise the names people actually type
ALIASES = {
    "control": "ctrl",
    "ctl": "ctrl",
    "option": "alt",
    "opt": "alt",
    "cmd": "windows",
    "win": "windows",
    "super": "windows",
    "meta": "windows",
    "esc": "escape",
    "scrolllock": "scroll lock",
    "scroll_lock": "scroll lock",
    "capslock": "caps lock",
    "numlock": "num lock",
}

MODIFIERS = {"ctrl", "shift", "alt", "windows"}

FALLBACK_HOTKEY = "caps lock"

# Seconds a replayed keystroke may take to arrive back through our own hook, if it
# arrives at all. Kept short: within this window the guard cannot tell an injected
# event from a real keypress, so a genuine press here is swallowed and the
# dictation does not start. The user presses again, which is the better failure -
# shortening the window instead lets the app read its own replayed tap as a press
# and start recording unasked.
_REPLAY_GRACE = 0.12


def normalise(name: str) -> str:
    n = name.strip().lower()
    return ALIASES.get(n.replace(" ", ""), ALIASES.get(n, n))


def parse_hotkey(spec: str):
    """'ctrl+shift+space' -> (['ctrl', 'shift'], 'space')"""
    parts = [normalise(p) for p in str(spec).split("+") if p.strip()]
    if not parts:
        return [], FALLBACK_HOTKEY
    return parts[:-1], parts[-1]


class HotkeyListener:
    def __init__(self, cfg: dict, on_press, on_release):
        self.cfg = cfg
        self.on_press = on_press
        self.on_release = on_release

        self.hotkey = str(cfg.get("hotkey", FALLBACK_HOTKEY))
        self.suppress = bool(cfg.get("suppress_hotkey", True))
        self.min_hold = float(cfg.get("min_hold_seconds", 0.25))
        self.max_hold = float(cfg.get("max_hold_seconds", 120))

        self.mods, self.trigger = parse_hotkey(self.hotkey)

        self._held = False
        self._lock = threading.Lock()
        self._down_at = 0.0
        self._kb = None

        # Windows delivers key events to a low-level hook one at a time, so a
        # blocking callback drops whatever arrives meanwhile - including the KEY-UP
        # that ends a hold. Callbacks only update state and enqueue; one worker
        # thread runs the real handlers in order.
        self._events: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._trigger_vk = 0

        # Suppressing a key takes over its normal job, so Caps Lock stops
        # toggling. A tap too short to be a dictation is replayed to give it back.
        #
        # That replay must be recognised if it returns through our own hook. The
        # keyboard package usually hides its injected events via a global
        # is_replaying flag, but the flag clears when SendInput returns while the
        # callback arrives on the listener thread, so under load it can slip
        # through. Counted exactly rather than timed: a miscount costs one ignored
        # press, whereas mistaking a replay for a real press leaves _held stuck
        # True and breaks every dictation until restart.
        self._replay_lock = threading.Lock()
        self._replay_pending = 0
        self._replay_deadline = 0.0

        # Set when the watchdog forces a release while the key still appears held.
        # Auto-repeat keeps delivering KEY-DOWN in that state, and each one would
        # read as a fresh press, looping dictations for as long as the key is
        # down. Cleared by the next real KEY-UP.
        self._ignore_until_release = False

    # -- validation ----------------------------------------------------

    def _validate(self, kb) -> bool:
        """Check every key name resolves to a scan code."""
        for name in [self.trigger, *self.mods]:
            try:
                kb.key_to_scan_codes(name)
            except Exception as e:
                log.error(
                    f"Hotkey {self.hotkey!r} is invalid: unknown key {name!r} ({e}). "
                    f"See https://github.com/boppreh/keyboard#api for valid names."
                )
                return False
        return True

    # -- main loop -----------------------------------------------------

    def run(self):
        """Block forever processing key events. Call from a daemon thread."""
        try:
            import keyboard as kb
        except ImportError:
            log.error("'keyboard' package not installed. Run: pip install keyboard")
            return

        self._kb = kb

        if not self._validate(kb):
            log.warning(
                f"Falling back to hotkey [{FALLBACK_HOTKEY}] - run "
                f"pick_hotkey.py to choose a key your keyboard actually has"
            )
            self.hotkey = FALLBACK_HOTKEY
            self.mods, self.trigger = parse_hotkey(FALLBACK_HOTKEY)
            if not self._validate(kb):
                log.error("Fallback hotkey also failed to bind; hotkey disabled.")
                return

        combo = "+".join([*self.mods, self.trigger])
        log.info(
            f"Hotkey listener active - hold [{combo}] to dictate "
            f"(suppress={self.suppress})"
        )

        self._worker = threading.Thread(
            target=self._drain, daemon=True, name="hotkey-worker"
        )
        self._worker.start()

        self._trigger_vk = self._resolve_trigger_vk()
        threading.Thread(
            target=self._watchdog, daemon=True, name="hotkey-watchdog"
        ).start()

        try:
            # Only the trigger key is suppressed; suppressing modifiers would
            # break every other shortcut on the system. The returned handles are
            # dropped because stop() uses unhook_all(): removing hooks one at a
            # time can miss one, and a key left swallowed after quitting is worse
            # than being imprecise about hooks nothing else here installs.
            kb.on_press_key(self.trigger, self._trigger_down,
                            suppress=self.suppress)
            kb.on_release_key(self.trigger, self._trigger_up,
                              suppress=self.suppress)
            # If the user lets go of Ctrl before Space, that's still a release.
            for m in self.mods:
                kb.on_release_key(m, self._modifier_up, suppress=False)
        except Exception as e:
            log.exception(f"Failed to bind hotkey [{combo}]: {e}")
            return

        try:
            kb.wait()
        except Exception as e:
            log.exception(f"Hotkey listener stopped: {e}")

    # -- event handlers ------------------------------------------------

    def _mods_satisfied(self) -> bool:
        if not self.mods:
            return True
        try:
            return all(self._kb.is_pressed(m) for m in self.mods)
        except Exception:
            return False

    # These run inside the Windows hook. Keep them at microsecond cost: no I/O, no
    # audio, no locks held across slow work.
    #
    # The return value decides suppression - keyboard's listener swallows the key
    # on a falsy result and passes it on for True. It has to stay conditional:
    # with ctrl+shift+space the trigger is "space", so returning falsy
    # unconditionally would eat the spacebar system-wide.

    _PASS = True      # let the keystroke reach the focused app
    _EAT = False      # Casper Flow consumed it

    def _consume_replay(self) -> bool:
        """
        True if this event is one we injected ourselves.

        Consumes one expected event, so exactly the keystrokes we sent are let
        through. The deadline stops a replay that never arrived from leaving the
        guard armed indefinitely.
        """
        with self._replay_lock:
            if self._replay_pending <= 0:
                return False
            if time.monotonic() > self._replay_deadline:
                self._replay_pending = 0
                return False
            self._replay_pending -= 1
            return True

    def _trigger_down(self, event):
        if log.isEnabledFor(logging.DEBUG):
            log.debug(f"hook DOWN held={self._held} "
                      f"replay_pending={self._replay_pending}")
        if self._consume_replay():
            return self._PASS         # our own injected tap - let it do its job
        with self._lock:
            if self._ignore_until_release:
                return self._EAT      # auto-repeat after a forced release
            if self._held:
                return self._EAT      # auto-repeat of a hold we own
            if not self._mods_satisfied():
                return self._PASS     # e.g. plain space: not our hotkey
            self._held = True
            self._down_at = time.monotonic()
        self._events.put(("press", None))
        return self._EAT

    def _trigger_up(self, event):
        if log.isEnabledFor(logging.DEBUG):
            log.debug(f"hook UP   held={self._held} "
                      f"replay_pending={self._replay_pending}")
        if self._consume_replay():
            return self._PASS
        with self._lock:
            latched = self._ignore_until_release
            self._ignore_until_release = False
        if latched:
            # Swallowed because its key-down was too: passing it through would be
            # an unpaired key-up.
            log.debug("Trigger released; auto-repeat suppression cleared")
            return self._EAT
        # Swallow the release only if we were the ones holding it.
        return self._EAT if self._end_hold() else self._PASS

    def _replay_tap(self):
        """
        Re-send a tap that was swallowed but not used.

        Without this, a suppressed binding removes the key from the system for as
        long as Casper Flow runs. Runs on the worker thread, never in the hook.
        """
        if not self.suppress or not self._kb:
            return
        # Arm the guard *before* sending, so the hook is already prepared if the
        # injected events come back to us. One key-down plus one key-up.
        with self._replay_lock:
            self._replay_pending = 2
            self._replay_deadline = time.monotonic() + _REPLAY_GRACE
        try:
            self._kb.send(self.trigger)
            log.debug(f"Replayed swallowed tap of {self.trigger!r}")
        except Exception as e:
            log.debug(f"Could not replay {self.trigger!r}: {e}")
        finally:
            # Disarmed explicitly rather than left to lapse: the keyboard package
            # usually hides its injected events, so nothing consumes the count and
            # a guard left armed swallows the next real press.
            #
            # On its own thread, not the event worker. The worker runs on_press,
            # which opens the recording, so sleeping here delayed capture by up to
            # _REPLAY_GRACE and clipped the first word of anyone who tapped the key
            # and then immediately held it.
            threading.Thread(target=self._disarm_replay, daemon=True,
                             name="replay-disarm").start()

    def _disarm_replay(self):
        """Take the replay guard down once the injected events can no longer arrive."""
        time.sleep(_REPLAY_GRACE)
        with self._replay_lock:
            self._replay_pending = 0

    def _modifier_up(self, event):
        # Releasing a required modifier ends the hold too. Modifier hooks are
        # never suppressing, so the return value is ignored here.
        self._end_hold()
        return self._PASS

    def _end_hold(self) -> bool:
        """End an active hold. Returns True if there was one."""
        with self._lock:
            if not self._held:
                return False
            held_for = time.monotonic() - self._down_at
            self._held = False
        self._events.put(("release", held_for))
        return True

    # -- stuck-key recovery -------------------------------------------

    def _resolve_trigger_vk(self) -> int:
        vk = _VK_TABLE.get(self.trigger)
        if vk is None and len(self.trigger) == 1 and self.trigger.isalnum():
            vk = ord(self.trigger.upper())
        if vk is None and _user32 and self._kb:
            try:
                # Mask off the 0xE0 extended prefix before mapping.
                scan = self._kb.key_to_scan_codes(self.trigger)[0] & 0xFF
                vk = _user32.MapVirtualKeyW(scan, 1) or None
            except Exception:
                vk = None
        return vk or 0

    def _watchdog(self):
        """
        Recover if a KEY-UP never arrives.

        Windows delivers events to a low-level hook one at a time, so a slow
        handler can cause a release to be dropped, leaving _held True forever:
        every later press reads as auto-repeat and the mic never stops. Insurance
        behind the event queue.

        Suppression changes what can be observed:
          * suppress off -> GetAsyncKeyState tracks the hold, so a dropped release
            is caught within ~180 ms.
          * suppress on  -> our hook swallows the keydown before it reaches the OS
            state table, so GetAsyncKeyState always reads up. Falls back to a
            generous ceiling that cannot cut a real dictation short.
        """
        # Which keys can we actually observe?
        #   * modifiers are never suppressed, so for a combo we can always
        #     watch them - this is the precise path and it works even when the
        #     trigger key is being swallowed.
        #   * a lone trigger is only observable when suppression is off.
        mod_vks = [vk for vk in (_VK_TABLE.get(m) for m in self.mods) if vk]
        watch_vks: list[int] = []
        if mod_vks and len(mod_vks) == len(self.mods):
            watch_vks = mod_vks
            log.info("Stuck-key recovery: OS modifier state (precise)")
        elif self._trigger_vk and not self.suppress:
            watch_vks = [self._trigger_vk]
            log.info("Stuck-key recovery: OS key state (precise)")
        else:
            why = "suppression hides the key from the OS" if self.suppress \
                else f"no virtual-key code for {self.trigger!r}"
            log.info(f"Stuck-key recovery: {self.max_hold:.0f}s ceiling ({why})")

        misses = 0
        while True:
            time.sleep(0.06)
            if not self._held:
                misses = 0
                continue

            if watch_vks:
                if all(_physically_down(vk) for vk in watch_vks):
                    misses = 0
                    continue
                misses += 1
                if misses >= 3:          # ~180 ms of confirmed release
                    misses = 0
                    log.warning(
                        "Hotkey release was never delivered (the OS reports the "
                        "keys released) - recovering and ending the hold"
                    )
                    self._end_hold()
            else:
                held_for = time.monotonic() - self._down_at
                if held_for > self.max_hold:
                    log.warning(
                        f"Hotkey has been held {held_for:.0f}s "
                        f"(> max_hold_seconds={self.max_hold:.0f}) - forcing "
                        f"release; a KEY-UP was probably lost"
                    )
                    # Set first, so no auto-repeat KEY-DOWN can slip in between and
                    # read as a new press.
                    with self._lock:
                        self._ignore_until_release = True
                    self._end_hold()

    # -- worker --------------------------------------------------------

    def _drain(self):
        """Run the real handlers off the hook thread, strictly in order."""
        while True:
            try:
                kind, payload = self._events.get()
            except Exception:
                return
            try:
                if kind == "press":
                    self.on_press()
                elif kind == "release":
                    held_for = payload
                    if held_for < self.min_hold:
                        log.info(
                            f"Hold too short ({held_for:.2f}s < {self.min_hold}s)"
                            f" - discarding and giving the key back"
                        )
                        self.on_release(discard=True)
                        # It was a tap, not dictation, so it should do whatever
                        # the key normally does.
                        self._replay_tap()
                    else:
                        self.on_release(discard=False)
            except Exception as e:
                log.exception(f"{kind} handler error: {e}")

    # -- teardown ------------------------------------------------------

    def stop(self):
        """Remove all keyboard hooks (used on quit so no key stays suppressed)."""
        if not self._kb:
            return
        try:
            self._kb.unhook_all()
            log.info("Keyboard hooks removed")
        except Exception as e:
            log.warning(f"Could not unhook keyboard: {e}")
