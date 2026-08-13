"""
Find the speech settings that work best for YOUR voice.

Accent matters enormously for code-mixed Hindi-English, and no amount of
guessing substitutes for a recording of the actual speaker. This records one
short phrase, runs it through every sensible combination of model, language and
prompt, scores each against what you actually said, and offers to save the
winner.

    venv\\Scripts\\python.exe tune_hinglish.py

Nothing is uploaded: every configuration tested here runs locally.
"""

import argparse
import json
import os
import sys
import time
import wave
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

# Transcripts may come back in Devanagari, which the console's default code page
# (cp1252 on most Windows installs) cannot encode - printing one would otherwise
# raise UnicodeEncodeError and abort the comparison mid-run.
for _stream in (sys.stdout, sys.stderr):
    try:
        if _stream is not None:
            _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

SETTINGS = ROOT / "settings.json"
SAMPLE = ROOT / "_tune_sample.wav"

PHRASE = "Kal ek meeting hai, please report bhej dena aaj shaam tak"

# The prompt under test is the one the app actually ships, imported rather than
# copied so the two cannot drift apart.
#
# This used to be a separate, sentence-shaped prompt:
#
#   "Kal ek meeting hai. Please report bhej dena. Main office se nikal
#    raha hoon. Aaj ka update ready hai kya? Thoda check karke bata dena."
#
# Whisper treats initial_prompt as text it has already transcribed and will
# happily continue it when the audio is unclear. That exact prompt caused a real
# bug: "Aaj ka update ready hai kya?" was pasted into a document during
# unrelated English dictation. Worse, this script offered to save that prompt
# into settings.json, so accepting its recommendation reintroduced the bug. A
# comma-separated word list primes the same vocabulary with no sentence to
# continue.
from config import DEFAULTS as _APP_DEFAULTS      # noqa: E402

WORD_LIST_PROMPT = _APP_DEFAULTS["initial_prompt"]

# (model, language, use_prompt)
#
# The language pins are included because they are informative, not because they
# are candidates: "en" turned "kal ek meeting hai" into "the luck meeting", and
# "hi" turned "are you listening to me" into "Arri Uresan enthume hai kya".
# Seeing that happen on your own voice is more convincing than being told.
CONFIGS = [
    ("base",  None, True),      # the shipped default
    ("base",  None, False),     # control: how much is the prompt worth?
    ("base",  "hi", True),
    ("base",  "en", True),
    ("small", None, True),
    ("small", None, False),
    ("small", "hi", True),
    ("small", "en", True),
]

SECONDS = 8


# --------------------------------------------------------------- scoring

def normalise(text: str) -> list[str]:
    keep = []
    for ch in text.lower():
        if ch.isalnum() or ch.isspace():
            keep.append(ch)
        else:
            keep.append(" ")
    return "".join(keep).split()


def word_error_rate(reference: str, hypothesis: str) -> float:
    ref, hyp = normalise(reference), normalise(hypothesis)
    if not ref:
        return 1.0
    # Levenshtein over words
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i]
        for j, h in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (r != h)))
        prev = cur
    return prev[-1] / len(ref)


def has_devanagari(text: str) -> bool:
    return any("\u0900" <= ch <= "\u097f" for ch in text)


# -------------------------------------------------------------- recording

def record(seconds: int, path: Path, sample_rate=16000) -> bool:
    try:
        import sounddevice as sd
        import numpy as np
    except ImportError:
        print("sounddevice/numpy missing - run install.ps1 first")
        return False

    print(f"\nRead this out loud, naturally, in your normal accent:\n")
    print(f"    {PHRASE}\n")
    for n in (3, 2, 1):
        print(f"  recording in {n}...", end="\r", flush=True)
        time.sleep(1)
    print(f"  RECORDING for {seconds}s - speak now.            ")

    frames = sd.rec(int(seconds * sample_rate), samplerate=sample_rate,
                    channels=1, dtype="int16")
    sd.wait()
    print("  done.")

    peak = int(abs(frames).max()) if frames.size else 0
    if peak < 500:
        print(f"\nThat was almost silent (peak {peak}/32767). Check the")
        print("microphone and try again.")
        return False

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(frames.tobytes())
    print(f"  captured {seconds}s, peak {peak}/32767")
    return True


