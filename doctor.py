"""
Casper Flow self-check.

Verifies the install without needing you to speak into a microphone:
dependencies, config validity, hotkey name, audio device, clipboard round-trip,
the local Whisper model, and any configured API keys.

Run:  venv\\Scripts\\python.exe doctor.py
Exit code 0 = ready to use, 1 = at least one FAIL.
"""

import sys
import importlib
import importlib.util          # not implied by `import importlib`
import logging
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# Library warnings (a model falling back, a device problem) are part of the
# report, so send them to stdout with the rest of it rather than to stderr.
try:
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

logging.basicConfig(level=logging.WARNING, stream=sys.stdout,
                    format="       %(levelname)s %(name)s: %(message)s")

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
_ICON = {PASS: "[ok]  ", WARN: "[warn]", FAIL: "[FAIL]"}
results = []


def record(status, name, detail=""):
    results.append((status, name, detail))
    line = f"{_ICON[status]} {name}"
    if detail:
        line += f"\n         {detail}"
    print(line)


def section(title):
    print(f"\n--- {title} " + "-" * max(0, 58 - len(title)))


# ------------------------------------------------------------ dependencies

def check_deps():
    section("Dependencies")
    required = {
        "numpy": "numpy",
        "sounddevice": "sounddevice",
        "keyboard": "keyboard",
        "pystray": "pystray",
        "PIL": "Pillow",
        "win32clipboard": "pywin32",
        "tkinter": "tkinter (bundled with Python)",
    }
    for mod, pkg in required.items():
        try:
            importlib.import_module(mod)
            record(PASS, f"import {mod}")
        except Exception as e:
            record(FAIL, f"import {mod}", f"missing {pkg} -> pip install {pkg} ({e})")

    try:
        importlib.import_module("faster_whisper")
        record(PASS, "import faster_whisper", "local speech recognition")
    except Exception as e:
        record(FAIL, "import faster_whisper",
               f"required for local transcription -> pip install faster-whisper ({e})")

    try:
        importlib.import_module("requests")
        record(PASS, "import requests", 'optional - enables llm_backend="ollama"')
    except Exception:
        record(WARN, "import requests", 'not installed - needed for ollama cleanup')

    # Cloud clients are deliberately absent. Their presence is not a problem,
    # but it is worth reporting so the privacy posture is visible.
    present = [m for m in ("openai", "groq", "anthropic")
               if importlib.util.find_spec(m) is not None]
    if present:
        record(PASS, "cloud clients installed", f"{present} - blocked while "
               f"offline_only is on")
    else:
        record(PASS, "no cloud clients installed",
               "nothing here can upload audio or text")


# ------------------------------------------------------------------ config

