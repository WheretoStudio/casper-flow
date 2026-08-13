"""
Microphone recorder.

Captures from the default (or configured) input device with sounddevice and writes
a temp 16-bit WAV for the transcription backend. Frames arrive on the PortAudio
callback thread; the pipeline and the overlay read them under _lock.
max_record_seconds caps the buffer so a stuck hotkey cannot exhaust RAM.
"""

import logging
import tempfile
import threading
import time
import wave
from pathlib import Path

import numpy as np

log = logging.getLogger("casper.recorder")

# int16 peak below this is effectively silence (~ -46 dBFS)
_SILENCE_PEAK = 160

# Ours alone, so sweep_recordings() can clear it without touching other apps.
RECORDING_DIR = Path(tempfile.gettempdir()) / "casper-flow"


def sweep_recordings() -> int:
    """
    Delete every leftover recording (each a WAV of the user's voice) and return the
    count. The pipeline deletes its own, but the tray's os._exit(0), an unhandled
    error and power loss all skip that. Safe at startup: the single-instance mutex
    rules out another live dictation.
    """
    if not RECORDING_DIR.is_dir():
        return 0
    removed = 0
    for leftover in RECORDING_DIR.glob("casper_*.wav"):
        try:
            leftover.unlink()
            removed += 1
        except Exception as e:
            # Usually locked by a running pipeline, which deletes it itself.
            log.debug(f"Could not delete leftover recording: {e}")
    if removed:
        log.info(f"Deleted {removed} leftover recording(s) from a previous run")
    return removed


