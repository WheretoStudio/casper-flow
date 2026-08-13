"""Shared fixtures and hardware detection.

Some of these tests need real hardware: a microphone, or an interactive desktop
that can receive injected keystrokes. Those cannot run on a CI runner, so they
are skipped rather than failed, and the skip reason says which piece is missing.
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
    """
    True if injected keystrokes can reach a real desktop.

    GetProcessWindowStation/GetUserObjectInformation would be the rigorous
    check; in practice a CI runner has no interactive session and setting the
    CI environment variable is the reliable signal.
    """
    import os
    if os.environ.get("CI"):
        return False
    return sys.platform == "win32"


def casper_is_running() -> bool:
    """
    True if a Casper Flow instance already holds the single-instance mutex.

    This matters for the keyboard tests. They inject real Caps Lock events, and a
    running app installs its own suppressing hook on the same key, so both hooks
    receive every injected event and compete over whether to swallow it. The
    result is ambiguous, and it also makes the app react to the test suite -
    visible in casper.log as bursts of "Hold too short (0.00s)", which is
    keyboard.send() delivering key-down and key-up back to back. Its replay flag
    is per-process, so it hides those events from the test's own hook but not
    from the app's.
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
    """
    One hidden Tk root for the whole test session.

    Only one Tk root can exist per process. Creating a second fails with
    "Can't find a usable tk.tcl", and destroying one breaks any created
    afterwards with "invalid command name tcl_findLibrary" - which is how the
    settings-window tests started breaking the wizard tests. Both windows accept
    a `master`, so they attach to this root as Toplevels instead of making their
    own.
    """
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except Exception as e:
        pytest.skip(f"no usable Tk: {e}")
    root.withdraw()
    yield root
    # Deliberately not destroyed: the process is about to exit anyway, and tearing
    # down the last root is what causes the failures described above.
