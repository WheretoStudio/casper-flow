"""
Score speech configurations against the recorded corpus.

    venv\\Scripts\\python.exe bench_hinglish.py

Runs every configuration over every recording in corpus/audio, reports word
error rate overall and per category, and writes corpus/RESULTS.md.

This is the measurement every published accuracy figure comes from, and everything
downstream of it depends on the number being real. Two rules make it so:

  * Word error rate is computed against transcripts of a real speaker, not a
    text-to-speech proxy. The proxy produced two wrong conclusions.
  * Per-category scores are reported alongside the aggregate, because a Hindi
    fine-tune can win overall while destroying English, and the aggregate would
    hide exactly the regression we care about when changing the default model.

Add a model with --models, e.g.

    bench_hinglish.py --models base,small
"""

import argparse
import json
import os
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

for _s in (sys.stdout, sys.stderr):
    try:
        if _s is not None:
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

CORPUS = ROOT / "corpus"
AUDIO = CORPUS / "audio"
PHRASES = CORPUS / "phrases.json"
RESULTS = CORPUS / "RESULTS.md"

# Reuse the app's prompt and the existing scorer rather than reimplementing
# either. Two copies of a WER function is two chances to be subtly wrong.
from config import DEFAULTS as APP_DEFAULTS          # noqa: E402
from wer import word_error_rate, has_devanagari      # noqa: E402
# Resolve names the same way the app does, or this script cannot score the model
# that actually ships: "swift-ct2" is a bundled directory, not a HuggingFace repo
# id, and handing it straight to WhisperModel makes it try to download a repo of
# that name and fail.
from transcribe import resolve_model                 # noqa: E402

# Fillers the cleanup step strips anyway, so the model omitting them is not an
# error worth counting against it.
FILLERS = tuple(APP_DEFAULTS.get("filler_words") or ())

WORD_LIST_PROMPT = APP_DEFAULTS["initial_prompt"]


def configurations(models: list[str], languages: list, prompts: list) -> list[dict]:
    """
    The grid. Kept deliberately small: every extra cell is another full pass
    over the corpus, and on a 2-core CPU that is minutes, not seconds.
    """
    return [{"model": m, "language": lang, "prompt": p}
            for m in models for lang in languages for p in prompts]


def label(cfg: dict) -> str:
    return (f"{cfg['model']} / lang={cfg['language'] or 'auto'} / "
            f"prompt={'yes' if cfg['prompt'] else 'no'}")


def load_corpus() -> list[dict]:
    phrases = json.loads(PHRASES.read_text(encoding="utf-8"))["phrases"]
    have = []
    for p in phrases:
        wav = AUDIO / f"{p['id']}.wav"
        if wav.exists():
            have.append({**p, "wav": wav})
    return have


