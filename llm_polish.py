"""
Cleanup and formatting step.

Takes the raw Whisper transcript and produces the text that gets pasted. Three
things can happen here, in increasing order of how much they are allowed to
change:

  cleanup      always. Fillers, spoken punctuation, spacing, sentence casing.
  grammar_fix  optional. Tense, agreement, articles, word order.
  format_mode  optional. Lay the text out as a message or an email body.

Backends: rules | ollama | openai | anthropic | groq. `rules` is the default and
is a deterministic text transform - it cannot write words that were not spoken,
which is why it is the default. The other two features are generative by
definition, so they do nothing unless a language model backend is configured.

**Design rule: this step must never lose your dictation.** Every failure path -
missing key, timeout, unreachable model, chatty model, a model that summarised
instead of cleaning, a model that dropped a phone number - falls back to the
deterministic cleanup of the same transcript. The user gets tidy plain text
rather than an error or a silently mangled sentence.
"""

import logging
import re
import threading
from functools import partial

from config import DEFAULTS, api_key_for

log = logging.getLogger("casper.llm_polish")

BASE_PROMPT = (
    "You are a dictation editor. The user sends you a raw speech-to-text "
    "transcript. Clean it up:\n"
    "1. Remove filler words and false starts: um, uh, er, like, you know, "
    "sort of, kind of, I mean, basically, matlab, yaar, and repeated words.\n"
    "2. Add correct punctuation: commas, full stops, question marks, "
    "apostrophes.\n"
    "3. Use sentence casing - capitalise the first word of each sentence, "
    "proper nouns, and the pronoun I. Do not upper-case anything else, and do "
    "not add headings, bullets, or markdown.\n"
    "4. Spoken commands for punctuation ('period', 'comma', 'new line', "
    "'question mark') become the actual punctuation.\n"
    "5. Never change the meaning, add content, answer questions, or summarise. "
    "The user is dictating text, not talking to you. If the transcript is a "
    "question, return the question - do not answer it.\n"
)

# Code-mixed speech needs explicit handling, otherwise models "helpfully"
# translate Hindi into English, which destroys the user's intended wording.
HINGLISH_RULES = (
    "6. The speaker mixes Hindi and English (Hinglish). This is intentional. "
    "NEVER translate between the two languages: keep every Hindi word Hindi "
    "and every English word English, in the order spoken.\n"
    "7. Speech recognition mangles Hindi words. Correct obvious mis-hearings "
    "to the intended Hindi word, using the surrounding context. For example "
    "'bej dina' -> 'bhej dena', 'K soth' -> 'ke saath', 'meeting high' -> "
    "'meeting hai', 'nikol rahoon' -> 'nikal raha hoon', 'sham tak' -> "
    "'shaam tak'. Use natural, conventional spellings.\n"
)

SCRIPT_RULES = {
    "latin": (
        "8. Write Hindi words in Roman script, the way Indians type them in "
        "chat. Do not use Devanagari. If the transcript contains Devanagari, "
        "transliterate it to Roman script.\n"
    ),
    "devanagari": (
        "8. Write Hindi words in Devanagari and keep English words in Latin "
        "script. If Hindi appears in Roman script, convert it to Devanagari.\n"
    ),
    "as-is": (
        "8. Keep each word in whichever script it already appears; do not "
        "transliterate.\n"
    ),
}

TAIL = "Return ONLY the cleaned text: no preamble, no quotes, no code fences."

# ------------------------------------------------------- grammar and layout

# Rule 5 of BASE_PROMPT forbids changing meaning, and grammar repair has to be
# allowed to change words. So this narrows the exception rather than widening
# rule 5: fix the error, keep the sentence.
GRAMMAR_RULE = (
    "9. Fix grammatical errors: verb tense and agreement, articles, plurals, "
    "prepositions and word order. Keep the speaker's own words and register "
    "wherever they are already correct - this is a correction pass, not a "
    "rewrite. Never negate or un-negate a statement, never change a number, a "
    "name, a date or an amount, and never make a hedged statement definite or "
    "the reverse. If a sentence is already correct, return it unchanged.\n"
)

