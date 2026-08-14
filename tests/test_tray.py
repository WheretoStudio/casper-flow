"""Tray status lines. Layout is not asserted; lying about a running backend is."""

from tray import polish_menu_label


class TestPolishMenuLabel:
    def test_rules_is_not_reported_as_skipped(self):
        assert polish_menu_label({"llm_polish": True, "llm_backend": "rules"}) \
            == "built-in cleanup"

    def test_polish_off(self):
        assert polish_menu_label({"llm_polish": False, "llm_backend": "rules"}) \
            == "off"

    def test_cloud_without_a_key_is_skipped(self):
        label = polish_menu_label({
            "llm_polish": True,
            "llm_backend": "openai",
            "openai_api_key": "",
        })
        assert "skipped" in label
        assert "openai" in label

    def test_cloud_with_a_key_names_the_backend(self):
        assert polish_menu_label({
            "llm_polish": True,
            "llm_backend": "openai",
            "openai_api_key": "sk-test",
        }) == "openai"

    def test_ollama_does_not_need_a_key(self):
        assert polish_menu_label({
            "llm_polish": True,
            "llm_backend": "ollama",
        }) == "ollama"
