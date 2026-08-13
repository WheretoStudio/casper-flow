"""
Casper Flow - system-wide AI dictation for Windows.

Entry point: starts the tray icon, the global hotkey listener, and the status
pill, then wires them to the record -> transcribe -> polish -> paste pipeline.

Threading model:
  main thread   - pystray icon loop (pystray requires this)
  pill-tk       - tkinter loop for the floating status pill
  hotkey        - keyboard hook loop (keyboard.wait())
  pipeline-N    - one short-lived worker per dictation
"""

import ctypes
import sys
import threading
import time
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from paths import DATA_DIR       # noqa: E402

# The log belongs beside the executable, not inside the frozen bundle where the
# first build put it - nobody looks in _internal, and an update replaces it.
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

# Transcripts can contain Devanagari and other non-Latin text. The console's
# default code page (cp1252 on most Windows installs) cannot encode it, and the
# stream handler would raise UnicodeEncodeError on every such log line.
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
        # Let the overlay read the live mic level and duration so it can show a
        # real meter instead of a decorative animation.
        self.pill.set_sources(
            level=lambda: self.recorder.level,
            elapsed=lambda: self.recorder.elapsed,
        )
        self.hotkey = HotkeyListener(cfg, self.on_press, self.on_release)
        self.tray = TrayApp(cfg, self.hotkey, on_quit=self.shutdown)

        self._active = 0
        self._active_lock = threading.Lock()
        self._seq = 0

        # Only the caption style displays text, so skip preview work entirely
        # for the others rather than burning CPU nobody can see.
        self.style_has_no_text = self.pill.style != "caption"

        # One Event per preview loop, replaced when a loop starts, so a loop only
        # ever obeys its own stop signal. A single shared Event meant a new
        # dictation clearing it could un-stop the previous dictation's loop, and
        # the two then transcribed the same buffer into the same overlay.
        self._preview_stop: threading.Event | None = None

        # Fires once a hold has lasted long enough to count as dictation. Until
        # then the microphone is already capturing but nothing is shown, so a
        # tap of the hotkey does not flash a recording indicator on screen.
        self._arm_timer: threading.Timer | None = None
        # Guards _arm_timer and _hold_generation, which are touched from the
        # hotkey worker, the timer thread and the release path.
        self._arm_lock = threading.Lock()
        self._hold_generation = 0

    # -- hotkey handlers -----------------------------------------------

    def on_press(self):
        if not self.tray.enabled:
            log.info("Hotkey pressed but Casper Flow is disabled - ignoring")
            return

        # The microphone is opened on another thread at startup, and on a cold or
        # exclusive-mode device that took 14.6 s here. Pressing inside that window
        # used to fall through to recorder.start(), which blocks until the device
        # opens - so the first seconds of speech were lost and the user had no
        # idea why. Say so instead. The key itself is already suppressed by this
        # point, so nothing leaks through to the focused window either.
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

        # Capture starts now, not when the hold is confirmed. Waiting would
        # throw away the beginning of the sentence, because people start
        # speaking as soon as they press. What waits is the *visible* part: the
        # overlay and the live preview only appear once the hold is long enough
        # to be a dictation, so a tap stays invisible and costs no CPU.
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
        The hold lasted long enough to be dictation. Show it.

        Runs on the timer thread, and holds `_arm_lock` for its whole body so it
        cannot interleave with `_cancel_arm`. `Timer.cancel()` does nothing once
        the timer has already fired, so a release arriving at exactly
        min_hold_seconds used to let this run *after* `on_release` had hidden the
        pill - leaving an overlay on screen with no recording behind it and a
        preview thread transcribing an empty buffer.
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
        Cancel the arm timer and invalidate any arming already in progress.

        Bumping the generation under the lock is what makes this reliable: either
        we get there first and `_on_armed` returns without doing anything, or it
        got there first and finishes before we proceed - so the caller's own
        `pill.hide()` is always the last word.
        """
        with self._arm_lock:
            self._hold_generation += 1
            timer, self._arm_timer = self._arm_timer, None
        if timer is not None:
            timer.cancel()

    # -- live preview ---------------------------------------------------

    def _start_preview(self):
        """
        Show words on screen while the user is still speaking.

        Preview passes are display-only and deliberately cheap: the final
        transcription still runs on the complete recording, so a rough preview
        can never affect what gets pasted. Passes run strictly one at a time,
        and each one waits for new audio, so this cannot pile up work on a
        slow machine.
        """
        if not self.cfg.get("live_preview", True):
            return
        if self.style_has_no_text:
            return

        # A zero or negative interval would spin this thread flat out against the
        # transcriber, on a machine that has two cores to begin with.
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
            # Silent for an ordinary tap of the key, which is the common case and
            # wants no interruption. But if the user actually spoke, they held the
            # key, said something, and got nothing - and without this there is no
            # way for them to discover that a minimum hold time exists at all.
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
            # A muted microphone and a hotkey that never registered look exactly
            # the same from the user's chair: they held a key, spoke, and nothing
            # happened. The recorder knows which it was, so say so.
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
                # Say so. From the user's side this is indistinguishable from a
                # paste that failed or a hotkey that did not register, and staying
                # silent invites them to dictate the same thing again into a
                # window that will not receive it either.
                log.warning("Empty transcript - nothing to paste")
                self.tray.notify(
                    "Nothing was recognised. Check the microphone in Settings, "
                    "and hold the key while you speak."
                )
                return

            text = raw
            if self.cfg.get("llm_polish", True):
                text = polish(raw, self.cfg)

            # Applied after cleanup, so a rewrite cannot undo a correction. This
            # is where your own names and jargon get fixed - see corrections.py.
            text = apply_corrections(text, self.cfg)

            if not text or not text.strip():
                log.warning("Polish returned nothing - falling back to raw transcript")
                text = raw

            # paste.py serialises the whole clipboard sequence internally,
            # including the deferred restore, which this lock never covered.
            ok = paste_text(text, self.cfg, hotkey_mods=self.hotkey.mods)
            if not ok:
                log.error("Paste failed; the text is still on the clipboard")
                self.tray.notify("Paste failed - press Ctrl+V to paste it yourself")
        except Exception as e:
            # The message, not the exception: a backend can put the transcript
            # into an exception string, and a tray balloon is visible to whoever
            # is looking at the screen.
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
            # close(), not discard(): the stream is now kept open between
            # dictations, so quitting has to actually release the device.
            self.recorder.close()
        except Exception:
            pass
        # The tray calls this and then os._exit(0), which runs no finally block
        # anywhere in the process - so a dictation still in flight would leave its
        # recording on disk. Sweeping here is the last chance to not do that.
        try:
            sweep_recordings()
        except Exception as e:
            log.debug(f"Recording sweep on shutdown failed: {e}")

    def run(self):
        # Anything left by a crash or a hard exit last time. Recordings are the
        # user's voice, so they do not get to accumulate in %TEMP%.
        try:
            sweep_recordings()
        except Exception as e:
            log.debug(f"Recording sweep at startup failed: {e}")

        # Warm the local Whisper model so the first dictation isn't a long stall
        # (and so the first-run model download happens before you need it).
        # This runs concurrently: a model that is still loading delays
        # transcription, but it must never delay capture.
        threading.Thread(
            target=preload, args=(self.cfg,), daemon=True, name="model-preload"
        ).start()

        # Opening the microphone and arming the hotkey run CONCURRENTLY.
        #
        # They used to be sequential, so that a press could never begin a
        # "recording" whose microphone opened after the key was already released -
        # a real bug, which captured silence. But the cure was worse: opening the
        # device was measured at 14.6 s on this machine, and for that entire
        # period the tray icon said the app was running while the hotkey was not
        # installed. Caps Lock therefore did what Caps Lock does, and the user got
        # stray capitals instead of a dictation, with nothing explaining why.
        #
        # Arming first and *checking* in on_press fixes both: the key is captured
        # immediately, so it cannot leak through, and a press that arrives before
        # the device is open gets told so rather than silently recording nothing.
        def open_microphone():
            if not self.recorder.warmup():
                log.error(
                    "Microphone unavailable - the hotkey is still active, but "
                    "check Settings > Privacy & security > Microphone"
                )

        threading.Thread(target=open_microphone, daemon=True, name="mic").start()
        threading.Thread(target=self.hotkey.run, daemon=True, name="hotkey").start()

        # First run: open setup once the hotkey is live, so the wizard's practice
        # step exercises the real pipeline rather than a simulation.
        if not self.cfg.get("setup_complete", False):
            threading.Thread(target=self._launch_setup, daemon=True,
                             name="setup").start()

        log.info("Casper Flow started")
        self.tray.run()   # blocks on the main thread

    def _launch_setup(self):
        """
        Run the wizard in a separate process.

        Not a thread: the overlay already owns a Tk root, and a second Tk root in
        the same process is unreliable - it fails outright once the first has been
        destroyed. A separate process keeps the two completely isolated, and the
        practice step still works because pasting targets whichever window has
        focus.
        """
        import subprocess
        # Give the model and the hotkey a moment, so the practice step is usable
        # the instant the user reaches it.
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
    Refuse to start twice.

    Two instances would install two keyboard hooks on the same key, so one
    dictation would record and paste twice. Easy to hit by double-clicking the
    launcher again when you think nothing happened.
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
    Tell Windows this process is Casper Flow and not its host interpreter.

    Without an explicit AppUserModelID, the shell identifies a windowed process
    by its executable, so our taskbar button was grouped under pythonw.exe and
    drew pythonw's icon - the "that isn't the icon we designed" symptom. Setting
    an ID of our own gives the taskbar button its own identity, lets it pin
    correctly, and makes Windows take the icon from our window rather than the
    interpreter.

    Must run before any window exists; the shell reads it when the first
    top-level window appears.
    """
    try:
        ctypes.WinDLL("shell32").SetCurrentProcessExplicitAppUserModelID(
            ctypes.c_wchar_p("CasperFlow.Dictation")
        )
    except Exception as e:
        log.debug(f"AppUserModelID not set: {e}")


