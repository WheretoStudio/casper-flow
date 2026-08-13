"""
Cleanup and formatting step: raw Whisper transcript in, pasted text out.

  cleanup      always. Fillers, spoken punctuation, spacing, sentence casing.
  grammar_fix  optional. Tense, agreement, articles, word order.
  format_mode  optional. Lay the text out as a message or an email body.

Backends: rules | ollama | openai | anthropic | groq. `rules` is the default
because it is a deterministic transform and cannot write words that were not
spoken; the other two features are generative and need a model backend.

This step must never lose the dictation. Every failure path - missing key,
timeout, unreachable or chatty model, a model that summarised - returns the
deterministic cleanup of the same transcript instead of an error.
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

# Without explicit rules, models translate Hindi into English and destroy the
# user's wording.
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

# Rule 5 forbids changing meaning, and grammar repair must change words, so this
# is scoped as a narrow exception to rule 5 rather than a loosening of it.
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
    # Rules 10 and 11 split "when you must bullet" from "when you must not"; a
    # single hedged rule made small models choose prose every time.
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

    # The blocks above end at rule 8, and both GRAMMAR_RULE and FORMAT_RULES start
    # at 9, so the layout rules shift up by one when grammar_fix is also on.
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

# Per-backend default model. config.DEFAULTS always supplies `llm_model`, so a
# per-call default cannot fire; without this table, switching backend without also
# editing `llm_model` sends an OpenAI id to another vendor and 404s.
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

    The shipped `llm_model` default names an OpenAI model, so other backends get
    their own default instead. A user-chosen value passes through untouched.
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

    An allow-list of literal loopback hosts, not a substring or looks-remote check.
    A denylist here fails open, and failing open ships the dictation to another
    host.
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

# Headroom past the configured timeout, kept small so the backend's own timeout
# gets to raise a useful error first.
_DEADLINE_GRACE = 1.5


def _call_with_deadline(fn, raw_text: str, cfg: dict) -> str:
    """
    Run a backend with a real wall-clock ceiling.

    The clients apply `llm_timeout_seconds` per attempt or per socket operation, so
    only an outer deadline can guarantee it. The worker is a daemon thread and is
    abandoned, not cancelled: a blocking socket read cannot be interrupted safely,
    and waiting for it costs the user their paste.
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
    # backend cannot, so the request is dropped rather than half-honoured.
    if backend == "rules" and is_generative(cfg):
        log.warning(
            f"format_mode={format_mode(cfg)!r} grammar_fix="
            f"{bool(cfg.get('grammar_fix'))} require a language model; the "
            f"'rules' backend cannot generate text. Pasting plain cleanup."
        )

    # The offline_only gate is enforced here, not in the caller, so no combination
    # of settings can send a transcript off the machine.
    if cfg.get("offline_only", True) and backend in CLOUD_BACKENDS:
        log.warning(
            f"llm_backend={backend!r} would send text off this machine and "
            f"offline_only is on. Using the built-in rules cleanup instead. "
            f"Install Ollama for smarter local cleanup."
        )
        backend = "rules"

    # Ollama is private only because it is local, so the url is gated too, not just
    # the backend name. An absent url means the default, which is loopback.
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

    # Computed up front because it is also the fallback: a rejected rewrite still
    # gets punctuation and casing.
    try:
        plain = _rules(raw_text, cfg)
    except Exception:
        plain = raw_text

    if fn is _rules:
        # DEBUG, not INFO: this is the dictation itself, and casper.log ships at
        # INFO and is never rotated.
        log.debug(f"Polished: {plain!r}")
        return plain

    try:
        out = _call_with_deadline(fn, raw_text, cfg)
    except TimeoutError as e:
        log.warning(f"{e}; pasting plain cleanup")
        return plain
    except Exception as e:
        log.warning(f"Cleanup backend failed ({e}); pasting plain cleanup")
        return plain

    # Only model output needs the plausibility guards; the rules backend cannot
    # invent text.
    cleaned = _sanitise(out, plain, cfg)
    log.debug(f"Polished: {cleaned!r}")
    return cleaned


# Growth ceiling as a multiple of input length, with a floor for short dictations.
# Per mode, because restructuring legitimately adds characters.
_GROWTH = {"plain": (3.0, 120), "message": (4.0, 200), "email": (6.0, 500)}