# ----------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--wav", help="score an existing recording instead of recording one")
    ap.add_argument("--said", help="what you actually said, if not the suggested phrase")
    ap.add_argument("--seconds", type=int, default=SECONDS)
    args = ap.parse_args()

    reference = args.said or PHRASE

    if args.wav:
        sample = Path(args.wav)
        if not sample.exists():
            print(f"no such file: {sample}")
            return 1
    else:
        sample = SAMPLE
        if not record(args.seconds, sample):
            return 1

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("faster-whisper missing - run install.ps1 first")
        return 1

    threads = os.cpu_count() or 2
    # Two threads beat four on a 2-core/4-thread CPU; see the README.
    threads = max(1, threads // 2)

    print(f"\nTesting {len(CONFIGS)} configurations on your recording.")
    print("The first run of a model downloads it, which may take a minute.\n")
    print(f"{'model':8}{'lang':6}{'prompt':8}{'secs':>7}{'WER':>7}  transcript")
    print("-" * 96)

    results = []
    cache = {}
    for model_name, lang, use_prompt in CONFIGS:
        try:
            if model_name not in cache:
                cache[model_name] = WhisperModel(
                    model_name, device="cpu", compute_type="int8",
                    cpu_threads=threads,
                )
            model = cache[model_name]

            t0 = time.perf_counter()
            segments, info = model.transcribe(
                str(sample),
                beam_size=1,
                language=lang,
                initial_prompt=WORD_LIST_PROMPT if use_prompt else None,
                vad_filter=True,
                without_timestamps=True,
                condition_on_previous_text=False,
            )
            text = " ".join(s.text.strip() for s in segments).strip()
            elapsed = time.perf_counter() - t0

            wer = word_error_rate(reference, text)
            results.append({
                "model": model_name, "language": lang, "prompt": use_prompt,
                "seconds": elapsed, "wer": wer, "text": text,
                "devanagari": has_devanagari(text),
            })
            print(f"{model_name:8}{str(lang or 'auto'):6}{'yes' if use_prompt else 'no':8}"
                  f"{elapsed:>7.2f}{wer:>7.2f}  {text[:52]!r}")
        except Exception as e:
            print(f"{model_name:8}{str(lang or 'auto'):6}"
                  f"{'yes' if use_prompt else 'no':8}  FAILED "
                  f"{type(e).__name__}: {str(e)[:40]}")

    if not results:
        print("\nNothing ran successfully.")
        return 1

    print("\n" + "=" * 96)
    print(f"You said: {reference!r}\n")

    ranked = sorted(results, key=lambda r: (round(r["wer"], 3), r["seconds"]))
    print("Ranked by accuracy, then speed:\n")
    for i, r in enumerate(ranked[:5], 1):
        script = "Devanagari" if r["devanagari"] else "Roman"
        print(f"  {i}. {r['model']} / lang={r['language'] or 'auto'} / "
              f"prompt={'yes' if r['prompt'] else 'no'}")
        print(f"     WER {r['wer']:.0%}, {r['seconds']:.2f}s, {script} script")
        print(f"     {r['text']!r}")

    best = ranked[0]
    fastest_good = min(
        (r for r in results if r["wer"] <= best["wer"] + 0.10),
        key=lambda r: r["seconds"],
    )

    print(f"\nMost accurate : {best['model']} / lang={best['language'] or 'auto'}"
          f"  ({best['wer']:.0%} WER, {best['seconds']:.2f}s)")
    print(f"Best balance  : {fastest_good['model']} / "
          f"lang={fastest_good['language'] or 'auto'}"
          f"  ({fastest_good['wer']:.0%} WER, {fastest_good['seconds']:.2f}s)")

    if best["devanagari"]:
        print("\nNote: the most accurate result is in Devanagari. To get Roman")
        print("script (kal ek meeting hai), enable the cleanup step with an API")
        print("key or a local Ollama model - see 'Hinglish' in the README.")

    if best["wer"] > 0.5:
        print("\nAll configurations scored poorly. Either the recording did not")
        print("match the phrase, or local models are struggling with this audio.")
        print("The Groq backend (whisper-large-v3-turbo) is markedly better for")
        print("Indian-accented speech; see the README.")

    choice = fastest_good

    if choice["language"] is not None:
        print(f"\nHeads up: the winning configuration pins language="
              f"{choice['language']!r}.")
        print("That scored best on this one recording, but pinning a language")
        print("breaks code-mixed speech in the other direction - an English")
        print("sentence under 'hi', or a Hindi one under 'en', can come back")
        print("mistranslated rather than mistranscribed. If you switch between")
        print("languages mid-sentence, keep language=null even at a small cost")
        print("in this score. Record a mixed phrase and re-run to see it.")

    try:
        answer = input(f"\nSave the balanced option "
                       f"({choice['model']}, lang={choice['language'] or 'auto'})"
                       f" to settings.json? (y/n) [y]: ").strip().lower()
    except EOFError:
        answer = "n"
    if answer in ("", "y"):
        try:
            cfg = json.loads(SETTINGS.read_text(encoding="utf-8-sig")) \
                if SETTINGS.exists() else {}
            cfg["whisper_model"] = choice["model"]
            cfg["language"] = choice["language"]
            cfg["initial_prompt"] = WORD_LIST_PROMPT if choice["prompt"] else None
            SETTINGS.write_text(json.dumps(cfg, indent=2, ensure_ascii=False),
                                encoding="utf-8")
            print("Saved. Restart Casper Flow to use it.")
        except Exception as e:
            print(f"Could not write settings.json: {e}")
            return 1
    else:
        print("Not saved.")

    if sample == SAMPLE:
        try:
            SAMPLE.unlink()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
