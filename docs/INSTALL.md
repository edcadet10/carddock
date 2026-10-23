# Install CardDock

## Download

Use [the latest GitHub release](https://github.com/edcadet10/carddock/releases/latest).
Choose `arm64` for Apple Silicon or `x86_64` for Intel. Download the **CardDock ZIP**, not GitHub's automatic “Source code” archive.

Unzip, drag `CardDock.app` into Applications, and open it. The app includes its own Python runtime; nothing else needs installing.

## First-launch macOS prompt

The free release uses an ad-hoc signature for bundle integrity. It has no paid Apple Developer ID certificate or notarization ticket. GitHub hosting does not change that.

1. Try opening CardDock once.
2. If macOS blocks the unidentified/unverified developer, open **System Settings → Privacy & Security**.
3. Find CardDock's blocked-app message and select **Open Anyway**.
4. Confirm that you intend to open CardDock. Authenticate if macOS asks.

This is Apple's documented exception for a specific app: [Safely open apps on your Mac](https://support.apple.com/102445). We do not recommend disabling Gatekeeper globally or running a pasted command to remove quarantine from arbitrary downloads. Work/school device policies may prevent the exception.

If macOS instead reports malware, a damaged app, or a revoked signature, do not treat that as the ordinary unidentified-developer prompt. Download again from this repository and report the exact message if it persists.

## Choose folders

- **From:** choose a connected drive from the menu, or use **Choose…** for a folder.
- **To:** choose your library folder. An external disk is supported; reconnect it before importing.
- **Preview:** checks contents and shows planned copies without changing source or destination files.
- **Import & Verify:** copies and verifies. Keeping originals is the default.

macOS may ask for access to removable disks or protected folders. Allow access to locations you selected. CardDock does not require Full Disk Access.

The app remembers folder bookmarks and checks volume identity when available. If a remembered destination cannot be resolved, it asks you to choose it again rather than silently using a different folder. Volume names can change; CardDock never renames disks.

## Optional checksum check

Each release includes `SHA256SUMS.txt`. To check an archive in Terminal:

```sh
cd ~/Downloads
shasum -a 256 CardDock-0.1.0-arm64.zip
```

Compare the result with the corresponding line in `SHA256SUMS.txt`. A checksum checks downloaded bytes against the published release; it is not Apple notarization or independent proof of publisher identity.

## Update / uninstall

Quit CardDock, download the new ZIP, and replace the app in Applications. There is no automatic updater. An updated non-notarized build may need another per-app exception.

To uninstall, quit and remove CardDock from Applications. Imported photos are unaffected. Preferences are stored under bundle ID `io.github.edcadet10.carddock`. Import history lives in `.carddock/imports.sqlite3` within each destination. Removing that history does not delete photographs, but changes the scope of duplicate lookup.
