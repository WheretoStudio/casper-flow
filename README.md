# Casper Flow

Push-to-talk dictation for Windows. Hold a key, speak, release, and the text is
inserted wherever your cursor is — in any application.

Everything runs on your own machine. Speech recognition is local, text cleanup is
local, and `offline_only` is `true` out of the box — a setting enforced in code, so
no combination of configuration can send your audio or your transcript to a server.
There are no accounts, no sign-in and no telemetry. Cloud backends exist in the
codebase for people who want them, and reaching them takes a deliberate opt-out.

```
hold key ──► record mic ──► Whisper ──► optional LLM cleanup ──► Ctrl+V at the caret
```

**Default hotkey: hold Caps Lock for two seconds.** Anything shorter is treated as an
ordinary Caps Lock press and handed back to Windows, so the key still toggles exactly
as it always did. Holding dictates, and does not change your typing case.

> The `Fn` key cannot be used as a hotkey. It is handled inside the keyboard's own
> firmware and is never delivered to Windows, so no application on any operating
> system can bind it.

---

## Contents

- [Requirements](#requirements)
- [Installation](#installation)
- [Usage](#usage)
- [Performance](#performance)
- [Configuration](#configuration)
- [Models](#models)
- [Choosing a hotkey](#choosing-a-hotkey)
- [The status overlay](#the-status-overlay)
- [Clipboard handling](#clipboard-handling)
- [Windows permissions and antivirus](#windows-permissions-and-antivirus)
- [Starting automatically](#starting-automatically)
- [Troubleshooting](#troubleshooting)
- [How it works](#how-it-works)
- [Privacy](#privacy)
- [Project layout](#project-layout)
- [Contributing](#contributing)
- [License](#license)

---

## Requirements

| | |
|---|---|
| OS | Windows 10 or 11 (x64) |
| Python | 3.10 or newer (developed and tested on 3.11) |
| Disk | ~150 MB for dependencies, plus 75 MB–1.5 GB for the speech model |
| Hardware | Any x64 CPU. A discrete GPU is optional and only affects speed. |
| Accounts | None. API keys are optional. |

Administrator rights are not required for normal use. See
[Windows permissions](#windows-permissions-and-antivirus) for the two exceptions.

---

## Installation

### If you just want to use it

Download **`CasperFlowSetup.exe`** and double-click it. No Python, no PowerShell, no
administrator rights, and no UAC prompt — it installs for your account only, into
`%LOCALAPPDATA%\Programs\CasperFlow`. A short wizard then checks your microphone, lets
you choose your key, and has you dictate one sentence to prove it works.

Both speech models are inside the download, so setup needs no internet connection.

| | |
|---|---|
| Download | ~234 MB |
| On disk after install | ~420 MB |
| Uninstall | Settings → Apps, or Start Menu → Casper Flow → Uninstall |

Windows will warn you about an unrecognised app, and Defender may quarantine it. That is
what happens to unsigned software that installs a keyboard hook; see
[Antivirus](#antivirus) for why and what to do. Checksums are published with
every release so you can verify the download rather than trust it.

**There is no published release yet.** Until there is, build the installer yourself with
`build_installer.ps1` — see below.

`CasperFlow-portable.zip` is also produced, for machines where an installer cannot run.
It has no Start Menu entry, no launch-at-login option and no uninstaller; to remove it you
delete the folder.

### If you want to work on it

```powershell
git clone <your-fork-url> casper-flow
cd casper-flow
powershell -ExecutionPolicy Bypass -File install.ps1
```

`install.ps1` is the **developer** path, not the one to send to a normal user. It locates
a suitable Python interpreter, creates a virtual environment in `.\venv`, installs
`requirements.txt`, optionally installs the cloud backends, creates `.env` from the
template, and finishes by running the self-check.

To build what users download:

```powershell
.\venv\Scripts\python.exe fetch_models.py        # once: assembles models\
powershell -ExecutionPolicy Bypass -File build_installer.ps1
```

**`fetch_models.py` is the first step and only has to be run once.** The two speech
models are 219 MB of weights and are not in git; `models\MODELS.lock.json` is, and it
records the source repository, the revision and a SHA-256 for every file. The script
downloads `base.en`, converts the Hinglish model, and fills in that lock file.
`build_installer.ps1` verifies against it and refuses to build if the weights on disk
are not the ones the published accuracy figures were measured on. Converting needs
`torch` and `transformers` once — the script prints the exact command if they are
missing, and they can be uninstalled afterwards.

The build then runs PyInstaller, compiles `installer.iss` with Inno Setup 6, zips the
portable copy and writes `SHA256SUMS.txt`. It needs
[Inno Setup 6](https://jrsoftware.org/isdl.php) (`winget install --id
JRSoftware.InnoSetup`) and writes everything to `%LOCALAPPDATA%\CasperFlowBuild`, outside
the repository — building inside a OneDrive-synced folder fails, because OneDrive holds
handles on the files while it uploads half a gigabyte of build output.

### Manual installation

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe doctor.py
```

Use `requirements.lock.txt` instead of `requirements.txt` to reproduce the exact
dependency versions this was tested against.

### Verifying an installation

```powershell
.\venv\Scripts\python.exe doctor.py
```

`doctor.py` checks the dependencies, validates `settings.json`, resolves the
configured hotkey, opens a real microphone stream, performs a full clipboard
save-and-restore cycle, and loads the speech model. It exits non-zero if anything
is broken, and prints a specific remedy for each failure.

---

## Usage

```powershell
.\start_casper.bat
```

A microphone icon appears in the notification area. Hold **Caps Lock** for two
seconds, speak, release. The text is pasted at the cursor position in whatever window
has focus. A shorter press just toggles Caps Lock.

The first launch downloads the speech models (145 MB for the default `base`, plus
75 MB for the `tiny` model used for live captions) into
`%USERPROFILE%\.cache\huggingface`. The models and the microphone stream are all
initialised during startup rather than on first use, and the hotkey is not armed until
they are ready, so the first dictation is no slower than the rest. Wait for
`Hotkey listener active` in the log.

Tray menu:

| Item | Effect |
|---|---|
| **Casper Flow Enabled** | Ignore the hotkey without quitting |
| Hold [...] to dictate | Shows the active hotkey and backends |
| **Launch at Login** | Adds or removes the `HKCU` Run entry |
| Open settings.json | Opens the config in your default editor |
| View log | Opens `casper.log` |
| Quit Casper Flow | Releases the keyboard hook and exits |

Starting Casper Flow twice is refused, because two instances would both hook the hotkey
and each dictation would be pasted twice.

---

## Performance

Dictation latency is dominated by the speech model, not by the rest of the
pipeline. It is worth understanding why, because the usual advice about real-time
factors does not apply to short utterances.

Whisper pads every request to a **30-second window**, so a four-second phrase costs
almost as much as a sixteen-second one. What matters is therefore absolute latency
on a short clip, not a real-time factor.

Reproduce any of these on your own machine:

```powershell
.\venv\Scripts\python.exe bench_latency.py --models tiny,base
```

### Model size is the dominant factor

Measured on a 2-core / 4-thread laptop CPU (Intel i3-1115G4 class), `int8`,
2 threads, median of 4 runs after a discarded warm-up, over a 5.8-second phrase and
a 16.8-second passage:

| Model | Median latency | Disk | Languages |
|---|---|---|---|
| `tiny` | 1.71 s | 75 MB | multilingual — used for live captions |
| **`base`** | **2.98 s** | 141 MB | multilingual — **default** |
| `Whisper-Hindi2Hinglish-Swift` | 3.00 s | 78 MB | Hindi/English, Roman output |

> **These numbers replace earlier, lower figures that could not be reproduced.**
> A previous version of this table claimed 0.86 s for `base`. Re-measuring with
> `bench_latency.py` gives 2.98 s under the settings the app actually ships.
>
> Part of the gap is explained: `WhisperModel.transcribe()` returns a **lazy
> generator**, and no decoding happens until it is consumed. Timing only the call
> reports roughly half the true cost — measured at 1.39 s versus 2.82 s on the same
> clip. Any benchmark that forgot to consume the generator was timing setup and
> calling it transcription.
>
> The *conclusions* did not change: model size still dominates, and the ordering of
> the models is the same. Only the absolute values were wrong. `small`,
> `distil-small.en` and `large-v3-turbo` have not yet been re-measured with this
> script; the figures previously published for them should be treated as unverified.

What drove the default:

- **Multilingual costs almost nothing** over the English-only build of the same size,
  and since `.en` models cannot transcribe Hindi at all, there is no reason to give up
  multilingual support for a rounding error.
- **`large-v3-turbo` is not usable on this class of CPU.** It was measured at over ten
  seconds for a few seconds of speech. It is, however, exactly what the Groq backend
  serves — the argument for the cloud if you want both accuracy and speed, and the
  reason we do not.
- **Reputation is not a benchmark.** `distil-small.en` measured no faster than `small`
  despite being widely described as a speed win.

### Other settings matter much less

Using the `small` model throughout:

| Setting | Latency |
|---|---|
| `int8`, 2 threads | 2.63 s |
| `int8`, auto threads | 2.80 s |
| `int8`, 4 threads | 2.99 s |
| `float32`, 2 threads | 4.80 s |

Two results worth stating explicitly, as both contradict common advice:

- **`beam_size` does not meaningfully affect short dictation.** Greedy decoding and
  beam search landed within measurement noise of each other, because the encoder
  dominates and the decoder emits very few tokens. Casper Flow uses `beam_size: 1`
  because it bounds the worst case on long recordings, not because it is faster.
- **Latency does not depend on how long you speak.** A 6.4-second clip and a
  3.6-second clip both cost about 1.65 seconds, because Whisper pads every request
  to a 30-second window before the encoder runs. Chunking the audio or trimming
  silence therefore buys nothing — the cost is per request, not per second. See
  [`corpus/LATENCY.md`](corpus/LATENCY.md).
- **This document previously claimed four threads were slower than two on a
  two-core machine. Re-measured, that was wrong** — 4 threads beat 2 by 1.23x. The
  earlier figure was almost certainly taken while something else was running, which
  on two cores is easy to do and hard to notice.

### Making it faster

1. **Use a smaller model** — by far the largest local win, since it reduces the
   fixed encoder cost. English-only `.en` variants are faster *and* more accurate
   for English than multilingual models of the same size.
2. **Try `cpu_threads` at your logical core count.** Worth about 1.2x here against
   half that. The default `0` lets CTranslate2 choose, and what it chooses has not
   been measured, so this may already be what you get.
3. **Use a GPU** — install a CUDA-enabled CTranslate2, then set
   `"whisper_device": "cuda"` and `"whisper_compute_type": "float16"`.
4. **Use a hosted model** — `transcribe_backend: "groq"` with
   `whisper-large-v3-turbo` is the fastest option available and is what commercial
   dictation tools generally rely on. It needs an API key and sends audio off your
   machine.

For reference, the on-screen overlay contributes about 3% to end-to-end latency, so
it is not worth disabling for speed.

---

## Configuration

All settings live in `settings.json`, next to `main.py` (tray → **Open
settings.json**). Changes take effect on the next launch. Unrecognised keys are
reported in the log rather than being silently ignored, and a `"//"` key is treated
as a comment so the file can explain itself.

### Local overrides

`settings.local.json` is applied on top of `settings.json` and is never committed.
Put machine-specific choices there — a converted model, a tuned hotkey — and leave
`settings.json` as the shipped default:

```json
{
  "whisper_model": "swift-ct2",
  "language": "en",
  "initial_prompt": null
}
```

Overrides are validated exactly like `settings.json`, so a bad value degrades to the
default with a log line rather than breaking startup. The log records which keys were
overridden, so a surprising setting is traceable to the file that set it.

### Using a locally converted model

Any directory under `models/` containing a `model.bin` can be selected by name:

```json
"whisper_model": "swift-ct2"     // loads models/swift-ct2
```

This is how a model you converted yourself becomes usable without a HuggingFace
identifier. The path is resolved to an absolute one, because the app is launched from
a shortcut, a `.bat` file and a scheduled task, and those do not agree on the working
directory. Anything that is not a local directory is passed through as a HuggingFace
identifier as before.

The two models Casper Flow ships are assembled by `fetch_models.py`, which is the
supported route and records what it did in `models\MODELS.lock.json`:

```powershell
.\venv\Scripts\python.exe fetch_models.py              # both models
.\venv\Scripts\python.exe fetch_models.py --verify     # check, change nothing
```

To convert some other Whisper-architecture model by hand:

```powershell
ct2-transformers-converter --model Oriserve/Whisper-Hindi2Hinglish-Swift `
  --output_dir models\swift-ct2 --copy_files tokenizer.json preprocessor_config.json `
  --quantization int8
```

That needs `torch` and `transformers`, which are build-time only. Install the CPU
wheel — the default on Windows pulls the CUDA build at roughly ten times the size for
a job that only loads weights:

```powershell
.\venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu transformers
```

### Hotkey

| Key | Default | Meaning |
|---|---|---|
| `hotkey` | `"caps lock"` | A single key or a combination. See [Choosing a hotkey](#choosing-a-hotkey). |
| `suppress_hotkey` | `true` | Prevent the key performing its normal function while held. Applied only when the whole combination matches. |
| `min_hold_seconds` | `2.0` | How long you must hold before the press counts as dictation. See below. |
| `max_hold_seconds` | `120` | Safety ceiling for recovering from a lost key-release event. See [How it works](#how-it-works). |

### Speech recognition

| Key | Default | Meaning |
|---|---|---|
| `transcribe_backend` | `"local"` | `local`, `groq` or `openai`. The cloud options are refused while `offline_only` is on. |
| `whisper_model` | `"swift-ct2"` | A Hinglish-tuned model bundled with the app. See [Models](#models). |
| `whisper_device` | `"cpu"` | `cpu` or `cuda`. Falls back to CPU with a warning if the GPU cannot be used. |
| `whisper_compute_type` | `"int8"` | `int8`, `float16` or `float32`. `int8` is roughly twice as fast as `float32` on CPU. |
| `cpu_threads` | `0` | `0` lets CTranslate2 decide. Your logical core count measured 1.2x faster than half of it — see [`corpus/LATENCY.md`](corpus/LATENCY.md). |
| `beam_size` | `1` | `1` is greedy decoding. |
| `language` | `"en"` | Pinned, because auto-detection is the largest latency cost in the pipeline and measured no more accurate here. See [`language` depends on which model you use](#language-depends-on-which-model-you-use). |
| `initial_prompt` | `null` | Not used with a Hinglish-tuned model: it cost accuracy and 39% latency. See [Keep `initial_prompt` a word list](#keep-initial_prompt-a-word-list-not-sentences). |
| `initial_prompt` | Hinglish word list | The single biggest accuracy lever for code-mixed speech. Must be a comma-separated word list, never a sentence. See [Keep `initial_prompt` a word list](#keep-initial_prompt-a-word-list-not-sentences). |
| `preload_model` | `true` | Load the model during startup instead of on first use. |
| `preview_model` | `null` | Model used for live captions. Only loaded when `live_preview` is on, and downloaded on demand since it is not bundled. |
| `groq_whisper_model` | `"whisper-large-v3-turbo"` | Only used when `offline_only` is off. |
| `openai_whisper_model` | `"gpt-4o-mini-transcribe"` | Only used when `offline_only` is off. |

### Text cleanup

| Key | Default | Meaning |
|---|---|---|
| `llm_polish` | `true` | Remove filler words and fix punctuation and casing. |
| `llm_backend` | `"rules"` | `rules`, `ollama`, or `openai`/`anthropic`/`groq`. See below. |
| `filler_words` | `um`, `uh`, … | The list the `rules` backend strips. Edit it freely. |
| `llm_model` | `"gpt-4o-mini"` | Only used by the cloud backends. |
| `llm_timeout_seconds` | `20` | Also used for cloud transcription. On timeout the raw transcript is pasted rather than nothing. |
| `ollama_url` / `ollama_model` | `localhost:11434`, `llama3` | Local LLM cleanup. Allowed under `offline_only`, because it never leaves the machine. |
| `output_script` | `"latin"` | `latin`, `devanagari` or `as-is`. See [Script of the output](#script-of-the-output). |
| `format_mode` | `"plain"` | `plain`, `message` or `email`. See [Grammar and layout](#grammar-and-layout). |
| `grammar_fix` | `false` | Fix tense, agreement and word order. Needs a language model. |

**`rules` is the default, and it is a deliberate choice rather than a placeholder.**
It is a deterministic pass: strip fillers, collapse repeats, fix spacing around
punctuation, capitalise sentences. It cannot invent a word that you did not say. An
LLM can, and during development one did — it echoed part of its own prompt into a
document as though it had been dictated. For dictation, where the output goes
straight into your work at the caret, a cleanup step that is incapable of
hallucinating is worth more than one that writes more elegant sentences.

`ollama` is the recommended upgrade if you want smarter rewriting: it is a genuine
LLM, it runs on localhost, and it stays inside the privacy guarantee.

If `llm_polish` is enabled but no key is configured for the chosen cloud backend, the
step is skipped and the raw transcript is used. The tray menu shows
`Polish: openai (no API key - skipped)` so this is visible rather than mysterious.

### Audio, overlay and paste

| Key | Default | Meaning |
|---|---|---|
| `sample_rate` / `channels` | `16000`, `1` | Whisper expects 16 kHz mono. |
| `input_device` | `null` | System default, or a device index, or part of a device name such as `"Realtek"`. |
| `max_record_seconds` | `300` | Prevents a stuck key from consuming memory indefinitely. |
| `keep_mic_open` | `true` | Create the microphone stream once and reuse it. See below. |
| `show_pill` | `true` | Show the on-screen indicator. |
| `pill_style` | `"blob"` | `blob`, `caption` or `capsule`. See [The status overlay](#the-status-overlay). |
| `pill_position` | `"bottom-center"` | Also `bottom-right`, `top-center`, `center`. |
| `pill_scale` | `1.0` | `0.5`–`3.0`. |
| `live_preview` | `false` | Stream a rough transcript into the overlay while you are still speaking. Only useful with `pill_style: "caption"`, since the other styles show no text. |
| `preview_interval_seconds` | `1.0` | How often a preview pass runs. Lower is more responsive and more CPU. |
| `paste_settle_seconds` | `0.06` | Delay before `Ctrl+V`, allowing focus to settle. |
| `clipboard_restore_seconds` | `0.4` | Delay before the previous clipboard contents are restored. |

**`keep_mic_open` is why dictation starts instantly.** Opening a PortAudio input
stream costs **1250–1450 ms** on a low-end CPU, measured, and it costs that every
time — closing and reopening is not cheaper. Paying it on the hotkey press meant the
microphone went live *after* short dictations had already ended, so they recorded
nothing at all. Creating the stream once at startup and starting it per dictation
takes the cost on the hot path from ~1300 ms to **0 ms**.

A created-but-stopped stream captures nothing. Verified: zero frames over a full
second while stopped, frames only after it is started, and none after it is stopped
again. Set `keep_mic_open` to `false` if you would rather the device be released the
moment a dictation ends and accept the delay on the next one.

### Your own words

| Key | Default | Meaning |
|---|---|---|
| `vocabulary` | `[]` | Canonical spelling and capitalisation for words you use. |
| `corrections` | `{}` | An explicit "heard this, meant that" mapping. |

No speech model has heard of your colleagues, and proper nouns are the weakest measured
category — 44.8% accuracy against 81.0% for code-switched speech generally. These two
settings let you tell the app your words:

```json
"vocabulary": ["WhatsApp", "Gmail", "Bangalore", "Priya"],
"corrections": { "thank you office": "Bangalore office" }
```

`vocabulary` is matched **exactly and case-insensitively**, so `whatsapp` becomes
`WhatsApp`. It never changes *which* word was transcribed. `corrections` is applied first
and exactly — reach for it when the same mistake keeps appearing.

**This was deliberately made less clever after measuring it.** Vocabulary entries used to
match by sound, so that one entry would catch every misspelling. That failed twice: the
real failures are not near-misses (`Bangalore` came back as `Thank you`, which no matcher
can recover), and sound matching rewrote `shaam` and `sharp` to `Sharma` in sentences that
were already correct. Both mechanisms are now incapable of altering a word you did not
name. See the comments in `corrections.py`.

### Privacy

| Key | Default | Meaning |
|---|---|---|
| `offline_only` | `true` | Refuse any backend that would leave the machine. Localhost services such as Ollama remain allowed. |

The check is not a filter applied to your configuration at load time — it sits in
`transcribe.py` and `llm_polish.py` immediately before the network call, so a stray
setting, a bad merge or a future code path cannot quietly start uploading. When it
fires it downgrades to the local equivalent and writes a line to the log explaining
what it refused. Setting it to `false` is the only way to reach a cloud backend, and
that is one edit you have to make on purpose.

### API keys

Copy `.env.example` to `.env` and fill in only what you need. Values may be quoted,
and `export KEY=value` is accepted. Real environment variables take precedence.

```env
OPENAI_API_KEY=sk-...
GROQ_API_KEY=gsk_...
ANTHROPIC_API_KEY=sk-ant-...
```

`.env` is listed in `.gitignore`, and keys are never written to `settings.json`.

**Running without any API key is fully supported.** Local transcription requires
none, and text cleanup is skipped automatically.

---

## Models

Everything Casper Flow uses is publicly downloadable and permissively licensed. There
are no proprietary assets in this repository and nothing to sign up for in order to
use the default configuration.

### Local speech recognition

Casper Flow uses [faster-whisper](https://github.com/SYSTRAN/faster-whisper), a
CTranslate2 implementation of OpenAI's Whisper. The weights are fetched on demand
from the [Systran](https://huggingface.co/Systran) organisation on HuggingFace —
for example `Systran/faster-whisper-base.en`. Whisper itself is released by OpenAI
under the MIT license.

| Model | Download | Latency | Suggested use |
|---|---|---|---|
| `tiny` | 75 MB | 0.5 s | live captions (used automatically), low-power machines |
| `base` | 145 MB | 0.86 s | **default**, general dictation, Hinglish |
| `small` | 465 MB | 2.6 s | longer passages, unusual vocabulary |
| `medium` | 1.5 GB | impractical on CPU | GPU only |
| `large-v3` | 2.9 GB | impractical on CPU | GPU only |

Add the `.en` suffix (`base.en`) only if you dictate English exclusively — those
variants are marginally faster but **cannot transcribe any other language**.

Latencies are from the [Performance](#performance) measurements above.

If the configured model cannot be loaded — most commonly no network on first run, or
an interrupted download — Casper Flow falls back to any complete model already in the
cache and records the substitution in the log, rather than failing every dictation.
An interrupted download leaves an empty directory behind, so completeness is checked
by looking for the required files rather than trusting that the directory exists.

### Hosted models (optional)

| Purpose | Default model | Provider |
|---|---|---|
| Transcription | `whisper-large-v3-turbo` | Groq |
| Transcription | `gpt-4o-mini-transcribe` | OpenAI |
| Text cleanup | `gpt-4o-mini` | OpenAI |
| Text cleanup | `claude-haiku-4-5` | Anthropic |
| Text cleanup | `openai/gpt-oss-20b` | Groq |
| Text cleanup | `llama3` | Ollama, on your own machine |

Hosted model identifiers are retired periodically. If a cloud backend starts
returning a "model decommissioned" error, update `llm_model` in `settings.json` and
consult the provider's deprecation notice — Groq publishes
[one here](https://console.groq.com/docs/deprecations). A stale identifier costs you
the cleanup pass, not your dictation, because failures fall back to the raw text.

---

## Hinglish and Indian languages

Casper Flow is set up for code-mixed Hindi-English out of the box. Three settings do
the work, and the reasoning behind each is worth knowing before you change them.

### Use a multilingual model

`whisper_model` defaults to `base`, not `base.en`. The `.en` variants **cannot
transcribe Hindi at all**, and multilingual costs almost nothing: 0.86 s versus
0.84 s. `doctor.py` warns if you select an English-only model.

### `language` depends on which model you use

The language code selects the decoder's token prior. On a general-purpose Whisper
model, pinning it breaks mixed-language speech in both directions:

| Setting | Spoken | Transcribed |
|---|---|---|
| `"en"` | "kal ek meeting hai" | "the luck meeting" |
| `"hi"` | "are you listening to me" | "Arri Uresan enthume hai kya" |

Pinning `"hi"` on a general model is worse than it looks. On a 30-recording corpus it
produced output in **Tamil script** for a Hindi phrase, and took 8.8 seconds to do it.

So with the default `base` model, `null` is correct: it detects the language per
recording, which is the only workable choice when one configuration has to handle both.

**But auto-detection is not free, and on measured data it was the single largest
latency cost in the pipeline.** `null` makes faster-whisper run a detection pass before
decoding. Measured over 30 real recordings:

| Model | `language` | Word error rate | Median latency |
|---|---|---|---|
| `base` | `null` | 13.3% on English | 5.55 s |
| `base` | `"en"` | **13.3% on English** | **1.30 s** |

Identical accuracy on English, **4.3 times faster**. The same holds for the Hinglish
model: accuracy-identical in all seven measured categories, 46% faster.

The rule is therefore: **`null` if one configuration must handle both languages, and
`"en"` if you have picked a model for the language you actually dictate.** Verify it on
your own voice rather than taking these numbers on trust:

```powershell
.\venv\Scripts\python.exe bench_hinglish.py --models base --languages auto,en --prompts no
```

### Keep `initial_prompt` a word list, not sentences

The prompt biases spelling and script, which helps Hinglish. But Whisper treats it
as text it was already transcribing, and **will continue it** when the audio is
unclear — pasting words you never said.

This is not theoretical. With a sentence-shaped prompt, unrelated English speech
was transcribed as `"Aaj ka update ready hai kya?"` — a sentence lifted verbatim
from the prompt.

So the default is a comma-separated word list, which gives similar vocabulary bias
with far less to copy. Add your own jargon, product names and colleagues' names to
it. Avoid full sentences.

As a second line of defence, Casper Flow compares each transcript against the prompt and
rejects it if it looks like an echo, re-transcribing once without the prompt. If
that also comes back matching, nothing is pasted — for dictation, pasting nothing
is much better than pasting confident nonsense. `doctor.py` warns if your prompt
looks sentence-shaped.

### Find the best settings for your own voice

Accent matters more than any other factor, and no default can account for yours:

```powershell
.\venv\Scripts\python.exe tune_hinglish.py
```

It records you reading one short phrase, runs every sensible combination of model,
language and prompt against it, scores each by word error rate, and offers to save
the winner. Everything runs locally; nothing is uploaded.

Use `--wav yourfile.wav --said "what you actually said"` to score an existing
recording instead.

### Measuring properly, with a corpus

One phrase is enough to notice a problem and not enough to make a decision. For
that there is a 30-phrase reference corpus in `corpus/phrases.json`, covering
mid-sentence code switching, pure English, pure Hindi, numbers and dates, proper
nouns, filler words and long sentences.

```powershell
.\venv\Scripts\python.exe record_corpus.py      # guided, resumable
.\venv\Scripts\python.exe bench_hinglish.py     # scores and writes corpus/RESULTS.md
```

`record_corpus.py` walks through the phrases one at a time, shows the input peak so
you can tell a bad take immediately, and lets you redo, skip or stop. Stopping and
re-running carries on where you left off.

`bench_hinglish.py` scores every configuration over every recording and reports word
error rate **per category as well as overall**. The split is the point: a Hindi
fine-tune can improve the aggregate while quietly ruining English, and an average
would hide precisely the regression that matters when changing the default model.

Two things worth knowing before you read your own numbers:

- **Read the phrases the way you actually dictate.** Careful enunciation in a silent
  room produces a corpus that flatters the model and then tells you nothing about
  real use.
- **Your recordings stay on your machine.** `corpus/audio/` is git-ignored, because
  it is your voice and this repository is public. The phrase list and the results
  table are committed; the audio is not.

### Grammar and layout

Two optional features, both **off by default**, and neither does anything unless
`llm_backend` is set to a model that can write — in practice `ollama`. With the shipped
defaults the pipeline is byte-for-byte what it was before these existed.

| Setting | What it does |
|---|---|
| `grammar_fix` | Fixes tense, agreement, articles, plurals, prepositions and word order. It is a correction pass, not a rewrite: correct sentences come back unchanged. |
| `format_mode: "message"` | Short text, with `- ` bullets **only if you actually listed several things**. No greeting, no sign-off. |
| `format_mode: "email"` | Paragraphs at your topic changes, numbered steps where you enumerated them. A greeting only if you greeted someone, a sign-off only if you said one. |

**Why these are opt-in.** Everything else in the cleanup step is a deterministic text
transform that cannot produce a word you did not say. These two are generative, and the
risks are not equal:

| | If it goes wrong |
|---|---|
| Filler removal, punctuation | A slightly wrong comma |
| Grammar correction | A changed meaning you did not notice |
| Restructuring into bullets | Content reordered, merged or dropped |

So the layout is **chosen, never inferred**. Some tools guess from whichever window has
focus; guessing wrong and silently reformatting your text is worse than being asked once.

**What happens when the model misbehaves.** The output is checked before it reaches your
document, and any of these rejects it in favour of the plain deterministic cleanup:

- Much longer than the transcript — the model started chatting, or answered your dictation
  instead of tidying it.
- Much shorter — it summarised. This is the failure that matters most and is the easiest to
  miss when proofreading.
- A digit that was dictated is missing. Amounts, dates, quantities and phone numbers are
  compared as a multiset, so the model may regroup them but cannot lose one.
- A timeout. A language-model pass on a slow machine is seconds, not milliseconds; waiting
  is worse than plain text.

In every one of those cases you still get punctuation and casing. The rewrite is discarded,
not your dictation.

### Script of the output

`output_script` controls the final text when the cleanup step runs:

| Value | Result |
|---|---|
| `latin` | `kal ek meeting hai` — default, how Hinglish is normally typed |
| `devanagari` | `कल एक मीटिंग है` |
| `as-is` | whatever the speech model produced |

Conversion is done by the LLM cleanup step, so it needs either an API key or a
local Ollama model. Rule-based transliteration was evaluated and rejected: it
produces `kala eka mITiMga hai`, which is worse than leaving the text alone.

The cleanup prompt is also explicitly told never to translate between Hindi and
English, and to repair mis-heard Hindi words such as `bej dina` → `bhej dena`.
Without that instruction, models "helpfully" translate Hindi into English and
destroy your wording.

### If accuracy is still not good enough

Local models have limits on Indian-accented speech. In order of effectiveness:

1. `tune_hinglish.py` — pick the best local configuration for your voice.
2. `whisper_model: "small"` — noticeably better on Hindi, at 2.6 s instead of
   0.86 s.
3. `transcribe_backend: "groq"` with `whisper-large-v3-turbo` — substantially
   better than anything runnable locally on a CPU, and still sub-second. The same
   model takes 13.4 s locally. Requires an API key and sends audio to Groq.

---

## Choosing a hotkey

The simplest approach is to let Casper Flow tell you what your keyboard actually sends:

```powershell
.\venv\Scripts\python.exe pick_hotkey.py
```

Hold the key or combination you want. The tool reports exactly what it received,
warns if that key is missing from many keyboards, and offers to save it. If nothing
is reported, Windows cannot see that key and it cannot be used.

Alternatively, edit `settings.json` directly:

```json
"hotkey": "caps lock"      // single key (recommended)
"hotkey": "right ctrl"     // single key
"hotkey": "ctrl+space"     // two keys
```

For a combination, the final element is the trigger and the others are modifiers
that must already be held. Releasing either the trigger or any required modifier
ends the recording.

### Key availability

Keyboards vary more than is commonly assumed, so the default deliberately uses a key
that exists everywhere:

| Keys | Availability |
|---|---|
| `caps lock`, `ctrl`, `shift`, `alt`, `space`, `tab`, `esc`, `f1`–`f12` | Every Windows keyboard |
| `right ctrl`, `right alt`, `right shift` | Most, but absent from some compact layouts. `right alt` is AltGr on international layouts and types characters. |
| `scroll lock`, `pause`, `num lock`, `insert` | Missing from most laptops |
| `f13`–`f24` | Only with a remapper or a specialist keyboard |
| `Fn` | Never available to software |

Caps Lock is a good push-to-talk key: one key, comfortable to hold with the left
little finger, universally present, and nothing else uses it as a hold.

**You do not lose the key.** Suppression is what stops a dictation from also
switching your typing to uppercase, but suppressing a key unconditionally would take
it away from you entirely — the earlier behaviour, where the Caps Lock light flickered
and the toggle simply stopped working for as long as the app was running. So a press
shorter than `min_hold_seconds` is replayed to Windows once it is clear it was a tap
rather than dictation:

| What you do | What happens |
|---|---|
| Hold Caps Lock under `min_hold_seconds` | Caps Lock toggles, as always. No dictation. |
| Hold Caps Lock longer | Dictation. Your typing case is untouched. |

### `min_hold_seconds` is a threshold, not a delay

The default is **2.0 seconds**, which is deliberately long: Caps Lock is a key people
press by accident, and a low threshold turns every stray press into a dictation.

The distinction that matters is *when the microphone opens*. It opens the instant you
press, not when the threshold passes, because people start speaking as soon as they
press a push-to-talk key — delaying capture by two seconds would quietly cut the
beginning off every sentence. What waits is only what you can see: the overlay and the
live caption appear once the hold is long enough to be real, so an ordinary Caps Lock
press does not flash a recording indicator or spend CPU on a preview.

The cost is that a dictation shorter than the threshold is discarded. If you want to
dictate three-word phrases, lower it:

```json
"min_hold_seconds": 0.4
```

Accepted range is `0`–`10` seconds. Above ten, every realistic dictation would be
thrown away, which reads as a broken hotkey rather than as a setting.

### Why a swallowed tap is replayed rather than passed through

Suppression has to happen at key-down, before the hold length is knowable, so the
keystroke is always swallowed first and handed back afterwards if it turns out to have
been a tap.

The `keyboard` package normally hides its own injected events — it sets
`_listener.is_replaying` and its hook returns early — so a replay does not come back
to us. But that flag is global and is cleared as soon as `SendInput` returns, while the
hook callback is delivered on a different thread, so under load a replayed event can
arrive after the flag is already down. That was observed once during testing, and the
consequence was severe: the replay looked like a fresh key-down, the internal held
flag stuck on, and every later dictation was ignored as auto-repeat until the app was
restarted.

The guard is therefore an exact count of the events we injected rather than a time
window, because the two failure modes are not equally bad. Miscounting costs at most
one ignored keypress. Mistaking a replay for a real press breaks dictation until
restart.

Key names follow the `keyboard` library's
[naming](https://github.com/boppreh/keyboard#api). An unrecognised name is caught at
startup, logged, and replaced with the default rather than leaving you with no
working hotkey.

### A note on suppression

`suppress_hotkey: true` suppresses the trigger key **only when the full combination
is held**. With `ctrl+space`, for example, `Ctrl+Space` is consumed by Casper Flow while
a plain space still types normally. This distinction matters: suppressing the
trigger unconditionally would swallow the space bar system-wide.

---

## The status overlay

The overlay indicates when the microphone is live and when transcription is running,
so there is never an ambiguous pause.

It appears only once a hold has passed `min_hold_seconds`, so an ordinary Caps Lock
press does not flash a recording indicator at you.

**`blob`** (default) is an organic shape that morphs continuously, with a soft halo,
waveform bars inside it and a quieter waveform trailing off to each side. It is red while
recording and amber while transcribing. The bars are driven by the **actual microphone
level**, which makes the overlay a live input meter: if the bars stay flat, the microphone
is not picking you up, and you know that before you finish speaking.

It shows no text, deliberately. That also means it needs no transcription to draw itself,
so `live_preview` is off by default and no second model is loaded or bundled — worth
74.6 MB off the download and a repeated transcription pass off the CPU.

**`caption`** shows the words as they are recognised, streaming a rough transcript while
you are still speaking. Choose it with `"pill_style": "caption"` and set
`"live_preview": true`; the preview model is downloaded on first use.

**`capsule`** is a compact dark bar with a pulsing indicator, a label, a level meter
and an elapsed timer. Choose it with `"pill_style": "capsule"`.

Both are click-through and never accept focus, so the overlay cannot take the caret
from the window you are dictating into.

Frames are rendered with Pillow and presented through a Win32 layered window using
`UpdateLayeredWindow`, which is what permits genuine per-pixel alpha — the halo,
the antialiased edges and the gradients. A tkinter canvas can only produce
hard-edged shapes keyed to a single transparent colour.

Rendering costs about 7 ms per frame at 24 fps for the default size, and stops
completely when the overlay is hidden. Measured contribution to transcription
latency on a 4-thread CPU: **3%**. If the layered window cannot be created, Casper Flow
falls back to a plain tkinter capsule and logs the reason — a flat rectangle with
centred text means you are seeing the fallback.

---

## Clipboard handling

Inserting text requires the clipboard, and Windows' `EmptyClipboard` clears every
format at once. Casper Flow therefore snapshots the existing contents and restores them
afterwards, including non-text data: plain text, bitmaps (`CF_DIB`, `CF_DIBV5`),
HTML, RTF and PNG all survive a dictation.

Two limitations are worth stating plainly:

- **Copied files** (`CF_HDROP`, as produced by Ctrl+C in Explorer) cannot be
  restored, because doing so requires reconstructing a `DROPFILES` structure. Casper Flow
  logs a line when it encounters this.
- If the snapshot fails entirely, Casper Flow leaves the dictated text on the clipboard
  rather than calling `EmptyClipboard` and destroying data it was unable to read.

The clipboard is opened with retries, since other applications hold it briefly and
`OpenClipboard` fails outright while they do. If it cannot be used at all, Casper Flow
types the text directly instead. Held modifier keys are released before `Ctrl+V` is
sent, so a modifier-based hotkey cannot turn the paste into `Ctrl+Shift+V`.

---

## Windows permissions and antivirus

Windows has no equivalent of macOS's Accessibility or Input Monitoring prompts, so
there is nothing to grant for the keyboard hook or the clipboard. Three things do
cause problems in practice.

### Microphone access

Symptom: no audio is captured, and the log reports `Audio is effectively silent`.

```
Settings → Privacy & security → Microphone
  Microphone access:                        On
  Let desktop apps access your microphone:  On
```

Also confirm no other application has taken exclusive control of the device.
`doctor.py` opens a real input stream, so it detects this before you wonder why your
dictation is empty.

### Antivirus

Symptom: Defender flags the `keyboard` package or blocks `pythonw.exe`.

Cause: global hotkeys require a low-level keyboard hook (`SetWindowsHookEx`), the
same mechanism keyloggers use. This is unavoidable for any push-to-talk tool. Casper Flow
does not log, store or transmit keystrokes; `hotkey.py` and `paste.py` are short
enough to audit.

Resolve it under **Windows Security → Virus & threat protection → Protection
history → Allow on device**, or add the folder under **Exclusions**.

### Elevated windows

Symptom: the hotkey does nothing while an elevated application has focus, such as
Task Manager or an administrator terminal, and text will not paste there.

Cause: Windows prevents a lower-integrity process from hooking or sending input to a
higher-integrity window. This is intentional security behaviour.

To dictate into elevated windows, run Casper Flow elevated: right-click
`start_casper.bat` → **Run as administrator**, or use the Task Scheduler method
below with highest privileges.

---

## Starting automatically

**Tray menu → Launch at Login** writes an entry to
`HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Run` pointing at `pythonw.exe`
rather than `python.exe`, so no console window appears at sign-in. No administrator
rights are needed.

| Key | Default | Meaning |
|---|---|---|
| `launch_at_login` | `false` | Mirrors the tray checkbox. The registry entry is the source of truth; this records the intended state. |
| `setup_complete` | `false` | Set to `true` once first-run setup has finished. While it is `false`, the setup window opens on startup. Delete it, or set it back to `false`, to run setup again. |

To start Casper Flow elevated at login, use Task Scheduler instead:

1. Create Task → Trigger: **At log on**
2. Action → Start a program
   - Program: `<install path>\venv\Scripts\pythonw.exe`
   - Arguments: `"<install path>\main.py"`
   - Start in: `<install path>\`
3. Enable **Run with highest privileges**
4. Under Conditions, clear *Start the task only if the computer is on AC power*

---

## Troubleshooting

Start with the log — tray → **View log**, or `casper.log` — then run `doctor.py`.

**The hotkey does nothing.**
Check whether `casper.log` contains a `Hotkey down` line. If it does not, the key
never reached Casper Flow: run `pick_hotkey.py` and press it. If nothing is reported,
Windows cannot see that key — `Fn` behaves this way on every laptop. If the line is
present but nothing else happens, the problem is further down the pipeline. Also
confirm **Casper Flow Enabled** is ticked, and see [elevated windows](#elevated-windows).

**It worked once and then stopped responding.**
Look for a `Hotkey down` with no matching `Hotkey up`. That indicates a lost release
event; see [How it works](#how-it-works). This is fixed, and Casper Flow now recovers by
itself, but the pattern is the signature to look for if it recurs.

**The pasted text is empty.**
The log prints the peak amplitude for every recording. A very low value means a
microphone permission problem or the wrong `input_device`.

**Transcription is too slow.**
See [Performance](#performance). In short: use `base.en` or `tiny.en`, try
`cpu_threads` at your logical core count, or switch to the Groq backend. Speaking for
less time will not help — latency is a fixed cost per dictation, not per second.

**Filler words are not being removed.**
The cleanup pass is being skipped. The tray shows
`Polish: ... (no API key - skipped)` when no key is configured. Add one to `.env`, or
set `llm_backend` to `ollama` to keep everything local.

**Text arrives in the wrong window.**
Whatever has focus when the pipeline finishes receives the paste. Avoid clicking
away while the amber overlay is visible.

**Clipboard contents were not restored.**
Increase `clipboard_restore_seconds` if the target application is slow to consume
the paste. Copied files cannot be restored; see
[Clipboard handling](#clipboard-handling).

**The overlay is missing, or is a plain flat bar.**
A flat rectangle with centred text is the fallback renderer. Search the log for
`Layered window unavailable` or `UpdateLayeredWindow failed`. The message
`Overlay ready: ... (layered window, per-pixel alpha)` confirms the proper renderer
is active. A minimal Python installation may lack tcl/tk, in which case Casper Flow runs
without an overlay.

**The model will not download.**
Interrupted HuggingFace downloads are common on unreliable connections. Re-run
`doctor.py`; downloads resume. Casper Flow falls back to any complete cached model in the
meantime.

---

## How it works

Four threads, by necessity rather than choice:

| Thread | Responsibility |
|---|---|
| main | pystray icon loop — pystray requires the main thread |
| `pill-ui` | tkinter loop for the overlay |
| `hotkey` | low-level keyboard hook |
| `pipeline-N` | one short-lived worker per dictation |

### Why the hotkey handlers must return immediately

Windows delivers events to a low-level keyboard hook **one at a time**. If a
callback is still running when the next event arrives, that event is discarded.

An earlier version called `recorder.start()` directly from the hook callback.
Opening the audio device from cold takes around two seconds, so the key-release that
ended the hold was dropped. The internal "held" flag then stayed set permanently:
subsequent presses were treated as auto-repeat and ignored, and the microphone kept
recording until the duration cap. A single press disabled the application until
restart.

This is reproducible: a callback that returns immediately yields `['down', 'up']`,
while one that blocks for two seconds yields only `['down']`.

Hook callbacks therefore now only update state and place an item on a queue. A
single worker thread runs the real handlers in order, off the hook. Two supporting
measures:

- **Warm start.** The microphone stream is created and the speech model is loaded
  during startup, so nothing slow runs on the hot path. The hotkey is deliberately
  armed *after* the stream exists: arming it first meant an early press started a
  recording whose microphone opened only after the key had been released.
- **Stuck-key recovery.** If a release is lost anyway, Casper Flow recovers. For a
  combination it watches the modifiers with `GetAsyncKeyState`, which detects the
  condition within about 180 ms. For a single suppressed key that API cannot be used
  — our own hook consumes the key press before it reaches the operating system's
  keyboard state, so it always reports the key as up. In that case Casper Flow falls back
  to the `max_hold_seconds` ceiling, which cannot cut a genuine dictation short.

If you add work to `on_press` or `on_release`, put it on a thread.

---

## Privacy

- **No telemetry.** Nothing is transmitted except to the API endpoints you
  explicitly configure.
- `transcribe_backend: "local"` with either `llm_polish: false` or
  `llm_backend: "ollama"` sends nothing off the machine at all.
- Recorded audio is written to a temporary file and deleted immediately after
  transcription.
- The keyboard hook observes all key events in order to detect the hotkey. Casper Flow
  does not record, store or transmit them.

---

## Project layout

```
casper-flow/
├── main.py                 entry point, pipeline orchestration, threading
├── config.py               settings.json and .env loading, validation
├── hotkey.py               global push-to-talk hotkey
├── recorder.py             microphone capture, level metering, WAV output
├── transcribe.py           Whisper: local, Groq, OpenAI
├── llm_polish.py           text cleanup: OpenAI, Anthropic, Groq, Ollama
├── paste.py                clipboard snapshot, Ctrl+V, restore
├── pill.py                 overlay window and animation loop
├── pill_render.py          overlay artwork
├── tray.py                 tray icon, menu, launch at login
├── doctor.py               installation self-check
├── pick_hotkey.py          interactive hotkey picker
├── settings.json           user configuration
├── .env.example            API key template
├── requirements.txt        dependencies
├── settings_ui.py          settings window
├── wizard.py               first-run setup
├── paths.py                where files live, source vs frozen
├── corrections.py          vocabulary and exact-match fixes
│
├── record_corpus.py        record the reference corpus
├── bench_hinglish.py       score configurations against it
├── bench_latency.py        time a model on short clips
├── wer.py                  word error rate, strict and fair
├── tune_hinglish.py        sweep model and prompt combinations
├── corpus/phrases.json     30 reference phrases, by category
│
├── casper.spec             PyInstaller build definition
├── installer.iss           Inno Setup script, per-user, no admin
├── build_installer.ps1     freeze, compile the installer, zip, checksum
├── make_icon.py            assets/casper.ico + the website favicon
├── make_og_image.py        the website's social share card
├── make_overlay_previews.py  overlay PNGs for the website, via pill_render
│
├── requirements.lock.txt   exact tested versions
├── requirements-dev.txt    tests and packaging
├── pytest.ini              test configuration
├── tests/                  pytest suite
├── install.ps1             developer setup
└── start_casper.bat        launcher
```

The three `make_*` scripts generate committed assets from code rather than storing
hand-made binaries, so the icon, the share card and the overlay previews cannot
drift away from what the application actually looks like. `make_overlay_previews.py`
imports `pill_render` and calls the same function the running app calls, which is
what stopped the website showing an overlay that did not exist.

---

## Contributing

Issues and pull requests are welcome.

- Run `doctor.py` before and after your change.
- Keep hook callbacks in `hotkey.py` non-blocking; see
  [How it works](#how-it-works).
- Latency claims should come with a measurement. Short-clip wall time is the metric
  that matters, not real-time factor.
- The overlay renderer in `pill_render.py` is pure: it takes a `FrameState` and
  returns an image, so it can be exercised without opening a window.

---

## License

MIT — see [LICENSE](LICENSE).

Casper Flow builds on [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
(MIT), OpenAI's [Whisper](https://github.com/openai/whisper) models (MIT),
[keyboard](https://github.com/boppreh/keyboard) (MIT),
[pystray](https://github.com/moses-palmer/pystray) (LGPL-3.0),
[sounddevice](https://github.com/spatialaudio/python-sounddevice) (MIT),
[Pillow](https://github.com/python-pillow/Pillow) (MIT-CMU) and
[pywin32](https://github.com/mhammond/pywin32) (PSF-2.0).
