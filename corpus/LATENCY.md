# Latency: what was measured, and what to do about it

The latency investigation. Its goal was a decision document with measured numbers,
on the explicit basis that recording a rejection counts as success.

Produced by `bench_latency.py` against `corpus/audio`, the same 30 recordings that
`corpus/RESULTS.md` scores for accuracy. Reproduce with:

```powershell
.\venv\Scripts\python.exe bench_latency.py --models models/swift-ct2 `
    --threads 2,4 --compute int8 --vad on --language en --limit 10 --repeats 3 `
    --by-duration
```

Hardware: Intel i3-1115G4, **2 physical cores / 4 logical**, 15.7 GB RAM. This is
deliberately a slow machine — the product's stated goal is to run on a ₹10,000
laptop, so the interesting number is the one from weak hardware.

**Read the `best` column, not just the median.** Two cores means anything else on
the machine competes directly with the benchmark, and early runs here were
contaminated by exactly that: two benchmark processes left running at once produced
medians that disagreed by 1.4x while their best-case times were within 4%. Those
runs are not in this document. The numbers below were taken with nothing else
running.

## The finding that matters

**Latency does not depend on how long you spoke.**

| audio | median | latency / audio |
|---|---|---|
| 3.6 s | 1.64 s | 0.46x |
| 3.8 s | 1.55 s | 0.41x |
| 4.0 s | 1.57 s | 0.39x |
| 4.3 s | 1.70 s | 0.40x |
| 5.8 s | 1.62 s | 0.28x |
| 6.4 s | 1.65 s | 0.26x |

A 6.4-second clip costs 1.65 s. A 3.6-second clip costs 1.64 s. Across a 1.8x
spread in audio length, latency varies 1.4x and does not trend with duration.

The reason is that Whisper pads every request to a **30-second window** before the
encoder runs. Every clip in this corpus is shorter than that, so every clip pays the
same encoder pass, and the decoder's per-token work is small enough at these lengths
to disappear into the noise.

Three consequences, and they rule out most of the obvious ideas:

- **Chunking or streaming the audio buys nothing** for dictation-length input. The
  cost is per request, not per second, so splitting one request into two makes it
  worse. This is the idea that sounds most promising and is most clearly wrong.
- **Trimming silence buys almost nothing** either, for the same reason. VAD is worth
  keeping for a different reason — see below — but not as a latency lever.
- **The only lever is the encoder**, which means a different model architecture
  rather than a different way of calling this one.

## What was measured

All at `int8`, `language=en`, on 10 clips with 3 repeats after a discarded warm-up.

| configuration | median | best |
|---|---|---|
| 4 threads | **1.66 s** | **1.51 s** |
| 2 threads | 2.04 s | 1.64 s |

| configuration | median | best |
|---|---|---|
| VAD on | **1.63 s** | 1.31 s |
| VAD off | 1.94 s | 1.13 s |

*(the VAD pair is over all 30 clips, so its absolute numbers are not comparable with
the thread pair above — only within the pair)*

### Threads: the existing claim in this repository is wrong

`bench_hinglish.py` says *"Two threads beat four on a 2-core/4-thread CPU"* and
`bench_latency.py`'s own `--threads` help said half the logical CPUs *"measured
fastest here"*. Measured again, cleanly: **4 threads beat 2 by 1.23x on the median
and 1.09x at best.** Hyperthreading is evidently worth something to CTranslate2's
GEMM kernels on this part, and the earlier conclusion was probably drawn on a
contended machine — the same trap described above.

**No default was changed on the strength of this.** The shipped setting is
`cpu_threads: 0`, which hands the decision to CTranslate2, and *what CTranslate2
actually picks was not measured* — the comparison above is between two explicit
values. If its default is already 4, there is nothing to change; if it is 2, there
is a free 1.2x available. Settling that is a ten-minute job and the single most
worthwhile follow-up here.

### VAD earns its place, for the right reason

VAD on is faster on the median (1.63 s vs 1.94 s) and slower at best (1.31 s vs
1.13 s). So it costs a fixed amount to run and saves a variable amount by giving the
decoder less to chew on. Keeping it on — which is what ships — is correct, but the
honest framing is that it reduces the *worst* case rather than the typical one.

### Auto-detection is the biggest avoidable cost, and is already avoided

With `language` unpinned, the same model measured ~4.1 s median against ~1.6 s
pinned. That is not a new finding — it is why `config.py` pins `language: "en"` — but
it is worth recording as a measured multiple, because it dwarfs every other lever in
this document. It also means **any latency number taken with auto-detect on is
measuring a configuration nobody ships**, which is a trap the benchmark tool itself
used to fall into: `bench_latency.py` had no `--language` flag at all until this
work, so every figure it had ever produced included detection overhead.

## Decisions

**Rejected: chunking, streaming and silence-trimming as latency levers.** Measured
to be aimed at the wrong cost. The encoder pass over a padded 30-second window
dominates, and none of these reduce it.

**Rejected: changing `cpu_threads` on this evidence.** The 1.2x is real but the
shipped value is `0`, and what that resolves to was not measured. Changing a default
on a partial measurement is the pattern this project's audit spent its time removing.

**Accepted, unchanged: `vad_filter` on and `language` pinned.** Both now have
measured justification rather than inherited assumption.

**Not tested: `sherpa-onnx` with an IndicConformer CTC model.** This is the one idea
the measurements *support* — a frame-synchronous CTC model has no 30-second padding
and no autoregressive decode, which attacks precisely the fixed cost identified
above. It could not be evaluated here: it needs a model download, and HuggingFace was
unreachable from this network throughout (`ConnectionResetError 10054`). The
Devanagari output question also remains open, and on this corpus that
matters — the reference transcripts are Roman Hinglish, so a Devanagari-emitting
model scores near 100% WER without being wrong, and would need the transliteration
step that naive schemes already failed at.

Recorded as unfinished rather than quietly dropped. The prerequisite is a network
connection, not more engineering.

## What would move the number

In the order the evidence supports:

1. Measure what `cpu_threads: 0` resolves to. Possibly a free 1.2x.
2. A CTC model via `sherpa-onnx`, judged on latency **and** on Roman-script accuracy
   against `corpus/RESULTS.md`. Faster-but-worse is a rejection, not a trade.
3. A smaller encoder. `swift-ct2` is already 74 M parameters; below that, accuracy on
   code-switched speech is the thing being spent.
4. CUDA, which helps the minority of this audience with a discrete GPU and does
   nothing for the ₹10,000 laptop the product is aimed at.
