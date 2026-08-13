"""
Transcription backends:
  - local  : faster-whisper (Whisper via CTranslate2) - fully offline
  - groq   : Groq Whisper API
  - openai : OpenAI Whisper API

`preload()` exists so the local model is loaded during startup rather than
during your first dictation - loading `small` from cold takes several seconds,
and the very first run also downloads ~460 MB.
"""

import logging
import threading
import time
import wave
from pathlib import Path

import numpy as np

import paths as _paths
from config import DEFAULTS, WHISPER_RATE

log = logging.getLogger("casper.transcribe")

# Module-level cache so the local model loads once and stays resident
_local_model = None
_local_key = None
# The model that is actually loaded, which is not always the one that was asked
# for - see the fallback in _load_local. None until the first load.
loaded_model_name: str | None = None
_model_lock = threading.Lock()


def transcribe(audio_path: Path, cfg: dict) -> str:
    backend = str(cfg.get("transcribe_backend", "local")).lower()

    # Privacy gate. Audio is the most sensitive thing this app touches, so the
    # refusal lives here rather than relying on configuration being correct.
    if cfg.get("offline_only", True) and backend != "local":
        log.warning(
            f"transcribe_backend={backend!r} would upload your audio and "
            f"offline_only is on. Using the local model instead."
        )
        backend = "local"

    log.info(f"Transcribing with backend: {backend}")

    if backend == "local":
        return _transcribe_local(audio_path, cfg)
    if backend == "groq":
        return _transcribe_groq(audio_path, cfg)
    if backend == "openai":
        return _transcribe_openai(audio_path, cfg)
    raise ValueError(f"Unknown transcribe_backend: {backend!r}")


# ---------------------------------------------------------------- local

# A usable faster-whisper snapshot needs all of these. An interrupted download
# leaves the repo directory in place with nothing in it, so presence of the
# repo alone is not enough to know a model will load.
_REQUIRED_FILES = {"config.json", "model.bin", "tokenizer.json"}


def _cached_models() -> list[str]:
    """
    Models that are already present and loadable, best fallback first.

    Three sources, because a model can arrive by three routes:

      * the standard Systran repos, referred to by bare size ("base")
      * a directory under models/, converted locally and referred to by its name
      * any other HuggingFace repo, referred to by its full "owner/name" id

    Only recognising the first would make a purpose-built model invisible to the
    fallback: a user whose only complete model is a converted Hinglish one would
    be told nothing is available.
    """
    order = ["tiny.en", "tiny", "base.en", "base", "small.en", "small",
             "medium.en", "medium", "large-v3"]
    sizes: set[str] = set()
    others: list[str] = []

    try:
        from huggingface_hub import scan_cache_dir
        for repo in scan_cache_dir().repos:
            files = {f.file_name for rev in repo.revisions for f in rev.files}
            if not _REQUIRED_FILES.issubset(files):
                continue
            name = repo.repo_id.split("/")[-1]
            if name.startswith("faster-whisper-"):
                sizes.add(name[len("faster-whisper-"):])
            else:
                others.append(repo.repo_id)
    except Exception as e:
        log.debug(f"Could not scan the model cache: {e}")

    local: list[str] = []
    for base in _model_dirs():
        try:
            if not base.is_dir():
                continue
            for d in sorted(base.iterdir()):
                if (d / "model.bin").is_file() and d.name not in local:
                    local.append(d.name)
        except Exception as e:
            log.debug(f"Could not scan {base}: {e}")

    # Known sizes first, in ascending cost order, because a fallback should be
    # something that loads quickly rather than something accurate. Local
    # conversions come next: they are on disk already and need no network.
    return [m for m in order if m in sizes] + local + others


# Bundled models are read-only inside the build; a model the user converted
# themselves sits beside the executable. Both are searched, the user's first.
MODELS_DIR = _paths.DATA_DIR / "models"
BUNDLED_MODELS_DIR = _paths.RESOURCE_DIR / "models"


