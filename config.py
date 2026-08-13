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
# committed. This is how a converted local model or a tuned hotkey can be used
# without editing the file that ships as everyone's default. .gitignore has
# referred to this file for some time; until now nothing read it.
LOCAL_SETTINGS_FILE = ROOT / "settings.local.json"
ENV_FILE = ROOT / ".env"

log = logging.getLogger("casper.config")

DEFAULTS = {
    # -- Hotkey ---------------------------------------------------------
    # A single key ("caps lock", "right ctrl", "f8") or a combo
    # ("ctrl+space", "ctrl+alt+d"). Hold it to record.
    #
    # Caps Lock is the default: one key, comfortable to hold with the left
    # little finger, present on every Windows keyboard, and nothing else uses
    # it as a hold. While Casper Flow runs its toggle is suppressed, so it will not
    # turn your typing uppercase.
    #
    # Note that Scroll Lock, Pause and F13-F24 are missing from most laptops,
    # and the Fn key is handled in keyboard firmware so no software on any OS
    # can bind it. Run pick_hotkey.py to confirm what your keyboard sends.
    "hotkey": "caps lock",
    # Stop the trigger key doing its normal job while Casper Flow is holding it.
    # Only applied when the full combo matches, so a plain space still types.
    "suppress_hotkey": True,
    # How long the hotkey must be held before the press counts as dictation.
    # A shorter press is thrown away and the keystroke is handed back to
    # Windows, so tapping Caps Lock still toggles Caps Lock.
    #
    # This is a commitment threshold, not a delay: the microphone starts
    # capturing the moment you press, so nothing you say is lost. Raising this
    # makes accidental dictation harder, at the cost of making genuinely short
    # dictations impossible - hold for less than this and you get nothing.
    "min_hold_seconds": 2.0,
    # Safety ceiling: if the key still looks held after this long, assume the
    # release event was lost and end the hold. Only used when suppress_hotkey
    # is true, because suppression hides the real key state from the OS.
    "max_hold_seconds": 120,

    # -- Privacy --------------------------------------------------------
    # When true, every backend that would send audio or text off this machine
    # is refused, whatever else the config says. This is the default and the
    # whole point of the project: your voice never leaves the device.
    #
    # Enforced centrally in transcribe.py and llm_polish.py rather than by
    # convention, so a stray setting cannot quietly start uploading audio.
    # Localhost services such as Ollama remain allowed.
    "offline_only": True,

    # -- Transcription backend ------------------------------------------
    # "local"  -> faster-whisper, fully offline (the only option that runs
    #             under offline_only)
    # "groq" / "openai" -> cloud APIs. Blocked unless you deliberately set
    #             offline_only to false.
    "transcribe_backend": "local",

    # faster-whisper model.
    #
    # "swift-ct2" is a Hinglish fine-tune, converted for CTranslate2 and shipped
    # inside the installer. It is the default because code-switched speech is what
    # this product exists for.
    #
    # Measured on the 30-recording corpus (corpus/RESULTS.md), accuracy as
    # 1 - fair WER:
    #
    #                  code-switch   english   hindi    median
    #   swift-ct2          81.0%      62.4%    68.9%    1.29 s
    #   base.en             6.6%      91.1%     0.0%    1.12 s
    #
    # Those two rows are why there are two profiles rather than one default: each
    # model is very bad at the other one's job, and no single bundled model is
    # good at both. Pick with Settings > Language, which writes this key. If you
    # only ever dictate English, "base.en" is the better choice by a wide margin.
    #
    # Other values are HuggingFace model names, downloaded on first use:
    #   tiny      fastest, adequate for short commands
    #   base      multilingual, general-purpose
    #   small     more accurate, ~3x slower
    #   large-v3  far too slow on a 2-core CPU; use the Groq backend instead
    "whisper_model": "swift-ct2",
    "whisper_device": "cpu",          # "cpu" or "cuda"
    "whisper_compute_type": "int8",   # int8 / float16 / float32
    # 0 = let CTranslate2 decide. Setting this to your core count helps.
    "cpu_threads": 0,
    # Beam search width. 1 is greedy.
    #
    # **This used to be 1, on the stated grounds that higher was "slower for no
    # measurable accuracy gain". Re-measured on the corpus, that was wrong.**
    # Accuracy as 1 - fair WER, with timestamps on, over 30 recordings
    # (corpus/ACCURACY.md):
    #
    #                  overall   code-switch   english   hindi   names
    #   beam_size 1     65.6%       79.6%       62.4%    88.9%   44.8%
    #   beam_size 5     68.1%       82.7%       64.7%    88.9%   51.4%
    #
    # Two and a half points overall, six on proper nouns, and it is what keeps the
    # published 81% code-switch figure true rather than optimistic.
    #
    # It is not free: median latency went from 1.94 s to 2.89 s on a two-core
    # laptop, which is the one setting here with a cost the user can feel. Lower it
    # to 1 if you would rather have the speed - the text stays usable, it just
    # misses more proper nouns.
    "beam_size": 5,

    # Dictation language as an ISO code, or null to detect it per recording.
    #
    # Pinned to "en", and that is correct for the bundled Hinglish model even
    # though you dictate Hindi words to it. Measured on the corpus, "en" was
    # accuracy-identical to auto-detect in every category and 46% faster, because
    # detection spent over a second per phrase concluding "en" anyway. Whisper
    # treats romanised Hinglish as English, which is what the fine-tune produces.
    #
    # Set it to null only on a general-purpose model (base, small) that you feed
    # both languages. On those, pinning is actively harmful in both directions:
    # "en" mangles Hindi into English-sounding nonsense ("kal ek meeting hai" ->
    # "the luck meeting"), and "hi" mangles plain English ("are you listening to
    # me" -> "Arri Uresan enthume hai kya").
    "language": "en",

    # Vocabulary hint, supplied to the decoder as preceding context. It biases
    # spelling and script, which helps with Hinglish.
    #
    # Deliberately a COMMA-SEPARATED WORD LIST, not sentences. Whisper treats
    # this as text it was already transcribing and will happily continue it, so
    # a prompt made of full sentences gets parroted back as your transcript
    # whenever the audio is unclear: a sentence-shaped prompt here caused
    # "Aaj ka update ready hai kya?" to be pasted for unrelated English speech.
    # A word list gives similar vocabulary bias with far less to copy, and
    # transcribe.py separately detects and rejects any leakage that still
    # occurs.
    #
    # **The shipped settings.json sets this to null, deliberately, and that is
    # the configuration the measurements describe.** On the bundled Hinglish
    # model the prompt made things worse: code-switch accuracy fell, latency rose
    # 39%, and there was no overall gain, because a model already trained on
    # Hinglish does not need priming towards it. It stays here as the recommended
    # starting point for anyone switching to a general-purpose model (base,
    # small), where priming does help, and because bench_hinglish.py scores it as
    # one of its configurations.
    #
    # If you do turn it on, add your own jargon, product names and colleagues'
    # names to the list. Keep it a comma-separated word list, not sentences.
    "initial_prompt": (
        "Hinglish: kal, aaj, abhi, thoda, matlab, theek hai, meeting, report, "
        "bhej dena, kar dena, ho gaya, chahiye, office, update, client."
    ),

    # Load the local model at startup instead of on first dictation.
    "preload_model": True,

    # Model used for the live caption only. Smaller than whisper_model on
    # purpose: previews run repeatedly while you talk, so they must be quick.
    # The pasted text never comes from this model. Set to null to reuse
    # whisper_model instead of loading a second one.
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
    # Interjections removed by the "rules" backend. Deliberately short: a
    # dictation tool must never delete words that carry meaning, so ambiguous
    # ones ("like", "matlab", "actually") are left alone.
    "filler_words": ["um", "uh", "uhh", "umm", "uhm", "er", "erm", "hmm",
                     "mmm", "ahh"],
    # Hard ceiling on the polish call. If it takes longer we paste raw text
    # rather than leaving you staring at a dead cursor.
    "llm_timeout_seconds": 20,

    "ollama_url": "http://localhost:11434",
    "ollama_model": "llama3",

    # -- Formatting -----------------------------------------------------
    # How the finished text is laid out. This is the one part of the pipeline
    # that is allowed to write words the user did not say, so both settings here
    # are off by default and neither does anything without a local language
    # model.
    #
    #   plain    cleanup only. Exactly the behaviour with these settings absent.
    #   message  short, with bullets *if the speech actually listed things*.
    #   email    greeting, paragraphs, numbered steps where speech enumerated.
    #
    # Chosen explicitly rather than inferred from the focused window. Guessing
    # that you are writing an email and silently reformatting a sentence is worse
    # than asking once, and a wrong guess is invisible until you have sent it.
    "format_mode": "plain",
    #
    # Grammar repair. Separate from format_mode because the risks differ: a
    # layout change is obvious when it is wrong, a changed tense or a swapped
    # negation is not. Requires a generative backend.
    "grammar_fix": False,

    # -- Audio ----------------------------------------------------------
    # Fixed, not a preference: Whisper accepts 16 kHz mono only. Anything else is
    # resampled before it reaches the model, and since PyAV was removed from the
    # build that resampling is worse than what the audio driver already does.
    # validate() pins this back to WHISPER_RATE if it is changed.
    "sample_rate": WHISPER_RATE,
    "channels": 1,
    # null = system default input device. Can be an index or a name substring.
    "input_device": None,
    # -- Corrections ----------------------------------------------------
    # Proper nouns are the weakest category measured: 44.8% accuracy against
    # 81.0% for code-switched speech in general. No speech model has heard of
    # your colleagues, so this is fixed by telling the app your words rather
    # than by downloading a bigger model.
    #
    # vocabulary: names, companies and jargon. Matched by sound, not spelling,
    # so one entry catches the variants - "Sharma" also fixes "sarma".
    "vocabulary": [],
    # corrections: an explicit "heard this, meant that" mapping, applied first
    # and exactly. For when the same mistake keeps appearing.
    #   "corrections": {"thank you office": "Bangalore office"}
    "corrections": {},

    # Safety cap so a stuck key can't eat all your RAM.
    "max_record_seconds": 300,
    # Create the microphone stream once and reuse it, instead of opening it on
    # every dictation. Opening costs ~1.3 s (measured) and paying that on the
    # hotkey press meant the microphone went live after the key was already
    # released, so short dictations recorded nothing at all.
    #
    # A stopped stream captures no audio - verified, zero frames while stopped.
    # Set this to false if you would rather the device be released the instant a
    # dictation ends, and accept the delay on the next one.
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

    # Set to true once the first-run wizard has been completed. Until then the
    # wizard opens on startup, because a user who has installed the app and does
    # not know which key to hold has not been onboarded, only installed to.
    "setup_complete": False,
}