def _apply_profile(profile_id: str) -> bool:
    """
    Write one of the named profiles into settings.json, then exit.

    This exists for the installer. Screen 4 asks whether the user speaks English
    or Hinglish, and that answer has to reach `settings.json` before the app first
    starts, or the choice was theatre.

    Doing it here rather than in Inno Setup's Pascal script is deliberate: the
    profile list, the model ids and the language each profile pins already live in
    `settings_ui.PROFILES`, and a second copy in an .iss file is a copy that would
    drift. The installer passes an id and knows nothing else about it.

    Deliberately does not mark setup complete - the wizard still runs, and it
    shows this choice already selected because `_step_profile` reads the config.
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

    # `--version` prints and exits, taking no mutex and opening no window. It is
    # also how build_installer.ps1 smoke-tests the frozen build: a packaging
    # mistake in a lazily imported module otherwise survives every check that only
    # inspects files, and first appears when a user opens Settings.
    if "--version" in args or "-V" in args:
        # A windowed build has no console, so sys.stdout may be None or a sink.
        # The exit code is the part the build script relies on; the text is a
        # convenience when run from a terminal.
        try:
            print(f"Casper Flow {__version__}")
        except Exception:
            pass
        sys.exit(0)

    # `--set-profile <id>` writes the profile and exits without starting anything.
    # Run silently by the installer between copying files and launching the app.
    if "--set-profile" in args:
        i = args.index("--set-profile")
        if i + 1 >= len(args):
            log.error("--set-profile needs a profile id")
            sys.exit(2)
        sys.exit(0 if _apply_profile(args[i + 1]) else 1)

    # `--setup` runs only the wizard and exits. Used by the running app on first
    # launch and by the installer's final screen, and it must not take the
    # single-instance mutex or it would refuse to start while the app is running.
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