def _model_dirs() -> list[Path]:
    seen, out = set(), []
    for d in (MODELS_DIR, BUNDLED_MODELS_DIR):
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def resolve_model(name: str) -> str:
    """
    Turn a configured model name into something WhisperModel can load.

    A name matching a directory under models/ is used as a local path, so a
    converted model can be selected by name like any built-in one. Everything
    else is passed through as a HuggingFace identifier.

    Resolved to an absolute path deliberately: a relative one would depend on the
    working directory, and the app is launched from a shortcut, a .bat file and a
    scheduled task, which do not agree on what that is.
    """
    if not name:
        return name
    for base in _model_dirs():
        candidate = base / name
        if (candidate / "model.bin").is_file():
            return str(candidate.resolve())
    # An explicit path, absolute or relative, is honoured as given.
    direct = Path(name)
    if (direct / "model.bin").is_file():
        return str(direct.resolve())
    return name


def _load_local(cfg: dict):
    """Load (and cache) the faster-whisper model. Thread-safe."""
    global _local_model, _local_key

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise RuntimeError(
            "faster-whisper not installed. Run: pip install faster-whisper"
        )

    # Fall back to the same value config.py documents as the default. A different
    # literal here means a missing key silently loads a different model than the
    # one every doc, test and profile says ships.
    model_size = cfg.get("whisper_model") or DEFAULTS["whisper_model"]
    device = cfg.get("whisper_device", "cpu")
    compute_type = cfg.get("whisper_compute_type", "int8")
    threads = int(cfg.get("cpu_threads", 0) or 0)
    key = (model_size, device, compute_type, threads)

    with _model_lock:
        if _local_model is not None and _local_key == key:
            return _local_model

        log.info(
            f"Loading Whisper model '{model_size}' on {device}/{compute_type} "
            f"(cpu_threads={threads or 'auto'}) ..."
        )

        def build(name, dev, ctype):
            return WhisperModel(resolve_model(name), device=dev,
                                compute_type=ctype, cpu_threads=threads)

        actual = model_size
        try:
            model = build(model_size, device, compute_type)
        except Exception as e:
            # Unsupported compute type or a CUDA build mismatch.
            if device != "cpu":
                log.warning(f"Could not load on {device} ({e}); retrying on CPU/int8")
                model = build(model_size, "cpu", "int8")
            else:
                # Most likely no network on first run. Rather than fail every
                # dictation, use a model that is already downloaded.
                cached = [m for m in _cached_models() if m != model_size]
                if not cached:
                    raise
                # Smallest complete model first: it is the fastest, and the
                # point here is to stay usable rather than to be accurate.
                fallback = cached[0]
                log.warning(
                    f"Could not load '{model_size}' ({type(e).__name__}). "
                    f"Falling back to cached model '{fallback}'. Set "
                    f"whisper_model to a cached model, or reconnect and restart."
                )
                # "int8", not the requested compute_type: an unsupported
                # compute_type is one of the things that lands us here, and
                # reusing it would fail again - from inside this except block, so
                # the user would get a chained traceback and every dictation
                # would fail. int8 is supported everywhere CTranslate2 runs.
                model = build(fallback, "cpu", "int8")
                actual = fallback

        _local_model = model
        # Cache under the REQUESTED key, not the one we ended up with. Keying on
        # the fallback would make every later call miss the cache and retry the
        # load that just failed, adding seconds to every single dictation.
        _local_key = key
        # Which model is actually answering. Because the cache key is the
        # requested name, this is the only way anything outside this function can
        # tell that a substitution happened - and a user dictating all day on a
        # fallback model has a right to be told. doctor.py reports it.
        global loaded_model_name
        loaded_model_name = actual
        log.info(f"Model '{actual}' ready"
                 + (f" (requested '{model_size}')" if actual != model_size else ""))
        return _local_model


def preload(cfg: dict):
    """Warm the local model so the first dictation isn't slow. Safe to call twice."""
    if str(cfg.get("transcribe_backend", "local")).lower() != "local":
        return
    if not cfg.get("preload_model", True):
        return
    try:
        _load_local(cfg)
    except Exception as e:
        log.error(f"Model preload failed (will retry on first dictation): {e}")
    # Warm the caption model too, so the first preview isn't a cold load.
    if cfg.get("live_preview", DEFAULTS["live_preview"]) and cfg.get("preview_model"):
        try:
            _load_preview(cfg)
        except Exception as e:
            log.warning(f"Preview model unavailable, captions disabled: {e}")


_preview_model = None
_preview_key = None
_preview_lock = threading.Lock()


