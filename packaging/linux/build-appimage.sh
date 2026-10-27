#!/bin/bash
# Build BuddyRemote-x86_64.AppImage (PyInstaller onedir + appimagetool).
# Usage: packaging/linux/build-appimage.sh   (run from repo root, inside a venv with pyinstaller + PyQt6)
# Env: MOONDECK_CLI=/path/to/moondeck-cli-linux.bin  (bundled CLI, required)
#      MOONDECK_CLI_SHA256=<sha>                      (pinned checksum, required)
#      APPIMAGETOOL=/path/to/appimagetool
#      EXTRA_LIBS_DIR=/path/to/xcb-util-libs (optional; Ubuntu 22.04 libxcb-cursor0, -icccm4, -image0, -keysyms1, -render-util0, -util1)
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT="$PWD"; PKG="$ROOT/packaging/linux"; OUT="$ROOT/dist"
: "${MOONDECK_CLI:?set MOONDECK_CLI}"; : "${MOONDECK_CLI_SHA256:?set MOONDECK_CLI_SHA256}"
APPIMAGETOOL="${APPIMAGETOOL:-appimagetool}"
echo "$MOONDECK_CLI_SHA256  $MOONDECK_CLI" | sha256sum -c -

rm -rf build dist/BuddyRemote AppDir
mkdir -p build/bundled build/licenses
cp "$MOONDECK_CLI" build/bundled/moondeck-cli && chmod 755 build/bundled/moondeck-cli
cp "$PKG"/licenses/* build/licenses/
cp LICENSE build/licenses/BuddyRemote-GPL-3.0.txt
SP="$(python -c 'import site;print(site.getsitepackages()[0])')"
cp "$SP"/pyqt6-*.dist-info/licenses/LICENSE build/licenses/PyQt6-GPL-3.0.txt
cp "$SP"/pyqt6_qt6-*.dist-info/LICENSE build/licenses/Qt6-LGPL-3.0.txt
cp "$SP"/pyqt6_sip-*.dist-info/licenses/LICENSE build/licenses/PyQt6-sip-BSD-2-Clause.txt
python -c 'import sys;print(sys.version)' > build/licenses/python-version.txt
cp "$(python -c 'import sys,os;print(os.path.join(sys.base_prefix,"lib","python%d.%d" % sys.version_info[:2],"LICENSE.txt"))')" build/licenses/Python-PSF-LICENSE.txt

BR_ROOT="$ROOT" pyinstaller --noconfirm --clean --distpath "$OUT" --workpath build/pyi "$PKG/BuddyRemote.spec"

mkdir -p AppDir/usr/lib AppDir/usr/share/licenses/BuddyRemote
cp -a "$OUT/BuddyRemote" AppDir/usr/lib/
cp build/licenses/* AppDir/usr/share/licenses/BuddyRemote/
cp "$PKG/AppRun" AppDir/AppRun
cp "$PKG/buddyremote.desktop" AppDir/
cp "$PKG/buddyremote.png" AppDir/buddyremote.png
ARCH=x86_64 "$APPIMAGETOOL" --no-appstream AppDir "$OUT/BuddyRemote-x86_64.AppImage"
ls -la "$OUT/BuddyRemote-x86_64.AppImage"