class AudioRecorder:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.sample_rate = int(cfg.get("sample_rate", 16000))
        self.channels = int(cfg.get("channels", 1))
        self.max_seconds = float(cfg.get("max_record_seconds", 300))
        self.device = cfg.get("input_device")

        self._frames: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._stream = None
        self.recording = False
        # Set by stop() when it returns None for a reason the user should hear.
        self.last_failure: str | None = None
        self._overflowed = False
        self._total = 0

        # Creating a PortAudio InputStream costs 1250-1450 ms every time; starting
        # an existing one is free. Create once, start/stop per dictation. A
        # created-but-stopped stream delivers no callbacks and captures nothing.
        self._keep_open = bool(cfg.get("keep_mic_open", True))

        # Written from the audio callback, read by the UI. A float assignment is
        # atomic enough for a display hint and keeps the callback lock-free.
        self._level = 0.0
        self._started_at = 0.0

    # -- helpers -------------------------------------------------------

    @property
    def _max_frames(self) -> int:
        return int(self.max_seconds * self.sample_rate)

    @property
    def level(self) -> float:
        """Current smoothed input level, 0.0-1.0 (for the meter)."""
        return self._level if self.recording else 0.0

    @property
    def elapsed(self) -> float:
        """Seconds since recording started (0 when idle)."""
        return (time.monotonic() - self._started_at) if self.recording else 0.0

    def _resolve_device(self):
        """Accept an index, a name substring, or None for the system default."""
        if self.device in (None, "", "default"):
            return None
        try:
            return int(self.device)
        except (TypeError, ValueError):
            pass
        try:
            import sounddevice as sd
            needle = str(self.device).lower()
            for idx, dev in enumerate(sd.query_devices()):
                if dev["max_input_channels"] > 0 and needle in dev["name"].lower():
                    log.info(f"Input device {idx}: {dev['name']}")
                    return idx
            log.warning(f"No input device matching {self.device!r}; using default")
        except Exception as e:
            log.warning(f"Device lookup failed ({e}); using default")
        return None

    # -- public API ----------------------------------------------------

    def _callback(self, indata, frames, time_info, status):
        """
        Runs on the PortAudio thread for every audio block. Installed once at
        stream creation, not per recording, so it checks self.recording itself.
        """
        if status:
            log.warning(f"Sounddevice status: {status}")

        # Outside the lock, so the meter keeps moving once the cap stops storing.
        try:
            peak = float(np.abs(indata).max())
            inst = min(1.0, peak / 9000.0)     # ~ -11 dBFS reads as full
            # Fast attack, slow release reads naturally on screen.
            self._level = inst if inst > self._level else (
                self._level * 0.80 + inst * 0.20
            )
        except Exception:
            pass

        with self._lock:
            if not self.recording:
                return
            if self._total >= self._max_frames:
                if not self._overflowed:
                    self._overflowed = True
                    log.warning(
                        f"Hit max_record_seconds ({self.max_seconds}s); "
                        f"dropping further audio"
                    )
                return
            self._frames.append(indata.copy())
            self._total += frames

    def _ensure_stream(self) -> bool:
        """Create the input stream if it does not exist yet. Returns success."""
        if self._stream is not None:
            return True
        try:
            import sounddevice as sd
        except ImportError:
            log.error("'sounddevice' not installed. Run: pip install sounddevice")
            return False
        try:
            t0 = time.monotonic()
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="int16",
                device=self._resolve_device(),
                callback=self._callback,
            )
            log.info(
                f"Audio stream ready in {time.monotonic() - t0:.2f}s "
                f"({self.sample_rate} Hz, {self.channels} ch, not yet capturing)"
            )
            return True
        except Exception as e:
            log.exception(f"Failed to open audio stream: {e}")
            self._stream = None
            return False

    @property
    def is_ready(self) -> bool:
        """
        True once there is a stream to capture into. main.py arms the hotkey first,
        since a cold USB mic or exclusive-mode driver can take 15 s to open, and
        reports any press that beats it.
        """
        return self._stream is not None

    def warmup(self) -> bool:
        """
        Create the stream ahead of the first dictation: creation takes over a
        second, which on the hot path costs the start of the phrase. Left stopped.
        """
        return self._ensure_stream()

    def start(self) -> bool:
        """Begin capturing. Returns True if capture is running."""
        if not self._ensure_stream():
            return False

        with self._lock:
            if self.recording:
                return True
            self._frames = []
            self._total = 0
            self._overflowed = False
            self._level = 0.0
            self._started_at = time.monotonic()
            self.recording = True

        try:
            if not self._stream.active:
                self._stream.start()
            log.info(f"Recording started ({self.sample_rate} Hz, {self.channels} ch)")
            return True
        except Exception as e:
            log.exception(f"Failed to start audio stream: {e}")
            with self._lock:
                self.recording = False
            # A stream that will not start is not worth keeping.
            self._close_stream()
            return False

    def stop(self) -> Path | None:
        """Stop recording, write a WAV, return its path (or None)."""
        with self._lock:
            was_recording = self.recording
            self.recording = False
            self._level = 0.0
            frames = self._frames
            self._frames = []

        self._pause_stream()

        # Set on each None path below; main.py shows it, since a muted mic and a
        # dead hotkey look identical to the user.
        self.last_failure = None

        if not was_recording:
            return None
        if not frames:
            log.warning("No audio frames captured - is the microphone muted or in use?")
            self.last_failure = (
                "No sound reached Casper Flow. The microphone may be muted or "
                "in use by another program."
            )
            return None

        audio = np.concatenate(frames, axis=0)
        duration = len(audio) / self.sample_rate
        peak = int(np.abs(audio).max()) if audio.size else 0
        log.info(f"Captured {duration:.2f}s, peak amplitude {peak}/32767")

        if duration < 0.3:
            log.warning("Recording shorter than 0.3s - ignoring")
            self.last_failure = (
                "That was too short to transcribe. Keep holding the key while "
                "you speak."
            )
            return None

        if peak < _SILENCE_PEAK:
            log.warning(
                "Audio is effectively silent. Check Settings > Privacy & security "
                "> Microphone, the input device, and that the mic isn't muted."
            )
            self.last_failure = (
                "The microphone recorded silence. Check that it is not muted, "
                "and that the right input device is chosen in Settings."
            )
            return None

        return self._write_wav(audio)

    def snapshot(self):
        """Audio so far as float32 mono, or None below 0.6 s (not worth a pass)."""
        with self._lock:
            if not self.recording or not self._frames:
                return None
            frames = list(self._frames)
        audio = np.concatenate(frames, axis=0)
        if audio.ndim > 1:
            audio = audio[:, 0]
        if len(audio) < int(0.6 * self.sample_rate):
            return None
        return audio.astype(np.float32) / 32768.0

    def discard(self) -> bool:
        """
        Stop and throw the audio away (too-short taps). Returns True if it held
        speech; main.py stays silent for a plain tap and explains min_hold_seconds
        otherwise.
        """
        with self._lock:
            self.recording = False
            self._level = 0.0
            frames = self._frames
            self._frames = []
            self._total = 0
        self._pause_stream()

        had_speech = False
        if frames:
            try:
                audio = np.concatenate(frames, axis=0)
                # 0.2 s is a syllable rather than a click or a desk knock.
                had_speech = (int(np.abs(audio).max()) >= _SILENCE_PEAK
                              and len(audio) >= int(0.2 * self.sample_rate))
            except Exception as e:
                log.debug(f"Could not measure discarded audio: {e}")

        log.info(f"Recording discarded (contained speech: {had_speech})")
        return had_speech

    def close(self):
        """Release the audio device. Called on quit."""
        with self._lock:
            self.recording = False
            self._level = 0.0
            self._frames = []
            self._total = 0
        self._close_stream()

    # -- internals -----------------------------------------------------

    def _pause_stream(self):
        """
        Stop capturing without destroying the stream, so the next dictation skips
        the 1.3 s creation cost. A stopped stream delivers no callbacks, so nothing
        is captured between dictations.
        """
        if not self._stream:
            return
        if not self._keep_open:
            self._close_stream()
            return
        try:
            if self._stream.active:
                self._stream.stop()
        except Exception as e:
            log.warning(f"Error stopping stream ({e}); closing it instead")
            self._close_stream()

    def _close_stream(self):
        if not self._stream:
            return
        try:
            self._stream.stop()
            self._stream.close()
        except Exception as e:
            log.warning(f"Error closing stream: {e}")
        finally:
            self._stream = None

    def _write_wav(self, audio: np.ndarray) -> Path | None:
        try:
            RECORDING_DIR.mkdir(parents=True, exist_ok=True)
            tmp = tempfile.NamedTemporaryFile(
                prefix="casper_", suffix=".wav", delete=False, dir=RECORDING_DIR
            )
            tmp.close()
            wav_path = Path(tmp.name)
            with wave.open(str(wav_path), "wb") as wf:
                wf.setnchannels(self.channels)
                wf.setsampwidth(2)   # int16
                wf.setframerate(self.sample_rate)
                wf.writeframes(audio.tobytes())
            # DEBUG only: names a file containing the user's voice.
            log.debug(f"WAV written to {wav_path}")
            log.info(f"Recording written, {audio.shape[0] / self.sample_rate:.1f}s")
            return wav_path
        except Exception as e:
            log.exception(f"Could not write WAV: {e}")
            return None
