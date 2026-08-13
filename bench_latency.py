"""
Measure transcription latency, reproducibly.

    venv\\Scripts\\python.exe bench_latency.py
    venv\\Scripts\\python.exe bench_latency.py --models tiny,base,models/swift-ct2

Every latency figure in the README should come from this script, so that anyone
can re-run it and get the same answer on their own hardware. It exists because a
previously published number could not be reproduced.

Two traps this avoids, both of which produce numbers that look better than
reality:

  * `WhisperModel.transcribe()` returns a lazy generator. Nothing is decoded
    until it is consumed. Timing only the call reports roughly half the true
    cost, measured. The segments are consumed inside the timed region here.
  * A cold model pays a one-off load. The first pass per model is discarded as a
    warm-up rather than averaged in.

Latency is reported as a median over repeats, with the minimum alongside, because
a single run on a laptop is at the mercy of whatever else the machine is doing.
"""

import argparse
import os
import platform
import statistics
import sys
import time
import wave
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

for _s in (sys.stdout, sys.stderr):
    try:
        if _s is not None:
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).parent
CLIPS = ROOT / "_clips"
CORPUS_AUDIO = ROOT / "corpus" / "audio"


def clip_paths() -> list[Path]:
    """Prefer real recordings; fall back to whatever is in _clips."""
    if CORPUS_AUDIO.exists():
        wavs = sorted(CORPUS_AUDIO.glob("*.wav"))
        if wavs:
            return wavs
    return sorted(CLIPS.glob("*.wav"))


def duration(path: Path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def dir_size_mb(p: Path) -> float:
    if not p.exists() or not p.is_dir():
        return 0.0
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) / (1024 * 1024)


