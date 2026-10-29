#!/bin/bash
# Build BuddyRemote-x86_64.AppImage (PyInstaller onedir + appimagetool).
# Usage: packaging/linux/build-appimage.sh   (run from repo root, inside a venv with pyinstaller + PyQt6
#        + PySDL2 + pysdl2-dll; pysdl2-dll only provides the prebuilt libSDL2 that gets bundled)
# Env: MOONDECK_CLI=/path/to/moondeck-cli-linux.bin  (bundled CLI, required)
#      MOONDECK_CLI_SHA256=<sha>                      (pinned checksum, required)
#      MOONDECK_CLI_VERSION=nightly MOONDECK_CLI_COMMIT=00f8c31  (shown in Options; these are the defaults)
#      APPIMAGETOOL=/path/to/appimagetool
#      EXTRA_LIBS_DIR=/path/to/xcb-util-libs (optional; Ubuntu 22.04 libxcb-cursor0, -icccm4, -image0, -keysyms1, -render-util0, -util1)
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT="$PWD"; PKG="$ROOT/packaging/linux"; OUT="$ROOT/dist"
: "${MOONDECK_CLI:?set MOONDECK_CLI}"; : "${MOONDECK_CLI_SHA256:?set MOONDECK_CLI_SHA256}"
APPIMAGETOOL="${APPIMAGETOOL:-appimagetool}"
echo "$MOONDECK_CLI_SHA256  $MOONDECK_CLI" | sha256sum -c -

rm -rf build dist/BuddyRemote AppDir
mkdir -p build/bundled build/licenses build/libsdl2
cp "$MOONDECK_CLI" build/bundled/moondeck-cli && chmod 755 build/bundled/moondeck-cli
# Version info for the Options dialog ("MoonDeck CLI: bundled (nightly, commit 00f8c31)");
# the app also re-copies the CLI into the user dir when this file changes.
printf '{"version": "%s", "commit": "%s", "sha256": "%s"}\n' \
  "${MOONDECK_CLI_VERSION:-nightly}" "${MOONDECK_CLI_COMMIT:-00f8c31}" "$MOONDECK_CLI_SHA256" \
  > build/bundled/moondeck-cli.version
cp "$PKG"/licenses/* build/licenses/
cp LICENSE build/licenses/BuddyRemote-GPL-3.0.txt
SP="$(python -c 'import site;print(site.getsitepackages()[0])')"
# Gamepad: only libSDL2 (zlib) from the pysdl2-dll wheel is bundled, not SDL2_mixer/image/ttf/gfx
cp "$SP"/sdl2dll/dll/libSDL2-2.0.so build/libsdl2/
python -c 'import sdl2dll;print("libSDL2 from pysdl2-dll", sdl2dll.__version__)' > build/licenses/SDL2-version.txt
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
APP_VERSION="$(sed -n 's/^APP_VERSION = "\(.*\)"$/\1/p' app.py)"
: "${APP_VERSION:?APP_VERSION not found in app.py}"
cp "$PKG/buddyremote.desktop" AppDir/
echo "X-AppImage-Version=$APP_VERSION" >> AppDir/buddyremote.desktop
cp "$PKG/buddyremote.png" AppDir/buddyremote.png
ARCH=x86_64 VERSION="$APP_VERSION" "$APPIMAGETOOL" --no-appstream AppDir "$OUT/BuddyRemote-x86_64.AppImage"
ls -la "$OUT/BuddyRemote-x86_64.AppImage"