FORMAT_RULES = {
    "plain": (
        "9. Return continuous prose. Do not add bullets, numbering, headings or "
        "markdown of any kind.\n"
    ),
    # "only when the speech actually enumerated something" is the acceptance
    # criterion for this feature, so it is stated three ways: when to use them,
    # when not to, and an explicit example of the failure.
    # Rules 10 and 11 are deliberately split into "when you must" and "when you
    # must not". An earlier single rule hedged both ways and ended with "if in
    # doubt, use prose", and a small model took the cautious branch every time:
    # measured 0 bullets out of 4 genuinely enumerated dictations, and 0 false
    # bullets. Perfect specificity, useless sensitivity. The positive case now
    # gives a concrete trigger to match on instead of a judgement to make.
    "message": (
        "9. Format as a short message.\n"
        "10. If the speaker listed three or more separate items, or counted them "
        "off with words like 'first', 'second', 'third', 'then' or 'also', "
        "rewrite that list as bullets: one item per line, each line starting "
        "with '- '. Keep the speaker's own words for each item.\n"
        "11. If the speaker made a single statement, return prose. A single "
        "statement is never a bullet list, however long it is, and neither is a "
        "question. Only an actual list of items becomes bullets.\n"
        "12. Do not add a greeting, a sign-off, headings or a subject line.\n"
    ),
    "email": (
        "9. Format as an email body.\n"
        "10. Open with a greeting only if the speaker addressed someone by "
        "name or said hello. Close with a sign-off only if the speaker said "
        "one. Do not invent a name for either.\n"
        "11. Break into short paragraphs at the speaker's natural topic "
        "changes. Use numbered steps ONLY where the speaker enumerated them "
        "('first', 'second', 'then'), and '- ' bullets only for a genuine list "
        "of items. A single statement is never a list.\n"
        "12. Do not add a subject line, and do not invent commitments, dates, "
        "prices or next steps that were not spoken.\n"
    ),
}


def format_mode(cfg: dict) -> str:
    mode = str(cfg.get("format_mode", "plain")).strip().lower()
    return mode if mode in FORMAT_RULES else "plain"


def is_generative(cfg: dict) -> bool:
    """True if the configuration asks for text the speaker did not say."""
    return format_mode(cfg) != "plain" or bool(cfg.get("grammar_fix", False))


def build_prompt(cfg: dict) -> str:
    script = str(cfg.get("output_script", "latin")).lower()
    rules = SCRIPT_RULES.get(script, SCRIPT_RULES["latin"])
    prompt = BASE_PROMPT + HINGLISH_RULES + rules

    # Grammar and layout rules are numbered from 9 because the blocks above end
    # at 8. Only one of the two occupies 9, so grammar shifts the layout rules
    # when both are on.
    mode = format_mode(cfg)
    if cfg.get("grammar_fix", False):
        prompt += GRAMMAR_RULE
        if mode != "plain":
            shifted = FORMAT_RULES[mode]
            for old, new in (("\n13.", "\n14."), ("\n12.", "\n13."),
                             ("\n11.", "\n12."), ("\n10.", "\n11."),
                             ("9.", "10.")):
                shifted = shifted.replace(old, new, 1)
            prompt += shifted
    else:
        prompt += FORMAT_RULES[mode]

    return prompt + TAIL


_MAX_TOKENS = 2048

# Per-backend default model. Each backend used to carry its own default inline -
# `cfg.get("llm_model", "claude-haiku-4-5")` - which could never fire, because
# config.DEFAULTS always supplies `llm_model`. So switching `llm_backend` to
# anthropic or groq without also editing `llm_model` sent OpenAI's model id to the
# wrong vendor, got a 404, and fell back to the rules cleanup - while the tray
# went on showing the backend as active.
_DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    # Unversioned alias so it keeps working across dated releases.
    "anthropic": "claude-haiku-4-5",
    # llama3-8b-8192 and llama-3.1-8b-instant are both retired.
    # See https://console.groq.com/docs/deprecations
    "groq": "openai/gpt-oss-20b",
}


