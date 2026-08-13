"""First-run setup.

The point of the wizard is that each step leaves something *verified*, so the
tests worth writing are about the gates: can a user reach the end without the
microphone having been heard, without a usable key, or without one successful
dictation.

Widget appearance is not asserted. Gating and persistence are.
"""

import json

import pytest

from conftest import needs_desktop

pytest.importorskip("tkinter")

import config                       # noqa: E402
import wizard                       # noqa: E402


class TestNeedsSetup:
    def test_a_fresh_config_needs_setup(self):
        assert wizard.needs_setup({}) is True

    def test_an_explicit_false_needs_setup(self):
        assert wizard.needs_setup({"setup_complete": False}) is True

    def test_a_completed_config_does_not(self):
        assert wizard.needs_setup({"setup_complete": True}) is False

    def test_setup_complete_is_a_known_setting(self):
        """Otherwise save_config would silently drop it and setup would reappear."""
        assert "setup_complete" in config.DEFAULTS

    def test_it_ships_incomplete(self):
        assert config.DEFAULTS["setup_complete"] is False


@needs_desktop
class TestGating:
    # One Tk root for the class: a second root in the same process is unreliable
    # once the first has been destroyed.
    @pytest.fixture(scope="class")
    def wiz(self, tk_root):
        w = wizard.Wizard(cfg=dict(config.DEFAULTS), master=tk_root)
        yield w
        w._close_meter()
        w.root.destroy()      # a Toplevel, so this is safe

    def test_the_microphone_step_starts_unverified(self, wiz):
        assert wiz.verified["mic"] is False, (
            "a user must not be able to continue past the microphone step until "
            "the level meter has actually moved"
        )

    def test_the_practice_step_starts_unverified(self, wiz):
        assert wiz.verified["practice"] is False, (
            "nobody should reach the end without one successful dictation"
        )

    def test_the_hotkey_step_starts_satisfied(self, wiz):
        """The shipped default is already a working key, so this is not a blocker."""
        assert wiz.verified["hotkey"] is True

    def test_every_step_has_a_gate(self, wiz):
        assert set(wiz.verified) == set(wiz.STEPS)

    def test_the_steps_are_in_the_documented_order(self, wiz):
        assert wiz.STEPS == ("mic", "hotkey", "profile", "practice")

    def test_giving_up_on_practice_is_explicit_and_points_somewhere(self, wiz):
        """
        A user whose microphone is broken must be able to finish, but must be told
        where to look rather than left with a dead wizard.
        """
        wiz.step = wiz.STEPS.index("practice")
        wiz._show()
        assert wiz.verified["practice"] is False
        wiz._practice_giveup()
        assert wiz.verified["practice"] is True
        assert "Diagnostics" in wiz.practice_status.cget("text")

    def test_choosing_a_profile_sets_model_and_language_together(self, wiz):
        wiz.step = wiz.STEPS.index("profile")
        wiz._show()
        wiz.profile_var.set("base.en")
        wiz._pick_profile()
        assert wiz.result["whisper_model"] == "base.en"
        assert wiz.result["language"] == "en"

    def test_only_known_settings_are_persisted(self, wiz, tmp_path, monkeypatch):
        """save_config drops unknown keys, so an unknown one would vanish."""
        written = {}
        monkeypatch.setattr(wizard, "save_config",
                            lambda cfg: written.update(cfg))
        wiz.result = {"hotkey": "right ctrl", "whisper_model": "base.en"}
        assert wiz._persist(True) is True
        assert written["setup_complete"] is True
        unknown = sorted(set(wiz.result) - set(config.DEFAULTS))
        assert not unknown, f"wizard would write unknown keys: {unknown}"


class TestPracticeUsesTheRealPipeline:
    """
    Documents the design decision, so a later refactor does not quietly replace it
    with a simulated success - which would tell the user something untrue.
    """

    def test_the_wizard_does_not_fake_a_transcript(self):
        source = (wizard.__file__).replace(".pyc", ".py")
        with open(source, encoding="utf-8") as fh:
            text = fh.read()
        # The practice step must observe the text box, not write into it.
        assert "_watch_practice" in text
        assert "self.practice.insert" not in text, (
            "the practice step must not put text in the box itself; the whole "
            "point is that a real dictation lands there"
        )
