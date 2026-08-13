"""
Casper Flow - system-wide AI dictation for Windows.

Entry point. Wires the tray icon, hotkey listener and status pill to the
record -> transcribe -> polish -> paste pipeline. Threads: main runs the pystray
loop (pystray requires the main thread), pill-tk the tkinter loop, hotkey the
keyboard.wait() hook, plus one pipeline-N worker per dictation.
"""

import ctypes
import sys
import threading
import time
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from paths import DATA_DIR       # noqa: E402

# Beside the executable, not in the frozen bundle an update replaces. paths.py.
ROOT = DATA_DIR

from config import load_config                    # noqa: E402
from tray import TrayApp                          # noqa: E402
from hotkey import HotkeyListener                 # noqa: E402
from recorder import AudioRecorder, sweep_recordings   # noqa: E402
from version import __version__                    # noqa: E402
from transcribe import transcribe, transcribe_array, preload   # noqa: E402
from llm_polish import polish                     # noqa: E402
from corrections import apply_corrections         # noqa: E402
from paste import paste_text                      # noqa: E402
from pill import RecordingPill                    # noqa: E402

# Transcripts can be Devanagari, which the console's default cp1252 cannot
# encode; the stream handler would raise UnicodeEncodeError on every such line.
try:
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_handlers = [logging.FileHandler(ROOT / "casper.log", encoding="utf-8")]
if sys.stdout is not None:          # None under pythonw.exe
    _handlers.append(logging.StreamHandler(sys.stdout))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=_handlers,
)
log = logging.getLogger("casper.main")


