# PyInstaller spec for the Linux AppImage build (run via build-appimage.sh).
# Only Python + PyQt6/Qt (from the wheels) are bundled; host system libraries
# (glibc, libstdc++, X11/xcb, Wayland, GL, fontconfig, glib, dbus ...) are taken
# from the target distro, except the xcb-util libs from EXTRA_LIBS_DIR
# (Ubuntu 22.04 builds), which Qt's xcb plugin needs and many distros lack.
# Gamepad: the PySDL2 bindings (pure Python, public domain/zlib) go into the PYZ and
# libSDL2 (zlib) from build/libsdl2 goes to <bundle>/libsdl2, where app.py points
# PYSDL2_DLL_PATH. The pysdl2-dll wrapper package (sdl2dll) itself is not shipped.
import os, sys
ROOT = os.environ["BR_ROOT"]
BUILD = os.path.join(ROOT, "build")
EXTRA = os.environ.get("EXTRA_LIBS_DIR", "")
KEEP_PREFIXES = tuple(os.path.realpath(p) for p in {sys.prefix, sys.base_prefix, BUILD})

a = Analysis(
    [os.path.join(ROOT, "app.py")],
    pathex=[ROOT],
    binaries=[
        (os.path.join(BUILD, "libsdl2", "libSDL2-2.0.so"), "libsdl2"),
    ],
    hiddenimports=["sdl2"],
    datas=[
        (os.path.join(ROOT, "lang"), "lang"),
        (os.path.join(ROOT, "config.json"), "."),
        (os.path.join(BUILD, "bundled"), "bundled"),
        (os.path.join(BUILD, "licenses"), "licenses"),
    ],
    # certifi: no own CA list is shipped; cacerts.py uses the system CA store
    excludes=["tkinter", "sdl2dll", "sdl2.ext", "numpy", "PIL", "certifi"],
)

def _keep(entry):
    src = os.path.realpath(entry[1])
    return src.startswith(KEEP_PREFIXES)

dropped = sorted({os.path.basename(b[0]) for b in a.binaries if not _keep(b)})
print("Excluding host system libs:", " ".join(dropped))
a.binaries = [b for b in a.binaries if _keep(b)]
if EXTRA:
    for f in sorted(os.listdir(EXTRA)):
        if ".so" in f:
            a.binaries.append((f, os.path.join(EXTRA, f), "BINARY"))

pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="BuddyRemote",
          console=False, strip=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="BuddyRemote")
