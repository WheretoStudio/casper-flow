"""
Record the reference corpus, one phrase at a time.

    venv\\Scripts\\python.exe record_corpus.py

Reads corpus/phrases.json, records each phrase to corpus/audio/<id>.wav, and can
be stopped and resumed - anything already recorded is skipped unless you ask to
redo it.

Recording runs until you press Enter rather than for a fixed number of seconds,
because the long phrases in the corpus take eight to ten seconds to say naturally
and a fixed window would quietly clip the end off them.

Speak the way you actually dictate. Reading each line carefully in a quiet room
produces a corpus that flatters the model and then tells you nothing about real
use, which is exactly the trap the earlier text-to-speech proxy fell into.

Recordings stay on your machine. corpus/audio/ is git-ignored, because this is
your voice and the repository is public.
"""

import argparse
import json
import sys
import threading
import time
import wave
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        if _s is not None:
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).parent
CORPUS = ROOT / "corpus"
AUDIO = CORPUS / "audio"
PHRASES = CORPUS / "phrases.json"

SAMPLE_RATE = 16000
SILENCE_PEAK = 500          # int16; below this the take is effectively silent
MIN_SECONDS = 0.8           # shorter than this is a slip, not a phrase
MAX_SECONDS = 60.0          # hard stop, in case Enter is never pressed


def load_phrases() -> list[dict]:
    return json.loads(PHRASES.read_text(encoding="utf-8"))["phrases"]


class Take:
    """One recording, running until stopped, with a live level meter."""

    def __init__(self):
        import numpy as np
        self._np = np
        self.frames: list = []
        self.peak = 0
        self._stop = threading.Event()
        self._started = 0.0

    def _callback(self, indata, _n, _t, status):
        if status:
            pass                    # over/underflow on a laptop mic is common
        self.frames.append(indata.copy())
        p = int(self._np.abs(indata).max())
        if p > self.peak:
            self.peak = p

    def _meter(self):
        while not self._stop.wait(0.1):
            elapsed = time.monotonic() - self._started
            # Instantaneous level from the most recent block.
            recent = self.frames[-3:]
            level = 0
            if recent:
                level = int(max(int(self._np.abs(f).max()) for f in recent))
            bars = min(34, int(34 * level / 9000))
            meter = ("#" * bars).ljust(34)
            sys.stdout.write(f"\r    {elapsed:5.1f}s  [{meter}]  ")
            sys.stdout.flush()

    def record_until_enter(self) -> float:
        import sounddevice as sd

        self._started = time.monotonic()
        meter = threading.Thread(target=self._meter, daemon=True)
        stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                               dtype="int16", callback=self._callback)
        stream.start()
        meter.start()
        try:
            # Blocks here while the callback fills the buffer.
            input()
        except EOFError:
            time.sleep(2.0)
        finally:
            self._stop.set()
            meter.join(timeout=0.5)
            stream.stop()
            stream.close()
            sys.stdout.write("\r" + " " * 60 + "\r")
            sys.stdout.flush()
        return time.monotonic() - self._started

    def audio(self):
        if not self.frames:
            return None
        return self._np.concatenate(self.frames, axis=0)


def write_wav(path: Path, frames) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(frames.tobytes())


