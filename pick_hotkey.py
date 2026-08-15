"""
Interactive hotkey picker.

Run it, press the key (or combo) you want to hold for dictation, and it tells
you exactly what Casper Flow will see and offers to save it to settings.json.

    venv\\Scripts\\python.exe pick_hotkey.py

Why this exists: keyboards differ enormously. Scroll Lock, Pause and F13-F24
are absent from most laptops and compact boards, and the Fn key never reaches
the operating system at all - it is handled inside the keyboard firmware, so no
software on any platform can bind it. Rather than guessing, this shows you what
actually arrives.
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

SETTINGS = ROOT / "settings.json"
LISTEN_SECONDS = 30

# Keys that exist on effectively every Windows keyboard
UNIVERSAL = {
    "ctrl", "shift", "alt", "space", "tab", "enter", "backspace", "escape",
    "caps lock", *(f"f{i}" for i in range(1, 13)),
}
# Commonly missing from laptops / tenkeyless / 60% boards
OFTEN_MISSING = {
    "scroll lock", "pause", "num lock", "insert", "menu",
    *(f"f{i}" for i in range(13, 25)),
}

MODIFIERS = {"ctrl", "shift", "alt", "windows",
             "left ctrl", "right ctrl", "left shift", "right shift",
             "left alt", "right alt", "left windows", "right windows"}


def base_name(name: str) -> str:
    """'left ctrl' -> 'ctrl' so the saved spec is layout independent."""
    for m in ("ctrl", "shift", "alt", "windows"):
        if name.endswith(m):
            return m
    return name


def main():
    try:
        import keyboard as kb
    except ImportError:
        print("The 'keyboard' package is missing. Run install.ps1 first.")
        return 1

    print(__doc__.strip())
    print("\n" + "=" * 64)
    print("Hold the key or combo you want to use, then release it.")
    print("Press Esc to cancel.\n")
    print("If NOTHING appears when you press a key, that key is invisible to")
    print("Windows and cannot be used. The Fn key behaves this way on every")
    print("laptop - pick something else.\n")

    captured = {"spec": None}
    seen_any = []

    def on_event(e):
        if e.event_type != "down":
            return
        name = (e.name or "").lower()
        if not name:
            return
        seen_any.append(name)

        if name == "esc" or name == "escape":
            captured["spec"] = "__cancel__"
            return

        if name in MODIFIERS:
            # Wait for a real trigger key; a modifier alone is usually not what
            # you want. Recorded anyway in case it is all they press.
            print(f"   modifier held: {base_name(name)}")
            return

        mods = []
        for m in ("ctrl", "shift", "alt", "windows"):
            try:
                if kb.is_pressed(m):
                    mods.append(m)
            except Exception:
                pass
        spec = "+".join([*mods, name])
        captured["spec"] = spec
        print(f"\n   captured: [{spec}]")

    kb.hook(on_event)

    deadline = time.time() + LISTEN_SECONDS
    while time.time() < deadline and captured["spec"] is None:
        time.sleep(0.05)
    kb.unhook_all()

    spec = captured["spec"]

    if spec == "__cancel__":
        print("\nCancelled. settings.json unchanged.")
        return 0

    if spec is None:
        print(f"\nNothing was captured in {LISTEN_SECONDS}s.")
        if not seen_any:
            print("Casper Flow received no key events at all. If you were pressing Fn,")
            print("that key never reaches Windows - try Caps Lock or Right Ctrl.")
        else:
            print("Only modifier keys were held (Alt, Ctrl, Shift or Windows).")
            print("A modifier by itself cannot be the dictation key - it would")
            print("steal Alt+Tab, copy/paste or the Start menu.")
            print("Try Caps Lock, Right Ctrl, or a modifier plus another key.")
        return 1

    # ---- advice -----------------------------------------------------
    parts = spec.split("+")
    trigger = parts[-1]
    print()
    if trigger in OFTEN_MISSING:
        print(f"NOTE: '{trigger}' is missing from many laptops and compact")
        print("      keyboards. Fine for this machine, but not portable.")
    elif trigger in UNIVERSAL or len(trigger) == 1:
        print(f"'{trigger}' exists on essentially every keyboard. Good choice.")

    if len(parts) == 1 and trigger in {"space", "enter", "tab", "backspace"} | {
        c for c in UNIVERSAL if len(c) == 1
    }:
        print(f"WARNING: '{trigger}' on its own is a key you type with.")
        print("         Casper Flow would swallow it. Add a modifier, e.g.")
        print(f"         ctrl+{trigger}")

    from hotkey import unsafe_bare_modifier
    reason = unsafe_bare_modifier(spec)
    if reason:
        print(f"\nRefusing to save. {reason}")
        return 1

    # ---- save -------------------------------------------------------
    try:
        answer = input(f"\nSave hotkey [{spec}] to settings.json? (y/n) [y]: ").strip().lower()
    except EOFError:
        answer = "y"
    if answer and answer != "y":
        print("Not saved.")
        return 0

    try:
        cfg = json.loads(SETTINGS.read_text(encoding="utf-8-sig")) if SETTINGS.exists() else {}
        cfg["hotkey"] = spec
        SETTINGS.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        print(f"Saved. hotkey = {spec!r}")
        print("Restart Casper Flow for it to take effect.")
    except Exception as e:
        print(f"Could not write settings.json: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