def _load_preview(cfg: dict):
    """
    Load the small model used for live captions.

    A separate, smaller model is worth the extra memory: previews run repeatedly
    while you speak, and using the main model made each pass take as long as the
    final transcription, so captions lagged seconds behind the speech.
    """
    global _preview_model, _preview_key

    name = cfg.get("preview_model") or cfg.get("whisper_model", "base")
    if name == cfg.get("whisper_model"):
        return _load_local(cfg)         # same model, reuse the one instance

    threads = int(cfg.get("cpu_threads", 0) or 0)
    key = (name, threads)
    with _preview_lock:
        if _preview_model is not None and _preview_key == key:
            return _preview_model
        from faster_whisper import WhisperModel
        log.info(f"Loading preview model '{name}' for live captions ...")
        _preview_model = WhisperModel(resolve_model(name), device="cpu",
                                      compute_type="int8",
                                      cpu_threads=threads)
        _preview_key = key
        return _preview_model


def transcribe_array(audio, cfg: dict) -> str:
    """
    Transcribe raw float32 mono audio, for the live preview during recording.

    Kept separate from transcribe() because it skips the WAV round-trip and is
    deliberately cheap: small model, no VAD, greedy, no timestamps. Preview text
    is display-only; the final pass re-transcribes the complete recording.
    """
    model = _load_preview(cfg)
    segments, _ = model.transcribe(
        audio,
        beam_size=1,
        language=cfg.get("language") or None,
        initial_prompt=cfg.get("initial_prompt") or None,
        vad_filter=False,
        # The live caption, deliberately unlike the final pass: this runs
        # repeatedly while the user is still speaking, so it is tuned for speed
        # over quality and the text it shows is never what gets pasted.
        without_timestamps=True,
        condition_on_previous_text=False,
    )
    text = " ".join(seg.text.strip() for seg in segments).strip()
    # Previews use the same prompt, so they can echo it too. Showing prompt
    # text back to the user as their own words is worse than showing nothing.
    if leaked_prompt(text, cfg.get("initial_prompt") or ""):
        return ""
    return text


def _tokens(text: str) -> list[str]:
    out = []
    for ch in (text or "").lower():
        out.append(ch if (ch.isalnum() or ch.isspace()) else " ")
    return "".join(out).split()


def leaked_prompt(text: str, prompt: str) -> bool:
    """
    True if the transcript looks like the initial_prompt echoed back.

    Whisper conditions on initial_prompt as if it were text it had just
    transcribed, so with unclear audio it can simply continue the prompt. The
    result is confidently pasted words the user never said, which is the worst
    possible failure for a dictation tool - much worse than pasting nothing.

    Leakage means Whisper *continued* the prompt, so the evidence is a run of
    words in the prompt's own order. Vocabulary overlap is not evidence: the
    recommended prompt is a list of the commonest Hinglish words, so "how much of
    this transcript appears somewhere in the prompt" is high for any genuine
    Hinglish sentence. An earlier version tested exactly that (`covered >= 0.85`,
    plus "every word is in the prompt" for short transcripts) and discarded real
    dictations - measured against the default prompt:

        "aaj office meeting hai"                 -> flagged
        "theek hai"                              -> flagged
        "abhi thoda kaam hai matlab meeting kal" -> flagged

    A discarded dictation is silent: nothing is pasted. And the guard got
    *stricter* the more vocabulary the user added, which is backwards.
    """
    t, p = _tokens(text), _tokens(prompt)
    if not t or not p:
        return False

    run = _longest_shared_run(t, p)
    # Four words of the prompt in the prompt's order is a continuation. Three is
    # only a continuation if it is most of what came back.
    return run >= 4 or (run >= 3 and run / len(t) >= 0.6)


