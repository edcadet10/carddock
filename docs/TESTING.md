# Release validation

## Automated engine regression suite

```sh
python3 -m unittest discover -s tests -v
```

32 tests cover collisions (including case variants), byte preservation, changed-content duplicates, missing/corrupt destination recovery, preview immutability, independent companion filenames, source/destination overlap, symlink history/files, unmounted destinations, corrupt SQLite history, low space, protected files, verification failures, deletion confirmation/scope and accurate interruption reporting after a deletion.

## Real native GUI smoke test

On a Mac with a graphical login session:

```sh
./scripts/build.sh arm64 --testing
python3 tests/gui_smoke.py
```

This creates disposable fixtures, operates the actual Preview and Import buttons, checks original and copied bytes, reruns duplicate detection, tests dark appearance at minimum window size, cancels deletion, and finally confirms deletion of only those fixtures. Snapshots go to ignored `work/gui/`. The test hooks are compiled out of normal releases. Do not use real photo libraries as automated-test fixtures.

## Release packaging

```sh
./scripts/build.sh arm64
./scripts/build.sh x86_64
```

Both bundles are ad-hoc signed and verified by `codesign --verify --deep --strict`. The runtime download has a pinned SHA-256 checksum for each architecture. Dependency licenses are extracted from the matching verified full runtime archive.

Local validation uses Apple Silicon hardware. An Intel build can be smoke-tested under Rosetta here; that does not replace native Intel hardware testing. The first-launch exception on a clean Mac, older supported macOS versions and all real card-reader combinations require wider testing. No claim of exhaustive hardware certification is made.