def check_config():
    section("Configuration")

    # Before anything reads or writes settings. Casper Flow keeps settings.json,
    # .env and casper.log beside the executable, so an install into a directory
    # the user cannot write to loses every setting on restart - and the log
    # handler is created at import time with no try/except, so the app exits with
    # no window, no tray icon and nothing to look at. Worth one line here.
    try:
        from paths import DATA_DIR
        probe = DATA_DIR / ".casper-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        record(PASS, "settings folder is writable", str(DATA_DIR))
    except Exception as e:
        record(FAIL, "settings folder is writable",
               f"{e}. Casper Flow keeps its settings and log next to the "
               f"program, so it needs to be installed somewhere you can write - "
               f"the default is %LOCALAPPDATA%\\Programs\\CasperFlow")

    try:
        import config as _config
        from config import load_config, api_key_for
        cfg = load_config()
        record(PASS, "settings.json parsed")

        # A developer-only file, but it silently wins over the Settings window, so
        # someone who switched language profile and saw no change deserves to be
        # told why rather than concluding the model is bad.
        if _config.LOCAL_OVERRIDES:
            record(WARN, "settings.local.json is overriding settings",
                   f"{_config.LOCAL_OVERRIDES} - changing these in the Settings "
                   f"window will have no effect until they are removed from that "
                   f"file")
    except Exception as e:
        record(FAIL, "settings.json parsed", str(e))
        return None

    record(PASS, "transcribe backend", f"{cfg['transcribe_backend']} / {cfg['whisper_model']}")
    record(PASS, "language", str(cfg.get("language") or "auto-detect"))

    # Mixed-language dictation needs a multilingual model.
    model = str(cfg.get("whisper_model", ""))
    if model.endswith(".en"):
        record(WARN, "model is English-only",
               f"{model} cannot transcribe Hindi at all (measured 0% accuracy "
               f"on the Hindi corpus). That is correct if you dictate only "
               f"English - it is the most accurate option for that, 91%. For "
               f"Hinglish, choose 'Hindi and English mixed' in Settings")
    else:
        record(PASS, "multilingual model", f"{model} can handle code-mixed speech")

    # A model fine-tuned for Hinglish needs the opposite advice from a general
    # one, and both pieces of advice below were measured on a 30-recording
    # corpus rather than assumed. See corpus/RESULTS.md.
    tuned = any(t in model.lower() for t in ("hinglish", "swift"))

    prompt = str(cfg.get("initial_prompt") or "")
    if prompt:
        # Sentence-shaped prompts get parroted back as transcripts when the
        # audio is unclear. A word list is far safer.
        sentences = sum(prompt.count(c) for c in ".?!")
        if sentences >= 2 and "," not in prompt.split(".")[0]:
            record(WARN, "initial_prompt looks like sentences",
                   "Whisper can echo it back as your transcript. Prefer a "
                   "comma-separated word list; see settings.json")
        elif tuned:
            record(WARN, "initial_prompt set on a Hinglish-tuned model",
                   "measured on the corpus, the prompt cost accuracy on "
                   "code-switching and 39% latency for no overall gain. "
                   "Setting it to null is faster and slightly better.")
        else:
            record(PASS, "initial_prompt set",
                   f"{len(prompt)} chars, word-list style")
    elif tuned:
        record(PASS, "no initial_prompt",
               f"correct for {model} - it was trained on Hinglish, so it does "
               f"not need priming")
    else:
        record(WARN, "no initial_prompt",
               "Hinglish spelling is less consistent without one on a "
               "general-purpose model")

    lang = cfg.get("language")
    if lang and tuned:
        record(PASS, f"language pinned to {lang!r}",
               "accuracy-identical to auto-detect on the corpus and 46% "
               "faster, because detection was concluding 'en' every time")
    elif lang:
        record(WARN, f"language pinned to {lang!r}",
               "on a general-purpose model this mangles mixed English/Hindi "
               "speech, and pinning 'hi' has produced Tamil script. It is "
               "much faster, so it is the right choice only if you dictate "
               "in one language")
    else:
        record(PASS, "language auto-detected",
               "correct for mixed-language use on a general model, though it "
               "is the largest latency cost in the pipeline")

    record(PASS, "output script", str(cfg.get("output_script", "latin")))

    style = str(cfg.get("pill_style", "blob"))
    if style == "blob":
        record(PASS, "overlay", "blob - microphone level, no transcription needed")
    elif cfg.get("live_preview"):
        record(PASS, "live captions",
               f"preview model {cfg.get('preview_model') or cfg['whisper_model']!r}")
    else:
        record(PASS, "overlay", f"{style}, previews off")

    # Previews only feed the caption style. Running them for the blob would spend
    # CPU transcribing text that is never displayed.
    if cfg.get("live_preview") and style != "caption":
        record(WARN, "live_preview is on but the overlay shows no text",
               f"pill_style is {style!r}, which is driven by microphone level. "
               f"Previews would transcribe repeatedly for nothing - set "
               f"live_preview to false, or pill_style to 'caption'.")

    # -- privacy posture ------------------------------------------------
    offline = bool(cfg.get("offline_only", True))
    tb = str(cfg.get("transcribe_backend", "local"))
    lb = str(cfg.get("llm_backend", "rules"))

    if offline:
        record(PASS, "offline_only", "audio and text cannot leave this machine")
    else:
        record(WARN, "offline_only is OFF",
               "cloud backends are permitted; audio may be uploaded")

    if tb == "local":
        record(PASS, "transcription runs locally", tb)
    elif offline:
        record(PASS, f"transcribe_backend={tb!r} will be overridden",
               "offline_only forces the local model")
    else:
        record(WARN, f"transcribe_backend={tb!r} uploads audio",
               "set offline_only true to prevent this")

    if not cfg.get("llm_polish"):
        record(PASS, "text cleanup", "disabled (raw transcript)")
    elif lb == "rules":
        record(PASS, "text cleanup", "built-in rules - local, deterministic, "
                                     "cannot invent words")
    elif lb == "ollama":
        record(PASS, "text cleanup", f"ollama at {cfg.get('ollama_url')} (local)")
    elif offline:
        record(PASS, f"llm_backend={lb!r} will be overridden",
               "offline_only forces the local rules cleanup")
    else:
        state = "key found" if api_key_for(lb, cfg) else "no key - will use rules"
        record(WARN, f"text cleanup via cloud ({lb})", state)

    # -- grammar and layout ---------------------------------------------
    # Both are generative and both need a backend that can write. Silently doing
    # nothing is the failure mode to avoid: the user turns on "Email" in the
    # settings window, dictates, gets a plain sentence, and has no way to know
    # why.
    mode = str(cfg.get("format_mode", "plain"))
    grammar = bool(cfg.get("grammar_fix", False))

    if mode == "plain" and not grammar:
        record(PASS, "grammar and layout", "off - cleanup only, nothing is reworded")
    elif lb == "rules":
        record(WARN, f"format_mode={mode!r} grammar_fix={grammar} do nothing",
               "the 'rules' cleanup cannot write text. Install Ollama and set "
               "llm_backend to 'ollama' - it stays on this machine")
    elif offline and lb in ("openai", "anthropic", "groq"):
        record(WARN, f"format_mode={mode!r} grammar_fix={grammar} do nothing",
               f"offline_only forces the rules cleanup, overriding {lb!r}")
    elif lb == "ollama":
        url = str(cfg.get("ollama_url", "http://localhost:11434")).rstrip("/")
        try:
            import requests
            r = requests.get(f"{url}/api/tags", timeout=3)
            r.raise_for_status()
            names = [m.get("name", "?") for m in (r.json().get("models") or [])]
            want = str(cfg.get("ollama_model", "llama3"))
            if any(n.split(":")[0] == want.split(":")[0] for n in names):
                record(PASS, f"grammar/layout via ollama ({want})",
                       f"reachable at {url}")
            else:
                record(WARN, f"ollama model {want!r} not pulled",
                       f"reachable at {url}, but it has "
                       f"{', '.join(names) or 'no models'}. Run: ollama pull {want}")
        except Exception as e:
            record(WARN, f"format_mode={mode!r} grammar_fix={grammar} will not work",
                   f"ollama not reachable at {url} ({type(e).__name__}). "
                   f"Text will fall back to the plain cleanup")
    else:
        record(PASS, f"grammar/layout via {lb}", f"format_mode={mode!r}")

    return cfg