def _model_for(backend: str, cfg: dict) -> str:
    """
    The model id to send to this backend.

    When `llm_model` still holds the shipped default, it describes OpenAI and
    nothing else, so every other backend gets its own default instead. A value the
    user actually chose is always passed through untouched.
    """
    configured = str(cfg.get("llm_model") or "").strip()
    fallback = _DEFAULT_MODELS.get(backend, configured)
    if not configured:
        return fallback
    if backend != "openai" and configured == DEFAULTS.get("llm_model"):
        log.info(
            f"llm_model is still the shipped default {configured!r}, which is an "
            f"OpenAI id; using {fallback!r} for the {backend} backend"
        )
        return fallback
    return configured


CLOUD_BACKENDS = ("openai", "anthropic", "groq")


def _is_loopback(url: str) -> bool:
    """
    True if this URL addresses this machine and nothing else.

    Deliberately an allow-list of literal loopback hosts rather than a check for
    things that look remote. A denylist here fails open, and failing open means
    quietly shipping the user's dictation to another host.
    """
    from urllib.parse import urlsplit

    try:
        host = (urlsplit(str(url).strip()).hostname or "").lower()
    except ValueError:
        return False
    if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return True
    # 127.0.0.0/8 is all loopback.
    return host.startswith("127.")

# How long past the configured timeout we wait before giving up on the backend
# ourselves. Small, because the point is to let the backend's own timeout produce
# a proper error first; this only catches the case where it doesn't.
_DEADLINE_GRACE = 1.5


def _call_with_deadline(fn, raw_text: str, cfg: dict) -> str:
    """
    Run a backend with a real wall-clock ceiling.

    `llm_timeout_seconds` documents itself as a hard ceiling - "if it takes
    longer we paste raw text rather than leaving you staring at a dead cursor" -
    and none of the backends could honour that on their own. The HTTP clients
    apply it per attempt, and `requests` applies it per socket operation, so a
    stalled connection could hold the paste for multiples of the setting. The
    cursor being dead is the whole thing the setting exists to prevent, so the
    ceiling is enforced here where it can actually be guaranteed.

    The worker is a daemon thread and is abandoned rather than cancelled: there is
    no safe way to interrupt a blocking socket read, and its own timeout will end
    it shortly. Abandoning it costs one idle thread; waiting for it costs the user
    their paste.
    """
    timeout = float(cfg.get("llm_timeout_seconds", 20))
    box: dict = {}

    def run():
        try:
            box["out"] = fn(raw_text, cfg)
        except BaseException as e:            # noqa: BLE001 - re-raised below
            box["err"] = e

    worker = threading.Thread(target=run, daemon=True,
                              name="casper-polish")
    worker.start()
    worker.join(timeout + _DEADLINE_GRACE)

    if worker.is_alive():
        raise TimeoutError(
            f"Cleanup backend did not answer within {timeout:g}s"
        )
    if "err" in box:
        raise box["err"]
    return box.get("out") or ""