class CasperFlow:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.recorder = AudioRecorder(cfg)
        self.pill = RecordingPill(cfg)
        self.pill.set_sources(
            level=lambda: self.recorder.level,
            elapsed=lambda: self.recorder.elapsed,
        )
        self.hotkey = HotkeyListener(cfg, self.on_press, self.on_release)
        self.tray = TrayApp(cfg, self.hotkey, on_quit=self.shutdown)

        self._active = 0
        self._active_lock = threading.Lock()
        self._seq = 0

        # Only the caption style shows text; the others need no preview work.
        self.style_has_no_text = self.pill.style != "caption"

        # One Event per loop, never shared: overlapping dictations must not stop
        # each other.
        self._preview_stop: threading.Event | None = None

        # Gates the overlay once a hold is long enough; capture is already running.
        self._arm_timer: threading.Timer | None = None
        # Guards _arm_timer and _hold_generation across hotkey, timer and release.
        self._arm_lock = threading.Lock()
        self._hold_generation = 0

    # -- hotkey handlers -----------------------------------------------

    def on_press(self):
        if not self.tray.enabled:
            log.info("Hotkey pressed but Casper Flow is disabled - ignoring")
            return

        # The mic opens on a background thread and can take 15 s on a cold or
        # exclusive-mode device. recorder.start() would block and lose the speech.
        if not self.recorder.is_ready:
            log.warning("Hotkey pressed before the microphone finished opening")
            self.pill.show("error")
            threading.Timer(2.0, self.pill.hide).start()
            self.tray.notify(
                "Still starting up - the microphone is not open yet. "
                "Try again in a moment."
            )
            return

        log.info("Hotkey down - starting recording")
        if not self.recorder.start():
            self.pill.show("error")
            threading.Timer(2.0, self.pill.hide).start()
            self.tray.notify(
                "Could not open the microphone. Check Settings > Privacy & "
                "security > Microphone, and that no other app is using it."
            )
            return

        # Only the overlay waits for confirmation; capture started above, because
        # people speak as soon as they press.
        delay = float(self.cfg.get("min_hold_seconds", 0.25))
        if delay <= 0:
            self._on_armed()
            return
        with self._arm_lock:
            timer = threading.Timer(delay, self._on_armed,
                                    args=(self._hold_generation,))
            timer.daemon = True
            self._arm_timer = timer
            timer.start()

    def _on_armed(self, generation: int):
        """
        Hold confirmed as dictation; show it. Runs on the timer thread.
        Timer.cancel() is a no-op once the timer has fired, so the generation
        check under _arm_lock is what stops a release racing this.
        """
        with self._arm_lock:
            if generation != self._hold_generation:
                return      # this timer belongs to a hold that has already ended
            self._arm_timer = None
            if not self.recorder.recording:
                return      # released in the meantime
            log.info("Hold confirmed as dictation")
            self.pill.show("recording")
            self._start_preview()

    def _cancel_arm(self):
        """
        Cancel the arm timer and invalidate arming already in progress. Bumping
        the generation under the lock orders the two paths, so the caller's
        pill.hide() is always last.
        """
        with self._arm_lock:
            self._hold_generation += 1
            timer, self._arm_timer = self._arm_timer, None
        if timer is not None:
            timer.cancel()

    # -- live preview ---------------------------------------------------

    def _start_preview(self):
        """
        Live caption while the user speaks. Display only: pasted text comes from a
        fresh pass over the whole recording. Passes run one at a time and each
        waits for new audio, so work cannot pile up.
        """
        if not self.cfg.get("live_preview", True):
            return
        if self.style_has_no_text:
            return

        # A zero interval would spin this thread against the transcriber.
        interval = max(0.2, float(self.cfg.get("preview_interval_seconds", 1.0)))
        stop = threading.Event()
        self._preview_stop = stop

        def loop():
            last_len = 0
            while not stop.wait(interval):
                audio = self.recorder.snapshot()
                if audio is None or len(audio) <= last_len:
                    continue
                last_len = len(audio)
                try:
                    t0 = time.monotonic()
                    text = transcribe_array(audio, self.cfg)
                    if stop.is_set():
                        return
                    if text:
                        self.pill.set_text(text)
                    log.debug(f"preview {len(audio) / 16000:.1f}s audio in "
                              f"{time.monotonic() - t0:.2f}s")
                except Exception as e:
                    log.debug(f"preview pass failed: {e}")
                    return

        threading.Thread(target=loop, daemon=True, name="preview").start()

    def _stop_preview(self):
        stop, self._preview_stop = self._preview_stop, None
        if stop is not None:
            stop.set()

    def on_release(self, discard: bool = False):
        self._cancel_arm()

        if discard:
            self._stop_preview()
            had_speech = self.recorder.discard()
            self.pill.hide()
            # Silent for a plain tap, but the threshold must be discoverable.
            if had_speech:
                hold = float(self.cfg.get("min_hold_seconds", 2.0))
                log.warning(
                    f"Discarded a dictation that contained speech: the hold was "
                    f"shorter than min_hold_seconds={hold:g}"
                )
                self.tray.notify(
                    f"That was shorter than {hold:g} seconds, so it was ignored. "
                    f"Hold the key for the whole phrase, or lower the hold time "
                    f"in Settings."
                )
            return

        if not self.recorder.recording:
            self._stop_preview()
            self.pill.hide()
            return

        log.info("Hotkey up - stopping recording")
        # Stop preview first: it competes for the same CPU as the final pass.
        self._stop_preview()
        audio_path = self.recorder.stop()

        if audio_path is None:
            log.warning("No usable audio captured")
            self.pill.hide()
            # A muted mic and a dead hotkey look identical to the user.
            if self.recorder.last_failure:
                self.tray.notify(self.recorder.last_failure)
            return

        self.pill.set_state("transcribing")
        self._begin()
        self._seq += 1
        threading.Thread(
            target=self._pipeline,
            args=(audio_path,),
            daemon=True,
            name=f"pipeline-{self._seq}",
        ).start()

    # -- pipeline ------------------------------------------------------

    def _begin(self):
        with self._active_lock:
            self._active += 1

    def _end(self):
        with self._active_lock:
            self._active -= 1
            idle = self._active <= 0
        if idle:
            self.pill.hide()

    def _pipeline(self, audio_path: Path):
        try:
            raw = transcribe(audio_path, self.cfg)
            if not raw or not raw.strip():
                log.warning("Empty transcript - nothing to paste")
                self.tray.notify(
                    "Nothing was recognised. Check the microphone in Settings, "
                    "and hold the key while you speak."
                )
                return

            text = raw
            if self.cfg.get("llm_polish", True):
                text = polish(raw, self.cfg)

            # After polish, so a rewrite cannot undo a correction.
            text = apply_corrections(text, self.cfg)

            if not text or not text.strip():
                log.warning("Polish returned nothing - falling back to raw transcript")
                text = raw

            # paste.py serialises the clipboard sequence, deferred restore too.
            ok = paste_text(text, self.cfg, hotkey_mods=self.hotkey.mods)
            if not ok:
                log.error("Paste failed; the text is still on the clipboard")
                self.tray.notify("Paste failed - press Ctrl+V to paste it yourself")
        except Exception as e:
            # Type name only in the balloon: a backend can embed the transcript in
            # its exception string, and the balloon is visible to bystanders.
            log.exception(f"Pipeline error: {e}")
            self.tray.notify(
                f"Dictation failed ({type(e).__name__}). See the log for details."
            )
        finally:
            try:
                audio_path.unlink(missing_ok=True)
            except Exception as e:
                log.debug(f"Could not delete {audio_path}: {e}")
            self._end()

    # -- lifecycle -----------------------------------------------------

    def shutdown(self):
        try:
            # close(), not discard(): the stream stays open between dictations.
            self.recorder.close()
        except Exception:
            pass
        # The tray follows this with os._exit(0): no finally block runs anywhere.
        try:
            sweep_recordings()
        except Exception as e:
            log.debug(f"Recording sweep on shutdown failed: {e}")

    def run(self):
        # Clear what a crash or hard exit left in %TEMP%: those files are voice.
        try:
            sweep_recordings()
        except Exception as e:
            log.debug(f"Recording sweep at startup failed: {e}")

        # Off the hot path: a load in progress may delay transcription, not capture.
        threading.Thread(
            target=preload, args=(self.cfg,), daemon=True, name="model-preload"
        ).start()

        # Mic open and hotkey arm run concurrently. Opening the device can take
        # 15 s, and until the hook is installed the trigger key does its normal
        # job, so arm first and let on_press check recorder.is_ready.
        def open_microphone():
            if not self.recorder.warmup():
                log.error(
                    "Microphone unavailable - the hotkey is still active, but "
                    "check Settings > Privacy & security > Microphone"
                )

        threading.Thread(target=open_microphone, daemon=True, name="mic").start()
        threading.Thread(target=self.hotkey.run, daemon=True, name="hotkey").start()

        # After the hotkey is live, so the practice step drives the real pipeline.
        if not self.cfg.get("setup_complete", False):
            threading.Thread(target=self._launch_setup, daemon=True,
                             name="setup").start()

        log.info("Casper Flow started")
        self.tray.run()   # blocks on the main thread

    def _launch_setup(self):
        """
        Run the wizard in a separate process. A second Tk root in this process
        fails once the overlay's root has been destroyed. Pasting targets the
        focused window, so the practice step still works.
        """
        import subprocess
        # Let the model load and the hook install before the practice step.
        time.sleep(1.5)
        try:
            if getattr(sys, "frozen", False):
                cmd = [sys.executable, "--setup"]
            else:
                cmd = [sys.executable, str(Path(__file__).resolve()), "--setup"]
            log.info("Opening first-run setup")
            subprocess.Popen(cmd, close_fds=True)
        except Exception as e:
            log.exception(f"Could not open first-run setup: {e}")


