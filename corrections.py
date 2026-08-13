"""
Deterministic post-transcription corrections.

Proper nouns are the worst category on the measured corpus: 44.8% accuracy,
against 81.0% for code-switched speech generally. `Bangalore` came back as
`Thank you`, `WhatsApp` as `Vah sab`. That is not a model-size problem - no
Whisper variant has heard of your colleagues - so it is not solved by a bigger
download.

It is solved by telling the app the words you use. Two mechanisms, in order of
precedence:

  replacements   an explicit "heard this, meant that" mapping. Exact, and always
                 applied. What you reach for when you see the same mistake twice.

  vocabulary     canonical spelling and capitalisation for words you use.
                 Matched case-insensitively and exactly, so `whatsapp` becomes
                 `WhatsApp`. It never changes which word was transcribed.

Both are deterministic. Neither can invent a word that is not in your own list,
which is the same property that made the `rules` cleanup preferable to an LLM.

**This layer was originally more ambitious and was cut down by measurement.**
Vocabulary entries used to match by *sound* rather than spelling, on the theory
that the weak proper-noun category was full of near-misses a phonetic match could
recover. Measured against the corpus, that theory was wrong twice over:

  * The failures are not near-misses. `Bangalore` was transcribed `Thank you`
    and `WhatsApp` as `Vah sab` - unrelated words, not misspellings. There is no
    signal left for a matcher to use.
  * Sound matching actively corrupted correct text. `shaam` (evening) and
    `sharp` both fold to within one edit of `Sharma`, so both were rewritten to
    a colleague's name in sentences that had been transcribed perfectly.

Fixing proper nouns needs the model biased *before* decoding, not patched
afterwards - that is what `initial_prompt` is for. What survives here is the part
that cannot be wrong: exact matching for canonical form, and explicit
replacements the user asked for by name.
"""

import logging
import re

log = logging.getLogger("casper.corrections")

# Combining marks are not \w in Python's `re`, and Devanagari writes most of its
# vowels with them. Without this, "मीटिंग" tokenises as ['म', 'ट', 'ग'] - the word
# is shredded, a Devanagari vocabulary entry can never match, and `\b` behaves
# backwards: `\bहै\b` fails (the trailing matra is not a word character, so \b
# demands another word character after it) while `\bमीट\b` happily matches inside
# "मीटिंग". Both were verified before this was added. output_script="devanagari"
# is a supported setting, so this is a supported script.
_MARKS = (
    "\u0900-\u0903"      # candrabindu, anusvara, visarga
    "\u093a-\u094f"      # vowel signs and virama
    "\u0951-\u0957"      # accents and additional vowel signs
    "\u0962-\u0963"      # vocalic l/ll signs
    "\u200c\u200d"       # ZWNJ / ZWJ, used to control conjunct forming
)

# One "word": word characters and the marks that attach to them.
_WORD_RE = re.compile(rf"(?:[^\W_]|[{_MARKS}])+", re.UNICODE)

# Stand-ins for \b that count those marks as part of the word. Both are
# single-character classes, so the lookbehind stays fixed-width.
_NOT_BEFORE = rf"(?<![^\W_]|[{_MARKS}])"
_NOT_AFTER = rf"(?![^\W_]|[{_MARKS}])"