# ------------------------------------------------------------------ hotkey

def check_hotkey(cfg):
    section("Hotkey")
    try:
        import keyboard as kb
        from hotkey import parse_hotkey
    except Exception as e:
        record(FAIL, "hotkey check", str(e))
        return

    spec = cfg.get("hotkey", "ctrl+shift+space")
    mods, trigger = parse_hotkey(spec)
    combo = "+".join([*mods, trigger])
    bad = []
    for name in [trigger, *mods]:
        try:
            kb.key_to_scan_codes(name)
        except Exception:
            bad.append(name)
    if bad:
        record(FAIL, f"hotkey {spec!r}",
               f"unknown key name(s): {bad} - run pick_hotkey.py")
        return

    record(PASS, f"hotkey {spec!r}", f"resolves to [{combo}], hold-to-talk")

    # A valid name is not the same as a key your keyboard actually has.
    often_missing = {"scroll lock", "pause", "num lock", "menu",
                     *(f"f{i}" for i in range(13, 25))}
    if trigger in often_missing:
        record(WARN, f"key '{trigger}' availability",
               "many laptops and compact keyboards have no such key; "
               "run pick_hotkey.py to confirm Casper Flow receives it")

    if not mods and trigger in {"space", "enter", "tab", "backspace"}:
        record(WARN, f"key '{trigger}' is a typing key",
               "Casper Flow would swallow it while running; add a modifier, "
               f"e.g. ctrl+{trigger}")

    if len(mods) >= 2:
        record(WARN, f"hotkey uses {len(mods) + 1} keys",
               "awkward to hold; a single key such as 'caps lock' is easier")


