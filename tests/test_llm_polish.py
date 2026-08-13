"""
The cleanup and formatting step.

`rules` is the default backend and runs on every dictation, including as the
fallback whenever a language model fails or is rejected. So almost every character
this app ever pastes has been through `_rules`, which makes a bug here a bug in
essentially all output.

The guards are tested against what a real 3B model actually did, not against
imagined misbehaviour. Every threshold in llm_polish.py exists because a measured
failure got past the guard before it.
"""

import time

import pytest

from config import DEFAULTS
from llm_polish import (
    _call_with_deadline,
    _collapse_repeated_clause,
    _content_retained,
    _digit_bag,
    _is_loopback,
    _model_for,
    _numbers_survived,
    _rules,
    _sanitise,
    polish,
)


def cfg(**over) -> dict:
    return {**DEFAULTS, **over}


class TestSpokenPunctuationDoesNotEatRealWords:
    """
    The worst class of bug this module can have: silently deleting a word the user
    said, in the default backend, with no error and nothing on screen.

    Measured before the context check existed:

        "the grace period ended"    -> "The grace. Ended."
        "put a comma there please"  -> "Put a, there please."

    "period" is absent from the table entirely and deliberately. No context rule
    saves it - the words in front of it are ordinary nouns in "notice period",
    "grace period", "trial period" - and "notice period" is everyday office speech
    in the market this is built for. Indian English says "full stop" for the mark.
    """

    @pytest.mark.parametrize("said", [
        "the grace period ended",
        "my notice period is two months",
        "during that period we hired twenty five people",
        "the trial period is over",
        "put a comma there please",
        "add a comma after that",
        "the question mark is missing",
        "send me a comma separated list",
        "without a full stop it looks wrong",
        "check this colon please",
        "use a semicolon in that line",
    ])
    def test_ordinary_speech_survives_unchanged(self, said):
        out = _rules(said, cfg())
        for mark in (".", ",", ":", ";", "?", "!"):
            # A single terminal full stop is the one mark _rules is allowed to add.
            assert out.count(mark) <= (1 if mark == "." else 0), (
                f"{said!r} -> {out!r}: a spoken-punctuation word was substituted "
                f"where the user was talking about the mark, not asking for one"
            )
        # Every word the user said is still there.
        assert len(out.split()) == len(said.split()), f"{said!r} -> {out!r}"

    @pytest.mark.parametrize("said,expected", [
        ("send the report comma and then the deck",
         "Send the report, and then the deck."),
        ("are you coming question mark", "Are you coming?"),
        ("that is done full stop", "That is done."),
        ("note colon buy milk", "Note: buy milk."),
        ("great work exclamation mark", "Great work!"),
        ("hello new line how are you", "Hello\nHow are you."),
        ("first para new paragraph second para", "First para\n\nSecond para."),
    ])
    def test_real_commands_still_work(self, said, expected):
        assert _rules(said, cfg()) == expected


class TestRulesCleanup:
    def test_fillers_are_removed(self):
        assert _rules("um so basically uh yeh wala better hai", cfg()) == (
            "So basically yeh wala better hai.")

    def test_immediate_duplicates_collapse(self):
        assert _rules("send the the report", cfg()) == "Send the report."

    def test_hinglish_intensifiers_keep_their_repetition(self):
        assert _rules("bahut bahut dhanyavad", cfg()) == "Bahut bahut dhanyavad."

    def test_standalone_i_is_capitalised(self):
        assert _rules("i will send i think", cfg()) == "I will send I think."

    def test_a_bullet_list_does_not_get_a_trailing_full_stop(self):
        """"- two." reads as a typo rather than as punctuation."""
        assert _rules("- one\n- two", cfg()) == "- one\n- two"
        assert _rules("1. alpha\n2. beta", cfg()) == "1. Alpha\n2. Beta"

    def test_a_sentence_does_get_one(self):
        assert _rules("just a sentence", cfg()) == "Just a sentence."

    def test_empty_input_is_safe(self):
        assert _rules("", cfg()) == ""
        assert _rules("   ", cfg()) == ""

    def test_a_string_filler_setting_cannot_shred_the_text(self):
        """
        `filler_words: "um"` is an easy hand-edit. Iterating a string would build
        an alternation of single letters and delete them as whole words.
        """
        said = "um I am a good person"
        out = _rules(said, cfg(filler_words="um"))
        assert "I am a good person" in out


