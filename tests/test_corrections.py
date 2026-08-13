"""The correction layer.

Cases are taken from real transcripts in corpus/RESULTS.md, where proper nouns
were the worst category at 44.8% accuracy.

The layer must fix what the user told it about and leave everything else alone.
The second half matters more than the first: a correction layer that rewrites
words the user did not ask about is worse than none, because it introduces errors
into text that was already right.
"""

import pytest

from corrections import Corrector


def make(vocabulary=(), corrections=None) -> Corrector:
    return Corrector({"vocabulary": list(vocabulary),
                      "corrections": corrections or {}})


class TestVocabularyFixesProperNouns:
    def test_canonical_casing_is_restored(self):
        c = make(["WhatsApp", "Gmail"])
        assert c.apply("whatsapp pe bhej dena") == "WhatsApp pe bhej dena"
        assert c.apply("gmail check nahi kar raha hoon").startswith("Gmail")

    def test_a_multi_word_term_is_matched_as_one_unit(self):
        c = make(["Sharma Ji"])
        assert c.apply("sharma ji call karenge") == "Sharma Ji call karenge"

    def test_longer_terms_win_over_shorter_ones(self):
        c = make(["Sharma", "Sharma Ji"])
        assert c.apply("sharma ji aa rahe hain") == "Sharma Ji aa rahe hain"

    def test_punctuation_and_spacing_survive(self):
        c = make(["Priya"])
        assert c.apply("priya, please dekho.") == "Priya, please dekho."

    def test_correct_text_is_left_untouched(self):
        c = make(["WhatsApp"])
        text = "WhatsApp pe bhej dena"
        assert c.apply(text) == text


class TestExplicitReplacements:
    def test_a_known_mishearing_is_fixed(self):
        """From nm02: 'Bangalore' was transcribed 'Thank you'."""
        c = make(corrections={"thank you office": "Bangalore office"})
        assert c.apply("Thank you office se sharma ji ka call") \
            == "Bangalore office se sharma ji ka call"

    def test_replacements_are_case_insensitive_but_preserve_the_replacement(self):
        c = make(corrections={"envoys": "invoice"})
        assert c.apply("Envoys amount is 42500") == "invoice amount is 42500"

    def test_replacements_do_not_fire_inside_longer_words(self):
        c = make(corrections={"cal": "call"})
        assert c.apply("please call me") == "please call me"

    def test_replacements_run_before_vocabulary(self):
        c = make(vocabulary=["Bangalore"], corrections={"thank you": "bangalore"})
        assert c.apply("thank you office") == "Bangalore office"


class TestDoesNotDamageGoodText:
    """
    The failure mode that matters. Every one of these must pass unchanged.
    """

    @pytest.mark.parametrize("text", [
        "kal ek meeting hai client ke saath, please report bhej dena",
        "the deposition is scheduled for Thursday morning",
        "please send me the quarterly report before the review",
        "let us move the standup to eleven o'clock",
        "mujhe yeh baat samajh nahi aayi",
        "invoice amount is 42500 rupees",
    ])
    def test_realistic_sentences_are_unchanged(self, text):
        c = make(["Bangalore", "WhatsApp", "Gmail", "Priya", "Rohit", "Sharma"])
        assert c.apply(text) == text

    @pytest.mark.parametrize("text", [
        # Both of these were rewritten to "Sharma" by an earlier phonetic
        # matcher, in sentences the model had transcribed perfectly.
        "thoda check karke bata dena, deadline kal shaam tak hai",
        "meeting hai twenty fourth March ko sharp three thirty pm",
    ])
    def test_words_that_merely_sound_similar_are_untouched(self, text):
        c = make(["Sharma", "Bangalore", "WhatsApp", "Gmail", "Priya", "Rohit"])
        assert c.apply(text) == text, (
            "a vocabulary entry captured an ordinary word, which turns a correct "
            "transcript into a wrong one"
        )

    def test_short_vocabulary_entries_do_not_capture_ordinary_words(self):
        c = make(["Raj"])
        assert c.apply("woh raat ko aayega") == "woh raat ko aayega"

    def test_an_unrelated_word_is_not_pulled_to_a_vocabulary_term(self):
        c = make(["Bangalore"])
        assert c.apply("the bungalow is ready") == "the bungalow is ready"

    def test_a_substituted_name_is_not_recoverable(self):
        """
        Documents the measured limitation rather than pretending otherwise:
        'Bangalore' was transcribed 'Thank you', and no post-hoc matcher can
        recover a word the model never emitted. Only an explicit replacement can.
        """
        c = make(["Bangalore"])
        assert c.apply("Thank you office") == "Thank you office"

    def test_empty_config_is_a_no_op(self):
        c = make()
        assert not c.enabled
        text = "kal ek meeting hai"
        assert c.apply(text) == text

    def test_empty_text_is_safe(self):
        assert make(["Priya"]).apply("") == ""


