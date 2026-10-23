#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
ARCH="${1:-arm64}"
case "$ARCH" in arm64|x86_64) ;; *) echo 'Usage: scripts/build.sh [arm64|x86_64] [--testing]'; exit 1 ;; esac
python3 scripts/runtime.py "$ARCH"
APP="$PWD/build/$ARCH/CardDock.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
FLAGS=(-O -swift-version 5)
if [[ "${2:-}" == "--testing" ]]; then FLAGS+=(-D TESTING); fi
swiftc "${FLAGS[@]}" -target "$ARCH-apple-macos13.0" app/main.swift -framework Cocoa -o "$APP/Contents/MacOS/CardDock"
cp app/Info.plist "$APP/Contents/Info.plist"
cp sd_import.py "$APP/Contents/Resources/sd_import.py"
cp LICENSE "$APP/Contents/Resources/LICENSE"
cp THIRD_PARTY_NOTICES.md "$APP/Contents/Resources/THIRD_PARTY_NOTICES.md"
if [[ ! -d "$APP/Contents/Resources/python" ]]; then ditto ".cache/$ARCH/python" "$APP/Contents/Resources/python"; fi
ditto ".cache/$ARCH/python/licenses" "$APP/Contents/Resources/python/licenses"
cp ".cache/$ARCH/python/PYTHON.json" "$APP/Contents/Resources/python/PYTHON.json"
swiftc -O app/makeicon.swift -framework Cocoa -o build/makeicon
build/makeicon build/AppIcon.iconset
iconutil -c icns build/AppIcon.iconset -o "$APP/Contents/Resources/AppIcon.icns"
# Ad-hoc signing preserves bundle integrity. It is NOT Developer ID/notarization.
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"
if [[ "${2:-}" != "--testing" ]]; then
  mkdir -p dist
  ditto -c -k --sequesterRsrc --keepParent "$APP" "dist/CardDock-0.1.0-$ARCH.zip"
  shasum -a 256 "dist/CardDock-0.1.0-$ARCH.zip"
fi