def _longest_shared_run(t: list[str], p: list[str]) -> int:
    """Length of the longest run of tokens appearing contiguously in both."""
    prev = [0] * (len(p) + 1)
    best = 0
    for i in range(1, len(t) + 1):
        cur = [0] * (len(p) + 1)
        ti = t[i - 1]
        for j in range(1, len(p) + 1):
            if ti == p[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def _decode_wav(path: Path) -> np.ndarray:
    """
    Read a WAV into the float32 mono 16 kHz array Whisper wants.

    **This exists to keep PyAV out of the build.** Handing faster-whisper a file
    path makes it call `decode_audio`, which decodes with PyAV, which bundles the
    FFmpeg libraries: 62.6 MB, 12.9% of the installed application, to read a WAV
    that we wrote ourselves moments earlier. Passing the samples directly removes
    the dependency entirely.

    Deliberately reproduces what `faster_whisper.audio.decode_audio` does rather
    than doing something equivalent-looking: it resamples to signed 16-bit mono at
    16 kHz and then divides by 32768.0. Our recorder already writes signed 16-bit,
    so for the default configuration this is bit-for-bit the same array PyAV
    produced - verified against all 30 corpus clips, not assumed.

    The two conversions below only run on configurations the default never
    reaches, and they are the one place this is *not* identical to PyAV:

      channels > 1   averaged, matching FFmpeg's stereo-to-mono downmix
      rate != 16 kHz linear interpolation, which is cruder than FFmpeg's
                     polyphase resampler

    Both are reachable because `sample_rate` and `channels` are configurable
    (8-48 kHz, 1-2 channels). Recording at anything other than 16 kHz mono is
    pointless work for a model that only accepts 16 kHz mono, so this logs a
    warning rather than silently doing a worse job than it used to.
    """
    with wave.open(str(path), "rb") as wf:
        channels = wf.getnchannels()
        width = wf.getsampwidth()
        rate = wf.getframerate()
        raw = wf.readframes(wf.getnframes())

    if width != 2:
        raise RuntimeError(
            f"{path.name} is {width * 8}-bit; Casper Flow records 16-bit. "
            f"Set sample_rate/channels back to their defaults and try again."
        )

    # int16 -> float32 in [-1, 1). The divisor is 32768.0, matching decode_audio;
    # using 32767 would introduce a tiny gain difference and break bit-equality.
    audio = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0

    if channels > 1:
        usable = (audio.shape[0] // channels) * channels
        audio = audio[:usable].reshape(-1, channels).mean(axis=1)
        log.warning(
            f"Recorded {channels} channels; downmixing to mono. "
            f"Set channels to 1 - Whisper only uses mono."
        )

    if rate != WHISPER_RATE:
        n_out = int(round(audio.shape[0] * WHISPER_RATE / rate))
        audio = np.interp(
            np.linspace(0.0, audio.shape[0] - 1, n_out),
            np.arange(audio.shape[0], dtype=np.float64),
            audio,
        ).astype(np.float32)
        log.warning(
            f"Recorded at {rate} Hz; resampling to {WHISPER_RATE} Hz by linear "
            f"interpolation, which may cost accuracy. Set sample_rate to "
            f"{WHISPER_RATE}."
        )

    return np.ascontiguousarray(audio)


def _transcribe_local(audio_path: Path, cfg: dict) -> str:
    model = _load_local(cfg)
    audio = _decode_wav(audio_path)

    t0 = time.perf_counter()
    segments, info = model.transcribe(
        audio,
        # Greedy decoding. Measured no slower than beam search on short
        # dictation, where the encoder dominates, and it avoids the worst case
        # on longer clips.
        beam_size=int(cfg.get("beam_size", 1)),
        # Pinning the language avoids Whisper mis-detecting on short clips and
        # "translating" your dictation into another language.
        language=cfg.get("language") or None,
        # Primes vocabulary and script. The largest single quality lever for
        # code-mixed speech, at no latency cost. See config.py.
        initial_prompt=cfg.get("initial_prompt") or None,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
        condition_on_previous_text=False,
        # Timestamps ON, even though we paste plain text and never read them.
        #
        # This was `without_timestamps=True` on the reasoning that per-word timings
        # are wasted work. They are - but suppressing them is not free, because
        # Whisper is trained with timestamp tokens interleaved through the
        # transcript. Removing them takes the decoder off the distribution it
        # learned, and it decodes worse.
        #
        # Measured over the 30-recording corpus (corpus/ACCURACY.md), accuracy as
        # 1 - fair WER:
        #
        #                    overall   hindi   code-switch   long
        #   suppressed        64.8%    68.9%      81.0%      59.6%
        #   timestamps on     65.6%    88.9%      79.6%      61.3%
        #
        # Twenty points on Hindi for tokens we discard. One example, same audio:
        #
        #   suppressed     "To phaah hi kahaan rakhi hai?"
        #   timestamps on  "Vah file kahaan rakhi hai?"     (said: woh file kahan rakhi hai)
        #
        # It also punctuates better, including question marks, which the rules
        # cleanup cannot produce at all.
        without_timestamps=False,
    )

    text = " ".join(seg.text.strip() for seg in segments).strip()
    lang = getattr(info, "language", "?")
    # The transcript itself goes to DEBUG. casper.log is a plaintext file beside
    # the executable that is never rotated, and INFO is the level that ships, so
    # logging it here wrote every dictation to disk forever - on a tool whose
    # entire pitch is that your voice never leaves the machine. INFO keeps the
    # shape of the event (language, timing, length), which is what a support
    # question needs.
    log.info(
        f"Local transcript ({lang}) in {time.perf_counter() - t0:.2f}s, "
        f"{len(text)} chars"
    )
    log.debug(f"Local transcript text: {text!r}")

    prompt = cfg.get("initial_prompt") or ""
    if prompt and leaked_prompt(text, prompt):
        log.warning(
            "Transcript looks like the initial_prompt echoed back; "
            "re-transcribing without it"
        )
        log.debug(f"Suspected prompt echo: {text!r}")
        segments, info = model.transcribe(
            # Reuses the decoded array; re-reading the file would decode twice.
            audio,
            beam_size=int(cfg.get("beam_size", 1)),
            language=cfg.get("language") or None,
            initial_prompt=None,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
            condition_on_previous_text=False,
            # Same as the first pass, for the reasons above. A retry that decoded
            # under different settings would not be comparable to what it replaces.
            without_timestamps=False,
        )
        retry = " ".join(seg.text.strip() for seg in segments).strip()
        log.debug(f"Retry without prompt: {retry!r}")
        # If it still matches the prompt the audio had nothing usable in it, and
        # pasting nothing is the correct outcome.
        text = "" if leaked_prompt(retry, prompt) else retry

    return text


# ---------------------------------------------------------------- groq

# Upload-and-transcribe ceiling for the cloud backends. Deliberately not
# `llm_timeout_seconds`: that setting documents itself as the ceiling on the
# *polish* call and defaults to 20s, which is a sensible wait for a text rewrite
# and far too short to upload a five-minute WAV (max_record_seconds allows 300)
# on an Indian home uplink. Sharing the two made a long recording fail on a
# setting the user had tuned for something else.
_CLOUD_TIMEOUT = 120.0


def _transcribe_groq(audio_path: Path, cfg: dict) -> str:
    api_key = cfg.get("groq_api_key", "")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set in .env")

    try:
        from groq import Groq
    except ImportError:
        raise RuntimeError("groq package not installed. Run: pip install groq")

    model = cfg.get("groq_whisper_model", "whisper-large-v3-turbo")
    client = Groq(api_key=api_key, timeout=_CLOUD_TIMEOUT)
    with open(audio_path, "rb") as f:
        kwargs = {
            "file": (audio_path.name, f.read()),
            "model": model,
            "response_format": "text",
            "language": cfg.get("language") or None,
        }
        if cfg.get("initial_prompt"):
            kwargs["prompt"] = cfg["initial_prompt"]
        resp = client.audio.transcriptions.create(**kwargs)
    text = (resp if isinstance(resp, str) else resp.text).strip()
    log.info(f"Groq transcript: {len(text)} chars")
    log.debug(f"Groq transcript text: {text!r}")
    return text


# -------------------------------------------------------------- openai

def _transcribe_openai(audio_path: Path, cfg: dict) -> str:
    api_key = cfg.get("openai_api_key", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set in .env")

    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("openai package not installed. Run: pip install openai")

    model = cfg.get("openai_whisper_model", "gpt-4o-mini-transcribe")
    client = OpenAI(api_key=api_key, timeout=_CLOUD_TIMEOUT)
    with open(audio_path, "rb") as f:
        kwargs = {"model": model, "file": f, "response_format": "text"}
        if cfg.get("language"):
            kwargs["language"] = cfg["language"]
        if cfg.get("initial_prompt"):
            kwargs["prompt"] = cfg["initial_prompt"]
        resp = client.audio.transcriptions.create(**kwargs)
    text = (resp if isinstance(resp, str) else resp.text).strip()
    log.info(f"OpenAI transcript: {len(text)} chars")
    log.debug(f"OpenAI transcript text: {text!r}")
    return text
