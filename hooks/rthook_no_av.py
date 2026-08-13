"""
PyInstaller runtime hook: satisfy `import av` without shipping PyAV.

PyAV is 62.6 MB — 12.9% of the installed application — and it is FFmpeg, bundled
so that faster-whisper can decode arbitrary audio formats. Casper Flow does not
need that. It records the audio itself, as 16-bit mono 16 kHz WAV, and
`transcribe._decode_wav` reads it with the standard library in about ten lines.

Excluding PyAV alone does not work, and the way it fails is worth writing down:

    faster_whisper/__init__.py  line 1:  from faster_whisper.audio import decode_audio
    faster_whisper/audio.py     line 15: import av

So `import faster_whisper` needs the module to *exist*, even though nothing we do
will ever call into it. `WhisperModel.transcribe` only reaches `decode_audio` when
its input is not already a numpy array:

    if not isinstance(audio, np.ndarray):
        audio = decode_audio(audio, sampling_rate=sampling_rate)

and we always pass an array. Verified in faster_whisper/transcribe.py at both call
sites.

This installs a module that satisfies the import and then refuses to do anything
else. It deliberately raises on *any* attribute access rather than returning a
harmless mock: if some future code path does try to decode a file, the failure
should name the reason and point at the fix, not surface three frames later as an
AttributeError on `av.audio`.
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
    # Dunders get the ordinary AttributeError, so introspection behaves normally.
    # Raising RuntimeError for these was a mistake worth recording: it made
    # `hasattr(av, "__version__")` blow up instead of returning False, which
    # would turn any library politely probing the module into a crash at import
    # time. Loud on real API use, invisible to inspection.
    if name.startswith("__") and name.endswith("__"):
        raise AttributeError(name)
    raise RuntimeError(f"{_MESSAGE} (tried to use av.{name})")


if "av" not in sys.modules:
    _stub = types.ModuleType("av")
    _stub.__doc__ = "Stub installed by Casper Flow. See hooks/rthook_no_av.py."
    # PEP 562: a module-level __getattr__ is consulted for any attribute that is
    # not already in the module namespace.
    _stub.__getattr__ = _refuse
    sys.modules["av"] = _stub
