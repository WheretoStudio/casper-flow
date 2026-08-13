"""
Put the speech models in models/ so a release build can bundle them.

    venv\\Scripts\\python.exe fetch_models.py            # assemble everything
    venv\\Scripts\\python.exe fetch_models.py --verify   # check, change nothing
    venv\\Scripts\\python.exe fetch_models.py --lock     # re-record the lock file

**Why this exists.** Casper Flow ships as one file that installs with the network
unplugged, which means every model has to be inside the installer. They were,
but they got there by two different accidents: `models/swift-ct2` happened to
exist on one laptop, and `base.en` was copied out of whatever the HuggingFace
cache held. `models/` is gitignored, nothing in the repository could regenerate
it, and the conversion command lived in a comment. So exactly one machine in the
world could build a release, and nobody could check that the weights in a release
were the weights the accuracy figures were measured on.

**We host the weights ourselves.** They come from a release asset on our own
repository, so a normal build reaches no third party. They cannot live in the
repository as ordinary files - git blocks anything over 100 MiB and
base.en/model.bin is 138 MB - and Git LFS would charge a monthly bandwidth quota
against every clone. Release assets have neither a size nor a bandwidth cap, and
are what GitHub documents for distributing binaries.

What *is* in git is `models/MODELS.lock.json`: the upstream repository, the exact
revision, the quantisation, and a SHA-256 for every file. It verifies the download
and it means the weights can be rebuilt from source if the upstream models ever
matter again.

**The user downloads one file and nothing else** - the installer, with both models
inside it. This script runs on a build machine, before PyInstaller, and changes
nothing about the install.

Three routes, in the order they are tried:

  bundle      one zip from our own release. The normal path, and the only one a
              contributor needs: no HuggingFace, no torch, no conversion.
  download    an upstream model already in CTranslate2 format, fetched as-is.
              This is `base.en`.
  convert     an upstream model published as transformers weights, converted
              locally. This is `swift-ct2`, and it needs torch and transformers -
              about 440 MB, used once.

The last two exist to *create* the bundle and to bootstrap a new weight version.
Maintainer flow when the weights change:

    python fetch_models.py --from-source     # rebuild from upstream
    python fetch_models.py --lock            # record the fingerprints
    python fetch_models.py --pack            # build the zip, prints the gh command
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODELS_DIR = ROOT / "models"
LOCK_FILE = MODELS_DIR / "MODELS.lock.json"

# --------------------------------------------------------------- our own bundle
#
# The models are hosted by us, as a release asset on our own repository. Nothing
# in a normal build reaches a third party.
#
# It has to be a release asset rather than a file in the repository: git refuses
# files over 100 MiB outright and base.en/model.bin is 138 MB, and Git LFS would
# bill a monthly bandwidth quota for every clone. Release assets have no size or
# bandwidth cap and are what GitHub documents for distributing binaries.
#
# Bump TAG when the weights change. The tag is part of the URL, so an old build
# keeps fetching exactly the bytes it was built against.
MODEL_BUNDLE = {
    "repo": "wheretostudio/casper-flow",
    "tag": "models-v1",
    "asset": "casper-models-v1.zip",
}


def bundle_url() -> str:
    b = MODEL_BUNDLE
    return (f"https://github.com/{b['repo']}/releases/download/"
            f"{b['tag']}/{b['asset']}")

# What a complete faster-whisper model directory looks like. An interrupted
# download leaves the directory in place, so its existence proves nothing.
REQUIRED = ("config.json", "model.bin", "tokenizer.json")

MODELS = {
    "base.en": {
        "how": "download",
        "repo": "Systran/faster-whisper-base.en",
        "why": "The English-only profile. 91% accurate on the English corpus, "
               "and it cannot transcribe Hindi at all.",
    },
    "swift-ct2": {
        "how": "convert",
        "repo": "Oriserve/Whisper-Hindi2Hinglish-Swift",
        "quantization": "int8",
        "copy_files": ("tokenizer.json", "preprocessor_config.json"),
        "why": "The default, and the reason this product exists. 81% accurate on "
               "code-switched Hindi-English. Apache 2.0.",
    },
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fingerprint(model_dir: Path) -> dict:
    """Every file in the model, by name, with its size and digest."""
    return {
        p.relative_to(model_dir).as_posix(): {
            "bytes": p.stat().st_size,
            "sha256": sha256(p),
        }
        for p in sorted(model_dir.rglob("*"))
        if p.is_file()
    }


def load_lock() -> dict:
    if not LOCK_FILE.is_file():
        return {}
    try:
        return json.loads(LOCK_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  ! {LOCK_FILE.name} is unreadable ({e}); treating it as absent")
        return {}


def is_complete(model_dir: Path) -> bool:
    return all((model_dir / f).is_file() for f in REQUIRED)


def pack(names: list[str], lock: dict) -> int:
    """
    Build the release asset from what is in models/. Maintainer step.

    This is how the bundle everyone else downloads gets made. Run it once after
    establishing or changing the weights, then attach the result to a release.
    """
    problems = verify(names, lock)
    if problems:
        print("Refusing to pack: models/ does not match the lock file.")
        for p in problems:
            print(f"  - {p}")
        return 1

    out = ROOT / "dist"
    out.mkdir(exist_ok=True)
    archive = out / MODEL_BUNDLE["asset"]
    print(f"Packing {len(names)} model(s) into {archive.name}\n")

    # ZIP_STORED, not DEFLATE: model.bin is quantised weights and compresses by a
    # percent or two, so deflating it costs minutes of CPU on both sides for
    # nothing. The installer compresses the payload later anyway.
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_STORED) as z:
        for name in names:
            for path in sorted((MODELS_DIR / name).rglob("*")):
                if path.is_file():
                    z.write(path, path.relative_to(MODELS_DIR).as_posix())
                    print(f"  + {path.relative_to(MODELS_DIR).as_posix()}")
        z.write(LOCK_FILE, LOCK_FILE.name)
        print(f"  + {LOCK_FILE.name}")

    size = archive.stat().st_size
    print(f"\n{archive}  ({size / 1e6:.1f} MB)")
    print(f"sha256  {sha256(archive)}")
    # Backtick continuations: this project is Windows-only and the shell is
    # PowerShell, where a trailing backslash is not a line continuation.
    print("\nPublish it:\n")
    print(f"    gh release create {MODEL_BUNDLE['tag']} `")
    print(f"        \"{archive}\" `")
    print(f"        --repo {MODEL_BUNDLE['repo']} `")
    print(f"        --title \"Speech models {MODEL_BUNDLE['tag']}\" `")
    print(f"        --notes \"Bundled weights. Verified against "
          f"models/MODELS.lock.json.\"")
    print(f"\nAfter that, `python fetch_models.py` on any machine gets them from")
    print(f"{bundle_url()}")
    return 0


def do_bundle(names: list[str]) -> bool:
    """
    Fetch every model at once from our own release asset.

    The fast path, and the only one a contributor should ever need: one download,
    no HuggingFace, no torch, no conversion. Returns False if the asset is not
    published yet, so the caller can fall back to building it from source.
    """
    url = bundle_url()
    tmp = MODELS_DIR / f".{MODEL_BUNDLE['asset']}.part"
    print(f"  {url}")
    try:
        with urllib.request.urlopen(url, timeout=60) as r, tmp.open("wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while chunk := r.read(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r  {done / 1e6:7.1f} / {total / 1e6:.1f} MB", end="")
        print()
    except urllib.error.HTTPError as e:
        tmp.unlink(missing_ok=True)
        if e.code == 404:
            print(f"  not published yet (404)")
            return False
        raise
    except Exception as e:
        tmp.unlink(missing_ok=True)
        print(f"  download failed: {type(e).__name__}: {e}")
        return False

    print("  extracting")
    with zipfile.ZipFile(tmp) as z:
        # Guard against a path escaping models/. The archive is ours, but a
        # zip that writes outside its target directory is the classic way an
        # archive extraction turns into arbitrary file overwrite.
        for member in z.namelist():
            target = (MODELS_DIR / member).resolve()
            if not target.is_relative_to(MODELS_DIR.resolve()):
                raise SystemExit(f"archive member escapes models/: {member!r}")
        z.extractall(MODELS_DIR)
    tmp.unlink(missing_ok=True)
    return True


def do_download(name: str, spec: dict, revision: str | None) -> str:
    """Fetch an already-converted model. Returns the revision actually used."""
    from huggingface_hub import snapshot_download

    target = MODELS_DIR / name
    print(f"  downloading {spec['repo']}"
          + (f" at {revision[:12]}" if revision else " (latest)"))
    # local_dir gives real files rather than symlinks into the shared cache, which
    # matters because PyInstaller follows what it is given and a symlinked payload
    # is not portable.
    path = snapshot_download(
        repo_id=spec["repo"],
        revision=revision,
        local_dir=str(target),
        allow_patterns=["*.json", "*.bin", "*.txt"],
    )
    return _resolved_revision(spec["repo"], revision) or Path(path).name


def _resolved_revision(repo: str, revision: str | None) -> str | None:
    try:
        from huggingface_hub import HfApi
        return HfApi().model_info(repo, revision=revision).sha
    except Exception:
        return revision


def do_convert(name: str, spec: dict, revision: str | None) -> str:
    """Convert transformers weights to CTranslate2. Returns the revision used."""
    target = MODELS_DIR / name

    if shutil.which("ct2-transformers-converter") is None:
        raise SystemExit(
            "ct2-transformers-converter is not on PATH. It comes with "
            "ctranslate2, so the virtual environment is probably not active."
        )
    try:
        import torch          # noqa: F401
        import transformers   # noqa: F401
    except ImportError:
        raise SystemExit(
            f"Converting {spec['repo']} needs torch and transformers, which are "
            f"deliberately not installed - they are ~440 MB and are used once.\n\n"
            f"Install the CPU wheels (the default pulls the CUDA build, roughly "
            f"ten times the size, to read weights off disk):\n\n"
            f"    .\\venv\\Scripts\\python.exe -m pip install torch "
            f"--index-url https://download.pytorch.org/whl/cpu transformers\n\n"
            f"Then run this again. You can uninstall them afterwards; the lock "
            f"file records the result so nobody has to repeat it."
        )

    print(f"  converting {spec['repo']} (this takes a minute)")
    if target.exists():
        shutil.rmtree(target)
    cmd = [
        "ct2-transformers-converter",
        "--model", spec["repo"],
        "--output_dir", str(target),
        "--quantization", spec.get("quantization", "int8"),
        "--copy_files", *spec.get("copy_files", ()),
    ]
    if revision:
        cmd += ["--revision", revision]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise SystemExit(f"ct2-transformers-converter failed ({result.returncode})")
    return _resolved_revision(spec["repo"], revision) or "unknown"


def verify(names: list[str], lock: dict) -> list[str]:
    """Return a list of problems. Empty means everything matches the lock file."""
    problems = []
    for name in names:
        entry = lock.get(name)
        model_dir = MODELS_DIR / name
        if not is_complete(model_dir):
            problems.append(f"{name}: not present in models/ (or incomplete)")
            continue
        if not entry or not entry.get("files"):
            problems.append(f"{name}: present, but {LOCK_FILE.name} has no "
                            f"record of it - run --lock to record it")
            continue
        actual = fingerprint(model_dir)
        for fname, want in entry["files"].items():
            got = actual.get(fname)
            if got is None:
                problems.append(f"{name}/{fname}: missing")
            elif got["sha256"] != want["sha256"]:
                problems.append(
                    f"{name}/{fname}: content does not match the lock file. "
                    f"These are not the weights the accuracy figures were "
                    f"measured on."
                )
        extra = sorted(set(actual) - set(entry["files"]))
        if extra:
            problems.append(f"{name}: unexpected extra file(s) {extra}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Assemble the bundled speech models for a release build.")
    ap.add_argument("--verify", action="store_true",
                    help="check models/ against the lock file and exit")
    ap.add_argument("--lock", action="store_true",
                    help="record what is in models/ into the lock file")
    ap.add_argument("--only", metavar="NAME", action="append",
                    choices=sorted(MODELS),
                    help="act on one model only (repeatable)")
    ap.add_argument("--force", action="store_true",
                    help="re-fetch even if the model is already present")
    ap.add_argument("--pack", action="store_true",
                    help="build the release asset from models/ (maintainer)")
    ap.add_argument("--from-source", action="store_true",
                    help="skip our release asset and rebuild from the upstream "
                         "model repositories (maintainer)")
    args = ap.parse_args()

    names = args.only or sorted(MODELS)
    lock = load_lock()

    if args.verify:
        print(f"Verifying {len(names)} model(s) against {LOCK_FILE.name}\n")
        problems = verify(names, lock)
        if problems:
            print("Problems:")
            for p in problems:
                print(f"  - {p}")
            print("\nRun:  python fetch_models.py")
            return 1
        for name in names:
            total = sum(f["bytes"] for f in lock[name]["files"].values())
            print(f"  [ok] {name:12} {total / 1e6:7.1f} MB  "
                  f"{lock[name]['repo']}")
        print("\nBoth models match the lock file.")
        return 0

    if args.lock:
        print(f"Recording {len(names)} model(s) into {LOCK_FILE.name}\n")
        for name in names:
            model_dir = MODELS_DIR / name
            if not is_complete(model_dir):
                print(f"  ! {name} is not in models/; skipping")
                continue
            entry = lock.setdefault(name, {})
            entry["repo"] = entry.get("repo") or MODELS[name]["repo"]
            entry.setdefault("revision", "unknown")
            entry["how"] = MODELS[name]["how"]
            if "quantization" in MODELS[name]:
                entry["quantization"] = MODELS[name]["quantization"]
            entry["why"] = MODELS[name]["why"]
            entry["files"] = fingerprint(model_dir)
            total = sum(f["bytes"] for f in entry["files"].values())
            print(f"  recorded {name:12} {len(entry['files'])} files, "
                  f"{total / 1e6:.1f} MB")
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        LOCK_FILE.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
        print(f"\nWritten: {LOCK_FILE}")
        print("Commit this file. It is how anyone else reproduces these weights.")
        return 0

    if args.pack:
        return pack(names, lock)

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Assembling {len(names)} model(s) into {MODELS_DIR}\n")

    # Our own release asset first. One download, no third party, no torch. The
    # per-model paths below exist to *create* this asset, and to bootstrap a new
    # weight version - they are not the normal route.
    already = all(is_complete(MODELS_DIR / n) for n in names)
    if not args.from_source and not (already and not args.force):
        print(f"Bundle from {MODEL_BUNDLE['repo']} release "
              f"{MODEL_BUNDLE['tag']}")
        if do_bundle(names):
            lock = load_lock()
            problems = verify(names, lock)
            if problems:
                print("\nThe bundle does not match its own lock file:")
                for p in problems:
                    print(f"  - {p}")
                return 1
            for name in names:
                total = sum(f["bytes"] for f in lock[name]["files"].values())
                print(f"  [ok] {name:12} {total / 1e6:7.1f} MB")
            print("\nReady. Next:  powershell -ExecutionPolicy Bypass "
                  "-File build_installer.ps1")
            return 0
        print("  falling back to building them from the upstream repositories\n")

    changed = False
    for name in names:
        spec = MODELS[name]
        model_dir = MODELS_DIR / name
        print(f"{name}  ({spec['why']})")

        if is_complete(model_dir) and not args.force:
            print("  already present; use --force to re-fetch")
            continue

        revision = (lock.get(name) or {}).get("revision")
        if revision in ("unknown", ""):
            revision = None
        used = (do_download if spec["how"] == "download" else do_convert)(
            name, spec, revision)

        if not is_complete(model_dir):
            raise SystemExit(
                f"{name}: finished without producing {REQUIRED}. Delete "
                f"{model_dir} and try again.")
        entry = lock.setdefault(name, {})
        entry["repo"] = spec["repo"]
        entry["revision"] = used
        entry["how"] = spec["how"]
        if "quantization" in spec:
            entry["quantization"] = spec["quantization"]
        entry["why"] = spec["why"]
        entry["files"] = fingerprint(model_dir)
        changed = True
        total = sum(f["bytes"] for f in entry["files"].values())
        print(f"  done: {total / 1e6:.1f} MB, revision {used[:12]}")

    if changed:
        LOCK_FILE.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
        print(f"\nUpdated {LOCK_FILE.name}. Commit it.")

    problems = verify(names, lock)
    if problems:
        print("\nStill not right:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nReady. Next:  powershell -ExecutionPolicy Bypass -File build_installer.ps1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
