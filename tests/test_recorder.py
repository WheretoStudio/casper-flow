"""Regression test for the bug that made dictation capture nothing.

The failure, from a real log:

    13:45:49,285  Hotkey down - starting recording
    13:45:51,390  Recording started        <- 2.1s after the press
    13:45:51,391  Hotkey up                <- 1ms later
    13:45:51,548  No audio frames captured

Creating a PortAudio InputStream costs 1250-1450 ms and costs that every time.
It was being created on the hotkey press, so the microphone went live after the
key had already been released. The fix creates the stream once and starts it per
dictation, which is ~0 ms.
"""

import time

import numpy as np
import pytest

from conftest import needs_microphone
from recorder import AudioRecorder

CFG = {
    "sample_rate": 16000,
    "channels": 1,
    "input_device": None,
    "max_record_seconds": 300,
    "keep_mic_open": True,
}

# Generous: the point is 0 ms versus 1300 ms, not a tight bound.
MAX_START_MS = 150


@pytest.fixture
def recorder():
    rec = AudioRecorder(dict(CFG))
    assert rec.warmup(), "could not create the input stream"
    yield rec
    rec.close()


@needs_microphone
class TestCaptureStartsImmediately:
    def test_start_is_fast_after_warmup(self, recorder):
        t0 = time.monotonic()
        assert recorder.start()
        elapsed_ms = (time.monotonic() - t0) * 1000
        recorder.stop()
        assert elapsed_ms < MAX_START_MS, (
            f"start() took {elapsed_ms:.0f} ms; the stream is being created on "
            f"the hot path again"
        )

    def test_stays_fast_across_repeated_dictations(self, recorder):
        """The original bug reproduced on every press, not just the first."""
        for i in range(3):
            t0 = time.monotonic()
            recorder.start()
            elapsed_ms = (time.monotonic() - t0) * 1000
            time.sleep(0.2)
            recorder.stop()
            assert elapsed_ms < MAX_START_MS, f"press {i + 1} took {elapsed_ms:.0f} ms"

    def test_a_short_hold_captures_audio(self, recorder):
        """
        The user held the key for ~2s and got zero frames. Any hold must produce
        samples, whatever the room sounds like.
        """
        recorder.start()
        time.sleep(0.9)
        audio = recorder.snapshot()
        recorder.stop()

        assert audio is not None, "no audio buffered during a 0.9s hold"
        assert len(audio) > 0.5 * CFG["sample_rate"], (
            f"only {len(audio)} samples for a 0.9s hold"
        )


@needs_microphone
class TestStoppedStreamCapturesNothing:
    """
    Keeping the stream open is only acceptable if it records nothing between
    dictations. This is the privacy claim in the README, so it gets a test.
    """

    def test_no_audio_is_buffered_before_start(self, recorder):
        time.sleep(0.8)
        assert recorder.snapshot() is None
        assert not recorder.recording

    def test_no_audio_accumulates_after_stop(self, recorder):
        recorder.start()
        time.sleep(0.5)
        recorder.stop()

        assert not recorder.recording
        time.sleep(0.8)
        # A fresh snapshot must not see anything from the idle period.
        assert recorder.snapshot() is None


@needs_microphone
class TestSilencePolicy:
    def test_silent_audio_is_rejected_rather_than_transcribed(self, recorder):
        """
        Whisper hallucinates on silence, so an effectively silent recording must
        produce no WAV at all.
        """
        recorder.start()
        # Overwrite the buffer with true digital silence, so the test does not
        # depend on how quiet the room is.
        with recorder._lock:
            recorder._frames = [np.zeros((16000, 1), dtype=np.int16)]
            recorder._total = 16000
        path = recorder.stop()
        assert path is None, "silent audio produced a WAV to transcribe"

    def test_discard_leaves_nothing_buffered(self, recorder):
        recorder.start()
        time.sleep(0.3)
        recorder.discard()
        assert not recorder.recording
        assert recorder.snapshot() is None
