"""
PyInstaller runtime hook: satisfy `import av` without shipping PyAV.

PyAV is 62.6 MB of FFmpeg, present only so faster-whisper can decode arbitrary
audio formats. Casper Flow records its own 16 kHz mono WAV and reads it with
transcribe._decode_wav. Excluding PyAV is not enough, because
faster_whisper/audio.py does `import av` at import time; the module has to exist,
but WhisperModel.transcribe only calls decode_audio when its input is not already
a numpy array, and we always pass an array.

Getting this wrong means the frozen app does not start at all.
"""

import sys
import types

_MESSAGE = (
    "PyAV is not bundled with Casper Flow. Audio is decoded by "
    "transcribe._decode_wav, and faster-whisper is only ever given a numpy "
    "array, so nothing should reach PyAV. Something passed a file path or an "
    "unsupported format to a decoder. Fix the caller rather than re-adding "
    "PyAV: it is 62.6 MB of FFmpeg for a WAV we wrote ourselves."
)


def _refuse(name):
    # Any real attribute use raises rather than returning a mock, so an attempt to
    # decode names its own cause instead of surfacing three frames later as an
    # AttributeError on av.audio. Dunders are the exception: faster-whisper probes
    # hasattr(av, "__version__"), and a RuntimeError there is a crash at import.
    if name.startswith("__") and name.endswith("__"):
        raise AttributeError(name)
    raise RuntimeError(f"{_MESSAGE} (tried to use av.{name})")


if "av" not in sys.modules:
    _stub = types.ModuleType("av")
    _stub.__doc__ = "Stub installed by Casper Flow. See hooks/rthook_no_av.py."
    # PEP 562: consulted for any attribute not already in the module namespace.
    _stub.__getattr__ = _refuse
    sys.modules["av"] = _stub
