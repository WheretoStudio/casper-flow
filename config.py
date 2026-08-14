"""
Config loader for Casper Flow.

Priority (highest -> lowest):
  1. settings.json  (user editable, lives next to main.py)
  2. .env           (API keys - never commit)
  3. Hard-coded defaults below

Unknown keys in settings.json are kept (forward compatible) but a warning is
logged so typos like "hotkeys" don't silently do nothing.
"""

import json
import os
import logging
from pathlib import Path

from paths import DATA_DIR, resource_file

ROOT = DATA_DIR
# User-writable, so it must sit beside the executable rather than inside the
# frozen bundle - see paths.py.
SETTINGS_FILE = ROOT / "settings.json"

# The only sample rate Whisper accepts. Declared here, next to the settings it
# constrains, and imported by transcribe.py so the number exists once.
WHISPER_RATE = 16000

# Machine-specific overrides, applied on top of settings.json and never
# committed. Lets a converted local model or a tuned hotkey be used without
# editing the file that ships as everyone's default.
LOCAL_SETTINGS_FILE = ROOT / "settings.local.json"
ENV_FILE = ROOT / ".env"

log = logging.getLogger("casper.config")

DEFAULTS = {
    # -- Hotkey ---------------------------------------------------------
    # A single key ("caps lock", "right ctrl", "f8") or a combo
    # ("ctrl+space", "ctrl+alt+d"). Hold it to record.
    #
    # Caps Lock is present on every Windows keyboard and nothing else uses it as
    # a hold. Its toggle is suppressed while Casper Flow runs.
    #
    # Scroll Lock, Pause and F13-F24 are absent from most laptops. Fn is handled
    # in keyboard firmware and emits no scan code, so it cannot be bound. Run
    # pick_hotkey.py to see what your keyboard actually sends.
    "hotkey": "caps lock",
    # Stop the trigger key doing its normal job while Casper Flow is holding it.
    # Only applied when the full combo matches, so a plain space still types.
    "suppress_hotkey": True,
    # How long the hotkey must be held before the press counts as dictation.
    # A shorter press is discarded and the keystroke is replayed, so tapping
    # Caps Lock still toggles Caps Lock.
    #
    # A commitment threshold, not a delay: capture starts on key-down, so
    # nothing said is lost. Anything held for less than this yields no text.
    "min_hold_seconds": 2.0,
    # Safety ceiling: if the key still looks held after this long, assume the
    # release event was lost and end the hold. Only used when suppress_hotkey
    # is true, because suppression hides the real key state from the OS.
    "max_hold_seconds": 120,

    # -- Privacy --------------------------------------------------------
    # Refuse every backend that would send audio or text off this machine,
    # whatever else the config says. Enforced in transcribe.py and llm_polish.py
    # rather than by convention. Localhost services such as Ollama stay allowed.
    "offline_only": True,

    # -- Transcription backend ------------------------------------------
    # "local"  -> faster-whisper, fully offline (the only option that runs
    #             under offline_only)
    # "groq" / "openai" -> cloud APIs, blocked while offline_only is true
    "transcribe_backend": "local",

    # faster-whisper model.
    #
    # "swift-ct2" is a Hinglish fine-tune converted for CTranslate2 and bundled
    # in the installer. "base.en" is also bundled and is much better on pure
    # English. Neither is usable for the other's job, which is why Settings >
    # Language offers both rather than picking one; see corpus/RESULTS.md.
    #
    # Other values are HuggingFace names, downloaded on first use:
    #   tiny      fastest, adequate for short commands
    #   base      multilingual, general-purpose
    #   small     more accurate, ~3x slower
    #   large-v3  too slow on a 2-core CPU; use the Groq backend instead
    "whisper_model": "swift-ct2",
    "whisper_device": "cpu",          # "cpu" or "cuda"
    "whisper_compute_type": "int8",   # int8 / float16 / float32
    # 0 = let CTranslate2 decide. Setting this to your core count helps.
    "cpu_threads": 0,
    # Beam search width. 1 is greedy.
    #
    # 5 buys ~2.5 points of overall accuracy and ~6 on proper nouns over greedy,
    # and costs about a second of median latency on a two-core CPU
    # (corpus/ACCURACY.md). Drop to 1 for speed; the text stays usable but misses
    # more names.
    "beam_size": 5,

    # Dictation language as an ISO code, or null to detect it per recording.
    #
    # "en" is right for the bundled Hinglish model even when dictating Hindi
    # words: Whisper treats romanised Hinglish as English, which is what the
    # fine-tune emits. Pinning it is accuracy-neutral and 46% faster than
    # auto-detect, which spends a second per phrase concluding "en" anyway.
    #
    # Use null on a general-purpose model (base, small) fed both languages. There
    # pinning corrupts both directions: "en" turns "kal ek meeting hai" into "the
    # luck meeting", "hi" turns plain English into transliterated nonsense.
    "language": "en",

    # Vocabulary hint supplied to the decoder as preceding context, biasing
    # spelling and script.
    #
    # Must be a comma-separated word list, never sentences. Whisper treats this
    # as text it was already transcribing and will continue it, so a
    # sentence-shaped prompt gets pasted verbatim whenever the audio is unclear.
    # transcribe.leaked_prompt() catches what gets through.
    #
    # settings.json ships this as null: on the bundled Hinglish model priming
    # lowered code-switch accuracy and added 39% latency, a model already trained
    # on Hinglish needing no push towards it. Kept here as the starting point for
    # general-purpose models, where it does help, and as a bench_hinglish.py case.
    "initial_prompt": (
        "Hinglish: kal, aaj, abhi, thoda, matlab, theek hai, meeting, report, "
        "bhej dena, kar dena, ho gaya, chahiye, office, update, client."
    ),

    # Load the local model at startup instead of on first dictation.
    "preload_model": True,

    # Model for the live caption only; keep it smaller than whisper_model, since
    # previews run repeatedly while you talk. Pasted text never comes from this
    # model. null reuses whisper_model rather than loading a second one.
    "preview_model": None,

    # Cloud transcription model IDs.
    #   groq   : whisper-large-v3-turbo (fastest hosted option in practice)
    #   openai : gpt-4o-mini-transcribe is quick and cheap; "gpt-transcribe"
    #            is more accurate; "whisper-1" is the legacy endpoint.
    "groq_whisper_model": "whisper-large-v3-turbo",
    "openai_whisper_model": "gpt-4o-mini-transcribe",

    # -- LLM polish -----------------------------------------------------
    # Script for the final text when you mix languages:
    #   "latin"      Roman script throughout - "kal meeting hai" (default,
    #                and what most Hinglish users type)
    #   "devanagari" Hindi words in Devanagari - "कल मीटिंग है"
    #   "as-is"      leave whatever the speech model produced
    # Only applies when the polish step runs, since it does the conversion.
    "output_script": "latin",

    "llm_polish": True,
    # "rules"  -> built-in deterministic cleanup. No model, no network, no
    #             dependencies, and it cannot invent words. Default.
    # "ollama" -> local LLM on localhost for smarter rewriting and
    #             Devanagari -> Roman transliteration. Still fully private.
    # "openai" | "anthropic" | "groq" -> cloud. Blocked under offline_only.
    "llm_backend": "rules",
    "llm_model": "gpt-4o-mini",
    # Interjections removed by the "rules" backend. Kept short: ambiguous words
    # ("like", "matlab", "actually") can carry meaning and are left alone.
    "filler_words": ["um", "uh", "uhh", "umm", "uhm", "er", "erm", "hmm",
                     "mmm", "ahh"],
    # Hard ceiling on the polish call. If it takes longer we paste raw text
    # rather than leaving you staring at a dead cursor.
    "llm_timeout_seconds": 20,

    "ollama_url": "http://localhost:11434",
    "ollama_model": "llama3",

    # -- Formatting -----------------------------------------------------
    # How the finished text is laid out. The only part of the pipeline allowed to
    # write words the user did not say, so both settings default to off and
    # neither does anything without a generative backend.
    #
    #   plain    cleanup only
    #   message  short, with bullets only where the speech listed things
    #   email    greeting, paragraphs, numbered steps where speech enumerated
    #
    # Set explicitly rather than inferred from the focused window: a wrong guess
    # is invisible until the message has been sent.
    "format_mode": "plain",
    # Grammar repair. Separate from format_mode because a bad layout change is
    # obvious and a swapped tense or negation is not.
    "grammar_fix": False,

    # -- Audio ----------------------------------------------------------
    # Fixed, not a preference: Whisper accepts 16 kHz mono only, and _validate()
    # pins this back to WHISPER_RATE if it is changed.
    "sample_rate": WHISPER_RATE,
    "channels": 1,
    # null = system default input device. Can be an index or a name substring.
    "input_device": None,
    # -- Corrections ----------------------------------------------------
    # Proper nouns are the weakest category measured, at roughly half the accuracy
    # of code-switched speech generally. No speech model has heard of your
    # colleagues, so the fix is naming them here rather than a bigger model.
    #
    # Names, companies and jargon, matched case-insensitively against the
    # transcript.
    "vocabulary": [],
    # Explicit "heard this, meant that" pairs, applied first and exactly, for a
    # mistake that keeps recurring:
    #   "corrections": {"thank you office": "Bangalore office"}
    "corrections": {},

    # Safety cap so a stuck key can't eat all your RAM.
    "max_record_seconds": 300,
    # Open the microphone stream once and reuse it. Opening costs ~1.3 s, which
    # paid on the hotkey press would put the mic live after the key was already
    # released. A stopped stream captures nothing, so this does not listen when
    # idle. Set false to release the device between dictations and accept the
    # delay on the next one.
    "keep_mic_open": True,

    # -- On-screen overlay ----------------------------------------------
    "show_pill": True,
    # "caption" -> live captions: shows words as they are recognised (default)
    # "blob"    -> organic animated blob with waveform, no text
    # "capsule" -> compact dark bar with label, meter and timer
    "pill_style": "blob",
    # Transcribe periodically while you speak so the caption updates live.
    # Display only: the final text always comes from a fresh pass over the
    # whole recording. Turn off to save CPU on a slow machine.
    "live_preview": False,
    "preview_interval_seconds": 1.0,
    # "bottom-center" | "bottom-right" | "top-center" | "center"
    "pill_position": "bottom-center",
    # 0.5-3.0, useful on high-DPI screens or if you want it smaller
    "pill_scale": 1.0,

    # -- Paste ----------------------------------------------------------
    # Delay before Ctrl+V so the target window has focus back.
    "paste_settle_seconds": 0.06,
    # Delay before the original clipboard is put back.
    "clipboard_restore_seconds": 0.4,

    # -- Misc -----------------------------------------------------------
    "launch_at_login": False,

    # Set once the first-run wizard has completed. Until then it opens on startup.
    "setup_complete": False,
}