# Held for the lifetime of the process; must stay referenced.
_instance_lock = None


def _claim_single_instance() -> bool:
    """
    Refuse to start twice: two instances install two keyboard hooks on the same
    key, so one dictation records and pastes twice.
    """
    global _instance_lock
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        ERROR_ALREADY_EXISTS = 183
        handle = k32.CreateMutexW(None, False, "CasperFlow_SingleInstance_Mutex")
        if not handle:
            return True     # can't tell; don't block startup
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            return False
        _instance_lock = handle
        return True
    except Exception as e:
        log.debug(f"Single-instance check skipped: {e}")
        return True


def _set_app_id() -> None:
    """
    Set an explicit AppUserModelID. Without one the shell identifies a windowed
    process by its executable, so the taskbar button groups under pythonw.exe,
    draws its icon and pins wrong. Must run before the first window exists.
    """
    try:
        ctypes.WinDLL("shell32").SetCurrentProcessExplicitAppUserModelID(
            ctypes.c_wchar_p("CasperFlow.Dictation")
        )
    except Exception as e:
        log.debug(f"AppUserModelID not set: {e}")


def _apply_profile(profile_id: str) -> bool:
    """
    Write a named profile into settings.json and exit. For the installer, whose
    language question must land before the app first starts. Profile ids and
    languages live only in settings_ui.PROFILES. Leaves setup incomplete.
    """
    from config import save_config
    from settings_ui import PROFILES

    chosen = next((p for p in PROFILES if p["id"] == profile_id), None)
    if chosen is None:
        known = ", ".join(p["id"] for p in PROFILES)
        log.error(f"Unknown profile {profile_id!r}. Known profiles: {known}")
        return False

    cfg = load_config()
    cfg["whisper_model"] = chosen["id"]
    cfg["language"] = chosen["language"]
    try:
        save_config(cfg)
    except Exception as e:
        log.exception(f"Could not save the profile: {e}")
        return False
    log.info(f"Profile set to {chosen['id']} (language={chosen['language']})")
    return True


def main():
    _set_app_id()

    args = sys.argv[1:]

    # Takes no mutex and opens no window. build_installer.ps1 uses it to smoke-test
    # the frozen build for missing lazy imports, so callers rely on the exit code.
    if "--version" in args or "-V" in args:
        # A windowed build has no console, so sys.stdout may be None.
        try:
            print(f"Casper Flow {__version__}")
        except Exception:
            pass
        sys.exit(0)

    # Run by the installer between copying files and launching the app.
    if "--set-profile" in args:
        i = args.index("--set-profile")
        if i + 1 >= len(args):
            log.error("--set-profile needs a profile id")
            sys.exit(2)
        sys.exit(0 if _apply_profile(args[i + 1]) else 1)

    # Wizard only, and must not take the mutex: the running app spawns it.
    if "--setup" in args:
        from wizard import open_wizard
        log.info("Running first-run setup")
        open_wizard()
        return

    if not _claim_single_instance():
        log.warning(
            "Casper Flow is already running (look for the microphone icon in the "
            "system tray, near the clock - you may need to click the ^ arrow). "
            "Exiting so the two copies don't both grab the hotkey."
        )
        return

    cfg = load_config()
    log.info(
        f"Config: hotkey={cfg['hotkey']!r} transcribe={cfg['transcribe_backend']} "
        f"model={cfg['whisper_model']} polish="
        f"{cfg['llm_backend'] if cfg.get('llm_polish') else 'off'} "
        f"language={cfg.get('language')}"
    )
    CasperFlow(cfg).run()


if __name__ == "__main__":
    main()
