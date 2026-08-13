# Getting closer to 90%: what was tried and what it bought

Companion to `RESULTS.md`, which reports the shipped configuration, and
`LATENCY.md`, which reports its speed. This file is the experiment log for *changing*
the configuration.

All figures are accuracy, meaning `1 - fair WER`, over the 30 recordings in
`corpus/audio`, with `swift-ct2`, `language=en`, VAD on, and the shipped correction
layer applied. Higher is better. Reproduce with `bench_hinglish.py`.

## Where it started, and where a day of measurement got to

| configuration | overall | code-switch | english | filler | hindi | long | names | numbers | median |
|---|---|---|---|---|---|---|---|---|---|
| **A** was shipping: no timestamps, greedy | 64.8% | 81.0% | 62.4% | 36.4% | 68.9% | 59.6% | 44.8% | 57.5% | 1.94 s |
| **B** timestamps on, greedy | 65.6% | 79.6% | 62.4% | 31.4% | **88.9%** | 61.3% | 44.8% | 53.1% | — |
| **C** timestamps on, beam 5 — **now shipping** | 68.1% | **82.7%** | 64.7% | 43.6% | **88.9%** | 57.8% | 51.4% | 53.1% | 2.89 s |
| **D** C + a names-only prompt | **69.7%** | 82.7% | **66.9%** | 43.6% | **88.9%** | **66.0%** | **63.3%** | 46.9% | 2.32 s |

## Finding 1: suppressing timestamps was costing 20 points of Hindi

`without_timestamps=True` was set on the reasoning that per-word timings are wasted
work when you only paste text. They are wasted — but suppressing them is not free.
Whisper is trained with timestamp tokens interleaved through the transcript, so
removing them takes the decoder off the distribution it learned.

Same audio, same model, same everything else:

```
said           woh file kahan rakhi hai
suppressed     "To phaah hi kahaan rakhi hai?"      60% fair WER
timestamps on  "Vah file kahaan rakhi hai?"          0% fair WER
```

Hindi went 68.9% → 88.9% for tokens we throw away. It also punctuates better,
including question marks, which the `rules` cleanup cannot produce at all — so some
of what reads as "bad grammar" was this.

Note this **cost 1.4 points on code-switch**, which is the category the published
81% headline comes from. On its own, B would have made that headline false. That is
why beam search went in at the same time rather than later.

## Finding 2: beam search does help, and the old note saying otherwise was wrong

The README and `config.py` both said beam search was "slower for no measurable
accuracy gain on short dictation, where the encoder dominates". The encoder part is
true — see `LATENCY.md` — but the conclusion did not follow. Beam 5 is worth
**+2.5 points overall and +6.6 on proper nouns** over greedy.

It is the one change here with a cost the user can feel: median 1.94 s → 2.89 s.
`beam_size: 1` remains available for anyone who would rather have the speed.

`beam_size: 3` was also measured and is **not** reported as a latency figure: it
timed at 7.03 s, slower than beam 5, which is not credible and means that run was
contended. Its accuracy matched beam 5 except on code-switch (84.7%, the best of
any configuration). Worth re-measuring on an idle machine — if it holds, beam 3 may
beat beam 5 on both axes.

## Finding 3: a names-only prompt is not the prompt that was rejected

`initial_prompt` was measured and rejected earlier in this project: it cost accuracy
on code-switching and 39% latency. **That prompt was a general Hinglish word list**
— `kal, aaj, abhi, thoda, matlab, theek hai, meeting, report, ...` — and priming a
model already fine-tuned on Hinglish with ordinary Hinglish vocabulary buys nothing
and biases the decoder.

A prompt of *proper nouns only* is a different intervention, and it is the largest
single win measured here:

```
said  Priya ko bol dena ki Rohit ne approve kar diya
  C   Krya ko bol dena ki aur itne approve kar diya.
  D   Priya ko bol dena ki Rohit ne approve kar diya.        exact

said  WhatsApp pe bhej dena, Gmail check nahi kar raha hoon
  C   WhatsApp par bhej dena ji main check nahin kar raha hoon.
  D   WhatsApp par bhej dena, Gmail check nahin kar raha hoon.
```