# Settings that settings.local.json is currently forcing to a different value than
# settings.json asked for. Populated by load_config, read by doctor.py. Not part of
# the config dict, because it describes the configuration rather than being part of
# it - and anything in that dict risks being written back out by save_config.
LOCAL_OVERRIDES: list[str] = []

# Keys that come from .env, never written back to settings.json
SECRET_KEYS = ("openai_api_key", "groq_api_key", "anthropic_api_key")


def _strip_value(val: str) -> str:
    """
    Strip whitespace, surrounding quotes and an unquoted trailing comment.

    The comment handling matters: `GROQ_API_KEY=abc123 # work key` otherwise
    yields a key with " # work key" attached, and the resulting authentication
    failure looks exactly like a wrong key. Only unquoted values are treated this
    way, because a quoted value is explicit about where it ends and "#" is a legal
    character inside one.
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

    # Whisper accepts 16 kHz mono and nothing else, so recording at any other
    # rate means resampling before transcription. That used to be free: audio was
    # handed to faster-whisper as a file path and PyAV resampled it on the way in.
    # PyAV is no longer in the build - it was 62.6 MB of FFmpeg to read a WAV we
    # wrote ourselves - and the replacement resamples by linear interpolation,
    # which is measurably worse than FFmpeg's.
    #
    # So rather than quietly do a worse job at a setting that never had a reason
    # to be changed, the setting is pinned. sounddevice already asks the device for
    # 16 kHz and lets the driver convert, which is where that conversion belongs.
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
        # Above ~10s every realistic dictation would be discarded, which reads
        # as "the hotkey does nothing" rather than as a setting.
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

    # Both features are generative, and the default cleanup backend cannot
    # generate. Rather than fail silently at dictation time - the user would see
    # unformatted text and have no idea why - say so once, here, at load.
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

    # An unsupported value here fails the model load on every dictation, and the
    # fallback path cannot rescue it because it is not a missing-model problem.
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

    # Both are individually in range and nonsensical together: every dictation
    # would be discarded as too short before it could ever be too long.
    if cfg["min_hold_seconds"] >= cfg["max_hold_seconds"]:
        log.warning(
            f"min_hold_seconds={cfg['min_hold_seconds']} is not less than "
            f"max_hold_seconds={cfg['max_hold_seconds']}; using the defaults for "
            f"both"
        )
        cfg["min_hold_seconds"] = DEFAULTS["min_hold_seconds"]
        cfg["max_hold_seconds"] = DEFAULTS["max_hold_seconds"]

    # A string here would be iterated character by character, so "um" would strip
    # every standalone "u" and "m" from the transcript.
    fillers = cfg.get("filler_words")
    if fillers is not None and not isinstance(fillers, (list, tuple)):
        log.warning(
            f"filler_words must be a list of words, not "
            f"{type(fillers).__name__}; using the defaults"
        )
        cfg["filler_words"] = list(DEFAULTS["filler_words"])

    # An English-only model cannot produce Hindi. Warn rather than silently
    # giving someone unusable Hinglish output.
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

    JSON has no comment syntax, and a settings file that cannot explain itself
    gets edited badly. A "//" key is the conventional workaround, so it is
    treated as a comment rather than reported as an unrecognised setting.
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
            # A frozen build ships a settings.json inside the bundle. Prefer
            # copying that over writing DEFAULTS, so the file the user first sees
            # is the documented one with its comments intact.
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
            # Which of these actually change a value, as opposed to restating it.
            # Those are the ones that make the Settings window appear broken: it
            # writes settings.json, this file is applied afterwards and wins, so
            # the setting silently reverts and nothing says why. Recorded as a
            # WARNING for exactly that reason - it was an INFO line listing every
            # key including the no-ops, which is easy to read past.
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
    }.get(backend, "")


def save_config(cfg: dict):
    """
    Persist non-secret settings back to settings.json.

    Written to a temporary file and then moved into place. `write_text` truncates
    first, so an error or a power cut between truncate and write left a
    half-written file - which `load_config` then failed to parse and silently
    replaced with the defaults, losing the user's hotkey, vocabulary and
    corrections. `os.replace` is atomic on Windows, so the file on disk is either
    the old settings or the new ones.
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
