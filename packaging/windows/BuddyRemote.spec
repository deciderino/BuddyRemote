# PyInstaller spec for the Windows build (run via packaging/windows/build-windows.sh,
# with a Windows Python: natively or under Wine). Result: onedir dist/win/BuddyRemote
# (BuddyRemote.exe + _internal), zipped by the script.
# Bundled: Python, PyQt6/Qt6 (QtCore/Gui/Widgets/Network + the plugins PyInstaller's hook
# collects), the MoonDeck CLI (bundled/moondeck-cli.exe, unmodified), SDL2.dll (zlib) for
# the gamepad in <bundle>/libsdl2 (gamepad.py points PYSDL2_DLL_PATH there), license texts.
# Not bundled: opengl32sw.dll (Mesa software OpenGL, only for Qt Quick / GL fallback) and
# d3dcompiler_47.dll; BuddyRemote is a Qt Widgets app and does not need them.
import os
ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
STAGE = os.path.join(ROOT, "build", "win-stage")

a = Analysis(
    [os.path.join(ROOT, "app.py")],
    pathex=[ROOT],
    binaries=[(os.path.join(STAGE, "libsdl2", "SDL2.dll"), "libsdl2")],
    hiddenimports=["sdl2"],
    datas=[
        (os.path.join(ROOT, "lang"), "lang"),
        (os.path.join(ROOT, "packaging", "default-config.json"), "packaging"),
        (os.path.join(ROOT, "packaging", "linux", "buddyremote.png"), "packaging"),
        (os.path.join(STAGE, "bundled"), "bundled"),
        (os.path.join(STAGE, "licenses"), "licenses"),
    ],
    # certifi: no own CA list is shipped; cacerts.py uses the Windows certificate store
    excludes=["tkinter", "sdl2dll", "sdl2.ext", "numpy", "PIL", "certifi"],
)

DROP = {"opengl32sw.dll", "d3dcompiler_47.dll"}
dropped = sorted({os.path.basename(b[0]) for b in a.binaries if os.path.basename(b[0]).lower() in DROP})
print("Not bundled:", " ".join(dropped) or "-")
a.binaries = [b for b in a.binaries if os.path.basename(b[0]).lower() not in DROP]

pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="BuddyRemote",
          console=False, strip=False, upx=False,
          icon=os.path.join(ROOT, "packaging", "windows", "buddyremote.ico"),
          version=os.path.join(STAGE, "version-info.txt"))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="BuddyRemote")
