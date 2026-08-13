"""Documentation must match the code.

Both files have already drifted from reality once. The README documented
whisper_model as base.en when it was base, language as "en" when it was null,
llm_backend as "openai" when it was "rules", and pill_style as "blob" when it
was "caption" - and it never mentioned offline_only at all while claiming cloud
transcription worked with just an API key. Docs nobody checks become fiction, so
a script checks them.
"""

import json
import re

import pytest

import config

SETTING_ROW = re.compile(r"^\|\s*`([a-z_]+)`[^|]*\|\s*`?([^|`]*)`?\s*\|", re.M)

# Working documents: kept by whoever is building the thing, deliberately not part
# of what gets published. The checks below still run against them when they are
# present, because they are worth having for the person who has them, and skip
# rather than fail where they are not - CI clones only what is distributed.
_NOT_DISTRIBUTED = {"PLAN.md"}


def _optional_doc(repo_root, name: str) -> str:
    path = repo_root / name
    if name in _NOT_DISTRIBUTED and not path.is_file():
        pytest.skip(f"{name} is a working document and is not distributed")
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def readme(repo_root) -> str:
    return (repo_root / "README.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def shipped(repo_root) -> dict:
    return json.loads((repo_root / "settings.json").read_text(encoding="utf-8"))


def slug(heading: str) -> str:
    s = re.sub(r"`|\*|\.|,|\(|\)|:|'|\"|/", "", heading.strip().lower())
    s = re.sub(r"[^\w\s-]", "", s)
    return re.sub(r"\s+", "-", s).strip("-")


class TestSettingsAreDocumented:
    def test_every_shipped_setting_appears_in_the_readme(self, readme, shipped):
        missing = sorted(k for k in shipped if k not in readme)
        assert not missing, f"settings.json keys absent from README: {missing}"

    def test_every_default_appears_in_the_readme(self, readme):
        """A setting that exists in config.py but is undocumented is invisible."""
        missing = sorted(k for k in config.DEFAULTS if k not in readme)
        assert not missing, f"config.DEFAULTS keys absent from README: {missing}"

    @pytest.mark.parametrize("key", [
        "min_hold_seconds", "whisper_model", "language",
        "llm_backend", "pill_style", "offline_only", "keep_mic_open",
    ])
    def test_documented_default_matches_the_shipped_value(self, readme, shipped, key):
        """
        These are the settings whose documented defaults were previously wrong.
        Only rows that state a literal default are checked; prose rows are
        skipped rather than guessed at.
        """
        rows = dict((m.group(1), m.group(2).strip()) for m in SETTING_ROW.finditer(readme))
        documented = rows.get(key)
        if documented is None:
            pytest.skip(f"{key} is documented in prose, not a table row")

        actual = shipped[key]
        expected = {True: "true", False: "false", None: "null"}.get(
            actual, str(actual))
        assert expected in documented.lower(), (
            f"README says {key} defaults to {documented!r}, "
            f"settings.json ships {actual!r}"
        )


class TestNoContradictions:
    """
    Drift caught by hand three times already, so it is now checked. Each of these
    was a real error in a shipped README: a default named that was not the
    default, and an option value that does not exist in the code.
    """

    # Phrases that assert a default. Each was wrong in a shipped README.
    DEFAULT_CLAIMS = [
        (r"\*?\*?`(?P<v>[\w.\-]+)`\*?\*? \(default\)", "pill_style"),
        (r"default `(?P<v>[\w.\-]+)`\)? into", "whisper_model"),
    ]

    @pytest.mark.parametrize("pattern,key", DEFAULT_CLAIMS)
    def test_a_value_called_the_default_really_is(self, readme, shipped, pattern, key):
        for m in re.finditer(pattern, readme):
            claimed = m.group("v")
            assert claimed == str(shipped[key]), (
                f"README calls {claimed!r} the default, but settings.json ships "
                f"{key}={shipped[key]!r}"
            )

    def test_output_script_values_exist_in_the_code(self, readme):
        """
        The README previously offered a `native` value that config.py rejects,
        which would have silently fallen back to `latin`.
        """
        valid = {"latin", "devanagari", "as-is"}
        after = readme.split("### Script of the output", 1)
        assert len(after) == 2, "output_script is no longer documented"
        # Bound the search to this section only; the next heading ends it.
        section = re.split(r"^#{2,3} ", after[1], maxsplit=1, flags=re.M)[0]
        offered = set(re.findall(r"^\|\s*`([a-z-]+)`\s*\|", section, re.M))
        assert offered, "no output_script values documented"
        assert offered <= valid, f"README offers unsupported values: {offered - valid}"

    def test_no_markdown_table_is_split_by_prose(self, repo_root):
        """
        Inserting a paragraph into the middle of a table silently turns the
        remaining rows into plain text. Done once by accident already.
        """
        for name in ("README.md", "PLAN.md"):
            if name in _NOT_DISTRIBUTED and not (repo_root / name).is_file():
                continue
            lines = (repo_root / name).read_text(encoding="utf-8").splitlines()
            for i, line in enumerate(lines):
                if not line.startswith("|"):
                    continue
                # A table row directly after a non-empty, non-table, non-heading
                # line means a table was interrupted.
                prev = lines[i - 1].strip() if i else ""
                if prev and not prev.startswith(("|", "#")):
                    pytest.fail(
                        f"{name}:{i + 1} a table row follows prose, which breaks "
                        f"the table:\n  prose: {prev[:70]}\n  row:   {line[:70]}"
                    )


class TestNoBrokenAnchors:
    @pytest.mark.parametrize("name", ["README.md", "PLAN.md"])
    def test_in_page_links_resolve(self, repo_root, name):
        text = _optional_doc(repo_root, name)
        anchors = {slug(h) for h in re.findall(r"^#{1,6}\s+(.*)$", text, re.M)}
        links = re.findall(r"\]\(#([^)]+)\)", text)
        broken = sorted({l for l in links if l not in anchors})
        assert not broken, f"{name} has broken in-page links: {broken}"


class TestNoStaleProductNames:
    @pytest.mark.parametrize("name", [
        "README.md", "PLAN.md", "settings.json", "requirements.txt",
        "install.ps1", ".env.example",
        # LICENSE and installer.iss are the two files a user reads *inside the
        # installer*, on screens 2 and 3. LICENSE was omitted from this list and
        # duly went to press saying "Jasper contributors".
        "LICENSE", "installer.iss",
    ])
    def test_old_names_are_gone(self, repo_root, name):
        if name in _NOT_DISTRIBUTED and not (repo_root / name).is_file():
            pytest.skip(f"{name} is a working document and is not distributed")
        """
        No leftover branding from before the rename.

        Lines that say "legacy" are exempt, because one deliberate reference is
        unavoidable: the application used to write its launch-at-login entry under
        the old name, and both `installer.iss` and `tray.py` have to name that
        registry value in order to delete it. Removing the exemption would mean
        choosing between this guard and cleaning up after the rename.
        """
        lines = (repo_root / name).read_text(
            encoding="utf-8", errors="replace").splitlines()

        def excused(i: int) -> bool:
            # The marker may sit on the line itself or in the comment directly
            # above it. In installer.iss it has to be above: that file's registry
            # lines use `;` as a parameter separator, so a trailing comment is a
            # syntax error rather than a comment.
            return any("legacy" in lines[j].lower()
                       for j in range(max(0, i - 2), i + 1))

        for stale in ("Jasper", "jasper", "VoxPad", "voxpad"):
            offenders = [ln.strip() for i, ln in enumerate(lines)
                         if stale in ln and not excused(i)]
            assert not offenders, (
                f"{name} still mentions {stale!r}: {offenders[:3]}"
            )


class TestPlanIsHonest:
    """
    The plan's value is that measured and published numbers are distinguishable.
    """

    @pytest.fixture(scope="class")
    def plan(self, repo_root) -> str:
        return _optional_doc(repo_root, "PLAN.md")

    def test_every_phase_has_an_acceptance_criterion(self, plan):
        phases = re.findall(r"^### (Phase \d+.*)$", plan, re.M)
        assert phases, "no phases found"
        without = []
        for phase in phases:
            after = plan.split(f"### {phase}", 1)[1]
            # A phase ends at the next phase heading or the next top-level
            # section - NOT at the next "### ", because a phase may legitimately
            # contain its own subsections.
            end = re.search(r"^(### Phase \d+|## )", after, re.M)
            body = after[: end.start()] if end else after
            if "**Acceptance:**" not in body:
                without.append(phase)
        assert not without, f"phases with no acceptance criterion: {without}"

    def test_phases_are_numbered_sequentially(self, plan):
        nums = [int(n) for n in re.findall(r"^### Phase (\d+)", plan, re.M)]
        assert nums == list(range(len(nums))), f"phase numbering is not sequential: {nums}"

    def test_unverified_claims_are_declared(self, plan):
        assert "## What we cannot yet verify" in plan
