"""
System tray icon and menu (pystray + Pillow).

Menu:
  Casper Flow Enabled     (checkbox)
  ------
  Hotkey: [...]      (informational)
  Backend: ...       (informational)
  ------
  Format as ->       (radio: Plain text / Message / Email)
  ------
  Launch at Login    (checkbox -> HKCU Run key)
  Settings...            (opens the settings window)
  Edit settings.json     (for people who prefer the file)
  View log
  ------
  Quit Casper Flow
"""

import logging
import os
import subprocess
import sys
import threading
import winreg
from pathlib import Path

from config import api_key_for

log = logging.getLogger("casper.tray")

from paths import DATA_DIR, FROZEN, icon_file, resource_file

ROOT = DATA_DIR
SETTINGS_FILE = ROOT / "settings.json"
LOG_FILE = ROOT / "casper.log"
APP_NAME = "Casper Flow"
STARTUP_REG_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"

# Names this application used before it was called Casper Flow. A Run key written
# under an old name keeps launching the app at login, but nothing in the current
# product can see it: the tray toggle reads APP_NAME and reports "off" while the
# app is in fact starting itself every morning, and the uninstaller deletes
# APP_NAME and leaves the old value behind for ever.
#
# Found on the development machine, which still had a "VoxPad" entry pointing at
# venv\Scripts\pythonw.exe main.py.
#
# One spelling is enough: registry value names are case-insensitive, verified by
# looking up all three casings and getting the same single value back.
LEGACY_APP_NAMES = ("VoxPad",)


def _launcher_command() -> str:
    """
    Build the command written to the Run key.

    Uses pythonw.exe so logging in at boot doesn't pop a console window that
    stays open for the life of the app.
    """
    if FROZEN:
        # sys.executable *is* the app. Passing a script path would be nonsense.
        return f'"{Path(sys.executable)}"'

    exe = Path(sys.executable)
    if exe.name.lower() == "python.exe":
        pythonw = exe.with_name("pythonw.exe")
        if pythonw.exists():
            exe = pythonw
    return f'"{exe}" "{Path(__file__).resolve().parent / "main.py"}"'


# Shipped with the build, so it comes from the bundle when frozen. A copy dropped
# beside the executable wins, which makes replacing the icon possible without a
# rebuild.
ICON_FILE = icon_file()

def _tray_icon_px() -> int:
    """
    The pixel size Windows wants for a notification icon.

    Asked rather than assumed, so the frame handed over needs no rescaling. The
    previous code resampled the 256 px frame down to 64 and let Windows shrink
    that again: two resamples, and the frames drawn specifically for small sizes
    were never used. On a 125% display that delivered a three-bar mark crushed
    into 20 px.

    Process DPI awareness is deliberately NOT changed here. It would make this
    return the scaled value, but it is a process-wide setting that also changes
    how window coordinates are interpreted - and the overlay positions itself
    from screen metrics. A slightly soft tray icon is a fair trade for not
    moving the recording indicator.
    """
    try:
        import ctypes
        # GetSystemMetrics(SM_CXSMICON) returns 16 in a DPI-unaware process even
        # on a scaled display, and Windows then enlarges whatever it is given.
        # GetDpiForSystem reports the real system DPI regardless of this
        # process's awareness, so the scaled size can be derived without
        # changing any process-wide state. 96 DPI is 100%, 120 is 125%, 144 is
        # 150%; the base small-icon size is 16 px by definition.
        dpi = int(ctypes.windll.user32.GetDpiForSystem())
        if not 72 <= dpi <= 480:
            raise ValueError(f"implausible system DPI {dpi}")
        want = round(16 * dpi / 96)
        return max(16, min(64, want))
    except Exception:
        try:
            import ctypes
            SM_CXSMICON = 49
            n = int(ctypes.windll.user32.GetSystemMetrics(SM_CXSMICON))
            return n if 12 <= n <= 64 else 16
        except Exception:
            return 16