# Settings that settings.local.json is forcing to a different value than
# settings.json asked for. Populated by load_config, read by doctor.py. Kept out
# of the config dict so save_config cannot write it back out.
LOCAL_OVERRIDES: list[str] = []

# Keys that come from .env, never written back to settings.json
SECRET_KEYS = ("openai_api_key", "groq_api_key", "anthropic_api_key")


def _strip_value(val: str) -> str:
    """
    Strip whitespace, surrounding quotes and an unquoted trailing comment.

    Without the comment handling, `GROQ_API_KEY=abc123 # work key` yields a key
    with the comment attached and fails authentication as though it were simply
    wrong. Quoted values are left alone: "#" is legal inside one.
    """
    val = val.strip()
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
        return val[1:-1]
    # " #" rather than "#", so a value that genuinely contains a hash survives.
    head, sep, _ = val.partition(" #")
    return head.strip() if sep else val


def _load_env():
    """Parse .env into os.environ. Handles quotes and `export KEY=VALUE`."""
    if not ENV_FILE.exists():
        return
    try:
        lines = ENV_FILE.read_text(encoding="utf-8-sig").splitlines()
    except Exception as e:
        log.warning(f"Could not read .env: {e}")
        return

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.lower().startswith("export "):
            line = line[7:]
        key, _, val = line.partition("=")
        key = key.strip()
        if not key:
            continue
        # Real environment variables win over .env
        os.environ.setdefault(key, _strip_value(val))