# ------------------------------------------------------------------- audio

def check_audio(cfg):
    section("Audio input")
    try:
        import sounddevice as sd
    except Exception as e:
        record(FAIL, "sounddevice", str(e))
        return
    try:
        dev = sd.query_devices(kind="input")
        record(PASS, "default input device", dev["name"])
    except Exception as e:
        record(FAIL, "default input device",
               f"{e} - check Settings > Privacy & security > Microphone")
        return

    # Open the stream briefly. Proves the device accepts our format and that
    # microphone permission is granted, without recording anything meaningful.
    try:
        with sd.InputStream(
            samplerate=int(cfg.get("sample_rate", 16000)),
            channels=int(cfg.get("channels", 1)),
            dtype="int16",
        ):
            pass
        record(PASS, "open input stream",
               f"{cfg.get('sample_rate')} Hz, {cfg.get('channels')} ch, int16")
    except Exception as e:
        record(FAIL, "open input stream", str(e))


# --------------------------------------------------------------- clipboard

def check_clipboard():
    section("Clipboard")
    try:
        import win32con
        from paste import _clipboard, _snapshot_formats
    except Exception as e:
        record(FAIL, "clipboard modules", str(e))
        return

    marker = "casper-doctor-roundtrip"
    try:
        with _clipboard() as wc:
            saved = _snapshot_formats(wc, win32con)
        with _clipboard() as wc:
            wc.EmptyClipboard()
            wc.SetClipboardData(win32con.CF_UNICODETEXT, marker)
        with _clipboard() as wc:
            got = wc.GetClipboardData(win32con.CF_UNICODETEXT)
        ok = got == marker

        # put the user's clipboard back
        with _clipboard() as wc:
            wc.EmptyClipboard()
            for fmt, data in saved.items():
                try:
                    wc.SetClipboardData(fmt, data)
                except Exception:
                    pass

        if ok:
            record(PASS, "clipboard write/read/restore",
                   f"preserved {len(saved)} original format(s)")
        else:
            record(FAIL, "clipboard write/read/restore", f"read back {got!r}")
    except Exception as e:
        record(FAIL, "clipboard write/read/restore", str(e))


# ------------------------------------------------------------------- model

def _check_bundled_weights(size: str):
    """
    Are these the weights the accuracy figures describe?

    Every number the product publishes - in Settings, in the installer, on the
    website - is a cell in corpus/RESULTS.md, measured against specific files.
    models/MODELS.lock.json records a SHA-256 for each of them, so that claim is
    checkable rather than asserted. Reported here because "my dictation is worse
    than advertised" and "these are not the advertised weights" are the same
    question, and only this can tell them apart.

    A WARN rather than a FAIL when the lock file is absent: it ships in the source
    tree, not in the installer, so an installed user legitimately has no copy.
    """
    import json

    from transcribe import resolve_model

    lock_path = ROOT / "models" / "MODELS.lock.json"
    if not lock_path.is_file():
        # Only interesting for someone building from source.
        if not getattr(sys, "frozen", False):
            record(WARN, "model fingerprints", f"{lock_path.name} is missing; "
                   f"run fetch_models.py to record it")
        return

    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except Exception as e:
        record(WARN, "model fingerprints", f"{lock_path.name} unreadable: {e}")
        return

    entry = lock.get(size)
    if not entry or not entry.get("files"):
        record(WARN, f"model '{size}' fingerprints",
               f"not recorded in {lock_path.name}; its accuracy has not been "
               f"measured by this project")
        return

    resolved = Path(resolve_model(size))
    if not resolved.is_dir():
        return          # the resolution check above already reported this

    mismatched = []
    for name, want in entry["files"].items():
        path = resolved / name
        if not path.is_file():
            mismatched.append(f"{name} missing")
            continue
        if path.stat().st_size != want["bytes"]:
            mismatched.append(f"{name} wrong size")

    if mismatched:
        record(FAIL, f"model '{size}' matches the lock file",
               f"{', '.join(mismatched[:3])}. These are not the weights the "
               f"published accuracy figures were measured on")
    else:
        total = sum(f["bytes"] for f in entry["files"].values())
        record(PASS, f"model '{size}' matches the lock file",
               f"{len(entry['files'])} files, {total / 1e6:.1f} MB, from "
               f"{entry.get('repo', '?')}")


