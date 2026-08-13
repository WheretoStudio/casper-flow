# Third-party notices

Casper Flow itself is MIT licensed; see `LICENSE`. The installer and the portable
zip also contain the libraries below, so their notices are distributed with it.

Versions are the ones in the build this file shipped with. `pip show <name>` on a
source checkout prints the licence text for any of them, and every project is
linked to its own repository, which is the authoritative copy.

## Licence obligation worth knowing about

**pystray is LGPL-3.0**, and it is the one dependency here whose licence asks for
more than attribution. Casper Flow uses it unmodified, as a separate Python
library that is imported at runtime, and it is shipped as its own files inside
`_internal/pystray/` rather than merged into the executable. Anyone who wants to
run Casper Flow against a different build of pystray can replace those files in
place — no relinking or rebuilding of Casper Flow is required — which is what
LGPL section 4 asks a combined work to allow. pystray's own source is at
<https://github.com/moses-palmer/pystray>.

Nothing here restricts what you may do with Casper Flow's own source, which stays
MIT.

## Speech and inference

| Component | Version | Licence |
|---|---|---|
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | 1.2.1 | MIT |
| [CTranslate2](https://github.com/OpenNMT/CTranslate2) | 4.8.1 | MIT |
| [onnxruntime](https://github.com/microsoft/onnxruntime) | 1.28.0 | MIT |
| [tokenizers](https://github.com/huggingface/tokenizers) | 0.22.2 | Apache-2.0 |
| [huggingface-hub](https://github.com/huggingface/huggingface_hub) | 0.36.2 | Apache-2.0 |

## Model weights

| Model | Source | Licence |
|---|---|---|
| `base.en` | [Systran/faster-whisper-base.en](https://huggingface.co/Systran/faster-whisper-base.en), a CTranslate2 conversion of OpenAI Whisper | MIT |
| `swift-ct2` | A Hinglish fine-tune of Whisper, converted for CTranslate2 | See `models/swift-ct2/README` in the source repository |

Whisper itself is MIT licensed by OpenAI. A fine-tune inherits the terms of the
checkpoint it was trained from and of its training data, so the fine-tune ships
with its own note rather than being covered by a blanket claim here.

## Audio, input and interface

| Component | Version | Licence |
|---|---|---|
| [sounddevice](https://github.com/spatialaudio/python-sounddevice) | 0.5.5 | MIT |
| [PortAudio](https://www.portaudio.com/) | bundled with sounddevice | MIT-style |
| [keyboard](https://github.com/boppreh/keyboard) | 0.13.5 | MIT |
| [pystray](https://github.com/moses-palmer/pystray) | 0.19.5 | **LGPL-3.0** |
| [Pillow](https://github.com/python-pillow/Pillow) | 12.3.0 | MIT-CMU |
| [pywin32](https://github.com/mhammond/pywin32) | 312 | PSF |

## Everything else

| Component | Version | Licence |
|---|---|---|
| [NumPy](https://github.com/numpy/numpy) | 2.4.6 | BSD-3-Clause (with 0BSD, MIT, Zlib and CC0-1.0 components) |
| [requests](https://github.com/psf/requests) | 2.34.2 | Apache-2.0 |
| [CPython](https://github.com/python/cpython) | 3.11 | PSF |

The OpenAI, Anthropic and Groq client libraries are **not** in the build. They are
excluded at package time, so the shipped binary has no code capable of sending
audio or text to a transcription API. See `casper.spec`.
