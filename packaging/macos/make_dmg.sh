#!/usr/bin/env bash
# Wraps dist/InsurancePolicyExtractor (PyInstaller onefolder build) into a
# distributable .dmg. The app is a local Flask server that opens itself in
# the default browser (no native window), so this just ships the folder
# with a symlink to /Applications for a familiar drag-to-install flow.
#
# Usage: packaging/macos/make_dmg.sh <output.dmg>
set -euo pipefail

OUT="${1:?usage: make_dmg.sh <output.dmg>}"
BUILD="dist/InsurancePolicyExtractor"
STAGE="$(mktemp -d)"

if [ ! -d "$BUILD" ]; then
  echo "error: $BUILD not found — run pyinstaller app.spec first" >&2
  exit 1
fi

mkdir -p "$STAGE/InsurancePolicyExtractor"
cp -R "$BUILD"/* "$STAGE/InsurancePolicyExtractor/"
ln -s /Applications "$STAGE/Applications"

rm -f "$OUT"
hdiutil create -volname "Insurance Policy Extractor" \
  -srcfolder "$STAGE" \
  -ov -format UDZO "$OUT"

rm -rf "$STAGE"
echo "Wrote $OUT"
