"""How a configured model name becomes something loadable.

A model can arrive by three routes - a bare Whisper size, a directory under
models/ converted locally, or a full HuggingFace "owner/name" id - and all three
have to work for the same `whisper_model` setting.
"""

from pathlib import Path

import pytest

import transcribe


class TestResolveModel:
    def test_bare_size_is_passed_through(self):
        """faster-whisper maps 'base' to a Systran repo itself."""
        assert transcribe.resolve_model("base") == "base"

    def test_hf_repo_id_is_passed_through(self):
        """
        Anything containing a slash is a HuggingFace id to faster-whisper, so it
        must reach it unchanged. This is what makes publishing a converted model
        need no code at all.
        """
        repo = "wheretostudio/whisper-hinglish-swift-ct2"
        assert transcribe.resolve_model(repo) == repo

    def test_local_directory_resolves_to_an_absolute_path(self, tmp_path, monkeypatch):
        model = tmp_path / "my-model"
        model.mkdir()
        (model / "model.bin").write_bytes(b"not a real model")
        monkeypatch.setattr(transcribe, "MODELS_DIR", tmp_path)

        resolved = transcribe.resolve_model("my-model")
        assert Path(resolved).is_absolute(), (
            "a relative path would depend on the working directory, and the app "
            "is launched from a shortcut, a .bat and a scheduled task"
        )
        assert Path(resolved) == model.resolve()

    def test_directory_without_weights_is_not_treated_as_local(self, tmp_path, monkeypatch):
        """An interrupted download leaves a directory with no model.bin."""
        (tmp_path / "half-downloaded").mkdir()
        monkeypatch.setattr(transcribe, "MODELS_DIR", tmp_path)
        assert transcribe.resolve_model("half-downloaded") == "half-downloaded"

    def test_empty_name_is_harmless(self):
        assert transcribe.resolve_model("") == ""


class TestFallbackCandidates:
    """
    If the configured model cannot load, the app falls back to one that is
    already present rather than failing every dictation.
    """

    def test_local_conversions_are_visible(self, tmp_path, monkeypatch):
        for name in ("swift-ct2", "something-else"):
            d = tmp_path / name
            d.mkdir()
            (d / "model.bin").write_bytes(b"x")
        monkeypatch.setattr(transcribe, "MODELS_DIR", tmp_path)

        found = transcribe._cached_models()
        assert "swift-ct2" in found, (
            "a locally converted model was invisible to the fallback, so a user "
            "whose only complete model is a purpose-built one would be told "
            "nothing is available"
        )
        assert "something-else" in found

    def test_incomplete_local_dirs_are_ignored(self, tmp_path, monkeypatch):
        (tmp_path / "empty").mkdir()
        monkeypatch.setattr(transcribe, "MODELS_DIR", tmp_path)
        assert "empty" not in transcribe._cached_models()

    def test_missing_models_dir_is_not_an_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(transcribe, "MODELS_DIR", tmp_path / "nope")
        transcribe._cached_models()      # must not raise

    def test_known_sizes_come_before_local_conversions(self, tmp_path, monkeypatch):
        """
        A fallback should load fast rather than be accurate, and the bare sizes
        have predictable cost.
        """
        d = tmp_path / "zzz-local"
        d.mkdir()
        (d / "model.bin").write_bytes(b"x")
        monkeypatch.setattr(transcribe, "MODELS_DIR", tmp_path)

        found = transcribe._cached_models()
        if not any(m in found for m in ("tiny", "base", "small")):
            pytest.skip("no standard models cached on this machine")
        first_local = found.index("zzz-local")
        assert any(found.index(m) < first_local
                   for m in ("tiny", "tiny.en", "base", "base.en", "small")
                   if m in found)


class TestTheLockFileDescribesWhatIsOnDisk:
    """
    models/MODELS.lock.json is what makes the published accuracy figures
    checkable. Every number in Settings, in the installer and on the website is a
    cell in corpus/RESULTS.md, measured against specific files; the lock file
    records a SHA-256 and a size for each of them.

    The weights themselves are 219 MB and are not in git, so this tests the
    fingerprint machinery rather than the weights.
    """

    @pytest.fixture
    def lock(self, repo_root):
        import json
        path = repo_root / "models" / "MODELS.lock.json"
        if not path.is_file():
            pytest.skip("models/MODELS.lock.json absent; run fetch_models.py")
        return json.loads(path.read_text(encoding="utf-8"))

    def test_both_bundled_models_are_recorded(self, lock):
        """The two the installer ships. Anything else is optional."""
        assert set(lock) >= {"swift-ct2", "base.en"}, (
            f"a bundled model has no fingerprints: {sorted(lock)}")

    def test_every_entry_names_its_upstream_source(self, lock):
        for name, entry in lock.items():
            assert entry.get("repo"), f"{name} does not say where it came from"
            assert entry.get("how") in ("download", "convert"), name

    def test_every_entry_fingerprints_a_loadable_model(self, lock):
        """
        A faster-whisper model needs all three of these. Recording a partial
        download would make the verification pass on something that cannot load.
        """
        for name, entry in lock.items():
            files = set(entry.get("files") or {})
            missing = {"config.json", "model.bin", "tokenizer.json"} - files
            assert not missing, f"{name} is missing {sorted(missing)}"

    def test_fingerprints_are_full_length_digests_and_real_sizes(self, lock):
        for name, entry in lock.items():
            for fname, meta in entry["files"].items():
                digest = meta.get("sha256", "")
                assert len(digest) == 64, f"{name}/{fname}: {digest!r}"
                assert all(c in "0123456789abcdef" for c in digest), \
                    f"{name}/{fname} is not a hex digest"
                assert meta.get("bytes", 0) > 0, f"{name}/{fname} has no size"

    def test_a_changed_file_size_is_detected(self, repo_root, monkeypatch):
        """
        The check has to actually fire. Left untested it would be a passing
        message rather than a guarantee, which is the failure doctor.py already
        had once: it printed "ok" while the app ran a different model.
        """
        import json

        import doctor

        lock_path = repo_root / "models" / "MODELS.lock.json"
        if not lock_path.is_file():
            pytest.skip("models/MODELS.lock.json absent")
        model_dir = repo_root / "models" / "swift-ct2"
        if not (model_dir / "model.bin").is_file():
            pytest.skip("weights absent; run fetch_models.py")

        original = lock_path.read_bytes()
        lock = json.loads(original.decode("utf-8"))
        lock["swift-ct2"]["files"]["model.bin"]["bytes"] = 1

        monkeypatch.setattr(doctor, "results", [])
        try:
            lock_path.write_text(json.dumps(lock), encoding="utf-8")
            doctor._check_bundled_weights("swift-ct2")
        finally:
            lock_path.write_bytes(original)

        failures = [r for r in doctor.results if r[0] == doctor.FAIL]
        assert failures, (
            "a wrong file size was not reported; the lock-file check is "
            "decorative")
