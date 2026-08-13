"""The application icon.

The tray icon looked "compressed and not proper", and the cause was measurable
rather than aesthetic: the mark's thinnest features were 1.25 px wide at 16 px,
the .ico had no 20 px frame so a 125% display got the three-bar 32 px frame
squashed, and the tray resampled the 256 px frame down to 64 before Windows
shrank it again.

These tests encode the parts of that which are objective facts about the file.
"""

import pytest

pytest.importorskip("PIL")

from PIL import Image

import make_icon


@pytest.fixture(scope="module")
def ico(repo_root):
    path = repo_root / "assets" / "casper.ico"
    if not path.exists():
        pytest.skip("run make_icon.py first")
    return Image.open(path)


@pytest.fixture(scope="module")
def frames(ico) -> dict[int, Image.Image]:
    return {w: ico.ico.getimage((w, w)).convert("RGBA")
            for w, _h in ico.ico.sizes()}


class TestSizesWindowsActuallyAsksFor:
    # Windows scales notification icons with the display: 16 px at 100%,
    # 20 at 125%, 24 at 150%, 32 at 200%, 40 at 250%. A missing frame means the
    # nearest larger one gets squashed, which is what went wrong.
    DPI_SIZES = (16, 20, 24, 32, 40)

    @pytest.mark.parametrize("size", DPI_SIZES)
    def test_the_frame_exists(self, ico, size):
        assert (size, size) in ico.ico.sizes(), (
            f"no {size}px frame, so Windows will rescale another one to fit"
        )

    def test_every_declared_size_is_present(self, ico):
        declared = {(s, s) for s in make_icon.SIZES}
        assert declared <= set(ico.ico.sizes())

    def test_there_is_a_large_frame_for_the_installer(self, ico):
        assert (256, 256) in ico.ico.sizes()


class TestSmallFramesAreLegible:
    """
    The original failure: features too fine to survive the size they are drawn
    for. Measured on the rendered pixels rather than argued about.
    """

    @pytest.mark.parametrize("size", (16, 20, 24))
    def test_the_mark_is_at_least_two_pixels_wide(self, frames, size):
        img = frames[size]
        w, h = img.size
        px = img.load()
        row = h // 2
        # Count horizontal runs of near-white across the middle of the mark.
        runs, run = [], 0
        for x in range(w):
            r, g, b, a = px[x, row]
            if a > 120 and r > 200 and g > 200 and b > 200:
                run += 1
            elif run:
                runs.append(run)
                run = 0
        if run:
            runs.append(run)
        assert runs, f"no mark visible at {size}px"
        assert max(runs) >= 2, (
            f"the widest part of the mark is {max(runs)}px at {size}px, which "
            f"antialiases into grey mush"
        )

    @pytest.mark.parametrize("size", (16, 20, 24))
    def test_small_frames_use_the_simple_mark(self, frames, size):
        """
        Below make_icon.SIMPLE_BELOW there should be one bar, not three. Three
        marks in a 16px box is the thing that looked compressed.
        """
        assert size < make_icon.SIMPLE_BELOW
        img = frames[size]
        w, h = img.size
        px = img.load()
        row = h // 2
        runs, run = 0, False
        for x in range(w):
            r, g, b, a = px[x, row]
            light = a > 120 and r > 200 and g > 200 and b > 200
            if light and not run:
                runs += 1
            run = light
        assert runs == 1, f"{runs} marks at {size}px; expected a single bar"

    def test_larger_frames_use_the_detailed_mark(self, frames):
        img = frames[64]
        w, h = img.size
        px = img.load()
        row = h // 2
        runs, run = 0, False
        for x in range(w):
            r, g, b, a = px[x, row]
            light = a > 120 and r > 200 and g > 200 and b > 200
            if light and not run:
                runs += 1
            run = light
        assert runs == 3, f"expected three bars at 64px, found {runs}"


class TestFramesAreNotJustResizes:
    def test_a_small_frame_differs_from_the_large_one_reduced(self, frames):
        """
        Each size is rendered at its own resolution. If the 16px frame were the
        256px frame downscaled it would be identical to this, and mush.
        """
        reduced = frames[256].resize((16, 16), Image.LANCZOS)
        assert frames[16].tobytes() != reduced.tobytes()


class TestTrayPicksTheRightFrame:
    def test_it_asks_windows_rather_than_assuming(self):
        import tray
        n = tray._tray_icon_px()
        assert 16 <= n <= 64

    def test_the_icon_handed_over_needs_no_rescaling(self, ico):
        import tray
        want = tray._tray_icon_px()
        img = tray._make_icon(True)
        assert img.size == (want, want), (
            "the tray should hand Windows a frame at exactly the size it asked "
            "for, so nothing is resampled"
        )

    def test_the_disabled_icon_is_the_same_shape(self):
        """Off should read as 'same app, currently off', not a different mark."""
        import tray
        on, off = tray._make_icon(True), tray._make_icon(False)
        assert on.size == off.size
        assert on.tobytes() != off.tobytes()
