"""
Deterministic post-transcription corrections. No speech model knows your
colleagues' names, so the user supplies them. Two mechanisms, highest precedence
first:

  replacements   explicit "heard this, meant that" pairs, applied exactly
  vocabulary     canonical spelling and capitalisation for known words, matched
                 case-insensitively and exactly ("whatsapp" -> "WhatsApp")

Neither can invent a word outside the user's own lists. Matching is exact only;
phonetic matching corrupts correct text. Biasing the decoder is the way to fix
proper nouns before the fact - see `initial_prompt`.
"""

import logging
import re

log = logging.getLogger("casper.corrections")

# Combining marks are not \w in Python's `re`, and Devanagari writes most of its
# vowels with them. Without this list, "मीटिंग" tokenises as ['म', 'ट', 'ग'] and \b
# lands mid-word, so no Devanagari vocabulary entry can ever match.
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

    Built once from config and reused; compiling the patterns per dictation would
    be wasted work on the hot path.
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

        Case-insensitive exact match only; phonetic matching corrupts correct text.
        Returns the term even when the words already match it, because the caller
        reads None as "try a narrower n-gram": with vocabulary ["Sharma ji",
        "sharma"], conflating the two lets the 1-gram rewrite a correct "Sharma ji".
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

        # Words and the separators between them, so punctuation and spacing survive
        # reassembly untouched.
        pieces = _WORD_RE.split(text)
        words = _WORD_RE.findall(text)
        if not words:
            return text

        # pieces[k] is the separator before words[k]. After consuming words[i:i+w]
        # the separator to emit is pieces[i+w], the one that followed the last word
        # consumed; emitting one per output token would strand a separator whenever
        # a multi-word term collapsed two words into one.
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
            # A function, not a template string: sub() would read the user's value
            # as a template, so "C:\temp" inserts a tab and "\1x" raises re.error
            # and loses the whole dictation.
            text = pattern.sub(lambda _m, r=right: r, text)
        text = self._apply_vocabulary(text)
        if text != before:
            # DEBUG, not INFO: this is the user's dictation, and casper.log is
            # plaintext and never rotated.
            log.debug(f"Corrections applied: {before!r} -> {text!r}")
        return text


_cached: tuple[str, Corrector] | None = None


def _cache_key(cfg: dict) -> str:
    """
    A key that changes when the settings this class reads change.

    Keyed on content, not `id(cfg)`: the settings window mutates the config dict in
    place, so identity never changes and edits would need a restart to take effect.
    """
    return repr((cfg.get("corrections"), cfg.get("vocabulary")))


def apply_corrections(text: str, cfg: dict) -> str:
    """Convenience wrapper that caches the Corrector for a given config."""
    global _cached
    key = _cache_key(cfg)
    if _cached is None or _cached[0] != key:
        _cached = (key, Corrector(cfg))
    return _cached[1].apply(text)
