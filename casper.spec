# PyInstaller build definition for Casper Flow.
#
#   venv\Scripts\pyinstaller.exe casper.spec --noconfirm
#
# --onedir, never --onefile. A onefile build unpacks itself into a temp directory
# on every launch, which is among the strongest heuristics antivirus engines use,
# and Defender already treats keyboard-hook code as suspicious. It also pays that
# unpack cost on every start.
#
# The three collect_all packages load native libraries and data files at runtime,
# so PyInstaller cannot infer them from imports.
#
# The excludes matter as much as the includes. torch and transformers are needed
# only to convert a model with ct2-transformers-converter, they are never used at
# runtime, and they are 436 MB. The cloud clients are excluded on privacy grounds
# before size: the distributed binary should be incapable of reaching a
# transcription API, not merely configured not to.

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
for pkg in ("faster_whisper", "ctranslate2", "onnxruntime"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# Data files. PyInstaller 6 puts COLLECT datas in `_internal\` beside the
# executable, not next to it - paths.RESOURCE_DIR (sys._MEIPASS) is what resolves
# them, and paths.resource_file() checks the writable directory beside the exe
# first so a user can override any of these without a rebuild.
datas += [
    ("assets/casper.ico", "assets"),
    ("settings.json", "."),
    # .env.example is deliberately not here. It documents API key names for the
    # cloud backends, and those clients are excluded from this build entirely, so
    # in a frozen install it describes something the binary cannot do. install.ps1
    # copies it from the source tree, which is where it is useful.
    # MIT requires the notice to travel with the binary, so it has to be in the
    # payload rather than only shown by the installer wizard. THIRD-PARTY-NOTICES
    # covers CTranslate2, onnxruntime, PortAudio, pystray's LGPL obligation and the
    # model weights, which have their own terms and are equally part of what gets
    # distributed.
    ("LICENSE", "."),
    ("THIRD-PARTY-NOTICES.md", "."),
]

# The bundled speech models.
#
# Both come from models/, assembled by fetch_models.py and pinned file-by-file in
# models/MODELS.lock.json. Previously only swift-ct2 was listed here and base.en
# was copied in afterwards by build_installer.ps1 out of the HuggingFace cache -
# two mechanisms, one of which depended on the state of one developer's home
# directory. One mechanism now.
#
# Conditional on purpose. `models/` holds 219 MB of weights and is not in git, so
# listing it unconditionally made `pyinstaller casper.spec` fail outright on a
# fresh clone and on CI. That turned "you cannot ship a release without the
# models", which is true and is enforced by build_installer.ps1, into "you cannot
# build at all", which needlessly stopped anyone from working on the app.
#
# A build without them still runs: the app falls back to a cached or downloaded
# model, and doctor.py reports the substitution as a failure rather than hiding it.
for _name in ("swift-ct2", "base.en"):
    _model = Path("models") / _name
    if (_model / "model.bin").is_file():
        datas.append((str(_model), f"models/{_name}"))
    else:
        print(f"casper.spec: models/{_name} is missing - building without it. "
              f"Run `python fetch_models.py` before a release build.")

EXCLUDES = [
    # PyAV: 62.6 MB of bundled FFmpeg, pulled in by faster_whisper.audio purely
    # to decode input files. We record our own WAV and decode it with the
    # standard library, and faster-whisper never sees a path - only an array.
    #
    # `import av` still has to succeed, because faster_whisper/__init__.py
    # imports decode_audio at module level. hooks/rthook_no_av.py installs a stub
    # that satisfies the import and raises if anything actually uses it.
    "av",
    # Build-time only: used by ct2-transformers-converter, never at runtime.
    "torch", "torchvision", "torchaudio", "transformers", "safetensors",
    "sympy", "networkx", "mpmath",
    # Cloud clients. Excluded so the binary cannot reach a transcription API.
    "openai", "groq", "anthropic", "httpx", "httpcore",
    # Test and build tooling.
    "pytest", "_pytest", "pluggy", "setuptools", "pip", "pkg_resources",
    # Unused stdlib weight.
    "tkinter.test", "test", "unittest", "pydoc_data", "lib2to3",
    "matplotlib", "scipy", "pandas", "IPython",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + [
        # tkinter is imported lazily by the overlay fallback and the settings UI.
        "tkinter", "tkinter.ttk",
        # These are imported inside functions rather than at module level, so
        # PyInstaller's static analysis does not see them. Without them the
        # frozen build starts fine and then fails the moment someone opens
        # Settings or runs the diagnostics - the worst kind of packaging bug,
        # because it survives every check that only launches the app.
        "settings_ui",
        "doctor",
        "wizard",
    ],
    hookspath=[],
    runtime_hooks=["hooks/rthook_no_av.py"],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CasperFlow",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX-packed binaries are themselves an antivirus trigger
    console=False,      # a tray app must not open a console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/casper.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="CasperFlow",
)