def main() -> int:
    ap = argparse.ArgumentParser(description="Measure transcription latency.")
    ap.add_argument("--models", default="tiny,base",
                    help="comma-separated model names or paths")
    ap.add_argument("--repeats", type=int, default=4)
    ap.add_argument("--compute", default="int8",
                    help="comma-separated to sweep: int8,int8_float32,float32")
    ap.add_argument("--threads", default="0",
                    help="comma-separated to sweep. 0 means half the logical CPUs, "
                         "which is NOT the fastest setting - see corpus/LATENCY.md, "
                         "where 4 threads beat 2 on a 2-core/4-thread part. It is "
                         "not the same as cpu_threads=0 in settings.json, which "
                         "lets CTranslate2 choose")
    ap.add_argument("--vad", default="on", choices=("on", "off", "both"),
                    help="voice-activity filtering. 'both' sweeps it")
    ap.add_argument("--language", default="",
                    help="ISO code to pin, or empty for auto-detect. The app pins "
                         "'en', so leaving this empty measures a configuration "
                         "nobody ships - auto-detection is a per-request cost")
    ap.add_argument("--limit", type=int, default=0,
                    help="use only the first N clips, for a quick sweep")
    ap.add_argument("--by-duration", action="store_true",
                    help="also report latency against clip length, which is how "
                         "you see whether the encoder pad dominates")
    args = ap.parse_args()

    clips = clip_paths()
    if not clips:
        print("No audio found. Record the corpus, or generate scratch clips.")
        return 1

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("faster-whisper missing - run install.ps1 first")
        return 1

    if args.limit:
        clips = clips[:args.limit]
    total_audio = sum(duration(c) for c in clips)

    default_threads = max(1, (os.cpu_count() or 2) // 2)
    thread_list = [int(t) or default_threads
                   for t in args.threads.split(",") if t.strip()]
    compute_list = [c.strip() for c in args.compute.split(",") if c.strip()]
    vad_list = {"on": [True], "off": [False], "both": [True, False]}[args.vad]

    print(f"{platform.processor() or 'unknown CPU'}")
    print(f"{os.cpu_count()} logical CPUs")
    print(f"{len(clips)} clip(s), {total_audio:.1f}s of audio, "
          f"{args.repeats} repeats after a discarded warm-up")
    configs = (len([m for m in args.models.split(',') if m.strip()])
               * len(thread_list) * len(compute_list) * len(vad_list))
    print(f"{configs} configuration(s)\n")

    rows = []
    for name in [m.strip() for m in args.models.split(",") if m.strip()]:
        local = ROOT / name
        size = dir_size_mb(local)
        for compute in compute_list:
            for threads in thread_list:
                try:
                    t0 = time.perf_counter()
                    model = WhisperModel(
                        str(local) if local.exists() else name,
                        device="cpu", compute_type=compute, cpu_threads=threads)
                    load = time.perf_counter() - t0
                except Exception as e:
                    print(f"{name} {compute} t{threads}: LOAD FAILED "
                          f"{type(e).__name__}: {e}")
                    continue

                for vad in vad_list:
                    label = (f"{name} / {compute} / {threads}t / "
                             f"vad={'on' if vad else 'off'} / "
                             f"lang={args.language or 'auto'}")
                    per_clip = []
                    for clip in clips:
                        times = []
                        for i in range(args.repeats + 1):
                            t0 = time.perf_counter()
                            segments, _info = model.transcribe(
                                str(clip), beam_size=1,
                                language=args.language or None,
                                vad_filter=vad,
                                vad_parameters=dict(min_silence_duration_ms=500),
                                condition_on_previous_text=False,
                                # Matches transcribe.py, so this measures the
                                # configuration that ships.
                                without_timestamps=False,
                            )
                            # Consuming the generator is where the work happens.
                            _text = " ".join(
                                s.text.strip() for s in segments).strip()
                            elapsed = time.perf_counter() - t0
                            if i:                   # discard the warm-up
                                times.append(elapsed)
                        per_clip.append(
                            (clip, statistics.median(times), min(times)))

                    med = statistics.median([m for _, m, _ in per_clip])
                    rows.append({"label": label, "size": size, "load": load,
                                 "median": med, "clips": per_clip})
                    print(f"{label}")
                    print(f"    median {med:.2f}s   "
                          f"best {min(lo for _, _, lo in per_clip):.2f}s   "
                          f"loaded in {load:.2f}s"
                          + (f"   {size:.0f} MB on disk" if size else ""))
                    if args.repeats and len(clips) <= 8:
                        for clip, m, lo in per_clip:
                            print(f"      {clip.name:14} "
                                  f"{duration(clip):5.1f}s audio -> "
                                  f"{m:5.2f}s  ({lo:.2f}s best)")
                    print()
                del model

    if len(rows) > 1:
        print("=" * 74)
        print(f"{'configuration':52}{'median':>10}{'vs best':>10}")
        print("-" * 74)
        best = min(r["median"] for r in rows)
        for r in sorted(rows, key=lambda r: r["median"]):
            print(f"{r['label']:52}{r['median']:>9.2f}s"
                  f"{r['median'] / best:>9.2f}x")

    if args.by_duration and rows:
        # The question this answers: does latency track how long you spoke, or is
        # it a fixed cost? Whisper pads every request to a 30-second window, so if
        # the encoder dominates, a 2-second clip costs about what a 10-second one
        # does - and shortening audio is not a lever worth pulling.
        r = min(rows, key=lambda r: r["median"])
        print(f"\n{'=' * 74}\nLatency against clip length - {r['label']}\n")
        print(f"{'audio':>8}{'median':>10}{'ratio':>10}")
        print("-" * 30)
        for clip, m, _lo in sorted(r["clips"], key=lambda c: duration(c[0])):
            d = duration(clip)
            print(f"{d:>7.1f}s{m:>9.2f}s{m / d:>9.2f}x")
        lengths = [duration(c) for c, _, _ in r["clips"]]
        meds = [m for _, m, _ in r["clips"]]
        if len(set(lengths)) > 1:
            spread = max(meds) / min(meds)
            audio_spread = max(lengths) / min(lengths)
            print(f"\naudio length varies {audio_spread:.1f}x, "
                  f"latency varies {spread:.1f}x")
            print("A latency spread far below the audio spread means the cost is "
                  "fixed\nper request rather than per second of speech.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