class TestGuardsRejectMisbehaviour:
    """
    `_sanitise` compares a model's output against the deterministic cleanup and
    returns the cleanup when the output is not plausible. Every case here is
    something a real 3B model produced.
    """

    def test_a_chatty_preamble_is_stripped(self):
        raw = "kal meeting hai"
        out = "Here is the cleaned text:\nKal meeting hai."
        assert _sanitise(out, raw, cfg()) == "Kal meeting hai."

    def test_padding_is_rejected(self):
        raw = "kal meeting hai"
        out = ("Kal meeting hai. " + "I hope this helps and please let me know "
               "if you would like me to adjust anything at all further. " * 4)
        assert _sanitise(out, raw, cfg()) == raw

    def test_summarising_is_rejected(self):
        """
        The old guard only looked for output that was too long, so a model that
        compressed five sentences into one passed silently.
        """
        raw = ("pehle budget discuss karna hai phir timeline dekhna hai aur "
               "uske baad resource allocation finalise karna hai aur team ko "
               "batana hai")
        assert _sanitise("Discuss budget.", raw, cfg()) == raw

    def test_a_dropped_number_is_rejected(self):
        raw = "mera number hai 9876543210"
        assert _sanitise("Mera number hai.", raw, cfg()) == raw

    def test_turning_words_into_digits_is_allowed(self):
        """
        The number guard allows extra digits on purpose. The retention guard used
        to reject this anyway: one content word of three survives, which scores as
        67% invented. Retention is now skipped below a floor of content words,
        because a ratio over three words is noise.
        """
        raw = "twenty five people"
        out = "25 people."
        assert _sanitise(out, raw, cfg()) == out

    @pytest.mark.parametrize("raw,out", [
        # Short transcripts, invented output. These must still be rejected, by the
        # novelty guard rather than by retention, or skipping retention on short
        # input would have opened a hole.
        ("budget timeline signoff",
         "Shaam ko sahi kaam karne ke liye dhanyavad."),
        ("twenty five people", "Please find the attached quarterly report."),
        ("kal meeting hai", "Thank you for reaching out about the invoice."),
    ])
    def test_short_transcripts_are_still_protected_from_invention(self, raw, out):
        assert _sanitise(out, raw, cfg()) == raw, (
            "invented text passed on a short transcript; the retention floor "
            "must not be a hole"
        )

    def test_invented_content_is_rejected(self):
        """
        Measured: asked to bullet a three-item list, a 3B model returned two empty
        bullets and a sentence of Hindi the speaker never said. Plausible length,
        no digits to lose, not a summary - every other guard passed it.
        """
        raw = ("first we need the budget second the timeline and third the "
               "sign off")
        out = "- first\n- second\n- shaam ko sahi kaam karne ke liye dhanyavad"
        assert _sanitise(out, raw, cfg()) == raw

    def test_empty_output_falls_back(self):
        raw = "kal meeting hai"
        assert _sanitise("", raw, cfg()) == raw
        assert _sanitise("   \n ", raw, cfg()) == raw

    def test_a_faithful_rewrite_is_accepted(self):
        raw = "kal ko meeting hai client ke saath report bhejna hai"
        out = ("Kal meeting hai client ke saath, aur report bhejna hai.")
        assert _sanitise(out, raw, cfg()) == out


class TestNumberGuard:
    def test_every_digit_must_survive(self):
        assert _numbers_survived("call 9876543210", "call 9876543210")
        assert not _numbers_survived("call me", "call 9876543210")

    def test_digit_bag_is_order_independent(self):
        assert _digit_bag("1 2 3") == _digit_bag("3 2 1")


class TestContentRetention:
    def test_identical_text_retains_everything(self):
        raw = "budget timeline resource allocation"
        assert _content_retained(raw, raw) == 1.0

    def test_unrelated_text_retains_nothing(self):
        assert _content_retained("completely different words here",
                                 "budget timeline resource") == 0.0


class TestPrivacyGate:
    """
    `offline_only` is the product's central promise. It has to hold for every
    backend that can reach the network, which includes a misconfigured Ollama.
    """

    @pytest.mark.parametrize("url,loopback", [
        ("http://localhost:11434", True),
        ("http://127.0.0.1:11434", True),
        ("http://127.1.2.3:11434", True),
        ("http://[::1]:11434", True),
        ("http://192.168.1.50:11434", False),
        ("http://ollama.example.com", False),
        ("not a url", False),
        ("", False),
    ])
    def test_loopback_detection(self, url, loopback):
        assert _is_loopback(url) is loopback

    def test_a_remote_ollama_is_refused_under_offline_only(self):
        """
        The backend name was on the allow-list while ollama_url was never checked,
        so one settings line sent every transcript to another machine with
        offline_only still reading as on.
        """
        out = polish("hello there", cfg(llm_backend="ollama", offline_only=True,
                                        ollama_url="http://192.168.1.50:11434"))
        assert out == "Hello there.", "did not fall back to the local rules"

    def test_an_absent_url_means_the_documented_default(self):
        c = cfg(llm_backend="ollama", offline_only=True)
        c.pop("ollama_url", None)
        assert _is_loopback(c.get("ollama_url") or DEFAULTS["ollama_url"])

    @pytest.mark.parametrize("backend", ["openai", "anthropic", "groq"])
    def test_cloud_backends_are_refused_under_offline_only(self, backend):
        out = polish("hello there", cfg(llm_backend=backend, offline_only=True))
        assert out == "Hello there."