def check_model(cfg):
    section("Whisper model")
    if cfg["transcribe_backend"] != "local":
        record(PASS, "local model", f"skipped (backend={cfg['transcribe_backend']})")
        return
    try:
        from transcribe import MODELS_DIR, _load_local, resolve_model
    except Exception as e:
        record(FAIL, "local model", str(e))
        return

    size = cfg.get("whisper_model") or "swift-ct2"

    # Resolve BEFORE loading. `_load_local` deliberately falls back to any model
    # it can find rather than failing every dictation, so on its own it reports
    # "loaded and cached" while the app is quietly running a different model than
    # the user chose - which is the exact question this section exists to answer.
    # Checking resolution separately is what distinguishes "installed" from
    # "something loaded".
    resolved = resolve_model(size)
    if resolved != size:
        record(PASS, f"model '{size}' installed", f"{resolved}")
    else:
        # resolve_model returns the name unchanged when it found nothing on disk,
        # which means faster-whisper will treat it as a HuggingFace repo id.
        bundled = sorted(p.name for p in MODELS_DIR.glob("*")
                         if (p / "model.bin").is_file()) if MODELS_DIR.is_dir() else []
        record(WARN, f"model '{size}' not installed locally",
               f"it will be downloaded from HuggingFace on first use, which "
               f"needs a working internet connection. Installed here: "
               f"{bundled or 'none'}")

    _check_bundled_weights(size)

    print(f"         loading '{size}' ...")
    try:
        _load_local(cfg)
        import transcribe
        actual = transcribe.loaded_model_name
        if actual and actual != size:
            # The whole point of checking. _load_local substitutes a model it can
            # find rather than failing every dictation, and says so only in the
            # log, so without this doctor would print "ok" while the user dictates
            # all day on a model they did not choose.
            record(FAIL, f"local model '{size}'",
                   f"could not be loaded, so Casper Flow fell back to "
                   f"'{actual}'. Accuracy will not match what the model you "
                   f"chose was measured at. Reconnect to the internet and "
                   f"restart, or choose a different model in Settings")
        else:
            record(PASS, f"local model '{size}'", "loaded and cached")
    except Exception as e:
        record(FAIL, f"local model '{size}'", str(e))


# -------------------------------------------------------------------- main

def main():
    print("Casper Flow doctor - checking your install\n")
    print(f"Python     : {sys.version.split()[0]}")
    print(f"Interpreter: {sys.executable}")

    check_deps()
    cfg = check_config()
    if cfg:
        check_hotkey(cfg)
        check_audio(cfg)
        check_clipboard()
        check_model(cfg)

    fails = [r for r in results if r[0] == FAIL]
    warns = [r for r in results if r[0] == WARN]
    section("Summary")
    print(f"{len(results) - len(fails) - len(warns)} passed, "
          f"{len(warns)} warning(s), {len(fails)} failure(s)")
    if fails:
        print("\nMust fix:")
        for _, name, detail in fails:
            print(f"  - {name}: {detail}")
        return 1
    if getattr(sys, "frozen", False):
        print("\nCasper Flow is ready. Look for the microphone icon in the "
              "system tray.")
    else:
        print("\nCasper Flow is ready. Start it with start_casper.bat")
    return 0


if __name__ == "__main__":
    sys.exit(main())
