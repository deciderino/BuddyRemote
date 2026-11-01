"""Shared by both PyInstaller specs: drop the Qt plugins and translations BuddyRemote
does not use. Qt Widgets app, HTTPS via Python's urllib/ssl (not Qt TLS), QtNetwork
only for QLocalServer/QLocalSocket, Qt's own translations only qtbase_<ui language>.

Kept: platforms xcb/wayland/windows + offscreen (headless tests/smoke runs), the
wayland-* and xcbglintegrations dirs, platformthemes (gtk3, xdgdesktopportal),
platforminputcontexts, styles, iconengines (svg theme icons) and the svg/ico image
formats (PNG is built into QtGui)."""
import os

UI_LANGS = ("cs", "de", "en", "es", "fr", "it", "ja", "ko")
KEEP_TRANSLATIONS = {f"qtbase_{c}.qm" for c in UI_LANGS}
KEEP_IMAGEFORMATS = ("qsvg", "qico")              # file stem starts with (lib)qsvg / (lib)qico
DROP_PLUGIN_DIRS = {"generic", "networkinformation", "tls", "egldeviceintegrations"}
DROP_PLATFORMS = ("qeglfs", "qlinuxfb", "qminimal", "qminimalegl", "qvnc", "qvkkhrdisplay")
DROP_LIBS = ("libQt6EglFSDeviceIntegration",)    # only used by the eglfs plugins


def _parts(dest):
    return dest.replace("\\", "/").split("/")


def _stem(name):
    name = name[3:] if name.startswith("lib") else name
    return name.split(".")[0]


def unused(dest):
    """True if the bundle path `dest` (relative, e.g. PyQt6/Qt6/plugins/tls/...) is dropped."""
    p = _parts(dest)
    if "Qt6" not in p:
        return False
    rest = p[p.index("Qt6") + 1:]
    name = rest[-1]
    if rest[0] == "translations":
        return name not in KEEP_TRANSLATIONS
    if rest[0] == "lib" and name.startswith(DROP_LIBS):
        return True
    if rest[0] != "plugins" or len(rest) < 3:
        return False
    kind = rest[1]
    if kind in DROP_PLUGIN_DIRS:
        return True
    if kind == "imageformats":
        return not _stem(name).startswith(KEEP_IMAGEFORMATS)
    if kind == "platforms":
        return _stem(name) in DROP_PLATFORMS
    return False


def trim(a):
    """Filter a PyInstaller Analysis' binaries and datas in place; print what was dropped."""
    gone = sorted({e[0] for e in list(a.binaries) + list(a.datas) if unused(e[0])})
    a.binaries = [e for e in a.binaries if not unused(e[0])]
    a.datas = [e for e in a.datas if not unused(e[0])]
    print(f"Qt trim: {len(gone)} files not bundled:", " ".join(os.path.basename(g) for g in gone))
