#!/usr/bin/env bash
# Wraps dist/InsurancePolicyExtractor (PyInstaller onefolder build) into a
# universal AppImage: chmod +x + double-click, no install and no package
# manager needed, runs on most glibc-based distros regardless of version.
#
# Usage: packaging/linux/make_appimage.sh <output.AppImage>
set -euo pipefail

OUT="${1:?usage: make_appimage.sh <output.AppImage>}"
BUILD="dist/InsurancePolicyExtractor"
APPDIR="dist/AppDir"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -d "$BUILD" ]; then
  echo "error: $BUILD not found — run pyinstaller app.spec first" >&2
  exit 1
fi

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
cp -R "$BUILD"/* "$APPDIR/usr/bin/"

cp "$HERE/InsurancePolicyExtractor.desktop" "$APPDIR/InsurancePolicyExtractor.desktop"
cp assets/icon.png "$APPDIR/InsurancePolicyExtractor.png"

cat > "$APPDIR/AppRun" <<'EOF'
#!/usr/bin/env bash
HERE="$(dirname "$(readlink -f "${0}")")"
exec "$HERE/usr/bin/InsurancePolicyExtractor" "$@"
EOF
chmod +x "$APPDIR/AppRun"

if [ ! -x appimagetool ]; then
  curl -fL -o appimagetool \
    https://github.com/AppImage/AppImageKit/releases/latest/download/appimagetool-x86_64.AppImage
  chmod +x appimagetool
fi

# CI runners typically lack FUSE, which appimagetool's own AppImage needs to
# mount itself; --appimage-extract-and-run works everywhere without FUSE.
ARCH=x86_64 ./appimagetool --appimage-extract-and-run "$APPDIR" "$OUT"
echo "Wrote $OUT"
