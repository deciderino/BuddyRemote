"""Build the Windows package: dist/BuddyRemote-Windows-x86_64.zip (PyInstaller onedir).

Run with a *Windows* Python (natively, or under Wine via build-windows.sh) that has
pyinstaller, PyQt6, PySDL2 and pysdl2-dll installed:

    python packaging\\windows\\build.py --cli C:\\path\\moondeck-cli-win.exe --sha256 <sha>
           [--cli-version nightly] [--cli-commit 00f8c31] [--buddy-api 9]

Why onedir + zip (not onefile): starts fast, nothing is unpacked to %TEMP% on every start
(onefile self-extractors are a classic antivirus false-positive pattern), the HKCU Run
autostart points at a stable BuddyRemote.exe, and the bundled MoonDeck CLI runs straight
from the folder.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import sysconfig
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "packaging" / "windows"
STAGE = ROOT / "build" / "win-stage"
DIST = ROOT / "dist" / "win"
ASSET = "BuddyRemote-Windows-x86_64.zip"


def app_version():
    sys.path.insert(0, str(ROOT))
    from paths import APP_VERSION
    return APP_VERSION


def numeric_version(v):
    nums = []
    for part in v.split("-")[0].split("."):
        nums.append(int(part) if part.isdigit() else 0)
    return tuple((nums + [0, 0, 0, 0])[:4])


def version_info(v):
    n = numeric_version(v)
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={n}, prodvers={n}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'BuddyRemote'),
      StringStruct('FileDescription', 'BuddyRemote - MoonDeck Buddy remote control'),
      StringStruct('FileVersion', '{v}'),
      StringStruct('InternalName', 'BuddyRemote'),
      StringStruct('LegalCopyright', 'GPL-3.0-or-later'),
      StringStruct('OriginalFilename', 'BuddyRemote.exe'),
      StringStruct('ProductName', 'BuddyRemote'),
      StringStruct('ProductVersion', '{v}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])])
"""


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cli", required=True, help="moondeck-cli-win.exe")
    ap.add_argument("--sha256", required=True, help="pinned checksum of --cli")
    ap.add_argument("--cli-version", default="nightly")
    ap.add_argument("--cli-commit", default="00f8c31")
    ap.add_argument("--buddy-api", type=int, default=9)
    a = ap.parse_args()
    if sys.platform != "win32":
        sys.exit("build.py needs a Windows Python (native or under Wine)")
    got = sha256(a.cli)
    if got != a.sha256.lower():
        sys.exit(f"CLI checksum mismatch: {got} != {a.sha256}")
    print("CLI checksum OK", got)

    v = app_version()
    shutil.rmtree(STAGE, ignore_errors=True)
    shutil.rmtree(DIST, ignore_errors=True)
    for d in ("bundled", "licenses", "libsdl2"):
        (STAGE / d).mkdir(parents=True)
    shutil.copy2(a.cli, STAGE / "bundled" / "moondeck-cli.exe")
    (STAGE / "bundled" / "moondeck-cli.version").write_text(json.dumps(
        {"version": a.cli_version, "commit": a.cli_commit, "sha256": got,
         "buddy_api": a.buddy_api}) + "\n", encoding="utf-8")

    lic = STAGE / "licenses"
    linux_lic = ROOT / "packaging" / "linux" / "licenses"
    for name in ("MoonDeck-CLI-GPL-3.0.txt", "PySDL2-PublicDomain-zlib.txt"):
        shutil.copy2(linux_lic / name, lic / name)
    for f in (PKG / "licenses").iterdir():
        shutil.copy2(f, lic / f.name)
    shutil.copy2(ROOT / "LICENSE", lic / "BuddyRemote-GPL-3.0.txt")
    sp = Path(sysconfig.get_paths()["purelib"])
    shutil.copy2(sp / "sdl2dll" / "dll" / "SDL2.dll", STAGE / "libsdl2" / "SDL2.dll")
    import sdl2dll
    (lic / "SDL2-version.txt").write_text(f"SDL2.dll from pysdl2-dll {sdl2dll.__version__}\n")

    def dist_info(pattern, rel):
        hits = sorted(sp.glob(pattern))
        if not hits:
            sys.exit(f"missing {pattern}")
        return hits[0] / rel
    shutil.copy2(dist_info("pyqt6-*.dist-info", "licenses/LICENSE"), lic / "PyQt6-GPL-3.0.txt")
    shutil.copy2(dist_info("pyqt6_qt6-*.dist-info", "LICENSE"), lic / "Qt6-LGPL-3.0.txt")
    shutil.copy2(dist_info("pyqt6_sip-*.dist-info", "licenses/LICENSE"), lic / "PyQt6-sip-BSD-2-Clause.txt")
    (lic / "python-version.txt").write_text(sys.version + "\n")
    # Python's LICENSE.txt also carries the notices for OpenSSL, libffi, zlib, expat, ...
    shutil.copy2(Path(sys.base_prefix) / "LICENSE.txt", lic / "Python-PSF-LICENSE.txt")
    (STAGE / "version-info.txt").write_text(version_info(v), encoding="utf-8")

    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                    "--distpath", str(DIST), "--workpath", str(STAGE / "pyi"),
                    str(PKG / "BuddyRemote.spec")], check=True)

    app_dir = DIST / "BuddyRemote"
    if not (app_dir / "BuddyRemote.exe").is_file():
        sys.exit("BuddyRemote.exe missing")
    zpath = DIST / ASSET
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(app_dir.rglob("*")):
            if f.is_file():
                z.write(f, Path("BuddyRemote") / f.relative_to(app_dir))
    print(f"{zpath}  {zpath.stat().st_size} bytes  sha256 {sha256(zpath)}")


if __name__ == "__main__":
    main()
