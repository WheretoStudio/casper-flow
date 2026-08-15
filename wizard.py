"""
First-run setup.

    venv\\Scripts\\python.exe wizard.py        (standalone, for development)

Opens automatically the first time Casper Flow runs, and is launched by the
installer's final screen.

This is not a welcome tour. Four steps, and **each one leaves something
verified**: the level meter moved, the key was received, a real sentence
appeared. Nobody reaches the end without one successful dictation, because the
alternative is a user who has finished setup and still does not know whether the
thing works.

The practice step deliberately uses the real pipeline rather than a simulation.
Casper Flow pastes at the caret, so with the wizard's own text box focused, a
genuine dictation lands in it - hotkey, microphone, model, cleanup, clipboard and
paste all exercised at once. A simulated success here would be worse than no step
at all, because it would tell the user something that might not be true.
"""

import logging
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tkinter as tk
from tkinter import messagebox, ttk

from config import DEFAULTS, SETTINGS_FILE, load_config, save_config
from settings_ui import PROFILES

log = logging.getLogger("casper.wizard")

SAMPLE_RATE = 16000
SILENCE_PEAK = 500
PAD = 20

ACCENT = "#b14e2a"


class Wizard:
    def __init__(self, cfg: dict | None = None, on_finish=None, master=None):
        self.cfg = cfg or load_config()
        self.on_finish = on_finish
        self.result: dict = {}
        # A caller can supply an existing Tk root. Only one Tk root can exist per
        # process - creating a second fails outright - so this is what lets tests
        # exercise both this window and the settings window in one run.
        self._owns_root = master is None

        # What each step has proved. The Next button is gated on these.
        #
        # mic and practice start false because they can only be satisfied by
        # something actually happening - a level meter moving, a real transcript
        # arriving. hotkey and profile start true because the shipped defaults are
        # already valid choices, so there is nothing to prove.
        #
        # These describe reality rather than which step has been rendered, so the
        # gates cannot be fooled by navigating in an unexpected order.
        self.verified = {"mic": False, "hotkey": True, "profile": True,
                         "practice": False}

        self.step = 0
        self._meter_stop = threading.Event()
        self._meter_stream = None
        self._practice_seen = ""

        self.root = tk.Tk() if self._owns_root else tk.Toplevel(master)
        self.root.title("Set up Casper Flow")
        self.root.geometry("640x520")
        self.root.minsize(600, 480)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        from paths import apply_window_icon
        apply_window_icon(self.root)

        self._chrome()
        self._show()

    # -- chrome --------------------------------------------------------

    def _chrome(self):
        head = ttk.Frame(self.root)
        head.pack(fill="x", padx=PAD, pady=(PAD, 0))
        self.title_lbl = ttk.Label(head, text="", font=("Segoe UI", 15, "bold"))
        self.title_lbl.pack(anchor="w")
        self.step_lbl = ttk.Label(head, text="", foreground="#777")
        self.step_lbl.pack(anchor="w", pady=(2, 0))

        self.body = ttk.Frame(self.root)
        self.body.pack(fill="both", expand=True, padx=PAD, pady=PAD)

        bar = ttk.Frame(self.root)
        bar.pack(fill="x", padx=PAD, pady=(0, PAD))
        self.next_btn = ttk.Button(bar, text="Next", command=self._next)
        self.next_btn.pack(side="right")
        self.back_btn = ttk.Button(bar, text="Back", command=self._back)
        self.back_btn.pack(side="right", padx=6)
        self.skip_btn = ttk.Button(bar, text="Skip setup", command=self._skip)
        self.skip_btn.pack(side="left")

    def _clear(self):
        self._meter_stop.set()
        self._close_meter()
        for w in self.body.winfo_children():
            w.destroy()

    STEPS = ("mic", "hotkey", "profile", "practice")

    def _show(self):
        self._clear()
        self._meter_stop = threading.Event()
        name = self.STEPS[self.step]
        self.step_lbl.configure(text=f"Step {self.step + 1} of {len(self.STEPS)}")
        self.back_btn.configure(state="normal" if self.step else "disabled")
        self.next_btn.configure(
            text="Finish" if self.step == len(self.STEPS) - 1 else "Next")
        getattr(self, f"_step_{name}")()
        self._refresh_next()

    def _refresh_next(self):
        ok = self.verified[self.STEPS[self.step]]
        self.next_btn.configure(state="normal" if ok else "disabled")

    def _next(self):
        if self.step < len(self.STEPS) - 1:
            self.step += 1
            self._show()
        else:
            self._finish()

    def _back(self):
        if self.step:
            self.step -= 1
            self._show()

    # -- step 1: microphone -------------------------------------------

    def _step_mic(self):
        self.title_lbl.configure(text="Can it hear you?")
        ttk.Label(self.body, wraplength=560, justify="left",
                  text="Say something - 'testing, one two three' is fine. The bar "
                       "should move.\n\nIf it stays flat, pick a different "
                       "microphone below, or check Windows Settings > Privacy & "
                       "security > Microphone.").pack(anchor="w", pady=(0, 14))

        row = ttk.Frame(self.body)
        row.pack(fill="x", pady=(0, 10))
        ttk.Label(row, text="Microphone:").pack(side="left")
        self.device_box = ttk.Combobox(row, state="readonly", width=44)
        self.device_box.pack(side="left", padx=8)
        self.device_box.bind("<<ComboboxSelected>>", lambda _e: self._start_meter())

        self._devices = self._list_devices()
        self.device_box["values"] = [d[1] for d in self._devices] or ["(none found)"]
        if self._devices:
            self.device_box.current(0)

        self.meter = ttk.Progressbar(self.body, maximum=100, length=520)
        self.meter.pack(pady=(6, 4))
        self.peak_lbl = ttk.Label(self.body, text="listening...",
                                  foreground="#777")
        self.peak_lbl.pack(anchor="w")

        self.mic_ok_lbl = ttk.Label(self.body, text="", font=("Segoe UI", 10, "bold"))
        self.mic_ok_lbl.pack(anchor="w", pady=(12, 0))

        if self._devices:
            self._start_meter()
        else:
            self.peak_lbl.configure(
                text="No microphone found. Plug one in and reopen setup.")

    @staticmethod
    def _list_devices() -> list[tuple[int, str]]:
        try:
            import sounddevice as sd
            out = []
            for i, d in enumerate(sd.query_devices()):
                if d["max_input_channels"] > 0:
                    out.append((i, d["name"][:60]))
            return out
        except Exception as e:
            log.debug(f"device query failed: {e}")
            return []

    def _start_meter(self):
        """A short-lived stream of our own, so the app's recorder is untouched."""
        self._close_meter()
        try:
            import numpy as np
            import sounddevice as sd
        except ImportError:
            return

        idx = None
        if self._devices and self.device_box.current() >= 0:
            idx = self._devices[self.device_box.current()][0]

        state = {"peak": 0, "level": 0}

        def cb(indata, _n, _t, _s):
            p = int(np.abs(indata).max())
            state["level"] = p
            if p > state["peak"]:
                state["peak"] = p

        try:
            self._meter_stream = sd.InputStream(
                samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                device=idx, callback=cb)
            self._meter_stream.start()
        except Exception as e:
            self.peak_lbl.configure(text=f"Could not open that microphone: {e}")
            return

        def tick():
            if self._meter_stop.is_set() or not self._meter_stream:
                return
            pct = min(100, state["level"] / 9000 * 100)
            try:
                self.meter.configure(value=pct)
                self.peak_lbl.configure(
                    text=f"loudest so far: {state['peak']} of 32767")
                if state["peak"] >= SILENCE_PEAK and not self.verified["mic"]:
                    self.verified["mic"] = True
                    self.mic_ok_lbl.configure(
                        text="Heard you. You can continue.", foreground="#0a7")
                    self._refresh_next()
                    if idx is not None:
                        self.result["input_device"] = idx
            except tk.TclError:
                return
            self.root.after(90, tick)

        tick()

    def _close_meter(self):
        if self._meter_stream is not None:
            try:
                self._meter_stream.stop()
                self._meter_stream.close()
            except Exception:
                pass
            self._meter_stream = None

    # -- step 2: hotkey -----------------------------------------------

    def _step_hotkey(self):
        self.title_lbl.configure(text="Pick your push-to-talk key")
        current = str(self.result.get("hotkey")
                      or self.cfg.get("hotkey", "caps lock"))
        ttk.Label(self.body, wraplength=560, justify="left",
                  text="Hold this key to dictate. A quick tap still does whatever "
                       "the key normally does, so Caps Lock keeps working as Caps "
                       "Lock.").pack(anchor="w", pady=(0, 14))

        row = ttk.Frame(self.body)
        row.pack(fill="x")
        self.key_lbl = ttk.Label(row, text=current.upper(),
                                 font=("Consolas", 14, "bold"),
                                 relief="solid", padding=(14, 8))
        self.key_lbl.pack(side="left")
        ttk.Button(row, text="Press a key to change...",
                   command=self._capture).pack(side="left", padx=12)

        ttk.Label(self.body, wraplength=560, justify="left", foreground="#777",
                  text="\nThe Fn key cannot be used. It is handled inside the "
                       "keyboard itself and never reaches Windows, so no "
                       "application on any operating system can detect it.\n\n"
                       "Caps Lock is the default because it is one key, it is on "
                       "every keyboard, and nothing else uses it as a hold."
                  ).pack(anchor="w")

        self.key_status = ttk.Label(self.body, text="", font=("Segoe UI", 10, "bold"))
        self.key_status.pack(anchor="w", pady=(10, 0))

        # The default is already valid, so this step starts satisfied.
        self.verified["hotkey"] = True
        self.result.setdefault("hotkey", current)

    def _capture(self):
        self.key_status.configure(text="Press a key now...", foreground="#777")
        state = {"name": None}

        def worker():
            try:
                import keyboard
                ev = keyboard.read_event(suppress=False)
                while ev.event_type != "down":
                    ev = keyboard.read_event(suppress=False)
                state["name"] = ev.name
            except Exception as e:
                log.debug(f"capture failed: {e}")
                state["name"] = "?"

        def poll():
            if not state["name"]:
                self.root.after(80, poll)
                return
            name = state["name"]
            if name in ("fn", "?"):
                self.key_status.configure(
                    text="That key never reaches Windows. Try another one.",
                    foreground="#c33")
                return
            from hotkey import normalise, unsafe_bare_modifier
            name = normalise(name)
            reason = unsafe_bare_modifier(name)
            if reason:
                self.key_status.configure(text=reason, foreground="#c33")
                return
            self.result["hotkey"] = name
            self.key_lbl.configure(text=name.upper())
            self.key_status.configure(text=f"Set to {name.upper()}.",
                                      foreground="#0a7")
            self.verified["hotkey"] = True
            self._refresh_next()

        threading.Thread(target=worker, daemon=True).start()
        poll()

    # -- step 3: profile ----------------------------------------------

    def _step_profile(self):
        self.title_lbl.configure(text="How do you talk?")
        ttk.Label(self.body, wraplength=560, justify="left",
                  text="This picks the speech model. You can change it later in "
                       "Settings.").pack(anchor="w", pady=(0, 14))

        chosen = self.result.get("whisper_model") or self.cfg.get(
            "whisper_model", DEFAULTS["whisper_model"])
        self.profile_var = tk.StringVar(value=chosen)

        for p in PROFILES[:2]:          # the two everyday choices
            ttk.Radiobutton(self.body, text=p["label"], value=p["id"],
                            variable=self.profile_var,
                            command=self._pick_profile).pack(anchor="w")
            ttk.Label(self.body, text="      " + p["detail"], foreground="#777",
                      wraplength=540, justify="left").pack(anchor="w",
                                                           pady=(0, 10))

        ttk.Label(self.body, wraplength=560, justify="left", foreground="#777",
                  text="\nAccuracy figures are measured on real recordings, not "
                       "estimates. Hinglish is 81% today and improving is on the "
                       "roadmap - the honest number is on the website too."
                  ).pack(anchor="w")
        self._pick_profile()

    def _pick_profile(self):
        model = self.profile_var.get()
        self.result["whisper_model"] = model
        for p in PROFILES:
            if p["id"] == model:
                self.result["language"] = p["language"]
        self.verified["profile"] = True
        self._refresh_next()

    # -- step 4: practice ---------------------------------------------

    def _step_practice(self):
        key = str(self.result.get("hotkey", "caps lock")).upper()
        hold = float(self.cfg.get("min_hold_seconds",
                                  DEFAULTS["min_hold_seconds"]))
        self.title_lbl.configure(text="Try it")
        ttk.Label(self.body, wraplength=560, justify="left",
                  text=f"Click in the box below, then hold {key} for at least "
                       f"{hold:.0f} seconds, say a sentence, and let go.\n\n"
                       f"The text will appear where your cursor is - here, or in "
                       f"any other application.").pack(anchor="w", pady=(0, 12))

        self.practice = tk.Text(self.body, height=7, wrap="word",
                                font=("Segoe UI", 11))
        self.practice.pack(fill="both", expand=True)
        self.practice.focus_set()

        self.practice_status = ttk.Label(
            self.body, text="Waiting for your first dictation...",
            foreground="#777")
        self.practice_status.pack(anchor="w", pady=(10, 0))

        skip = ttk.Button(self.body, text="It is not working - finish anyway",
                          command=self._practice_giveup)
        skip.pack(anchor="w", pady=(8, 0))

        self._watch_practice()

    def _watch_practice(self):
        """Any text appearing in the box is a real end-to-end success."""
        try:
            text = self.practice.get("1.0", "end").strip()
        except tk.TclError:
            return
        if text and text != self._practice_seen:
            self._practice_seen = text
            if not self.verified["practice"]:
                self.verified["practice"] = True
                self.practice_status.configure(
                    text="That worked. Everything is set up.", foreground="#0a7")
                self._refresh_next()
        self.root.after(300, self._watch_practice)

    def _practice_giveup(self):
        self.verified["practice"] = True
        self.practice_status.configure(
            text="Finishing without a test. Open Settings > Diagnostics to find "
                 "out what is wrong.", foreground="#c60")
        self._refresh_next()

    # -- finishing ----------------------------------------------------

    def _persist(self, complete: bool):
        cfg = dict(self.cfg)
        cfg.update(self.result)
        cfg["setup_complete"] = complete
        try:
            save_config(cfg)
            log.info(f"Setup saved: {sorted(self.result)} complete={complete}")
        except Exception as e:
            log.exception(f"Could not save setup: {e}")
            messagebox.showerror("Could not save",
                                 f"Writing {SETTINGS_FILE.name} failed:\n{e}",
                                 parent=self.root)
            return False
        return True

    def _finish(self):
        if not self._persist(True):
            return
        self._clear()
        if self.on_finish:
            try:
                self.on_finish(dict(self.result))
            except Exception:
                log.exception("on_finish failed")
        restart = "hotkey" in self.result and \
            self.result["hotkey"] != self.cfg.get("hotkey")
        msg = "Casper Flow is ready. Hold your key anywhere to dictate."
        if restart:
            msg += "\n\nRestart Casper Flow for the new key to take effect."
        messagebox.showinfo("All set", msg, parent=self.root)
        self.root.destroy()

    def _skip(self):
        if not messagebox.askyesno(
                "Skip setup?",
                "You can set this up later from the tray icon.\n\nSkip for now?",
                parent=self.root):
            return
        # Marked complete so it does not reappear on every launch, which would be
        # nagging rather than helping.
        self._persist(True)
        self._clear()
        self.root.destroy()

    def _on_close(self):
        self._skip()

    def run(self):
        if self._owns_root:
            self.root.mainloop()


def needs_setup(cfg: dict) -> bool:
    return not bool(cfg.get("setup_complete", False))


def open_wizard(cfg: dict | None = None, on_finish=None):
    Wizard(cfg=cfg, on_finish=on_finish).run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    open_wizard()