class TestCannotHallucinate:
    def test_output_words_come_only_from_input_or_the_user_list(self):
        """
        The property that made deterministic cleanup preferable to an LLM: it
        cannot produce a word the user did not supply.
        """
        vocab = ["Bangalore", "WhatsApp"]
        c = make(vocab)
        out = c.apply("sarma ji ne kaha ki bangalore office band hai")
        allowed = set("sarma ji ne kaha ki bangalore office band hai".split())
        allowed |= {v.lower() for v in vocab}
        for word in out.lower().split():
            assert word.strip(".,") in allowed, f"invented {word!r}"


class TestReplacementValuesAreLiteralText:
    """
    A correction value is text the user typed, not a regex replacement template.

    It used to be passed straight to `re.Pattern.sub`, which interprets
    backslashes and group references. Two measured consequences, both of which
    reached the user: a Windows path in a correction value pasted a tab character
    into their document, and a stray group reference raised `re.error` out of the
    pipeline and discarded the whole dictation with a message about invalid group
    references. The patterns were escaped; the replacements were not.
    """

    @pytest.mark.parametrize("value", [
        r"C:\temp",          # \t became a tab
        r"C:\new\report",    # \n and \r
        r"\1x",              # raised re.error: invalid group reference
        r"\g<0>",
        r"\\",
        "50% \\ done",
    ])
    def test_the_value_is_pasted_exactly_as_written(self, value):
        c = make(corrections={"placeholder": value})
        assert c.apply("the placeholder here") == f"the {value} here"

    def test_a_backslash_value_cannot_raise_out_of_the_pipeline(self):
        """
        main.py catches exceptions from this layer by discarding the dictation, so
        anything raising here costs the user everything they just said.
        """
        for value in (r"\1", r"\g<9>", "\\", r"\x"):
            c = make(corrections={"foo": value})
            c.apply("say foo now")     # must not raise


class TestDevanagariIsAWholeWord:
    """
    `output_script: "devanagari"` is a supported setting, so Devanagari has to
    survive this layer.

    Python's `re` does not count combining marks as word characters, and
    Devanagari writes most of its vowels with them. That broke both mechanisms in
    opposite directions, and both were measured before being fixed:

        _WORD_RE.findall("कल मीटिंग है")  ->  ['कल', 'म', 'ट', 'ग', 'ह']
        re.search(r"\\bहै\\b",  "कल मीटिंग है")  ->  False   (never matches)
        re.search(r"\\bमीट\\b", "कल मीटिंग है")  ->  True    (matches mid-word)

    So a Devanagari vocabulary entry could never match, and a Devanagari
    correction key could rewrite the middle of a longer word.
    """

    def test_a_word_ending_in_a_vowel_sign_can_be_matched(self):
        c = make(corrections={"है": "hai"})
        assert c.apply("कल मीटिंग है") == "कल मीटिंग hai"

    def test_a_key_does_not_match_inside_a_longer_word(self):
        c = make(corrections={"मीट": "MEAT"})
        assert c.apply("कल मीटिंग है") == "कल मीटिंग है", (
            "rewrote the middle of मीटिंग, which is the Devanagari form of the "
            "'cal' must not rewrite 'call' rule"
        )

    def test_a_whole_devanagari_word_is_replaced(self):
        c = make(corrections={"मीटिंग": "meeting"})
        assert c.apply("कल मीटिंग है") == "कल meeting है"

    def test_devanagari_vocabulary_leaves_a_correct_sentence_alone(self):
        c = make(vocabulary=["मीटिंग"])
        text = "कल मीटिंग है"
        assert c.apply(text) == text

    def test_latin_word_boundaries_still_hold(self):
        """The Devanagari fix must not loosen the Latin behaviour it replaced."""
        c = make(corrections={"cal": "call"})
        assert c.apply("cal me") == "call me"
        assert c.apply("i will call you") == "i will call you"
        assert c.apply("calendar is full") == "calendar is full"


class TestBadSettingsDegradeQuietly:
    """
    These are hand-edited JSON values. A wrong type must not cost a dictation:
    `corrections: []` used to raise AttributeError out of the pipeline.
    """

    @pytest.mark.parametrize("cfg", [
        {"corrections": []},
        {"corrections": "heard=meant"},
        {"vocabulary": "WhatsApp"},
        {"vocabulary": {"a": "b"}},
        {"corrections": None, "vocabulary": None},
    ])
    def test_a_wrong_type_is_ignored_rather_than_raised(self, cfg):
        text = "say something ordinary"
        assert Corrector(cfg).apply(text) == text


class TestAlreadyCorrectTextIsNotRematched:
    def test_a_multi_word_term_is_not_undone_by_a_shorter_one(self):
        """
        With both entries present, "Sharma ji" matched the two-word term, was
        found to be already correct, and was reported as no match - so the loop
        tried again with the one-word entry and rewrote it. "Not a term" and
        "already correct" have to be different answers.
        """
        c = make(vocabulary=["Sharma ji", "sharma"])
        assert c.apply("Sharma ji") == "Sharma ji"