def _validate(cfg: dict) -> dict:
    """Clamp / correct obviously bad values so the app still starts."""
    from hotkey import FALLBACK_HOTKEY, unsafe_bare_modifier

    spec = str(cfg.get("hotkey", DEFAULTS["hotkey"]))
    reason = unsafe_bare_modifier(spec)
    if reason:
        log.warning(reason + f" Falling back to {FALLBACK_HOTKEY!r}.")
        cfg["hotkey"] = FALLBACK_HOTKEY

    tb = str(cfg.get("transcribe_backend", "local")).lower()
    if tb not in ("local", "groq", "openai"):
        log.warning(f"Invalid transcribe_backend {tb!r}; falling back to 'local'")
        tb = "local"
    cfg["transcribe_backend"] = tb

    lb = str(cfg.get("llm_backend", "rules")).lower()
    if lb not in ("rules", "ollama", "openai", "anthropic", "groq"):
        log.warning(f"Invalid llm_backend {lb!r}; disabling polish")
        cfg["llm_polish"] = False
    else:
        cfg["llm_backend"] = lb

    # Whisper accepts 16 kHz mono only, so any other rate needs resampling, and
    # with PyAV out of the build the in-process fallback is linear interpolation.
    # Pinned rather than resampled badly: sounddevice asks the device for 16 kHz
    # and lets the driver convert, which is where that belongs.
    rate = cfg.get("sample_rate", WHISPER_RATE)
    if rate != WHISPER_RATE:
        log.warning(
            f"sample_rate={rate} is not supported; using {WHISPER_RATE}. "
            f"Whisper only accepts {WHISPER_RATE} Hz and your audio device "
            f"handles the conversion."
        )
    cfg["sample_rate"] = WHISPER_RATE

    for key, lo, hi in (
        ("channels", 1, 2),
        ("max_record_seconds", 5, 3600),
        ("llm_timeout_seconds", 1, 300),
        # Above ~10s every realistic dictation is discarded, which presents as
        # the hotkey doing nothing.
        ("min_hold_seconds", 0.0, 10.0),
        ("max_hold_seconds", 5, 3600),
    ):
        try:
            v = type(DEFAULTS[key])(cfg.get(key, DEFAULTS[key]))
        except (TypeError, ValueError):
            v = DEFAULTS[key]
        if not (lo <= v <= hi):
            log.warning(f"{key}={v} out of range [{lo},{hi}]; using {DEFAULTS[key]}")
            v = DEFAULTS[key]
        cfg[key] = v

    lang = cfg.get("language")
    if isinstance(lang, str):
        lang = lang.strip().lower() or None
    cfg["language"] = lang

    script = str(cfg.get("output_script", "latin")).lower()
    if script not in ("latin", "devanagari", "as-is"):
        log.warning(f"Invalid output_script {script!r}; using 'latin'")
        script = "latin"
    cfg["output_script"] = script

    mode = str(cfg.get("format_mode", "plain")).strip().lower()
    if mode not in ("plain", "message", "email"):
        log.warning(f"Invalid format_mode {mode!r}; using 'plain'")
        mode = "plain"
    cfg["format_mode"] = mode
    cfg["grammar_fix"] = bool(cfg.get("grammar_fix", False))

    # Both features are generative and the default cleanup backend is not, which
    # would otherwise present as unformatted text with no explanation.
    if (mode != "plain" or cfg["grammar_fix"]) and \
            str(cfg.get("llm_backend", "rules")).lower() == "rules":
        log.warning(
            f"format_mode={mode!r} grammar_fix={cfg['grammar_fix']} need a "
            f"language model, and llm_backend is 'rules', which cannot write "
            f"text. Install Ollama and set llm_backend to 'ollama', or these "
            f"settings will do nothing."
        )

    style = str(cfg.get("pill_style", DEFAULTS["pill_style"])).lower()
    if style not in ("caption", "blob", "capsule"):
        log.warning(
            f"Invalid pill_style {style!r}; using {DEFAULTS['pill_style']!r}")
        style = DEFAULTS["pill_style"]
    cfg["pill_style"] = style

    position = str(cfg.get("pill_position", DEFAULTS["pill_position"])).lower()
    if position not in ("bottom-center", "bottom-right", "top-center", "center"):
        log.warning(
            f"Invalid pill_position {position!r}; using "
            f"{DEFAULTS['pill_position']!r}")
        position = DEFAULTS["pill_position"]
    cfg["pill_position"] = position

    device = str(cfg.get("whisper_device", DEFAULTS["whisper_device"])).lower()
    if device not in ("cpu", "cuda", "auto"):
        log.warning(f"Invalid whisper_device {device!r}; using 'cpu'")
        device = "cpu"
    cfg["whisper_device"] = device

    # An unsupported value fails the model load on every dictation, and the
    # missing-model fallback cannot rescue it.
    ctype = str(cfg.get("whisper_compute_type",
                        DEFAULTS["whisper_compute_type"])).lower()
    if ctype not in ("int8", "int8_float16", "int8_float32", "int16",
                     "float16", "bfloat16", "float32", "default"):
        log.warning(f"Invalid whisper_compute_type {ctype!r}; using 'int8'")
        ctype = "int8"
    cfg["whisper_compute_type"] = ctype

    # These two go straight to CTranslate2, where a zero or negative value is an
    # error rather than a default.
    for key, lo, hi in (("cpu_threads", 0, 256), ("beam_size", 1, 20)):
        try:
            v = int(cfg.get(key, DEFAULTS[key]))
        except (TypeError, ValueError):
            v = DEFAULTS[key]
        if not (lo <= v <= hi):
            log.warning(f"{key}={v} out of range [{lo},{hi}]; using {DEFAULTS[key]}")
            v = DEFAULTS[key]
        cfg[key] = v

    for key, lo, hi in (
        ("pill_scale", 0.5, 3.0),
        # A zero interval would spin the preview thread against the transcriber.
        ("preview_interval_seconds", 0.2, 10.0),
        ("paste_settle_seconds", 0.0, 2.0),
        ("clipboard_restore_seconds", 0.05, 10.0),
    ):
        try:
            v = float(cfg.get(key, DEFAULTS[key]))
        except (TypeError, ValueError):
            v = DEFAULTS[key]
        if not (lo <= v <= hi):
            log.warning(f"{key}={v} out of range [{lo},{hi}]; using {DEFAULTS[key]}")
            v = DEFAULTS[key]
        cfg[key] = v

    # Individually in range, nonsensical together: every dictation would be
    # discarded as too short before it could ever be too long.
    if cfg["min_hold_seconds"] >= cfg["max_hold_seconds"]:
        log.warning(
            f"min_hold_seconds={cfg['min_hold_seconds']} is not less than "
            f"max_hold_seconds={cfg['max_hold_seconds']}; using the defaults for "
            f"both"
        )
        cfg["min_hold_seconds"] = DEFAULTS["min_hold_seconds"]
        cfg["max_hold_seconds"] = DEFAULTS["max_hold_seconds"]

    # A bare string would be iterated per character, stripping every standalone
    # "u" and "m" from the transcript.
    fillers = cfg.get("filler_words")
    if fillers is not None and not isinstance(fillers, (list, tuple)):
        log.warning(
            f"filler_words must be a list of words, not "
            f"{type(fillers).__name__}; using the defaults"
        )
        cfg["filler_words"] = list(DEFAULTS["filler_words"])

    # An English-only model cannot produce Hindi, and the output is unusable
    # rather than merely worse.
    model = str(cfg.get("whisper_model", ""))
    if model.endswith(".en") and cfg.get("initial_prompt"):
        log.warning(
            f"whisper_model={model!r} is English-only, so Hindi words cannot be "
            f"transcribed. Use a multilingual model such as 'base' for Hinglish."
        )
    return cfg