# Shrink floor, catching a model that summarised. Generous, because filler removal
# legitimately shortens text.
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
    Words long enough to carry meaning, lowercased. Four characters and up skips
    articles, prepositions and short inflected verbs - what a grammar pass changes.
    """
    return [w for w in re.findall(r"[^\W\d_]+", (text or "").lower()) if len(w) >= 4]


def _content_retained(out: str, raw: str) -> float:
    """
    What fraction of the transcript's content words survived. Catches content
    swapped for invented content at a plausible length, which the length and number
    guards cannot see.
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


# Below this share of the transcript's content words the output is not a tidied
# version of it. Generous, since grammar and spelling fixes change words.
_RETENTION = 0.5

# Fewest content words for the retention ratio to mean anything; below this one
# word moves it by a third or more. See _sanitise.
_RETENTION_MIN_WORDS = 4


def _novel_share(out: str, raw: str) -> float:
    """
    What fraction of the output is words the speaker never said. Retention catches
    dropped content; this catches added content, which scores perfect retention and
    can still fit the length ceiling.
    """
    have = _content_words(out)
    if not have:
        return 0.0
    said = set(_content_words(raw))
    return sum(1 for w in have if w not in said) / len(have)


# Greetings, sign-offs and rephrased connectives are legitimately new words, so
# some novelty is expected. Past half, most of the paste was never said.
_NOVELTY = 0.5


def _numbers_survived(out: str, raw: str) -> bool:
    """
    Every digit in the transcript still appears in the output. Compared as a
    multiset, so the model may regroup or reformat them, and extra digits are
    allowed: "twenty five" -> "25".
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

    Strips code fences and wrapping quotes, then rejects output that is not a
    cleaned-up version of the input: too long (chatting, or answering the
    question), too short (summarised), or missing dictated numbers. Rejection
    returns `raw`, which `polish()` sets to the deterministic cleanup.
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

    # A leading "Here is the cleaned-up transcript:" line, which small models add
    # despite TAIL and which is too short to trip a size guard. The pattern needs a
    # self-referential opener, a word about the text and a colon, so legitimate
    # first lines like "There are three blockers:" survive.
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

    # Retention is a ratio, so on a short dictation one word swings it far enough to
    # reject legitimate rewrites: "twenty five people" -> "25 people" keeps one
    # content word of three. Below the floor the novelty guard covers the same
    # ground from the other side and does not care how short the input was.
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

# Spoken punctuation, longest first so "new paragraph" wins over "new line". The
# third field marks phrases that are also ordinary nouns; those get a context check,
# since substituting blindly deletes a word the user said ("put a comma there").
#
# "period" is excluded: no context rule saves it, since the preceding word is an
# ordinary noun in "notice period", "grace period", "period of time".
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

# A determiner, possessive or preposition in front means the user is talking about
# the mark, not asking for one: "put a comma", "without a full stop".
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


# A run this long repeated verbatim is a transcription artefact, not speech. Three
# is too few: "kar do kar do" and "bahut bahut dhanyavad" are things people say.
_REPEAT_MIN_WORDS = 4


def _collapse_repeated_clause(text: str) -> str:
    """
    Remove a clause the speech model transcribed twice in a row.

    Whisper repeats a phrase inside one segment while staying confident, so neither
    its compression-ratio nor its log-probability check fires.

    Exact, adjacent, whole-word repeats of at least `_REPEAT_MIN_WORDS` only, and
    never the last copy: deleting words the user said is worse than leaving a
    duplicate they can see. Paraphrased restatements are left alone; catching those
    needs fuzzy matching, which rewrites correct words into wrong ones.
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
        # Longest run first, so "a b c d a b c d a b c d" collapses in one pass.
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

    Fixes punctuation, spacing, casing and interjections. Must not change wording -
    that is what makes it safe as the default. Use the ollama backend for rewriting.
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

    # 3. immediate duplicated words ("the the report" -> "the report"), keeping the
    #    first spelling and skipping words Hinglish legitimately repeats.
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

    # A leading filler leaves a space behind, which would hide the first letter from
    # the casing rule below.
    out = out.strip()

    # 6. sentence casing, without touching the rest of a word
    def upper_first(m):
        return m.group(1) + m.group(2).upper()

    out = re.sub(r"(^|[.!?]\s+|\n)([a-z])", upper_first, out)

    # 7. collapse duplicated terminal punctuation, then ensure the text ends
    #    with some
    out = re.sub(r"([.!?]){2,}", r"\1", out).strip()
    # A list item is not a sentence: "- two." reads as a typo.
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