class Corrector:
    """
    Applies replacements and vocabulary matching to a transcript.

    Built once from config and reused, because folding every vocabulary entry on
    every dictation would be wasted work on the hot path.
    """

    def __init__(self, cfg: dict):
        raw_repl = cfg.get("corrections") or {}
        if not isinstance(raw_repl, dict):
            log.warning(
                f"'corrections' must be an object of \"heard\": \"meant\" pairs, "
                f"not {type(raw_repl).__name__}; ignoring it"
            )
            raw_repl = {}
        self.replacements: list[tuple[re.Pattern, str]] = []
        for wrong, right in raw_repl.items():
            if not str(wrong).strip():
                continue
            # Whole-phrase, case-insensitive. Word boundaries on both ends so
            # "cal" does not rewrite the middle of "call".
            pattern = re.compile(
                _NOT_BEFORE + re.escape(str(wrong).strip()) + _NOT_AFTER, re.I
            )
            self.replacements.append((pattern, str(right)))

        raw_vocab = cfg.get("vocabulary") or []
        if isinstance(raw_vocab, str) or not isinstance(raw_vocab, (list, tuple)):
            log.warning(
                f"'vocabulary' must be a list of words, not "
                f"{type(raw_vocab).__name__}; ignoring it"
            )
            raw_vocab = []
        self.vocabulary = [str(v).strip() for v in raw_vocab if str(v).strip()]
        # Grouped by word count so multi-word terms are matched as n-grams:
        # "Sharma ji" has to be considered before "Sharma".
        self._by_len: dict[int, list[tuple[str, str]]] = {}
        for term in self.vocabulary:
            parts = term.split()
            self._by_len.setdefault(len(parts), []).append((term.lower(), term))

        self.enabled = bool(self.replacements or self.vocabulary)

    # -- vocabulary ----------------------------------------------------

    def _match_term(self, words: list[str]) -> str | None:
        """
        The canonical form of this run of words, or None if it is not a term.

        Returns the term even when the text already matches it exactly. "Not a
        term" and "already correct" have to be different answers, because the
        caller uses None to mean "try a narrower n-gram" - and conflating them
        let an already-correct phrase be re-matched by a shorter entry. With
        vocabulary ["Sharma ji", "sharma"], the correct text "Sharma ji" fell
        through the 2-gram and was rewritten by the 1-gram to "sharma ji".

        Case-insensitive exact match only. Deliberately not fuzzy: a phonetic
        match rewrote `shaam` and `sharp` to `Sharma` on this corpus, turning
        correct transcripts into wrong ones. A layer that damages good text is
        worse than no layer.
        """
        candidates = self._by_len.get(len(words))
        if not candidates:
            return None
        lowered = " ".join(words).lower()
        for term_lower, term in candidates:
            if lowered == term_lower:
                return term
        return None

    def _apply_vocabulary(self, text: str) -> str:
        if not self._by_len:
            return text

        # Tokenise into words and the separators between them, so punctuation and
        # spacing survive reassembly untouched.
        pieces = _WORD_RE.split(text)
        words = _WORD_RE.findall(text)
        if not words:
            return text

        # pieces[k] is the separator before words[k], and pieces[-1] is whatever
        # trailed the last word. So after consuming words[i:i+w] the separator to
        # emit is pieces[i+w] - the one that followed the last word consumed.
        # Emitting per output token instead would leave a stray separator behind
        # whenever a multi-word term collapsed two words into one.
        result = [pieces[0]]
        i = 0
        # Longest terms first, so "Sharma ji" wins over "Sharma".
        widths = sorted(self._by_len, reverse=True)
        while i < len(words):
            width = 1
            token = words[i]
            for w in widths:
                if w <= 0 or i + w > len(words):
                    continue
                term = self._match_term(words[i:i + w])
                if term is not None:
                    original = " ".join(words[i:i + w])
                    if original != term:
                        log.debug(f"vocabulary: {original!r} -> {term!r}")
                    token, width = term, w
                    break
            result.append(token)
            result.append(pieces[i + width])
            i += width
        return "".join(result)

    # -- public --------------------------------------------------------

    def apply(self, text: str) -> str:
        if not text or not self.enabled:
            return text
        before = text
        for pattern, right in self.replacements:
            # A function replacement, not a template string. `pattern.sub(right,
            # ...)` interprets the user's text as a replacement template, so a
            # correction value of "C:\temp" pasted a tab character and one of
            # "\1x" raised re.error - which propagated out of the pipeline and
            # discarded the whole dictation. Both were verified. The patterns are
            # escaped; the replacements were not.
            text = pattern.sub(lambda _m, r=right: r, text)
        text = self._apply_vocabulary(text)
        if text != before:
            # DEBUG, not INFO: this is the user's dictation, and casper.log is a
            # plaintext file that is never rotated.
            log.debug(f"Corrections applied: {before!r} -> {text!r}")
        return text


_cached: tuple[str, Corrector] | None = None


def _cache_key(cfg: dict) -> str:
    """
    A key that changes when the settings this class reads change.

    Keyed on the content rather than on `id(cfg)`: the settings window mutates
    the config dict in place, so the identity never changed and edits to
    `vocabulary` or `corrections` were ignored until the app was restarted.
    """
    return repr((cfg.get("corrections"), cfg.get("vocabulary")))


def apply_corrections(text: str, cfg: dict) -> str:
    """Convenience wrapper that caches the Corrector for a given config."""
    global _cached
    key = _cache_key(cfg)
    if _cached is None or _cached[0] != key:
        _cached = (key, Corrector(cfg))
    return _cached[1].apply(text)
