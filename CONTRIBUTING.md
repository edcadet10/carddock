# Contributing to CardDock

Keep imports understandable, local and conservative. Changes affecting deletion, duplicate detection, path handling or recovery need regression tests before UI polish.

## Layout

- `app/main.swift`: native AppKit interface, folder bookmarks, process protocol.
- `sd_import.py`: standalone import engine; standard library only.
- `tests/test_import.py`: disposable-file regression tests.
- `scripts/runtime.py`: pinned Python runtime URLs, digests and dependency licenses.
- `scripts/build.sh`: compile, bundle, ad-hoc sign, verify and ZIP.
- `docs/`: installation and safety documentation.

## Development

Engine: Python 3.10+. Build tooling: macOS, Apple's command-line tools and Python 3.12+ (for safe tar extraction).

```sh
python3 -m unittest discover -s tests -v
./scripts/build.sh arm64
open build/arm64/CardDock.app
```

Use `./scripts/build.sh x86_64` to cross-compile an Intel build on an Apple Silicon Mac. Cross-compilation is not a substitute for Intel hardware testing.

`./scripts/build.sh arm64 --testing` enables opt-in fixture automation compiled behind `#if TESTING`. Normal release builds exclude it. Run `python3 tests/gui_smoke.py` to exercise the real GUI with disposable fixtures; see [test instructions](docs/TESTING.md). Use only disposable media for automated import/deletion tests. The bundler preserves runtime licenses and verifies upstream archives before extraction.

## Changes

Describe the user-visible behavior, test evidence and remaining limitations. Never commit real photo libraries, personal paths, credentials, build caches or runtime binaries. Treat existing files as user-owned unless the current operation created them. Keep deletion opt-in and independently confirmed.

## Release checklist

1. Run tests and native GUI fixture checks.
2. Update version in engine, Info.plist, build script and documentation.
3. Build both architectures with no `--testing` flag; verify code signatures.
4. Check install/launch on supported machines, including the first-launch security prompt.
5. Create `SHA256SUMS.txt` from release ZIPs; publish versioned GitHub Release assets and accurate notes.

Public releases use ad-hoc signing. Do not describe them as notarized or Apple-verified.
