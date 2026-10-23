# How CardDock handles your originals

## Copy guarantees and limits

1. Validate that source and destination are separate, non-overlapping folders. Check that `/Volumes` paths still correspond to mounted volumes.
2. Scan regular files, excluding symbolic links and hidden directories. Read every candidate's content with SHA-256.
3. Compare potential duplicates with actual destination contents, not only names, sizes, dates or remembered hashes. Missing or modified destination copies are imported again.
4. Reserve names across the entire plan, case-insensitively. Preserve existing files and append numeric suffixes when needed.
5. Copy to a unique temporary file in the destination folder. Flush data, reread the copy, and in the default thorough mode reread the source as well.
6. Publish with macOS `renamex_np(RENAME_EXCL)`, which refuses to replace an existing destination. Unsupported filesystems fail closed rather than falling back to overwriting.
7. Record completed imports in SQLite with full synchronous transactions. A per-library lock prevents concurrent CardDock imports to that library.

The hash checks file contents; it does not guarantee that the camera originally recorded an uncorrupted image. Originals are not re-encoded. Modification times are preserved; Finder tags and every extended attribute are not promised.

The app does not clean up arbitrary `.part` files. An ordinary interruption removes only that operation's unique `.carddock-*.partial` temporary file. A hard crash may leave one behind; it can be inspected and removed manually after confirming no import is active.

## Preview

Preview never creates the destination, writes import history, removes partial files, copies files or deletes originals. Existing history is opened read-only. Reading a file can still update access-time metadata on filesystems that track it; application preferences may be saved when settings change.

## Deletion

Keeping originals is the default. Optional deletion requires both an initial choice and a second destructive confirmation. The default scope is this run's completed copies; earlier imports require a separate opt-in.

Before each deletion the engine verifies source identity, checksums the destination, checksums the source again, and rechecks source identity. Camera-protected files are left alone. Failed imports prevent the deletion stage. Originals are permanently unlinked; they do not go to Trash. Companion files are independently verified before deletion.

A general-purpose filesystem cannot make hashing two files and deleting one a single atomic operation. Do not edit, replace or concurrently synchronize source/destination files during an import or deletion. The implementation narrows the race with immediate checks, but does not claim protection against a malicious process changing files at exactly that moment. A verified single destination is not a second backup.

## Recovery and storage

- Completed files survive a stopped run. Restart to compare and import what remains.
- Individual interrupted files restart from zero; this is not byte-level resume.
- The app reports already-completed deletions when interrupted; stopping cannot undo them.
- Disconnected drives and write/read failures stop the affected operation. No intentional fallback to another destination.
- A 256 MB free-space margin is checked before copying; space can still be consumed by other software afterward, so write failures remain possible.
- Local folders and mounted disks are the intended targets. Network shares, cloud-managed folders, unusual camera packages and all possible USB/filesystem failures have not been exhaustively validated.

## Metadata and companions

The lightweight metadata reader supports EXIF dates in JPEG and supported TIFF-based formats. Unsupported/missing/invalid dates fall back to file modification time, reported in the log. This includes CR3, RAF, HEIC and many video files. Companion dates currently use their own file metadata; proprietary camera folder relationships and perfectly coupled collision-renaming of companion groups are not guaranteed. No files are converted or rewritten.

## Validation

`python3 -m unittest discover -s tests -v` exercises the actual engine on disposable files. Coverage includes collision handling, content-based duplicates, read-only preview, changed/missing destination recovery, source/destination overlap, symlink rejection, low space, explicit deletion confirmation, protected files and both-copy rechecks.

The native GUI is tested locally with an instrumented build and synthetic media files. GUI screenshots come from that app, not a mockup. Synthetic RAW bytes test preservation, not camera-format decoding. Automated CI covers engine tests and native compilation. Real Intel hardware, every supported macOS version and every card filesystem have not all been tested.

## Local data and privacy

The engine has no network requests. Preferences stay in macOS UserDefaults; import history contains relative destination paths, sizes, hashes and import timestamps. The activity log remains in the app window. Choosing a cloud-sync destination may cause that separate cloud client to upload files. GitHub links open your browser only when selected.