def _make_icon(active: bool = True):
    """
    The tray icon, as a PIL image.

    Prefers assets/casper.ico, which is the same mark used by the executable, the
    installer and the website, so all four are recognisably one product. Falls
    back to drawing a microphone if the asset is missing, because a tray app with
    no icon is invisible and therefore unquittable.

    When disabled the mark is desaturated rather than swapped for a different
    shape: the tray should read as "same app, currently off".
    """
    from PIL import Image, ImageDraw, ImageEnhance

    if ICON_FILE.exists():
        try:
            img = Image.open(ICON_FILE)
            want = _tray_icon_px()
            try:
                available = sorted({w for w, _h in img.ico.sizes()})
                # Exact frame if we drew one, otherwise the next size up so any
                # scaling Windows does is a reduction, never an enlargement.
                pick = want if want in available else next(
                    (s for s in available if s >= want), available[-1])
                img = img.ico.getimage((pick, pick))
                log.debug(f"Tray icon: Windows asked for {want}px, "
                          f"using the {pick}px frame")
            except Exception:
                img = img.resize((want, want), Image.LANCZOS)
            img = img.convert("RGBA")
            if not active:
                img = ImageEnhance.Color(img).enhance(0.15)
                img = ImageEnhance.Brightness(img).enhance(0.75)
            return img
        except Exception as e:
            log.debug(f"Could not load {ICON_FILE.name} ({e}); drawing a fallback")

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bg = "#b14e2a" if active else "#6c757d"

    d.ellipse([0, 0, size - 1, size - 1], fill=bg)
    d.rounded_rectangle([23, 13, 41, 35], radius=9, fill="white")
    d.arc([15, 25, 49, 49], start=0, end=180, fill="white", width=3)
    d.line([32, 49, 32, 55], fill="white", width=3)
    d.line([24, 55, 40, 55], fill="white", width=3)
    return img