def polish(raw_text: str, cfg: dict) -> str:
    if not raw_text or not raw_text.strip():
        return raw_text

    backend = str(cfg.get("llm_backend", "rules")).lower()

    # Grammar repair and restructuring need a model that can write. The rules
    # backend cannot, so the request is dropped rather than half-honoured, and
    # the user gets clean plain text instead of nothing.
    if backend == "rules" and is_generative(cfg):
        log.warning(
            f"format_mode={format_mode(cfg)!r} grammar_fix="
            f"{bool(cfg.get('grammar_fix'))} require a language model; the "
            f"'rules' backend cannot generate text. Pasting plain cleanup."
        )

    # Privacy gate. Enforced here rather than trusted to the caller, so no
    # combination of settings can send a transcript off the machine.
    if cfg.get("offline_only", True) and backend in CLOUD_BACKENDS:
        log.warning(
            f"llm_backend={backend!r} would send text off this machine and "
            f"offline_only is on. Using the built-in rules cleanup instead. "
            f"Install Ollama for smarter local cleanup."
        )
        backend = "rules"

    # The same gate for Ollama, which is only private because it is local. The
    # backend name was on the allow-list while `ollama_url` was never checked, so
    # pointing it at another machine sent every transcript there with
    # offline_only still reading as on - the one thing this setting promises
    # cannot happen.
    # An absent ollama_url means the documented default, which is loopback.
    ollama_url = cfg.get("ollama_url") or DEFAULTS["ollama_url"]
    if backend == "ollama" and cfg.get("offline_only", True) \
            and not _is_loopback(ollama_url):
        log.warning(
            f"ollama_url={cfg.get('ollama_url')!r} is not on this machine and "
            f"offline_only is on. Using the built-in rules cleanup instead. Set "
            f"offline_only to false if you meant to use a remote Ollama."
        )
        backend = "rules"

    if backend in CLOUD_BACKENDS and not api_key_for(backend, cfg):
        log.warning(f"No API key for {backend!r}; using the rules cleanup")
        backend = "rules"

    log.info(f"Cleaning up with backend: {backend}")
    try:
        fn = {
            "rules": _rules,
            "openai": _openai,
            "anthropic": _anthropic,
            "groq": _groq,
            "ollama": _ollama,
        }[backend]
    except KeyError:
        log.warning(f"Unknown llm_backend {backend!r}; using the rules cleanup")
        fn = _rules

    # The deterministic result, computed up front because it is also the
    # fallback. A rejected rewrite should still get punctuation and casing - the
    # user asked for tidy text and a model misbehaving is not their problem.
    try:
        plain = _rules(raw_text, cfg)
    except Exception:
        plain = raw_text

    if fn is _rules:
        # DEBUG, not INFO: this is the finished text, i.e. the dictation itself,
        # and casper.log ships at INFO and is never rotated.
        log.debug(f"Polished: {plain!r}")
        return plain

    try:
        out = _call_with_deadline(fn, raw_text, cfg)
    except TimeoutError as e:
        log.warning(f"{e}; pasting plain cleanup")
        return plain
    except Exception as e:
        # Timeouts land here, which is the common case on a slow machine: an
        # LLM pass is seconds, and waiting is worse than plain text.
        log.warning(f"Cleanup backend failed ({e}); pasting plain cleanup")
        return plain

    # The rules backend is deterministic and cannot invent text, so the
    # plausibility guards (aimed at chatty models) only apply to the rest.
    cleaned = _sanitise(out, plain, cfg)
    log.debug(f"Polished: {cleaned!r}")
    return cleaned


# Growth ceilings, as a multiple of the input length, with a floor for very
# short dictations. Restructuring legitimately adds characters - "- " on every
# bullet, blank lines between paragraphs, a greeting - so one threshold for all
# three modes would either reject good email output or wave through a model that
# started chatting.
_GROWTH = {"plain": (3.0, 120), "message": (4.0, 200), "email": (6.0, 500)}

# Shrink floor. This closes a real hole: the old guard only looked for output
# that was too *long*, so a model that summarised five sentences into one passed
# it silently, and summarising a dictation is a worse failure than padding it.
# Filler removal legitimately shortens text, so the floor is generous.
_SHRINK = 0.35


_PREAMBLE = re.compile(
    r"^(?:sure|certainly|okay|ok)?[,:]?\s*"
    r"(?:here(?:\s+is|\s+are|'s)|below\s+is|this\s+is)\b[^\n]*?"
    r"\b(?:text|transcript|version|message|email|note|cleaned|corrected|"
    r"tidied|formatted|rewritten)\b[^\n]*:\s*\n+",
    re.IGNORECASE,
)


def _digit_bag(text: str) -> list[str]:
    return sorted(ch for ch in text if ch.isdigit())


def _content_words(text: str) -> list[str]:
    """
    Words long enough to carry meaning, lowercased.

    Four characters and up, which skips articles, prepositions and most inflected
    short verbs. Those are exactly the words a grammar pass is meant to change, so
    counting them would penalise correct output.
    """
    return [w for w in re.findall(r"[^\W\d_]+", (text or "").lower()) if len(w) >= 4]


def _content_retained(out: str, raw: str) -> float:
    """
    What fraction of the transcript's content words survived.

    This guard exists because a measured failure got past every other one. Asked
    to bullet "first we need the budget second the timeline and third the sign
    off", a 3B model returned "- first / - second / - shaam ko sahi kaam karne ke
    liye dhanyavad" - it dropped every actual item and invented a sentence of
    Hindi the speaker never said. The output was a plausible length, contained no
    digits to lose and was not a summary, so the length and number guards all
    passed it.

    Substitution of invented content for real content is the worst thing this
    step can do, and length alone cannot detect it. Word overlap can.
    """
    want = _content_words(raw)
    if not want:
        return 1.0
    have = _content_words(out)
    pool = list(have)
    kept = 0
    for w in want:
        if w in pool:
            pool.remove(w)
            kept += 1
    return kept / len(want)