def run_config(cfg: dict, corpus: list[dict], threads: int, cache: dict,
               corrector=None) -> dict:
    from faster_whisper import WhisperModel

    if cfg["model"] not in cache:
        print(f"    loading {cfg['model']} ...", end="", flush=True)
        cache[cfg["model"]] = WhisperModel(
            resolve_model(cfg["model"]), device="cpu", compute_type="int8",
            cpu_threads=threads,
        )
        print(" ok")
    model = cache[cfg["model"]]

    per_phrase = []
    for item in corpus:
        t0 = time.perf_counter()
        segments, _info = model.transcribe(
            str(item["wav"]),
            # From DEFAULTS, so this scores the shipped decoder rather than a
            # hard-coded one that can drift away from it.
            beam_size=int(APP_DEFAULTS["beam_size"]),
            language=cfg["language"],
            initial_prompt=WORD_LIST_PROMPT if cfg["prompt"] else None,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
            condition_on_previous_text=False,
            # Matches transcribe.py. If these diverge, RESULTS.md stops describing
            # the application - see the comment there for why timestamps are on.
            without_timestamps=False,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        elapsed = time.perf_counter() - t0

        if corrector is not None:
            text = corrector.apply(text)

        per_phrase.append({
            "id": item["id"],
            "category": item["category"],
            "reference": item["text"],
            "hypothesis": text,
            "wer": word_error_rate(item["text"], text),
            "fair": word_error_rate(item["text"], text, fair=True,
                                    drop_fillers=FILLERS),
            "seconds": elapsed,
            "devanagari": has_devanagari(text),
            "empty": not text,
        })
        print(".", end="", flush=True)
    print()

    by_cat = defaultdict(list)
    by_cat_fair = defaultdict(list)
    for r in per_phrase:
        by_cat[r["category"]].append(r["wer"])
        by_cat_fair[r["category"]].append(r["fair"])

    return {
        "config": cfg,
        "label": label(cfg),
        "wer": statistics.mean(r["wer"] for r in per_phrase),
        "fair": statistics.mean(r["fair"] for r in per_phrase),
        "median_seconds": statistics.median(r["seconds"] for r in per_phrase),
        "category_wer": {c: statistics.mean(v) for c, v in sorted(by_cat.items())},
        "category_fair": {c: statistics.mean(v)
                          for c, v in sorted(by_cat_fair.items())},
        "devanagari_count": sum(1 for r in per_phrase if r["devanagari"]),
        "empty_count": sum(1 for r in per_phrase if r["empty"]),
        "phrases": per_phrase,
    }


def write_results(runs: list[dict], corpus: list[dict]) -> None:
    cats = sorted({item["category"] for item in corpus})
    lines = [
        "# Hinglish benchmark results",
        "",
        "Generated by `bench_hinglish.py`. Word error rate, lower is better.",
        "",
        f"Corpus: **{len(corpus)} recordings** of a real speaker "
        f"(`corpus/phrases.json`).",
        "",
        "These numbers are measured on one person's voice. They are the right",
        "basis for choosing this installation's defaults and the wrong basis for",
        "a general claim about a model.",
        "",
        "## How to read these numbers",
        "",
        "**Compare configurations, not absolute values.** Word error rate against",
        "Roman Hinglish overstates error, because Hinglish has no canonical",
        "spelling: `yeh`/`yah`, `woh`/`vah`, `kahan`/`kahaan` and `hai`/`hain` are",
        "all legitimate, and an exact word match counts every variant as wrong.",
        "Every configuration is scored identically, so the comparison between them",
        "is sound even though the absolute figures are inflated.",
        "",
        "Three categories are especially affected and should not be read as",
        "straightforward failure:",
        "",
        "- **numbers** - the model writes digits where the reference has words.",
        "  `forty two thousand five hundred rupees` transcribed as `42500 rupees`",
        "  scores as six errors while arguably being the better output.",
        "- **filler** - the model drops `um` and `uh`, which the reference keeps.",
        "  That scores as a deletion, and the cleanup step strips them anyway, so",
        "  the model doing it first costs nothing.",
        "- **names** - proper nouns are genuinely hard, and a single mangled name in",
        "  a short phrase moves the percentage a long way.",
        "",
        "**code-switch and english are the two that matter.** The first is the",
        "product's reason to exist. The second is the regression check, because a",
        "Hindi fine-tune can win overall while quietly ruining English.",
        "",
        "## Overall",
        "",
        "`strict` is exact word match. `fair` folds romanisation variants and",
        "number formats and ignores dropped fillers - see `wer.py` for exactly",
        "what it forgives, including what it over-forgives. Accuracy is",
        "`1 - fair`.",
        "",
        "| Configuration | strict WER | fair WER | accuracy | Median | Empty |",
        "|---|---|---|---|---|---|",
    ]
    for r in sorted(runs, key=lambda r: r["fair"]):
        lines.append(
            f"| {r['label']} | {r['wer']:.1%} | **{r['fair']:.1%}** | "
            f"**{1 - r['fair']:.1%}** | {r['median_seconds']:.2f} s | "
            f"{r['empty_count']}/{len(corpus)} |"
        )

    lines += ["", "## By category (fair WER)", "",
              "| Configuration | " + " | ".join(cats) + " |",
              "|---" * (len(cats) + 1) + "|"]
    for r in sorted(runs, key=lambda r: r["fair"]):
        cells = [f"{r['category_fair'].get(c, float('nan')):.1%}" for c in cats]
        lines.append(f"| {r['label']} | " + " | ".join(cells) + " |")

    lines += ["", "## By category (strict WER)", "",
              "| Configuration | " + " | ".join(cats) + " |",
              "|---" * (len(cats) + 1) + "|"]
    for r in sorted(runs, key=lambda r: r["fair"]):
        cells = [f"{r['category_wer'].get(c, float('nan')):.1%}" for c in cats]
        lines.append(f"| {r['label']} | " + " | ".join(cells) + " |")

    best = min(runs, key=lambda r: r["fair"])
    lines += [
        "",
        "## Worst phrases for the best configuration",
        "",
        f"Configuration: `{best['label']}`",
        "",
        "Ranked by fair WER, so what is listed here is genuine error rather than",
        "spelling difference. These are the phrases to fix.",
        "",
        "| id | fair | strict | Said | Transcribed |",
        "|---|---|---|---|---|",
    ]
    for r in sorted(best["phrases"], key=lambda r: -r["fair"])[:10]:
        said = r["reference"].replace("|", "\\|")
        got = (r["hypothesis"] or "(nothing)").replace("|", "\\|")
        lines.append(f"| {r['id']} | {r['fair']:.0%} | {r['wer']:.0%} | "
                     f"{said} | {got} |")

    lines.append("")
    RESULTS.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Benchmark speech configs on the corpus.")
    ap.add_argument("--models", default="base",
                    help="comma-separated model list (default: base)")
    ap.add_argument("--languages", default="auto",
                    help="comma-separated, 'auto' for detection (default: auto)")
    ap.add_argument("--prompts", default="yes,no",
                    help="'yes', 'no', or both (default: yes,no)")
    ap.add_argument("--corrections", action="store_true",
                    help="also apply the correction layer, using the vocabulary "
                         "in settings.json")
    args = ap.parse_args()

    if not PHRASES.exists():
        print(f"missing {PHRASES}")
        return 1

    corpus = load_corpus()
    total = len(json.loads(PHRASES.read_text(encoding="utf-8"))["phrases"])
    if not corpus:
        print("No recordings found in corpus/audio.")
        print("\nRecord them first:")
        print("    venv\\Scripts\\python.exe record_corpus.py")
        return 1
    if len(corpus) < total:
        print(f"Note: {len(corpus)} of {total} phrases recorded. Scoring what "
              f"exists.\n")

    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        print("faster-whisper missing - run install.ps1 first")
        return 1

    # Half the logical CPUs. Note that this is NOT the fastest setting: measured
    # cleanly in corpus/LATENCY.md, 4 threads beat 2 by 1.23x on this 2-core/4-thread
    # part, and the older "two beat four" claim was almost certainly taken on a
    # contended machine. It is kept here anyway, because this script's job is
    # comparing models to each other and a lower thread count leaves the machine
    # responsive over a long run - accuracy does not depend on it. Use
    # bench_latency.py for latency questions.
    threads = max(1, (os.cpu_count() or 2) // 2)
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    languages = [None if lang.strip().lower() in ("auto", "none", "null") else lang.strip()
                 for lang in args.languages.split(",") if lang.strip()]
    prompts = [p.strip().lower() in ("yes", "true", "1")
               for p in args.prompts.split(",") if p.strip()]
    grid = configurations(models, languages, prompts)

    print(f"{len(grid)} configurations x {len(corpus)} recordings, "
          f"{threads} threads.\n")

    corrector = None
    if args.corrections:
        from config import load_config
        from corrections import Corrector
        app_cfg = load_config()
        corrector = Corrector(app_cfg)
        if not corrector.enabled:
            print("--corrections given but settings.json has no vocabulary or "
                  "corrections; measuring without it.\n")
            corrector = None
        else:
            print(f"corrections: {len(corrector.vocabulary)} vocabulary entries, "
                  f"{len(corrector.replacements)} replacements\n")

    cache: dict = {}
    runs = []
    for cfg in grid:
        print(f"  {label(cfg)}")
        try:
            runs.append(run_config(cfg, corpus, threads, cache, corrector))
        except Exception as e:
            print(f"    FAILED {type(e).__name__}: {e}")

    if not runs:
        print("Nothing ran successfully.")
        return 1

    print("\n" + "=" * 78)
    print(f"{'configuration':40}{'strict':>9}{'fair':>8}{'accuracy':>10}{'median':>9}")
    print("-" * 78)
    for r in sorted(runs, key=lambda r: r["fair"]):
        print(f"{r['label']:40}{r['wer']:>8.1%}{r['fair']:>8.1%}"
              f"{1 - r['fair']:>10.1%}{r['median_seconds']:>8.2f}s")

    best = min(runs, key=lambda r: r["fair"])
    print(f"\nBest: {best['label']}")
    print(f"    accuracy {1 - best['fair']:.1%}  (fair WER {best['fair']:.1%}, "
          f"strict {best['wer']:.1%})")
    for cat in sorted(best["category_fair"]):
        fair = best["category_fair"][cat]
        strict = best["category_wer"][cat]
        print(f"    {cat:14} accuracy {1 - fair:>6.1%}   "
              f"(fair {fair:.1%}, strict {strict:.1%})")

    if best["empty_count"]:
        print(f"\n{best['empty_count']} recording(s) produced no text at all. "
              f"That is the prompt-leak guard or the silence check firing; "
              f"check corpus/RESULTS.md.")

    write_results(runs, corpus)
    print(f"\nWritten: {RESULTS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