class TrayApp:
    def __init__(self, cfg: dict, hotkey_listener, on_quit=None):
        self.cfg = cfg
        self.hotkey_listener = hotkey_listener
        self.on_quit = on_quit
        self.enabled = True
        self._icon = None

    # -- launch at login ----------------------------------------------

    def _is_launch_at_login(self) -> bool:
        # Done here because this is the first thing the menu asks, so the answer
        # is correct the first time it is shown rather than after a restart.
        self._migrate_legacy_autostart()
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY) as key:
                winreg.QueryValueEx(key, APP_NAME)
            return True
        except FileNotFoundError:
            return False
        except Exception as e:
            log.debug(f"Could not read Run key: {e}")
            return False

    @staticmethod
    def _migrate_legacy_autostart() -> str | None:
        """
        Move a Run key written under an old product name onto the current one.

        Migrated rather than deleted: the entry means the user once asked for
        launch-at-login, and silently switching that off is as wrong as silently
        leaving an invisible one behind. So if the old name is present and the
        current one is not, the current one is written with today's command.

        Returns the name it migrated, or None. Never raises - a registry quirk
        must not stop the tray from starting.
        """
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY, 0,
                                winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE) as key:
                current = None
                try:
                    current, _ = winreg.QueryValueEx(key, APP_NAME)
                except FileNotFoundError:
                    pass

                migrated = None
                for legacy in LEGACY_APP_NAMES:
                    try:
                        winreg.QueryValueEx(key, legacy)
                    except FileNotFoundError:
                        continue
                    winreg.DeleteValue(key, legacy)
                    migrated = legacy
                    log.info(f"Removed legacy startup entry {legacy!r}")

                if migrated and not current:
                    cmd = _launcher_command()
                    winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
                    log.info(
                        f"Migrated launch-at-login from {migrated!r} to "
                        f"{APP_NAME!r}: {cmd}"
                    )
                return migrated
        except Exception as e:
            log.debug(f"Legacy startup migration skipped: {e}")
            return None

    def _set_launch_at_login(self, enable: bool):
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY, 0, winreg.KEY_SET_VALUE
            ) as key:
                if enable:
                    cmd = _launcher_command()
                    winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
                    log.info(f"Launch at login enabled: {cmd}")
                else:
                    try:
                        winreg.DeleteValue(key, APP_NAME)
                        log.info("Launch at login disabled")
                    except FileNotFoundError:
                        pass
        except Exception as e:
            log.error(f"Registry error: {e}")

    # -- menu callbacks -----------------------------------------------

    def _toggle_enabled(self, icon, item):
        self.enabled = not self.enabled
        log.info(f"Casper Flow {'enabled' if self.enabled else 'disabled'}")
        try:
            icon.icon = _make_icon(self.enabled)
        except Exception:
            pass
        icon.update_menu()

    def _toggle_login(self, icon, item):
        target = not self._is_launch_at_login()
        self._set_launch_at_login(target)
        self.cfg["launch_at_login"] = target
        icon.update_menu()

    # -- formatting ----------------------------------------------------

    def _formatting_available(self) -> bool:
        """
        Whether a backend that can actually write text is configured.

        The menu entries are shown but disabled otherwise, rather than hidden.
        A user who has read about the feature and cannot find it will assume it
        is missing; a greyed-out entry says it exists and something is needed.
        """
        return str(self.cfg.get("llm_backend", "rules")).lower() != "rules"

    def _make_format_setter(self, value: str):
        def setter(icon, item):
            self.cfg["format_mode"] = value
            log.info(f"Format mode set to {value!r}")
            # Persisted, so the choice survives a restart - the same expectation
            # the launch-at-login toggle sets.
            try:
                from config import save_config
                save_config(self.cfg)
            except Exception as e:
                log.warning(f"Could not persist format_mode: {e}")
            icon.update_menu()
        return setter

    def _make_format_check(self, value: str):
        return lambda _item: str(self.cfg.get("format_mode", "plain")) == value

    def _open_settings_window(self, icon, item):
        """
        Open the settings window.

        On its own thread with its own Tk root: pystray owns the main thread, and
        the overlay already runs a Tk loop, so blocking either would freeze the
        tray icon or the recording indicator.
        """
        def worker():
            try:
                from settings_ui import open_settings
                open_settings()
            except Exception as e:
                log.exception(f"Could not open the settings window: {e}")
                self.notify("Settings window failed to open - see the log")

        threading.Thread(target=worker, daemon=True,
                         name="settings-window").start()

    def _open_settings(self, icon, item):
        if not SETTINGS_FILE.exists():
            SETTINGS_FILE.write_text("{}", encoding="utf-8")
        self._open(SETTINGS_FILE)

    def _open_log(self, icon, item):
        if LOG_FILE.exists():
            self._open(LOG_FILE)
        else:
            log.info("No log file yet")

    @staticmethod
    def _open(path: Path):
        try:
            os.startfile(str(path))          # respects the user's default editor
        except Exception:
            subprocess.Popen(["notepad.exe", str(path)])

    def _quit(self, icon, item):
        log.info("Quit requested")
        try:
            if self.hotkey_listener:
                self.hotkey_listener.stop()   # release suppressed keys
            if self.on_quit:
                self.on_quit()
        except Exception as e:
            log.warning(f"Cleanup during quit failed: {e}")
        icon.stop()
        # Tk runs its own loop on another thread; _exit is the reliable way out.
        os._exit(0)

    # -- run -----------------------------------------------------------

    def run(self):
        try:
            import pystray
            from pystray import MenuItem as Item, Menu
        except ImportError:
            log.error("pystray not installed. Run: pip install pystray")
            threading.Event().wait()   # keep daemon threads alive
            return

        combo = "+".join(
            [*self.hotkey_listener.mods, self.hotkey_listener.trigger]
        ) if self.hotkey_listener else self.cfg.get("hotkey", "")

        backend = self.cfg.get("transcribe_backend", "local")
        model = (
            self.cfg.get("whisper_model", "small") if backend == "local"
            else self.cfg.get(f"{backend}_whisper_model", "")
        )
        if not self.cfg.get("llm_polish"):
            polish = "off"
        else:
            lb = self.cfg.get("llm_backend", "openai")
            # Surface a missing key here rather than only in the log, otherwise
            # "why is my text not cleaned up?" is invisible from the UI.
            polish = lb if api_key_for(lb, self.cfg) else f"{lb} (no API key - skipped)"

        menu = Menu(
            Item(
                "Casper Flow Enabled",
                self._toggle_enabled,
                checked=lambda _: self.enabled,
                default=True,
            ),
            Menu.SEPARATOR,
            Item(f"Hold [{combo}] to dictate", None, enabled=False),
            Item(f"Transcribe: {backend} ({model})", None, enabled=False),
            Item(f"Polish: {polish}", None, enabled=False),
            Menu.SEPARATOR,
            # Layout is switchable from here because people move between writing
            # a message and writing an email several times an hour, and opening a
            # settings window for that would mean nobody used it.
            Item("Format as", Menu(*[
                Item(
                    label,
                    self._make_format_setter(value),
                    checked=self._make_format_check(value),
                    radio=True,
                    enabled=self._formatting_available(),
                )
                for value, label in (("plain", "Plain text"),
                                     ("message", "Message"),
                                     ("email", "Email"))
            ])),
            Menu.SEPARATOR,
            Item(
                "Launch at Login",
                self._toggle_login,
                checked=lambda _: self._is_launch_at_login(),
            ),
            Item("Settings...", self._open_settings_window),
            Item("Edit settings.json", self._open_settings),
            Item("View log", self._open_log),
            Menu.SEPARATOR,
            Item("Quit Casper Flow", self._quit),
        )

        self._icon = pystray.Icon(
            APP_NAME,
            icon=_make_icon(True),
            title=f"{APP_NAME} - hold [{combo}] to dictate",
            menu=menu,
        )

        log.info("Tray icon running")
        self._icon.run()   # blocks on the main thread

    def notify(self, message: str, title: str = APP_NAME):
        """Best-effort balloon notification (silently ignored if unsupported)."""
        try:
            if self._icon:
                self._icon.notify(message, title)
        except Exception as e:
            log.debug(f"Notification failed: {e}")
