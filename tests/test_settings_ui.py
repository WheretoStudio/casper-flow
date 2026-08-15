"""The settings window.

Widget layout is not worth asserting. What is worth asserting is the logic that
can silently do the wrong thing: turning what the user picked into config values,
and not writing something that contradicts itself.

The window is constructed and destroyed without entering the event loop, so these
run headless-ish - they still need a Windows desktop for Tk, so they skip
elsewhere.
"""

import json
import sys

import pytest

from conftest import needs_desktop

pytest.importorskip("tkinter")

import settings_ui                                    # noqa: E402
from settings_ui import OVERLAY_STYLES, PROFILES      # noqa: E402


class TestProfilesAreHonest:
    """
    The window shows accuracy and latency next to each choice. Those numbers are
    measured, and if a model is renamed the label must not silently drift from it.
    """

    def test_every_profile_names_a_real_model(self):
        import transcribe
        for p in PROFILES:
            assert p["id"], "a profile with no model id"
            # Either resolvable locally or a plausible HuggingFace / size name.
            assert transcribe.resolve_model(p["id"])

    def test_every_profile_states_what_it_costs(self):
        for p in PROFILES:
            detail = p["detail"].lower()
            assert "%" in detail, f"{p['id']} does not state its accuracy"
            assert "s" in detail, f"{p['id']} does not state its speed"

    def test_no_profile_leaks_jargon_into_the_label(self):
        """A non-coder should never be shown int8 or a model filename."""
        banned = ("int8", "float16", "ct2", "whisper", "beam", "quantis")
        for p in PROFILES:
            label = p["label"].lower()
            for word in banned:
                assert word not in label, f"{p['label']!r} contains {word!r}"

    def test_the_hinglish_profile_is_the_default_model(self):
        import config
        assert PROFILES[0]["id"] == config.DEFAULTS["whisper_model"]


class TestOverlayChoices:
    def test_blob_is_offered_first(self):
        """It is the default, so it should be the first thing offered."""
        assert OVERLAY_STYLES[0][0] == "blob"

    def test_blob_is_described_as_having_no_text(self):
        detail = OVERLAY_STYLES[0][2].lower()
        assert "no text" in detail

    def test_the_caption_style_warns_about_the_extra_download(self):
        caption = next(s for s in OVERLAY_STYLES if s[0] == "caption")
        assert "download" in caption[2].lower(), (
            "captions need a model that is not bundled, and the user should be "
            "told before choosing it"
        )


@needs_desktop
class TestCollect:
    """What the window writes, given what the user chose."""

    # One window for the whole class. Creating a second Tk root in the same
    # process after destroying the first fails with "invalid command name
    # tcl_findLibrary", and these tests only exercise _collect(), which is pure -
    # it reads the widgets and returns a dict without writing anything.
    @pytest.fixture(scope="class")
    def win(self, tk_root):
        w = settings_ui.SettingsWindow(master=tk_root)
        yield w
        w.root.destroy()      # a Toplevel, so this is safe

    def test_previews_are_off_unless_captions_are_chosen(self, win):
        """
        The blob and capsule draw from microphone level. Leaving previews on would
        transcribe repeatedly and display none of it.
        """
        for style in ("blob", "capsule"):
            win._vars["pill_style"].set(style)
            assert win._collect()["live_preview"] is False, style

        win._vars["pill_style"].set("caption")
        assert win._collect()["live_preview"] is True

    def test_choosing_a_profile_sets_model_and_language_together(self, win):
        win._profile.set("base.en")
        out = win._collect()
        assert out["whisper_model"] == "base.en"
        assert out["language"] == "en", (
            "language must move with the model, or a profile change leaves an "
            "inconsistent pair"
        )

    def test_vocabulary_is_split_into_lines_and_stripped(self, win):
        win._vocab.delete("1.0", "end")
        win._vocab.insert("1.0", "WhatsApp\n  Gmail  \n\n\nBangalore\n")
        assert win._collect()["vocabulary"] == ["WhatsApp", "Gmail", "Bangalore"]

    def test_corrections_parse_the_heard_equals_meant_form(self, win):
        win._fixes.delete("1.0", "end")
        win._fixes.insert("1.0", "thank you office = Bangalore office\n"
                                 "envoys = invoice\n"
                                 "rubbish line with no equals\n")
        fixes = win._collect()["corrections"]
        assert fixes == {"thank you office": "Bangalore office",
                         "envoys": "invoice"}

    def test_a_position_label_maps_back_to_its_config_value(self, win):
        win._position_box.set("Top centre")
        assert win._collect()["pill_position"] == "top-center"

    def test_numbers_are_saved_as_numbers_not_strings(self, win):
        win._vars["min_hold_seconds"].set(1.5)
        out = win._collect()
        assert isinstance(out["min_hold_seconds"], float)
        assert out["min_hold_seconds"] == 1.5

    def test_collect_only_produces_known_settings(self, win):
        import config
        unknown = sorted(set(win._collect()) - set(config.DEFAULTS))
        assert not unknown, f"window would write unknown keys: {unknown}"

    def test_the_displayed_hotkey_is_included_in_what_save_would_write(self, win):
        """Closing without this key in _vars used to leave the old hotkey on disk."""
        out = win._collect()
        assert "hotkey" in out
        assert out["hotkey"]