# Below this share of the transcript's content words, the output is treated as
# something other than a cleaned-up version of what was said. Set with headroom:
# legitimate grammar correction and Hinglish spelling fixes change words, and
# restructuring drops connective phrasing, so real output measured well above
# this while the hallucination above scored 0.29.
_RETENTION = 0.5

# Fewest content words in the transcript for the retention ratio to mean anything.
# Below this, one word is a third or more of the score. See _sanitise.
_RETENTION_MIN_WORDS = 4


def _novel_share(out: str, raw: str) -> float:
    """
    What fraction of the output is words the speaker never said.

    Retention catches content being *dropped*. This catches content being *added*,
    which is a separate failure with its own measured example: asked to lay out "i
    am running late for the review call" as an email, a 3B model returned "I am
    running late for the review call. I am going to be about 15 minutes behind
    schedule. I apologize for any inconvenience this may cause..." - it invented a
    delay of fifteen minutes and an apology. Every word of the transcript survived,
    so retention was perfect, and the length was inside the email ceiling.

    A dictation tool inventing a specific commitment and pasting it into your
    message is worse than doing nothing at all.
    """
    have = _content_words(out)
    if not have:
        return 0.0
    said = set(_content_words(raw))
    return sum(1 for w in have if w not in said) / len(have)


# A greeting and a sign-off are legitimately new words, and restructuring
# rephrases connectives, so some novelty is expected. Half is not: past this, most
# of what would be pasted is text the speaker did not say.
_NOVELTY = 0.5


def _numbers_survived(out: str, raw: str) -> bool:
    """
    Every digit in the transcript still appears in the output.

    Dictated numbers - amounts, dates, phone numbers, quantities - are the
    content where a silent change does the most damage and is the hardest to
    notice when proofreading. Compared as a multiset so the model may regroup or
    reformat them, and extra digits are allowed because turning "twenty five"
    into "25" is a reasonable thing for it to do.
    """
    have = _digit_bag(out)
    for d in _digit_bag(raw):
        if d in have:
            have.remove(d)
        else:
            return False
    return True