def _strip_comments(data):
    """
    Drop "//" keys.

    JSON has no comment syntax, so the shipped settings.json documents itself
    with "//" keys. They are comments, not unrecognised settings.
    """
    if not isinstance(data, dict):
        return data
    return {k: v for k, v in data.items() if not str(k).startswith("//")}


def load_config() -> dict:
    _load_env()
    cfg = dict(DEFAULTS)

    if SETTINGS_FILE.exists():
        try:
            user = _strip_comments(
                json.loads(SETTINGS_FILE.read_text(encoding="utf-8-sig")))
            if not isinstance(user, dict):
                raise ValueError("settings.json must contain a JSON object")
            unknown = sorted(set(user) - set(DEFAULTS))
            if unknown:
                log.warning(f"Unrecognised settings.json keys (ignored by app): {unknown}")
            cfg.update(user)
            log.info(f"Loaded settings from {SETTINGS_FILE}")
        except Exception as e:
            log.warning(f"Could not parse settings.json ({e}); using defaults")
    else:
        try:
            # Prefer the settings.json inside the frozen bundle over dumping
            # DEFAULTS, so the first file the user sees keeps its "//" comments.
            shipped = resource_file("settings.json")
            if shipped.exists() and shipped != SETTINGS_FILE:
                SETTINGS_FILE.write_text(
                    shipped.read_text(encoding="utf-8-sig"), encoding="utf-8")
            else:
                SETTINGS_FILE.write_text(
                    json.dumps(DEFAULTS, indent=2), encoding="utf-8")
            log.info(f"Created default settings.json at {SETTINGS_FILE}")
        except Exception as e:
            log.warning(f"Could not write settings.json: {e}")

    # Applied last so it wins, and validated with everything else so a bad value
    # here degrades exactly as it would in settings.json.
    if LOCAL_SETTINGS_FILE.exists():
        try:
            local = _strip_comments(
                json.loads(LOCAL_SETTINGS_FILE.read_text(encoding="utf-8-sig")))
            if not isinstance(local, dict):
                raise ValueError("settings.local.json must contain a JSON object")
            unknown = sorted(set(local) - set(DEFAULTS))
            if unknown:
                log.warning(
                    f"Unrecognised settings.local.json keys (ignored): {unknown}"
                )
            # Only the keys that actually change a value, not those restating it.
            # These are what make the Settings window look broken: it writes
            # settings.json, this file is applied afterwards and wins, so the
            # setting reverts with nothing to explain why. Hence WARNING.
            pinned = sorted(k for k in set(local) & set(DEFAULTS)
                            if cfg.get(k) != local[k])
            cfg.update(local)
            if pinned:
                log.warning(
                    f"{LOCAL_SETTINGS_FILE.name} is overriding {pinned}. "
                    f"Changing these in the Settings window will have no effect "
                    f"until they are removed from that file."
                )
            log.info(
                f"Applied local overrides from {LOCAL_SETTINGS_FILE.name}: "
                f"{sorted(set(local) & set(DEFAULTS))}"
            )
            global LOCAL_OVERRIDES
            LOCAL_OVERRIDES = pinned
        except Exception as e:
            log.warning(f"Could not parse settings.local.json ({e}); ignoring it")

    cfg = _validate(cfg)

    # Inject API keys from environment (never persisted to settings.json)
    cfg["openai_api_key"] = os.environ.get("OPENAI_API_KEY", "")
    cfg["groq_api_key"] = os.environ.get("GROQ_API_KEY", "")
    cfg["anthropic_api_key"] = os.environ.get("ANTHROPIC_API_KEY", "")

    return cfg


def api_key_for(backend: str, cfg: dict) -> str:
    """Return the API key a given backend needs ('' when none/not required)."""
    return {
        "openai": cfg.get("openai_api_key", ""),
        "groq": cfg.get("groq_api_key", ""),
        "anthropic": cfg.get("anthropic_api_key", ""),
        "ollama": "n/a",   # local server, no key
        "local": "n/a",    # local model, no key
        "rules": "n/a",    # built-in cleanup, no key
    }.get(backend, "")


def save_config(cfg: dict):
    """
    Persist non-secret settings back to settings.json.

    Written to a temp file and moved into place. write_text truncates first, so
    an interrupted write leaves a file load_config cannot parse and replaces with
    the defaults, losing the user's hotkey, vocabulary and corrections.
    os.replace is atomic on Windows: the file is either the old settings or the
    new ones.
    """
    out = {k: cfg[k] for k in DEFAULTS if k in cfg and k not in SECRET_KEYS}
    tmp = SETTINGS_FILE.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(out, indent=2), encoding="utf-8")
        os.replace(tmp, SETTINGS_FILE)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    log.info("settings.json saved")