Names 51.4% → 63.3%, long 57.8% → 66.0%, english 64.7% → 66.9%, overall 68.1% →
69.7% — and it was *faster* than C, presumably because a decoder that recognises the
word stops searching sooner.

**It is not shipped, and must not be until one test passes.** The prompt used
contained exactly the names in the recordings, so part of that gain is fitting the
test set. The real product form is to build the prompt from the user's own
`vocabulary` setting, which is where they already list their colleagues and tools.
The risk is the failure this project has already had once: a prompt whose words get
pasted as though they were spoken.

The test that decides it: run the same corpus with a prompt of **decoy** proper nouns
that appear nowhere in the audio (`Chennai, Iyer, Ananya, Vikram, Telegram, Outlook,
PhonePe, Indiranagar`) and check whether any of them appear in a transcript. It was
started and abandoned when the benchmark machine slowed to roughly 30 s per clip
after several hours of load — not because of a result. Clean, it ships; leaking, it
does not.

## What is still between here and 90%

Code-switch is at 82.7% (84.7% if the beam-3 number holds). The remaining error is
not spelling variance — the fair scorer already folds `woh`/`vah`, `kahan`/`kahaan`
and number formats. It is genuine acoustic confusion:

```
said  kal ki meeting mein humein pehle budget discuss karna hai phir timeline ...
got   Alty evening mein hamen pahle budget discuss karna hai. Paytm line aur ...
```

`kal ki` → `Alty`, `phir timeline` → `Paytm line`, `resource` → `at the source`. No
decoding parameter fixes that. What might:

1. **The names-only prompt from `vocabulary`**, pending the decoy test. Worth
   ~1.6 points overall and far more on proper nouns.
2. **Re-measure beam 3 on an idle machine.** Possibly the best code-switch number
   available, for less latency than beam 5.
3. **In-segment repetition — attempted, and it does not reach these cases.**
   Two of the worst phrases duplicate themselves (`nm02`, `fl02`), and Whisper's own
   guards do not catch it: `compression_ratio` is 1.07–1.36 against a 2.4 threshold
   and `avg_logprob` is −0.11 to −0.19, so the model is confident about the wrong
   answer. An exact adjacent-clause collapse now runs in `llm_polish._rules`, and it
   is safe — it alters none of the 30 reference transcripts and none of a list of
   deliberate repetitions like `bahut bahut dhanyavad`. But it does **not** fix
   `nm02` or `fl02`, because those are paraphrased restatements (`kar rahe hain` vs
   `kar sakte hain`), not exact repeats. Catching those needs fuzzy matching, which
   is the technique already measured and rejected in `corrections.py` for turning
   correct words into wrong ones. Kept as free insurance against the degenerate
   loop case, not counted as progress toward 90%.
4. **A larger fine-tune.** A larger Oriserve model was measured at 86% on both languages
   and ~19 s per phrase, which is not dictation. This is the ceiling problem, not a
   tuning problem.
5. **Grammar** genuinely needs a language model. `grammar_fix` with a local Ollama
   is implemented and measured (7/10 repairs, 10/10 meaning preserved, 5–8 s), and
   nothing rule-based will approach it. The cheap part of grammar — punctuation and
   sentence casing — improved on its own from finding 1.

## Numbers to re-measure before publishing anything from this file

`RESULTS.md` still reflects configuration A. Regenerate it, and expect these to move:

```powershell
.\venv\Scripts\python.exe bench_hinglish.py --models swift-ct2 `
    --languages en --prompts no --corrections
```

Then update, if they have changed: `settings_ui.PROFILES` (currently 81% / 1.3 s),
`installer.iss` screen 4, and `website/src/components/site/constants.ts`. The
accuracy figures should improve; the latency figure will get worse, and both need to
match the table above rather than the older one.
