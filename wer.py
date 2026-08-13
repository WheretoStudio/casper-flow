"""
Word error rate, with an honest second opinion for Romanised Hinglish.

Exact word matching is the standard metric and it is unfair to this task, because
Hinglish written in Latin script has no canonical spelling. `yeh` and `yah`,
`woh` and `vah`, `kahan` and `kahaan`, `nahi` and `nahin` are all the same word
to a reader, and all count as errors to a plain scorer. So do digits against
number words, where `42500` is arguably a better transcript than `forty two
thousand five hundred`.

Two metrics are therefore reported:

  strict  - exact word match. Comparable to published WER figures.
  fair    - spelling variants and number formats folded together first.

`fair` is a judgement call, and a metric that flatters results is worse than no
metric, so three rules keep it honest:

  * it only ever folds forms a Hindi speaker would read as the same word,
  * it never folds two different words together - `Bangalore` and `Thank you`
    stay a mistake,
  * both numbers are always reported side by side, so the gap between them is
    visible rather than hidden.

The gap itself is informative: a large one means the model heard correctly and
spelled differently, a small one means it genuinely misheard.
"""

import re

__all__ = ["word_error_rate", "tokens", "fold", "has_devanagari"]

# Spoken number words to digits, so "forty two thousand five hundred" and
# "42500" compare equal. Indian English also uses lakh and crore.
_UNITS = {
    "zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}
_SCALES = {"hundred": 100, "thousand": 1000, "lakh": 100000, "crore": 10000000,
           "million": 1000000}

# Ordinals appear in dates: "twenty fourth March".
_ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
    "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11,
    "twelfth": 12, "thirteenth": 13, "fourteenth": 14, "fifteenth": 15,
    "sixteenth": 16, "seventeenth": 17, "eighteenth": 18, "nineteenth": 19,
    "twentieth": 20, "thirtieth": 30,
}


def has_devanagari(text: str) -> bool:
    return any("\u0900" <= ch <= "\u097f" for ch in text)


def tokens(text: str) -> list[str]:
    """Lowercase words, punctuation dropped. Digits kept as their own tokens."""
    out = []
    for ch in str(text).lower():
        out.append(ch if (ch.isalnum() or ch.isspace()) else " ")
    return "".join(out).split()


def _numbers_to_digits(words: list[str]) -> list[str]:
    """
    Collapse runs of number words into a single digit token.

    Handles both a spoken quantity ("forty two thousand five hundred" -> 42500)
    and digits read out one by one ("nine eight seven" -> 987), because speakers
    do both and models transcribe both as digits.
    """
    out: list[str] = []
    i = 0
    while i < len(words):
        w = words[i]
        if w not in _UNITS and w not in _ORDINALS and w not in _SCALES:
            out.append(w)
            i += 1
            continue

        # Consume the whole run of number words.
        run = []
        while i < len(words) and (
            words[i] in _UNITS or words[i] in _ORDINALS or words[i] in _SCALES
            or words[i] == "and"
        ):
            run.append(words[i])
            i += 1
        run = [r for r in run if r != "and"]
        if not run:
            continue

        # A run of single digits with no scale word is a digit string.
        if all(r in _UNITS and _UNITS[r] <= 9 for r in run) and len(run) > 1:
            out.append("".join(str(_UNITS[r]) for r in run))
            continue

        total, current = 0, 0
        for r in run:
            if r in _ORDINALS:
                current += _ORDINALS[r]
            elif r in _UNITS:
                current += _UNITS[r]
            else:
                scale = _SCALES[r]
                if scale == 100:
                    current = max(1, current) * 100
                else:
                    total += max(1, current) * scale
                    current = 0
        out.append(str(total + current))
    return out


# Romanisation differences that a reader ignores. Ordered: longer patterns first.
_FOLD = [
    (r"aa+", "a"), (r"ee+", "i"), (r"ii+", "i"), (r"oo+", "u"), (r"uu+", "u"),
    (r"w", "v"),                              # woh/vah, wala/vaala
    (r"z", "j"),                              # zyada/jyada
    (r"ph", "f"),                             # phir/fir
    (r"chh", "ch"),
    (r"([bcdfghjklmnpqrstvxyz])\1", r"\1"),   # doubled consonants
    (r"n$", ""),                              # nahi/nahin, hai/hain
    # Trailing vowels and h are optional in romanisation: yeh/yah/ye,
    # thoda/thode. The lookbehind keeps at least one character, or a word made
    # entirely of these ("hai") would reduce to nothing and fall back to itself,
    # so it would never match its own nasal variant ("hain").
    (r"(?<=.)[aeiouh]+$", ""),
]

# High-frequency words whose vowels differ in ways the rules cannot catch without
# also merging unrelated words. An explicit table is transparent and cannot
# over-reach, which a general internal-vowel rule would.
_ALIASES = {
    "hum": "ham",
    "tum": "tam",
    "kyun": "kyon",
    "kuch": "kuchh",
}


def fold(word: str) -> str:
    """
    A spelling-variant-insensitive key for one word.

    Never applied to a token containing a digit, so numbers survive intact.

    **Known limitation, stated rather than hidden:** stripping trailing vowels
    merges the short postpositions - `ka`, `ki`, `ke` and `ko` all reduce to `k`.
    Those are grammatically distinct, so the fair metric forgives a class of small
    grammatical error a strict reader would count. That is the price of not
    counting `yeh` against `yah`, and it is why both metrics are always reported
    together rather than the fair one replacing the strict one.
    """
    if any(c.isdigit() for c in word):
        return word
    w = _ALIASES.get(word, word)
    for pattern, repl in _FOLD:
        w = re.sub(pattern, repl, w)
    return w or word


def _edit_distance(ref: list[str], hyp: list[str]) -> int:
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i]
        for j, h in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h)))
        prev = cur
    return prev[-1]


def word_error_rate(reference: str, hypothesis: str, *, fair: bool = False,
                    drop_fillers: tuple[str, ...] = ()) -> float:
    """
    Word error rate. 0.0 is perfect; values above 1.0 are possible when the
    hypothesis is longer than the reference.

    fair=True folds number formats and romanisation variants first.
    drop_fillers removes those words from both sides, for the case where the
    cleanup step strips them anyway and their absence is not an error.
    """
    ref, hyp = tokens(reference), tokens(hypothesis)

    if drop_fillers:
        drop = {f.lower() for f in drop_fillers}
        ref = [w for w in ref if w not in drop]
        hyp = [w for w in hyp if w not in drop]

    if fair:
        ref, hyp = _numbers_to_digits(ref), _numbers_to_digits(hyp)
        ref, hyp = [fold(w) for w in ref], [fold(w) for w in hyp]

    if not ref:
        return 0.0 if not hyp else 1.0
    return _edit_distance(ref, hyp) / len(ref)
