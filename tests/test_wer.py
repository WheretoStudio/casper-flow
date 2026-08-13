"""The scoring metric itself.

A metric that flatters results is worse than no metric, so the "fair" variant is
tested from both directions: it must forgive romanisation and number-format
differences, and it must still count genuine mistakes as mistakes.

Cases are taken from real transcripts in corpus/RESULTS.md.
"""

import pytest

from wer import fold, word_error_rate


class TestFairForgivesSpelling:
    """Alternative romanisations of the same Hindi word."""

    @pytest.mark.parametrize("a,b", [
        ("yeh", "yah"),
        ("woh", "vah"),
        ("wala", "vaala"),
        ("kahan", "kahaan"),
        ("nahi", "nahin"),
        ("hai", "hain"),
        ("zyada", "jyada"),
        ("phir", "fir"),
        ("theek", "thik"),
        ("bhej", "bhej"),
        ("ham", "hum"),
    ])
    def test_variants_fold_together(self, a, b):
        assert fold(a) == fold(b), f"{a!r} and {b!r} should read as the same word"

    def test_a_real_sentence_scores_zero(self):
        """From cs04: only the spelling differs."""
        said = "matlab yeh feature abhi kaam nahi kar raha hai"
        got = "matlab yah feature abhi kam nahin kar raha hain"
        assert word_error_rate(said, got, fair=True) == 0.0
        assert word_error_rate(said, got) > 0.3, "strict should still penalise it"


class TestFairForgivesNumbers:
    def test_spoken_quantity_matches_digits(self):
        said = "invoice amount is forty two thousand five hundred rupees"
        got = "Envoys amount is 42500 rupees."
        # 'invoice'/'Envoys' is a real error; the number must not also count.
        assert word_error_rate(said, got, fair=True) < 0.25
        assert word_error_rate(said, got) > 0.5

    def test_digit_string_read_out_matches(self):
        said = "mera number hai nine eight seven six five four three two one zero"
        got = "mera number hai 9876543210"
        assert word_error_rate(said, got, fair=True) == 0.0

    def test_ordinal_dates_match(self):
        assert word_error_rate("twenty fourth march", "24 march", fair=True) == 0.0

    def test_lakh_is_handled(self):
        assert word_error_rate("two lakh fifty thousand", "250000", fair=True) == 0.0


class TestFairStillCatchesRealErrors:
    """The important direction. These are genuine failures from the corpus."""

    def test_a_wrong_proper_noun_is_an_error(self):
        said = "Bangalore office se Sharma ji call karenge"
        got = "Thank you office se sharma ji ka call"
        assert word_error_rate(said, got, fair=True) > 0.3, (
            "'Bangalore' becoming 'Thank you' must not be forgiven"
        )

    def test_hindi_inserted_into_english_is_an_error(self):
        said = "please send me the quarterly report before the review"
        got = "Please send me the call to make report bahut deri view"
        assert word_error_rate(said, got, fair=True) > 0.3

    @pytest.mark.parametrize("a,b", [
        ("kal", "kaam"),
        ("meeting", "eating"),
        ("bhej", "baith"),
        ("bangalore", "thank"),
        ("quarterly", "call"),
        ("report", "deri"),
    ])
    def test_different_words_do_not_fold(self, a, b):
        assert fold(a) != fold(b), f"{a!r} and {b!r} folded together"

    def test_empty_transcript_is_total_failure(self):
        assert word_error_rate("kal ek meeting hai", "", fair=True) == 1.0

    def test_digits_are_never_folded_as_words(self):
        assert fold("42500") == "42500"
        assert fold("2026") == "2026"


class TestFillerHandling:
    def test_dropped_fillers_can_be_excluded(self):
        said = "um so basically yeh wala approach better hai"
        got = "so basically yah vaala approach better hai"
        # The model dropped 'um', which the cleanup step strips anyway.
        assert word_error_rate(said, got, fair=True,
                               drop_fillers=("um", "uh")) == 0.0
        assert word_error_rate(said, got, fair=True) > 0.0


class TestMetricSanity:
    def test_identical_is_zero(self):
        assert word_error_rate("kal ek meeting hai", "kal ek meeting hai") == 0.0

    def test_punctuation_and_case_are_ignored(self):
        assert word_error_rate("kal ek meeting hai", "Kal, ek MEETING hai.") == 0.0

    def test_insertions_can_exceed_one(self):
        assert word_error_rate("hello", "hello hello hello") > 1.0

    def test_empty_reference_with_empty_hypothesis_is_perfect(self):
        assert word_error_rate("", "") == 0.0
