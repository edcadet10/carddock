# Third-party notices

Release apps bundle CPython 3.13.17 from Astral's python-build-standalone release
20261021. The runtime and its dependencies retain their upstream licenses and
notices in `CardDock.app/Contents/Resources/python` (including its `licenses`
directory and Python license). CardDock's MIT license does not replace these.

- CPython: https://www.python.org/psf/license/
- Runtime source/build recipes: https://github.com/astral-sh/python-build-standalone
- Pinned download URLs and SHA-256 values: `scripts/runtime.py`

The app uses Apple's system frameworks and system-provided SF Symbols on macOS.
No third-party Python packages are required by the import engine.
