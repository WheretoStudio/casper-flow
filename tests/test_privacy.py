"""The privacy guarantee, tested rather than asserted in a README.

offline_only is the single promise the whole product rests on. These tests run
with no network available to them by construction: if a cloud path were ever
reached, the test would need an API key and would fail rather than quietly pass.
"""

import pytest

import llm_polish
import transcribe


class TestOfflineOnlyGate:
    """
    There are two independent reasons a cloud backend gets skipped: the privacy
    gate, and having no API key. A test that omits the key would pass because of
    the second one while proving nothing about the first, so these supply a fake
    key and then assert the cloud function was never reached.
    """

    @pytest.fixture
    def spy(self, monkeypatch):
        """Fake credentials for every backend, and tripwires on each cloud call."""
        called: list[str] = []
        monkeypatch.setattr(llm_polish, "api_key_for", lambda *a, **k: "sk-fake-key")
        for name in ("_openai", "_anthropic", "_groq", "_ollama"):
            monkeypatch.setattr(
                llm_polish, name,
                lambda text, cfg, _n=name: (called.append(_n), "LEAKED OFF MACHINE")[1],
            )
        return called

    BASE = {"llm_polish": True, "filler_words": ["um", "uh"]}

    @pytest.mark.parametrize("backend", ["openai", "anthropic", "groq"])
    def test_cloud_backend_is_never_called_even_with_a_key(self, spy, backend):
        cfg = {**self.BASE, "offline_only": True, "llm_backend": backend}
        out = llm_polish.polish("um so the report is uh ready", cfg)

        assert not spy, f"{backend} was called despite offline_only"
        assert out != "LEAKED OFF MACHINE"
        # The rules backend ran instead: fillers stripped, sentence capitalised.
        assert "um" not in out.lower().split()
        assert "uh" not in out.lower().split()

    def test_gate_defaults_to_on_when_the_key_is_absent(self, spy):
        """A config with no offline_only key must behave as if it were true."""
        cfg = {**self.BASE, "llm_backend": "openai"}
        out = llm_polish.polish("um the meeting is confirmed", cfg)
        assert not spy, "cloud backend was reached when offline_only was unset"
        assert out != "LEAKED OFF MACHINE"

    def test_ollama_is_allowed_because_it_is_localhost(self, spy):
        """
        The gate blocks what leaves the machine, not local inference. If Ollama
        were caught by it, the recommended local upgrade path would be dead.
        """
        cfg = {**self.BASE, "offline_only": True, "llm_backend": "ollama"}
        llm_polish.polish("um the report is ready", cfg)
        assert spy == ["_ollama"], "Ollama should run under offline_only"

    def test_cloud_backend_is_reachable_once_the_gate_is_turned_off(self, spy):
        """
        The inverse case. If this passed while the gate was on, the tests above
        would prove nothing.
        """
        cfg = {**self.BASE, "offline_only": False, "llm_backend": "openai"}
        llm_polish.polish("um the report is ready", cfg)
        assert spy == ["_openai"]

    def test_every_cloud_backend_is_covered_by_the_gate(self):
        """CLOUD_BACKENDS must list every backend that leaves the machine."""
        assert {"openai", "anthropic", "groq"} <= set(llm_polish.CLOUD_BACKENDS)
        # Ollama is localhost and rules is offline, so both are deliberately out.
        assert "ollama" not in llm_polish.CLOUD_BACKENDS
        assert "rules" not in llm_polish.CLOUD_BACKENDS