def _sanitise(out: str, raw: str, cfg: dict | None = None) -> str:
    """
    Guard against a model that ignores instructions.

    Strips code fences and wrapping quotes, then rejects output that does not
    look like a cleaned-up version of the input: too long (the model started
    chatting or answered the question), too short (it summarised), or missing
    numbers that were dictated.

    Returns the fallback text on rejection. The caller decides what that is;
    `polish()` passes the deterministic cleanup rather than the raw transcript,
    so a rejected rewrite still gets punctuation and casing.
    """
    if not out or not out.strip():
        return raw
    text = out.strip()

    # ```...``` or ```text ... ```
    fence = re.match(r"^```[a-zA-Z]*\s*\n?(.*?)\n?```$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    # Wrapping quotes the model added around the whole thing
    if len(text) >= 2 and text[0] in "\"'\u201c\u2018" and text[-1] in "\"'\u201d\u2019":
        text = text[1:-1].strip()

    # A leading "Here is the cleaned-up transcript:" line. TAIL forbids preambles
    # and a small model ignores that, and this one is too short to trip any size
    # guard - it just gets pasted into the document. Measured, from llama3.2:3b.
    #
    # Deliberately narrow: it needs a self-referential opener AND a word about the
    # text itself AND a trailing colon. "The steps are:" and "There are three
    # blockers:" are legitimate first lines that also end in a colon, and must
    # survive.
    text = _PREAMBLE.sub("", text, count=1).strip()

    mode = format_mode(cfg or {})
    factor, floor = _GROWTH[mode]

    if len(text) > max(floor, len(raw) * factor):
        log.warning(
            f"Cleaned text implausibly longer than the transcript "
            f"({len(text)} vs {len(raw)} chars, mode={mode}); discarding it"
        )
        return raw

    if len(text) < len(raw) * _SHRINK:
        log.warning(
            f"Cleaned text implausibly shorter than the transcript "
            f"({len(text)} vs {len(raw)} chars); it looks summarised, "
            f"discarding it"
        )
        return raw

    if not _numbers_survived(text, raw):
        log.warning(
            "Numbers in the transcript are missing from the cleaned text; "
            "discarding it rather than pasting altered figures"
        )
        return raw

    # Retention is a ratio, so on a very short dictation one word moves it a long
    # way and legitimate rewrites start failing it. "twenty five people" -> "25
    # people" retains one content word of three, which reads as 33% invented text
    # and was rejected - even though converting spoken numbers to digits is
    # something this module's own comments call a reasonable thing for a model to
    # do, and the number guard deliberately allows.
    #
    # Below the floor the novelty guard carries the same load from the other
    # direction: it asks whether the output contains words that were never
    # dictated, which is what actually distinguishes invention from tidying and
    # does not care how short the input was.
    raw_content = _content_words(raw)
    if len(raw_content) >= _RETENTION_MIN_WORDS:
        kept = _content_retained(text, raw)
        if kept < _RETENTION:
            log.warning(
                f"Only {kept:.0%} of the dictated words survived the rewrite; it "
                f"looks like invented text rather than a tidied version of what "
                f"was said, discarding it"
            )
            return raw

    novel = _novel_share(text, raw)
    if novel > _NOVELTY:
        log.warning(
            f"{novel:.0%} of the rewritten text is words that were not dictated; "
            f"the model has padded or invented content, discarding it"
        )
        return raw

    return text or raw


# ---------------------------------------------------------------- rules

# Spoken punctuation, longest first so "new paragraph" wins over "new line".
#
# The third field says whether the phrase is also an ordinary English noun. Those
# need a context check, because substituting one blindly deletes a word the user
# actually said - the worst thing a dictation tool can do. Measured before the
# guard existed:
#
#   "the grace period ended"          -> "The grace. Ended."
#   "put a comma there please"        -> "Put a, there please."
#
# "period" is absent from this table on purpose. No context rule saves it: the
# words before it are ordinary nouns in "notice period", "grace period", "trial
# period", "period of time" - and "notice period" is everyday office speech in
# the market this is built for. Indian English says "full stop" for the mark
# anyway, and that is still here.
_SPOKEN = [
    # phrase,             mark,   also an ordinary noun
    ("new paragraph",     "\n\n", False),
    ("new line",          "\n",   False),
    ("next line",         "\n",   False),
    ("question mark",     "?",    True),
    ("exclamation mark",  "!",    True),
    ("exclamation point", "!",    True),
    ("full stop",         ".",    True),
    ("comma",             ",",    True),
    ("colon",             ":",    True),
    ("semicolon",         ";",    True),
    ("open bracket",      "(",    True),
    ("close bracket",     ")",    True),
]

# A determiner, possessive or preposition in front means the user is talking
# *about* the mark rather than asking for one: "put a comma", "the question mark
# is missing", "without a full stop".
_TALKING_ABOUT_BEFORE = frozenset("""
    a an the this that these those my your his her its our their
    one no any some each every another per
    of in on at during after before within without with for
""".split())

# Same idea on the other side: "comma separated", "colon key".
_TALKING_ABOUT_AFTER = frozenset("separated delimited seperated key symbol".split())

_WORD_BEFORE = re.compile(r"([^\W\d_]+)\W*$")
_WORD_AFTER = re.compile(r"^\W*([^\W\d_]+)")


def _spoken_replacement(m: "re.Match", mark: str) -> str:
    """The mark, or the original words when this reads as speech about the mark."""
    before = _WORD_BEFORE.search(m.string[:m.start()])
    if before and before.group(1).lower() in _TALKING_ABOUT_BEFORE:
        return m.group(0)
    after = _WORD_AFTER.match(m.string[m.end():])
    if after and after.group(1).lower() in _TALKING_ABOUT_AFTER:
        return m.group(0)
    return mark


# A run of words long enough that saying it twice in a row is a transcription
# artefact rather than speech. Three is too few - "kar do kar do", "haan haan theek
# hai" and "bahut bahut dhanyavad" are things people say. Checked against all 30
# reference transcripts and a list of deliberate repetitions: four alters none of
# them.
_REPEAT_MIN_WORDS = 4


def _collapse_repeated_clause(text: str) -> str:
    """
    Remove a clause the speech model transcribed twice in a row.

    Whisper sometimes emits the same phrase two or three times inside one segment.
    Its own guards do not catch it, and this was measured rather than assumed: on
    the two corpus recordings where it happens, `compression_ratio` was 1.07 and
    1.36 against the 2.4 threshold that triggers the temperature fallback, and
    `avg_logprob` was -0.19 and -0.11. The model is confident about the wrong
    answer, so neither the compression nor the log-probability check fires.

    Only exact, adjacent, whole-word repeats of at least `_REPEAT_MIN_WORDS`, and
    it never removes the last copy. Deliberately conservative: deleting words the
    user did say is worse than leaving a duplicate they can see and fix.

    **What this does not fix, stated so nobody assumes otherwise.** The two corpus
    recordings that duplicate themselves are *paraphrased* restatements, not exact
    repeats:

        said  uh mujhe lagta hai ki hum kal discuss kar sakte hain
        got   Mujhe lagta hai ki kal ham kal discuss kar rahe hain,
              phir ham kal discuss kar sakte hain.

    "kar rahe hain" against "kar sakte hain" is not an exact repeat, so this leaves
    it alone. Catching it would need fuzzy matching, which is precisely the
    technique measured and rejected in corrections.py for rewriting correct words
    into wrong ones. This handles the degenerate exact-loop case, which is a real
    Whisper failure mode, and costs nothing when it does not occur.
    """
    words = text.split()
    if len(words) < _REPEAT_MIN_WORDS * 2:
        return text

    def key(w: str) -> str:
        return w.strip(".,;:!?\"'()").lower()

    keys = [key(w) for w in words]
    i = 0
    out: list[str] = []
    while i < len(keys):
        # Longest run first, so "a b c d a b c d a b c d" collapses in one pass
        # rather than leaving a stray copy behind.
        for width in range((len(keys) - i) // 2, _REPEAT_MIN_WORDS - 1, -1):
            if keys[i:i + width] == keys[i + width:i + 2 * width]:
                log.debug(
                    f"Dropped a repeated clause of {width} words: "
                    f"{' '.join(words[i:i + width])!r}"
                )
                # Skip the first copy; the loop re-examines the second, so a
                # third identical copy collapses too.
                i += width
                break
        else:
            out.append(words[i])
            i += 1
    return " ".join(out)


def _rules(text: str, cfg: dict) -> str:
    """
    Deterministic cleanup: no model, no network, no dependencies.

    Chosen as the default because it cannot invent words. An LLM in this slot
    already caused prompt text to be pasted as though the user had said it,
    which for dictation is worse than leaving the transcript slightly rough.

    Handles the mechanical part of dictation - interjections, spoken
    punctuation, spacing, sentence casing - and deliberately leaves wording
    alone. Use the ollama backend for genuine rewriting.
    """
    out = text.strip()
    if not out:
        return out

    # 1. spoken punctuation commands
    for phrase, mark, ambiguous in _SPOKEN:
        pattern = rf"(?<![\w]){re.escape(phrase)}(?![\w])"
        if ambiguous:
            out = re.sub(pattern, partial(_spoken_replacement, mark=mark), out,
                         flags=re.IGNORECASE)
        else:
            out = re.sub(pattern, mark, out, flags=re.IGNORECASE)

    # 2. interjections, only as whole words
    fillers = cfg.get("filler_words") or []
    if fillers:
        alts = "|".join(re.escape(f) for f in fillers)
        out = re.sub(rf"\b(?:{alts})\b[,.]?\s*", " ", out, flags=re.IGNORECASE)

    # 2b. a clause the speech model transcribed twice
    out = _collapse_repeated_clause(out)

    # 3. immediate duplicated words ("the the report" -> "the report").
    #    Case-insensitive but preserves the first spelling. Skips words that
    #    are legitimately repeated in Hinglish, e.g. "bahut bahut".
    keep_doubles = {"bahut", "bohot", "very", "no", "ha", "haan"}
    out = re.sub(
        r"\b(\w+)(\s+\1\b)+",
        lambda m: m.group(1) if m.group(1).lower() not in keep_doubles else m.group(0),
        out,
        flags=re.IGNORECASE,
    )

    # 4. spacing: no space before punctuation, one after
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)
    out = re.sub(r"([,;:])(?=\S)", r"\1 ", out)
    out = re.sub(r"([.!?])(?=[A-Za-z])", r"\1 ", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r" *\n *", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out)

    # 5. standalone "i" -> "I" (English only; harmless elsewhere)
    out = re.sub(r"\bi\b", "I", out)

    # Removing a leading filler leaves a space, which would stop the casing
    # rule below from seeing the first letter at the start of the string.
    out = out.strip()

    # 6. sentence casing, without touching the rest of a word
    def upper_first(m):
        return m.group(1) + m.group(2).upper()

    out = re.sub(r"(^|[.!?]\s+|\n)([a-z])", upper_first, out)

    # 7. collapse duplicated terminal punctuation, then ensure the text ends
    #    with some
    out = re.sub(r"([.!?]){2,}", r"\1", out).strip()
    # A bullet or numbered item is not a sentence, so don't end one with a full
    # stop: "- two." reads as a typo rather than as punctuation.
    last_line = out.rsplit("\n", 1)[-1].lstrip()
    a_list_item = bool(re.match(r"(?:[-*\u2022]|\d+[.)])\s", last_line))
    if out and out[-1] not in ".!?:\n" and not a_list_item:
        out += "."
    return out


# --------------------------------------------------------------- openai

def _openai(text: str, cfg: dict) -> str:
    from openai import OpenAI
    client = OpenAI(
        api_key=cfg["openai_api_key"],
        timeout=float(cfg.get("llm_timeout_seconds", 20)),
        max_retries=0,   # llm_timeout_seconds is a ceiling; a retry doubles it
    )
    resp = client.chat.completions.create(
        model=_model_for("openai", cfg),
        messages=[
            {"role": "system", "content": build_prompt(cfg)},
            {"role": "user", "content": text},
        ],
        temperature=0.2,
        max_tokens=_MAX_TOKENS,
    )
    return resp.choices[0].message.content or ""


# ------------------------------------------------------------ anthropic

def _anthropic(text: str, cfg: dict) -> str:
    import anthropic
    client = anthropic.Anthropic(
        api_key=cfg["anthropic_api_key"],
        timeout=float(cfg.get("llm_timeout_seconds", 20)),
        max_retries=0,   # llm_timeout_seconds is a ceiling; a retry doubles it
    )
    resp = client.messages.create(
        model=_model_for("anthropic", cfg),
        max_tokens=_MAX_TOKENS,
        system=build_prompt(cfg),
        messages=[{"role": "user", "content": text}],
    )
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


# ----------------------------------------------------------------- groq

def _groq(text: str, cfg: dict) -> str:
    from groq import Groq
    client = Groq(
        api_key=cfg["groq_api_key"],
        timeout=float(cfg.get("llm_timeout_seconds", 20)),
        max_retries=0,   # llm_timeout_seconds is a ceiling; a retry doubles it
    )
    resp = client.chat.completions.create(
        model=_model_for("groq", cfg),
        messages=[
            {"role": "system", "content": build_prompt(cfg)},
            {"role": "user", "content": text},
        ],
        temperature=0.2,
        max_tokens=_MAX_TOKENS,
    )
    return resp.choices[0].message.content or ""


# --------------------------------------------------------------- ollama

def _ollama(text: str, cfg: dict) -> str:
    import requests
    url = str(cfg.get("ollama_url", "http://localhost:11434")).rstrip("/")
    payload = {
        "model": cfg.get("ollama_model", "llama3"),
        "messages": [
            {"role": "system", "content": build_prompt(cfg)},
            {"role": "user", "content": text},
        ],
        "stream": False,
        "options": {"temperature": 0.2},
    }
    resp = requests.post(
        f"{url}/api/chat",
        json=payload,
        timeout=float(cfg.get("llm_timeout_seconds", 20)),
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"]