def mic_check() -> bool:
    """Prove the microphone hears you before asking for 30 phrases."""
    import sounddevice as sd

    try:
        dev = sd.query_devices(kind="input")
        print(f"Input device: {dev['name']}")
    except Exception as e:
        print(f"Could not query the input device: {e}")
        return False

    print("\nMicrophone check. Say anything - 'testing one two three' is fine.")
    print("Press Enter to start, then Enter again when you have finished.")
    try:
        input()
    except EOFError:
        return True

    take = Take()
    print("    speak now, Enter to stop:")
    take.record_until_enter()

    if take.peak < SILENCE_PEAK:
        print(f"\nThe microphone captured almost nothing (peak "
              f"{take.peak}/32767).")
        print("Check Settings > Privacy & security > Microphone, make sure the")
        print("right device is the default, and that it is not muted. Then")
        print("run this again.")
        return False

    headroom = take.peak / 32767
    print(f"\nPeak {take.peak}/32767 ({headroom:.0%} of full scale).")
    if headroom < 0.05:
        print("That is quite quiet. It will probably still work, but speaking")
        print("closer to the microphone will give the model more to work with.")
    elif headroom > 0.95:
        print("That is clipping. Move back a little or lower the input level,")
        print("because clipped audio loses information the model needs.")
    else:
        print("Good level.")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="Record the Hinglish reference corpus.")
    ap.add_argument("--redo", action="store_true",
                    help="re-record phrases that already have audio")
    ap.add_argument("--only", help="record a single phrase id, e.g. cs03")
    ap.add_argument("--category", help="record one category only, e.g. english")
    ap.add_argument("--skip-check", action="store_true",
                    help="skip the microphone check")
    args = ap.parse_args()

    try:
        import sounddevice  # noqa: F401
        import numpy        # noqa: F401
    except ImportError:
        print("sounddevice/numpy missing - run install.ps1 first")
        return 1

    phrases = load_phrases()
    if args.only:
        phrases = [p for p in phrases if p["id"] == args.only]
    if args.category:
        phrases = [p for p in phrases if p["category"] == args.category]
    if not phrases:
        print("No phrases matched.")
        return 1

    todo = [p for p in phrases
            if args.redo or not (AUDIO / f"{p['id']}.wav").exists()]
    done = len(phrases) - len(todo)

    print("=" * 68)
    print("Casper Flow - Hinglish reference corpus")
    print("=" * 68)

    if not args.skip_check and todo:
        if not mic_check():
            return 1

    print()
    print(f"{len(phrases)} phrases selected, {done} already recorded, "
          f"{len(todo)} to go.")
    if not todo:
        print("Nothing to record. Use --redo to record them again.")
        return 0

    print()
    print("For each phrase: Enter to start, speak it, Enter to stop.")
    print("Then Enter to keep, 'r' to redo, 's' to skip, 'q' to stop for now.")
    print()
    print("Say it the way you would actually dictate it - normal speed, normal")
    print("accent. If you misread a line, redo it, or the reference transcript")
    print("will not match what you said.")
    print()

    recorded = 0
    for i, phrase in enumerate(todo, 1):
        target = AUDIO / f"{phrase['id']}.wav"
        while True:
            print(f"[{i}/{len(todo)}]  {phrase['id']}  ({phrase['category']})")
            print(f"    \"{phrase['text']}\"")
            try:
                key = input("    Enter to record / s skip / q quit: ").strip().lower()
            except EOFError:
                key = "q"

            if key == "q":
                print(f"\nStopped. {recorded} recorded this session.")
                print("Re-run to carry on where you left off.")
                return 0
            if key == "s":
                print("    skipped\n")
                break

            print("    recording - press Enter when you have finished:")
            take = Take()
            seconds = take.record_until_enter()
            audio = take.audio()

            if audio is None or seconds < MIN_SECONDS:
                print(f"    only {seconds:.1f}s captured - let's try that again.\n")
                continue
            if take.peak < SILENCE_PEAK:
                print(f"    almost silent (peak {take.peak}/32767) - not saved.\n")
                continue

            bars = min(30, int(30 * take.peak / 20000))
            print(f"    {seconds:.1f}s, peak {take.peak:>5}/32767  "
                  f"{'#' * bars}")

            try:
                again = input("    Enter to keep, 'r' to redo: ").strip().lower()
            except EOFError:
                again = ""
            if again == "r":
                print()
                continue

            write_wav(target, audio)
            recorded += 1
            print(f"    saved {target.name}\n")
            break

    total = sum(1 for p in load_phrases() if (AUDIO / f"{p['id']}.wav").exists())
    all_n = len(load_phrases())
    print("=" * 68)
    print(f"{recorded} recorded this session. {total}/{all_n} of the corpus exists.")
    if total == all_n:
        print("\nCorpus complete. Now measure:")
        print("    venv\\Scripts\\python.exe bench_hinglish.py "
              "--models base,models/swift-ct2")
    else:
        print(f"\n{all_n - total} to go. Re-run this to continue.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