class TestPromptsAreWordListsEverywhere:
    """
    Any prompt our own tooling can write into settings.json must be a word list.

    tune_hinglish.py shipped with a sentence-shaped prompt containing
    "Aaj ka update ready hai kya?" - the exact string that was once pasted into
    a document during unrelated English dictation - and it offered to save that
    prompt. Accepting its recommendation reintroduced the bug it was meant to
    help diagnose.
    """

    @staticmethod
    def _looks_like_sentences(prompt: str) -> bool:
        # Sentence-enders are the giveaway. A single trailing full stop on a
        # comma-separated list is fine; question and exclamation marks are not,
        # and neither is a full stop in the middle of the text.
        if "?" in prompt or "!" in prompt:
            return True
        return "." in prompt.rstrip().rstrip(".")

    def test_the_shipped_default_prompt_is_a_word_list(self):
        import config
        prompt = config.DEFAULTS["initial_prompt"]
        assert prompt, "no default prompt to check"
        assert not self._looks_like_sentences(prompt), (
            f"config.DEFAULTS initial_prompt looks sentence-shaped: {prompt!r}"
        )

    def test_the_tuning_tool_writes_a_word_list(self):
        import tune_hinglish
        prompt = tune_hinglish.WORD_LIST_PROMPT
        assert not self._looks_like_sentences(prompt), (
            f"tune_hinglish would save a sentence-shaped prompt: {prompt!r}"
        )

    def test_the_tuning_tool_does_not_keep_its_own_copy_of_the_prompt(self):
        """
        Two copies drift. The tool must use the app's prompt, not a duplicate.
        """
        import config
        import tune_hinglish
        assert tune_hinglish.WORD_LIST_PROMPT == config.DEFAULTS["initial_prompt"]

    def test_a_sentence_prompt_would_be_caught(self):
        """The detector has to actually fire, or the tests above prove nothing."""
        assert self._looks_like_sentences(
            "Kal ek meeting hai. Aaj ka update ready hai kya?"
        )


class TestPromptLeakGuard:
    """
    Whisper can continue initial_prompt as though it were speech, which pastes
    words the user never said. This happened for real: a prompt sentence was
    pasted into a document during unrelated English dictation.
    """

    PROMPT = ("Hinglish: kal, aaj, abhi, thoda, matlab, theek hai, meeting, "
              "report, bhej dena, kar dena, ho gaya, chahiye, office, update, client.")

    def test_detects_a_transcript_made_of_prompt_vocabulary(self):
        assert transcribe.leaked_prompt("kal aaj abhi thoda matlab", self.PROMPT)

    def test_detects_a_short_run_of_the_prompt_in_prompt_order(self):
        """Three prompt words in the prompt's own order, and nothing else."""
        assert transcribe.leaked_prompt("kal aaj abhi", self.PROMPT)

    @pytest.mark.parametrize("said", [
        # Every one of these is ordinary Hinglish office speech, and every one
        # was flagged as a leak by the vocabulary-overlap version of this guard.
        # A flagged transcript is discarded and nothing is pasted, so these were
        # silently lost dictations.
        "theek hai",
        "aaj office meeting hai",
        "update chahiye aaj",
        "abhi thoda kaam hai matlab meeting kal",
        "office ka update client ko bhej dena",
    ])
    def test_does_not_flag_ordinary_speech_built_from_prompt_words(self, said):
        """
        The prompt is a list of the commonest Hinglish words, so real speech is
        *made of* prompt vocabulary. Only the prompt's word order is evidence of
        a leak; shared vocabulary is evidence of the prompt working.
        """
        assert not transcribe.leaked_prompt(said, self.PROMPT)

    def test_the_guard_does_not_get_stricter_as_vocabulary_grows(self):
        """
        Adding your colleagues' names to the prompt must not start discarding
        your dictations. The overlap version got stricter with every word added,
        which is backwards.
        """
        said = "aaj office meeting hai"
        bigger = self.PROMPT + (" Priya, Rahul, Bangalore, Koramangala, "
                                "standup, sprint, retro, deployment.")
        assert not transcribe.leaked_prompt(said, bigger)

    def test_allows_genuine_speech_that_shares_some_words(self):
        real = "can you send me the report by tomorrow morning please"
        assert not transcribe.leaked_prompt(real, self.PROMPT)

    def test_allows_genuine_hinglish_using_prompt_words_naturally(self):
        # The prompt primes this vocabulary, so real speech will contain it.
        # Flagging that as a leak would break the feature it protects.
        real = "kal team ke saath ek naya design review schedule kar lete hain"
        assert not transcribe.leaked_prompt(real, self.PROMPT)

    def test_no_prompt_means_no_leak(self):
        assert not transcribe.leaked_prompt("anything at all", "")

    def test_empty_transcript_is_not_a_leak(self):
        assert not transcribe.leaked_prompt("", self.PROMPT)
