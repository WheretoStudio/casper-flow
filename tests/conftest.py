"""Shared fixtures and hardware detection.

Tests needing a microphone or an interactive desktop cannot run on CI, so they
skip with a reason naming the missing piece.
"""

import sys
from pathlib import Path

import pytest

# Tests import the application modules directly; they live in the repo root.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def has_input_device() -> bool:
    try:
        import sounddevice as sd
        return any(d["max_input_channels"] > 0 for d in sd.query_devices())
    except Exception:
        return False


def has_interactive_desktop() -> bool:
    """True if injected keystrokes can reach a real desktop. CI runners cannot."""
    import os
    if os.environ.get("CI"):
        return False
    return sys.platform == "win32"


def casper_is_running() -> bool:
    """True if a Casper Flow instance holds the single-instance mutex.

    Its suppressing hook on Caps Lock competes with the keyboard tests' own hook
    over every injected event, making the outcome ambiguous.
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        SYNCHRONIZE = 0x00100000
        handle = k32.OpenMutexW(SYNCHRONIZE, False, "CasperFlow_SingleInstance_Mutex")
        if handle:
            k32.CloseHandle(handle)
            return True
        return False
    except Exception:
        return False


needs_microphone = pytest.mark.skipif(
    not has_input_device(), reason="no audio input device available"
)

needs_app_not_running = pytest.mark.skipif(
    casper_is_running(),
    reason="Casper Flow is running; its keyboard hook would compete with the "
           "test's on the same key. Quit it from the tray and re-run.",
)

needs_desktop = pytest.mark.skipif(
    not has_interactive_desktop(),
    reason="needs an interactive Windows desktop (injects real keystrokes)",
)


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return ROOT


@pytest.fixture(scope="session")
def tk_root():
    """One hidden Tk root for the whole session.

    Only one root can exist per process, and destroying one breaks any created
    afterwards. Both windows accept a `master` and attach here as Toplevels.
    """
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except Exception as e:
        pytest.skip(f"no usable Tk: {e}")
    root.withdraw()
    yield root
    # Not destroyed: tearing down the last root breaks anything created later, and
    # the process is about to exit anyway.
