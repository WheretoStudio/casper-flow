"""Config loading and validation.

A dictation tool reads its settings from a hand-editable JSON file, so a bad
value has to degrade to the default with a log line rather than crash on the
hotkey press.
"""

import json

import pytest

import config


class TestRangeValidation:
    @pytest.mark.parametrize("value", [-1, 999, 11])
    def test_out_of_range_min_hold_falls_back(self, value, tmp_path, monkeypatch):
        cfg = self._load({"min_hold_seconds": value}, tmp_path, monkeypatch)
        assert cfg["min_hold_seconds"] == config.DEFAULTS["min_hold_seconds"]

    @pytest.mark.parametrize("value", [0, 0.4, 2.0, 10])
    def test_in_range_min_hold_is_kept(self, value, tmp_path, monkeypatch):
        cfg = self._load({"min_hold_seconds": value}, tmp_path, monkeypatch)
        assert cfg["min_hold_seconds"] == pytest.approx(float(value))

    def test_absurd_sample_rate_falls_back(self, tmp_path, monkeypatch):
        cfg = self._load({"sample_rate": 3}, tmp_path, monkeypatch)
        assert cfg["sample_rate"] == config.DEFAULTS["sample_rate"]

    def test_unknown_transcribe_backend_falls_back_to_local(self, tmp_path, monkeypatch):
        cfg = self._load({"transcribe_backend": "nonsense"}, tmp_path, monkeypatch)
        assert cfg["transcribe_backend"] == "local"

    @staticmethod
    def _load(overrides: dict, tmp_path, monkeypatch) -> dict:
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps(overrides), encoding="utf-8")
        monkeypatch.setattr(config, "SETTINGS_FILE", settings)
        monkeypatch.setattr(config, "ENV_FILE", tmp_path / ".env")
        return config.load_config()


class TestShippedDefaults:
    """
    The shipped settings.json is what a new user gets, so its values are part of
    the product rather than an example file.
    """

    @pytest.fixture
    def shipped(self, repo_root) -> dict:
        return json.loads((repo_root / "settings.json").read_text(encoding="utf-8"))

    def test_privacy_gate_ships_enabled(self, shipped):
        assert shipped["offline_only"] is True

    def test_transcription_ships_local(self, shipped):
        assert shipped["transcribe_backend"] == "local"

    def test_cleanup_ships_deterministic(self, shipped):
        """
        'rules' cannot invent a word. An LLM can, and during development one
        echoed its own prompt into a document as though it had been dictated.
        """
        assert shipped["llm_backend"] == "rules"

    def test_language_is_pinned_because_detection_is_the_slowest_step(self, shipped):
        """
        This assertion used to require `null`, on the reasoning that pinning a
        language mangles code-mixed speech - which is true of a general-purpose
        model, where pinning 'hi' produced Tamil script.

        Measured on the corpus with the shipped Hinglish model, pinning 'en' is
        accuracy-identical to auto-detection in all seven categories and 46%
        faster, because detection was concluding 'en' every time. See
        corpus/RESULTS.md.
        """
        assert shipped["language"] == "en"

    def test_the_shipped_model_is_the_one_measured_best_for_hinglish(self, shipped):
        """
        Swift scores 81.0% on code-switching against base's 20.5%, and base
        cannot transcribe Hindi at all (100% WER). A `.en` model would be worse
        still - it has no Hindi.
        """
        assert not shipped["whisper_model"].endswith(".en")
        assert shipped["whisper_model"] == "swift-ct2"

    def test_no_prompt_is_shipped(self, shipped):
        """
        With a model actually trained on Hinglish the prompt cost accuracy on
        code-switching and 39% latency, and it is what caused the prompt-leak bug.
        """
        assert shipped["initial_prompt"] is None

    def test_initial_prompt_is_a_word_list_not_sentences(self, shipped):
        """
        Sentences in initial_prompt get parroted back as if dictated. A
        comma-separated word list primes vocabulary without giving Whisper a
        sentence to continue.
        """
        prompt = shipped.get("initial_prompt") or ""
        if not prompt:
            pytest.skip("no initial_prompt configured")
        # No sentence-ending punctuation except the single trailing full stop.
        assert "?" not in prompt, "question marks mean sentences, which get parroted"
        assert "!" not in prompt
        assert prompt.count(",") >= 5, "expected a comma-separated vocabulary list"

    def test_every_shipped_key_is_a_known_setting(self, shipped):
        """A typo in settings.json should not silently do nothing."""
        unknown = sorted(set(shipped) - set(config.DEFAULTS))
        assert not unknown, f"settings.json has keys config.py does not know: {unknown}"