class TestBackendModelSelection:
    """
    Each backend used to carry an inline default that could never fire, because
    config.DEFAULTS always supplies llm_model. Switching backend without also
    editing the model sent an OpenAI id to the wrong vendor, got a 404, and fell
    back silently while the tray still showed the backend as active.
    """

    @pytest.mark.parametrize("backend,expected", [
        ("openai", "gpt-4o-mini"),
        ("anthropic", "claude-haiku-4-5"),
        ("groq", "openai/gpt-oss-20b"),
    ])
    def test_the_shipped_default_maps_to_each_vendor(self, backend, expected):
        assert _model_for(backend, cfg()) == expected

    @pytest.mark.parametrize("backend", ["openai", "anthropic", "groq"])
    def test_a_model_the_user_chose_is_passed_through(self, backend):
        assert _model_for(backend, cfg(llm_model="my/model")) == "my/model"


class TestTimeoutIsAHardCeiling:
    """
    llm_timeout_seconds documents itself as a hard ceiling - "if it takes longer we
    paste raw text rather than leaving you staring at a dead cursor". No backend
    could honour that alone: the HTTP clients applied it per attempt and requests
    applies it per socket operation.
    """

    def test_a_backend_that_never_answers_gives_up(self):
        def never(_text, _cfg):
            time.sleep(30)
            return "never"

        t0 = time.monotonic()
        with pytest.raises(TimeoutError):
            _call_with_deadline(never, "x", {"llm_timeout_seconds": 1})
        assert time.monotonic() - t0 < 5, "waited far past the configured ceiling"

    def test_an_exception_is_re_raised_for_the_caller_to_handle(self):
        def boom(_text, _cfg):
            raise RuntimeError("backend exploded")

        with pytest.raises(RuntimeError, match="exploded"):
            _call_with_deadline(boom, "x", {"llm_timeout_seconds": 5})

    def test_a_prompt_answer_is_returned(self):
        assert _call_with_deadline(lambda t, c: "done", "x",
                                   {"llm_timeout_seconds": 5}) == "done"


class TestPolishNeverLosesTheDictation:
    """
    The module's stated design rule. Every failure path must still paste the
    deterministic cleanup of the same transcript.
    """

    def test_a_failing_backend_falls_back_to_cleanup(self, monkeypatch):
        import llm_polish

        def broken(_text, _cfg):
            raise RuntimeError("no")

        monkeypatch.setattr(llm_polish, "_ollama", broken)
        out = polish("um kal meeting hai", cfg(llm_backend="ollama",
                                               offline_only=False))
        assert out == "Kal meeting hai."

    def test_an_unknown_backend_falls_back_to_cleanup(self):
        assert polish("um kal meeting hai",
                      cfg(llm_backend="nonsense")) == "Kal meeting hai."

    def test_blank_input_is_returned_untouched(self):
        assert polish("", cfg()) == ""
        assert polish("   ", cfg()) == "   "


class TestRepeatedClauseCollapse:
    """
    Whisper sometimes transcribes the same phrase twice inside one segment, and its
    own guards do not catch it - on the corpus recordings where this happens,
    compression_ratio is 1.07-1.36 against the 2.4 threshold and avg_logprob is
    -0.11 to -0.19, so the model is confident about the wrong answer.

    The second half of this class matters more than the first. Deleting words the
    user actually said is worse than leaving a visible duplicate, and Hinglish
    repeats words for emphasis routinely.
    """

    def test_an_exact_repeated_clause_is_collapsed(self):
        said = "kal ham kal discuss kar sakte hain kal ham kal discuss kar sakte hain"
        assert _collapse_repeated_clause(said) == "kal ham kal discuss kar sakte hain"

    def test_three_copies_collapse_to_one(self):
        one = "please send me the report before the review"
        assert _collapse_repeated_clause(" ".join([one] * 3)) == one

    def test_punctuation_and_case_do_not_hide_a_repeat(self):
        said = "Sharma ji call karenge please. sharma ji call karenge please"
        assert _collapse_repeated_clause(said) == "sharma ji call karenge please"

    @pytest.mark.parametrize("text", [
        # Deliberate repetition. Every one of these is something a person says.
        "haan haan theek hai",
        "kar do kar do",
        "bahut bahut dhanyavad",
        "very very good",
        "no no no no",
        "chalo chalo",
        # Ordinary sentences with an incidental word in common.
        "kal ek meeting hai client ke saath please report bhej dena",
        "the deposition is scheduled for Thursday morning",
        "please send me the quarterly report before the review",
        "I will follow up with the vendor later today",
        # A restatement that is not word-identical must survive intact.
        "budget discuss karna hai phir timeline discuss karna hoga",
    ])
    def test_real_speech_is_never_altered(self, text):
        assert _collapse_repeated_clause(text) == text

    def test_no_reference_transcript_in_the_corpus_is_altered(self, repo_root):
        """
        The strongest available check that this cannot damage good text: run it over
        every phrase a real speaker was recorded saying.
        """
        import json
        phrases = json.loads(
            (repo_root / "corpus" / "phrases.json").read_text(encoding="utf-8")
        )["phrases"]
        altered = [p["id"] for p in phrases
                   if _collapse_repeated_clause(p["text"]) != p["text"]]
        assert not altered, f"altered correct transcripts: {altered}"

    def test_a_short_repeat_is_below_the_floor(self):
        """Three words is too few - see _REPEAT_MIN_WORDS."""
        said = "kar do kar do"
        assert _collapse_repeated_clause(said) == said
