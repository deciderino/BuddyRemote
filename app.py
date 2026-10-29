#!/usr/bin/env python3
"""
BuddyRemote – Portable host control for MoonDeck Buddy
"""

import json
import os
import sys
import subprocess
import threading
import time
import socket
import uuid
import logging
import random
import urllib.request
import hashlib
import shutil
from pathlib import Path

# Set process name so system monitor / KDE show "BuddyRemote" instead of python/app.py
try:
    import ctypes
    import ctypes.util
    libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6")
    libc.prctl(15, b"BuddyRemote", 0, 0, 0)  # PR_SET_NAME
except Exception:
    pass

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFrame, QScrollArea, QDialog, QFormLayout,
    QLineEdit, QCheckBox, QSpinBox, QMessageBox, QSystemTrayIcon, QMenu,
    QTextEdit, QComboBox, QAbstractButton, QStatusBar, QBoxLayout, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QEvent, QSettings
from PyQt6.QtGui import QIcon, QAction, QColor, QPalette, QPixmap, QPainter, QPen, QShortcut, QKeySequence, QFontMetrics

# ---------------------------------------------------------------------------
APP_DIR = Path(__file__).resolve().parent
# Packaging: read-only resources (lang/, default config, bundled CLI) live next to
# the code / inside the bundle; writable files go to a user dir when packaged.
RES_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
PACKAGED = bool(getattr(sys, "frozen", False) or os.environ.get("APPIMAGE"))
if PACKAGED:
    APP_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "BuddyRemote"
CONFIG_FILE = APP_DIR / "config.json"
CLI_DIR = APP_DIR / "cli"
CLI_BIN = CLI_DIR / "moondeck-cli"
CLI_SCRIPT = CLI_DIR / "cli.py"  # fallback
LANG_DIR = RES_DIR / "lang"
LOCK_FILE = APP_DIR / ".lock"
LOG_FILE = APP_DIR / "buddyremote.log"
WINDOW_STATE_FILE = APP_DIR / "window.ini"  # UI only: size/maximized/position

# ---------------------------------------------------------------------------
def prepare_packaged_dir():
    """Packaging only: create the user dir and seed it from the bundle on first start."""
    if not PACKAGED:
        return
    APP_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists() and (RES_DIR / "config.json").exists():
        shutil.copyfile(RES_DIR / "config.json", CONFIG_FILE)
    bundled_cli = RES_DIR / "bundled" / "moondeck-cli"
    if not CLI_BIN.exists() and bundled_cli.exists():
        CLI_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(bundled_cli, CLI_BIN)
        CLI_BIN.chmod(0o755)

def setup_logging(enabled: bool):
    handlers = [logging.FileHandler(LOG_FILE, encoding="utf-8")] if enabled else [logging.NullHandler()]
    logging.basicConfig(level=logging.DEBUG if enabled else logging.WARNING,
                        format="%(asctime)s [%(levelname)s] %(message)s",
                        handlers=handlers, force=True)

def load_lang(code="en") -> dict:
    path = LANG_DIR / f"{code}.json"
    if not path.exists():
        path = LANG_DIR / "en.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

L = load_lang()
def t(key, **kw):
    s = L.get(key, key)
    try:
        return s.format(**kw) if kw else s
    except Exception:
        return s


def wayland_session() -> bool:
    return bool(os.environ.get("WAYLAND_DISPLAY")) or os.environ.get("XDG_SESSION_TYPE") == "wayland"


def prefer_x11_enabled() -> bool:
    """Opt-in, default off: BUDDYREMOTE_X11=1/0 or prefer_x11 in window.ini."""
    env = os.environ.get("BUDDYREMOTE_X11")
    if env is not None:
        return env.strip().lower() in ("1", "true", "yes", "on")
    try:
        st = QSettings(str(WINDOW_STATE_FILE), QSettings.Format.IniFormat)
        return str(st.value("prefer_x11", "false")).lower() == "true"
    except Exception:
        return False


def apply_platform_preference():
    """UI only, before QApplication: Wayland does not let apps place their own
    window, so the saved position cannot be restored there. If the user opted in,
    use the X11 (XWayland) backend instead. An explicit QT_QPA_PLATFORM always wins."""
    if os.environ.get("QT_QPA_PLATFORM"):
        return
    if not (wayland_session() and os.environ.get("DISPLAY")):
        return
    if prefer_x11_enabled():
        os.environ["QT_QPA_PLATFORM"] = "xcb"


def touch_css(light: bool) -> str:
    """UI only: larger touch/TV-friendly controls and a clearly visible focus ring.
    Appended after each theme stylesheet so it overrides sizes, not colors."""
    acc = "#1565c0" if light else "#4fc3f7"
    focus_bg = "#d6e6fa" if light else "#1d3b4f"
    edit = "#e65100" if light else "#ffb74d"
    edit_bg = "#fff3e0" if light else "#2b2620"
    prim, prim_b, prim_h = ("#1565c0", "#0d47a1", "#1976d2") if light else ("#1f5f8b", "#2a7ab0", "#2670a3")
    return f"""
        QWidget {{ font-size: 15px; }}
        QPushButton {{ min-height: 32px; min-width: 24px; padding: 6px 10px; border-width: 2px; border-radius: 6px; }}
        QPushButton:focus {{ border: 2px solid {acc}; background: {focus_bg}; }}
        QPushButton[touchRole="action"] {{ min-width: 56px; }}
        QPushButton[touchRole="icon"] {{ min-width: 24px; padding: 6px 2px; }}
        QPushButton[primary="true"] {{ background: {prim}; color: #ffffff; border: 2px solid {prim_b}; }}
        QPushButton[primary="true"]:hover {{ background: {prim_h}; }}
        QPushButton[primary="true"]:focus {{ background: {prim_h}; border: 2px solid {acc}; }}
        QMessageBox QPushButton, QDialog QPushButton {{ min-width: 80px; }}
        QLineEdit, QSpinBox, QComboBox {{ min-height: 36px; padding: 4px 8px; border-width: 2px; border-radius: 4px; }}
        QDialog QLineEdit {{ min-width: 260px; }}
        QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border: 2px solid {acc}; }}
        QCheckBox {{ spacing: 12px; min-height: 34px; padding: 2px 6px; border: 2px solid transparent; border-radius: 6px; }}
        QCheckBox:focus {{ border: 2px solid {acc}; background: {focus_bg}; }}
        QCheckBox::indicator {{ width: 26px; height: 26px; }}
        QLineEdit[editMode="true"], QSpinBox[editMode="true"], QComboBox[editMode="true"] {{ border: 2px solid {edit}; background: {edit_bg}; }}
    """


class _DialogNavFilter(QObject):
    """UI only: controller-friendly focus handling inside dialogs.
    Fields (line edits, spin boxes, combo boxes) have two states:
      navigation = focused + highlighted; arrows move focus, Enter enters edit mode
      edit mode  = amber border; keys edit the value; Enter accepts, Escape reverts.
    Mouse click or typing a character enters edit mode immediately (desktop-first).
    Enter on a field never triggers the dialog's default button."""
    _ARROWS = (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Right)
    _ENTER = (Qt.Key.Key_Return, Qt.Key.Key_Enter)
    _MODS = (Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Meta,
             Qt.Key.Key_AltGr, Qt.Key.Key_CapsLock, Qt.Key.Key_NumLock)

    def __init__(self, dlg: QDialog):
        super().__init__(dlg)
        self.dlg = dlg
        self.fields = set()
        self.saved = {}
        for w in dlg.findChildren(QWidget):
            if isinstance(w, (QLineEdit, QSpinBox, QComboBox)) and not isinstance(w.parent(), (QSpinBox, QComboBox)):
                self.fields.add(w)
                w.setProperty("editMode", False)
                w.installEventFilter(self)
                if isinstance(w, QSpinBox):
                    w.lineEdit().installEventFilter(self)  # mouse clicks land on the inner edit
            elif isinstance(w, QAbstractButton):
                w.installEventFilter(self)

    @staticmethod
    def _value(w):
        if isinstance(w, QLineEdit):
            return w.text()
        if isinstance(w, QSpinBox):
            return w.value()
        return w.currentIndex()

    @staticmethod
    def _restore(w, v):
        if isinstance(w, QLineEdit):
            w.setText(v)
        elif isinstance(w, QSpinBox):
            w.setValue(v)
        else:
            w.setCurrentIndex(v)

    def editing(self, w) -> bool:
        return bool(w.property("editMode"))

    def _set_edit(self, w, on: bool):
        if self.editing(w) == on:
            return
        if on:
            self.saved[w] = self._value(w)
        w.setProperty("editMode", on)
        w.style().unpolish(w)
        w.style().polish(w)
        w.update()

    def _move(self, forward: bool):
        self.dlg.focusNextPrevChild(forward)
        fw = QApplication.focusWidget()
        p = fw.parent() if fw else None
        while p is not None and p is not self.dlg:
            if isinstance(p, QScrollArea):
                p.ensureWidgetVisible(fw)
                break
            p = p.parent()

    def eventFilter(self, obj, ev):
        et = ev.type()
        field = obj if obj in self.fields else (obj.parent() if obj.parent() in self.fields else None)
        if field is None:  # buttons / checkboxes: arrows move focus, Enter on a checkbox toggles it
            if et == QEvent.Type.KeyPress and not ev.modifiers() & ~Qt.KeyboardModifier.KeypadModifier:
                if ev.key() in self._ARROWS:
                    self._move(ev.key() in (Qt.Key.Key_Down, Qt.Key.Key_Right))
                    return True
                if ev.key() in self._ENTER and isinstance(obj, QCheckBox):
                    obj.click()
                    return True
            return False
        if et == QEvent.Type.MouseButtonPress and not isinstance(field, QComboBox):
            self._set_edit(field, True)
        elif et == QEvent.Type.FocusIn and obj is field:
            if ev.reason() == Qt.FocusReason.MouseFocusReason and not isinstance(field, QComboBox):
                self._set_edit(field, True)
        elif et == QEvent.Type.FocusOut and obj is field:
            if ev.reason() != Qt.FocusReason.PopupFocusReason:
                self._set_edit(field, False)  # leaving a field keeps (accepts) its value
        elif et == QEvent.Type.KeyPress and obj is field:
            key = ev.key()
            if self.editing(field):
                if key in self._ENTER:
                    self._set_edit(field, False)
                    return True
                if key == Qt.Key.Key_Escape:
                    self._restore(field, self.saved.get(field, self._value(field)))
                    self._set_edit(field, False)
                    return True
                return False
            # navigation mode
            if key in self._ARROWS and not ev.modifiers() & ~Qt.KeyboardModifier.KeypadModifier:
                self._move(key in (Qt.Key.Key_Down, Qt.Key.Key_Right))
                return True
            if key in self._ENTER:
                self._set_edit(field, True)
                le = field if isinstance(field, QLineEdit) else (field.lineEdit() if isinstance(field, QSpinBox) else None)
                if le is not None:
                    le.deselect()
                    le.end(False)  # cursor at the end, ready to edit with arrows/keyboard
                return True
            if key in (Qt.Key.Key_Escape, Qt.Key.Key_Tab, Qt.Key.Key_Backtab) or key in self._MODS:
                return False
            self._set_edit(field, True)  # typing / Backspace / paste etc. edits right away
            return False
        return False


def install_dialog_nav(dlg: QDialog):
    dlg._nav_filter = _DialogNavFilter(dlg)


def fit_dialog_to_screen(dlg: QDialog):
    """UI only: if a dialog is taller than ~90% of the screen (e.g. Steam Deck at 150%),
    move its contents into a scroll area so nothing ends up off-screen."""
    scr = dlg.screen() or QApplication.primaryScreen()
    if not scr or not dlg.layout():
        return
    max_h = int(scr.availableGeometry().height() * 0.9)
    if dlg.sizeHint().height() <= max_h:
        return
    inner = QWidget()
    inner.setLayout(dlg.layout())  # reparents the existing layout and its widgets
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.Shape.NoFrame)
    sa.setWidget(inner)
    inner.setObjectName("fitInner")
    sa.setStyleSheet("QScrollArea, QWidget#qt_scrollarea_viewport, QWidget#fitInner { background: transparent; }")
    outer = QVBoxLayout(dlg)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.addWidget(sa)
    dlg.resize(inner.sizeHint().width() + sa.verticalScrollBar().sizeHint().width() + 4, max_h)


def dialog_stylesheet(parent=None) -> str:
    """Return a stylesheet for dialogs based on the current theme."""
    light = False
    if parent and hasattr(parent, "cfg"):
        light = parent.cfg.get("settings", {}).get("theme", "Dark") == "Light"
    if light:
        return """
            QDialog, QMessageBox { background: #f5f5f5; color: #222; }
            QLabel { color: #222; }
            QPushButton { background: #e0e0e0; color: #222; border: 1px solid #ccc; padding: 4px 8px; border-radius: 3px; }
            QPushButton:hover { background: #d0d0d0; }
            QLineEdit, QSpinBox, QComboBox { background: #ffffff; color: #222; border: 1px solid #ccc; padding: 3px; }
            QCheckBox { color: #222; }
            QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #888; border-radius: 3px; background: #fff; }
            QCheckBox::indicator:checked { background: #4caf50; border-color: #388e3c; }
            QCheckBox::indicator:checked:hover { background: #66bb6a; }
        """ + touch_css(True)
    else:
        return """
            QDialog, QMessageBox { background: #1e1e1e; color: #e0e0e0; }
            QLabel { color: #e0e0e0; }
            QPushButton { background: #2d2d2d; color: #e0e0e0; border: 1px solid #444; padding: 4px 8px; border-radius: 3px; }
            QPushButton:hover { background: #3d3d3d; }
            QLineEdit, QSpinBox, QComboBox { background: #2a2a2a; color: #e0e0e0; border: 1px solid #444; padding: 3px; }
            QCheckBox { color: #e0e0e0; }
            QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #666; border-radius: 3px; background: #2a2a2a; }
            QCheckBox::indicator:checked { background: #4caf50; border-color: #388e3c; }
            QCheckBox::indicator:checked:hover { background: #66bb6a; }
        """ + touch_css(False)


# ---------------------------------------------------------------------------
DEFAULT_CONFIG = {
    "version": 1,
    "settings": {
        "status_interval": 30,
        "auto_status": True,
        "logging": False,
        "start_minimized": True,
        "language": "en",
        "autostart": False,
        "confirm_actions": True,
        "tray_color_change": True,
        "client_id": "",
        "theme": "Dark",
        "cli_verified": False,
        "cli_hash": "",
        "cli_verified_at": ""
    },
    "hosts": []
}

def load_config() -> dict:
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        return json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        data.setdefault("settings", {})
        for k, v in DEFAULT_CONFIG["settings"].items():
            data["settings"].setdefault(k, v)
        data.setdefault("hosts", [])
        return data
    except Exception:
        logging.exception("config load failed")
        return json.loads(json.dumps(DEFAULT_CONFIG))

def save_config(cfg: dict):
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    tmp.replace(CONFIG_FILE)

# ---------------------------------------------------------------------------
def cli_available() -> bool:
    return CLI_BIN.exists() or CLI_SCRIPT.exists()

def run_cli(args: list, timeout=90, config_override: Path | None = None) -> tuple[int, str, str]:
    if not cli_available():
        return -1, "", t("cli_not_found")
    cfg = str(config_override or CONFIG_FILE)
    if CLI_BIN.exists():
        cmd = [str(CLI_BIN), "--config-file", cfg] + args
    else:
        cmd = [sys.executable, str(CLI_SCRIPT), "--config-file", cfg] + args
    logging.debug("CLI %s", cmd)
    try:
        p = subprocess.run(cmd, cwd=str(CLI_DIR), capture_output=True, text=True, timeout=timeout)
        logging.debug("CLI rc=%s", p.returncode)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Timeout"
    except Exception as e:
        logging.exception("CLI error")
        return -1, "", str(e)

def ping_host(ip: str, port: int = 59999, timeout=2.0) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except Exception:
        return False

def check_buddy_api(ip: str, port: int = 59999, timeout=5.0) -> tuple[bool, str]:
    """Direct HTTPS check to Buddy, ignoring self-signed cert. Returns (ok, message)."""
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    url = f"https://{ip}:{port}/apiVersion"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            body = r.read().decode(errors="replace")[:200]
            return True, body
    except Exception as e:
        return False, str(e)

def acquire_lock() -> bool:
    if LOCK_FILE.exists():
        try:
            os.kill(int(LOCK_FILE.read_text().strip()), 0)
            return False
        except (OSError, ValueError):
            pass
    LOCK_FILE.write_text(str(os.getpid()))
    return True

def release_lock():
    LOCK_FILE.unlink(missing_ok=True)

def verify_existing_cli() -> tuple[bool, str]:
    """Re-check the already downloaded CLI against the current GitHub digest."""
    if not CLI_BIN.exists():
        return False, "CLI not found"
    try:
        API_URL = "https://api.github.com/repos/FrogTheFrog/moondeck/releases/tags/nightly"
        with urllib.request.urlopen(API_URL, timeout=15) as r:
            data = json.loads(r.read().decode())
        expected = ""
        for a in data.get("assets", []):
            if a.get("name") == "moondeck-cli-linux.bin":
                expected = a.get("digest", "").split(":")[-1]
                break
        if not expected:
            return False, "No official checksum available"
        h = hashlib.sha256()
        with open(CLI_BIN, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        actual = h.hexdigest()
        if actual != expected:
            return False, f"Mismatch\nExpected: {expected[:16]}…\nGot: {actual[:16]}…"
        # Save result
        cfg = load_config()
        cfg["settings"]["cli_verified"] = True
        cfg["settings"]["cli_hash"] = actual
        cfg["settings"]["cli_verified_at"] = time.strftime("%Y-%m-%d %H:%M")
        save_config(cfg)
        return True, f"Verified\n{actual[:16]}…"
    except Exception as e:
        return False, str(e)

def download_cli(progress_cb=None) -> bool:
    """Download and verify the MoonDeck CLI binary. Returns True on success."""
    CLI_RELEASE = "nightly"
    CLI_URL = f"https://github.com/FrogTheFrog/moondeck/releases/download/{CLI_RELEASE}/moondeck-cli-linux.bin"
    API_URL = f"https://api.github.com/repos/FrogTheFrog/moondeck/releases/tags/{CLI_RELEASE}"
    SOURCE = "github.com/FrogTheFrog/moondeck"

    CLI_DIR.mkdir(parents=True, exist_ok=True)
    dest = CLI_DIR / "moondeck-cli"

    def status(msg, pause=1.2):
        if progress_cb:
            progress_cb(msg)
        time.sleep(pause)

    try:
        status(f"Preparing MoonDeck CLI\nSource: {SOURCE}\nRelease: {CLI_RELEASE}")

        status("Fetching release information...")
        with urllib.request.urlopen(API_URL, timeout=15) as r:
            data = json.loads(r.read().decode())
        expected = ""
        for a in data.get("assets", []):
            if a.get("name") == "moondeck-cli-linux.bin":
                expected = a.get("digest", "").split(":")[-1]
                break

        if expected:
            status(f"Expected checksum:\n{expected[:16]}…")
        else:
            status("No official checksum available\n(download continues)")

        status(f"Downloading\nmoondeck-cli-linux.bin\nfrom {SOURCE}")
        urllib.request.urlretrieve(CLI_URL, dest)
        dest.chmod(0o755)

        if expected:
            status("Verifying checksum…")
            h = hashlib.sha256()
            with open(dest, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            actual = h.hexdigest()
            if actual != expected:
                dest.unlink(missing_ok=True)
                status("Checksum mismatch!\nDownload aborted.", pause=2.0)
                return False
            status(f"Checksum verified\n{actual[:16]}…", pause=1.5)
            # Persist verification result
            try:
                cfg = load_config()
                cfg["settings"]["cli_verified"] = True
                cfg["settings"]["cli_hash"] = actual
                cfg["settings"]["cli_verified_at"] = time.strftime("%Y-%m-%d %H:%M")
                save_config(cfg)
            except Exception:
                pass
        else:
            status("No checksum to verify\n(file saved)", pause=1.5)

        status("MoonDeck CLI ready.", pause=1.2)
        return True
    except Exception as e:
        logging.exception("CLI download failed")
        status(f"Download failed:\n{e}", pause=2.5)
        return False

def ensure_client_id(cfg: dict) -> str:
    """Generate and store a unique client ID if missing."""
    cid = cfg["settings"].get("client_id", "")
    if not cid:
        cid = f"buddyremote-{uuid.uuid4().hex[:8]}"
        cfg["settings"]["client_id"] = cid
        save_config(cfg)
    return cid

def set_autostart(enabled: bool):
    d = Path.home() / ".config" / "autostart"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "buddyremote.desktop"
    launcher = os.environ.get("APPIMAGE") or (sys.executable if getattr(sys, "frozen", False) else APP_DIR / "BuddyRemote")
    if enabled:
        f.write_text(f"""[Desktop Entry]
Type=Application
Name=BuddyRemote
Exec={launcher}
Terminal=false
Icon=buddyremote
X-GNOME-Autostart-enabled=true
StartupWMClass=BuddyRemote
""")
    else:
        f.unlink(missing_ok=True)

# ---------------------------------------------------------------------------
class Signals(QObject):
    status_update = pyqtSignal(str, str)  # host_id, status_text
    action_done = pyqtSignal(str, bool, str)  # title, success, message

# ---------------------------------------------------------------------------
# UI only: colours for the main window (cards, status dots, toasts, status bar)
def ui_colors(light: bool) -> dict:
    if light:
        return dict(card="#ffffff", card_b="#dcdcdc", cur="#eaf2fc", cur_b="#1565c0", name="#222222",
                    pill="#e8e8e8", pill_t="#555555", sub="#666666", err="#c62828",
                    online="#43a047", offline="#9e9e9e", busy="#ffb300", error="#e53935", unknown="#c8c8c8",
                    bar="#ececec", bar_b="#d0d0d0", bar_t="#555555", tb_b="#d8d8d8",
                    ok_bg="#e8f5e9", ok_b="#43a047", ok_t="#1b5e20",
                    er_bg="#ffebee", er_b="#e53935", er_t="#b71c1c",
                    in_bg="#fff8e1", in_b="#ffb300", in_t="#5d4037", dim="#666666")
    return dict(card="#262626", card_b="#303030", cur="#24313a", cur_b="#4fc3f7", name="#ffffff",
                pill="#333333", pill_t="#bbbbbb", sub="#9a9a9a", err="#ef9a9a",
                online="#43a047", offline="#757575", busy="#ffb300", error="#e53935", unknown="#4a4a4a",
                bar="#252525", bar_b="#333333", bar_t="#aaaaaa", tb_b="#2e2e2e",
                ok_bg="#2e3b2f", ok_b="#43a047", ok_t="#e6e6e6",
                er_bg="#3b2a2a", er_b="#e53935", er_t="#e6e6e6",
                in_bg="#3a3424", in_b="#ffb300", in_t="#e6e6e6", dim="#a8a8a8")


class _ResizeWatcher(QObject):
    """UI only: calls back when a widget is resized (used for responsive host cards)."""
    def __init__(self, target, callback):
        super().__init__(target)
        self._cb = callback
        target.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Resize:
            self._cb()
        return False


class HostRow(QFrame):
    """One host as a card: status dot, name + IP pill, status line, and one visible
    button per existing action. UI only; every button calls the same handler as before."""
    def __init__(self, host: dict, parent_app):
        super().__init__()
        self.host = host
        self.app = parent_app
        self.setObjectName("hostCard")
        self.setProperty("current", False)
        self.state = "unknown"      # UI only: online / offline / unknown (last status check)
        self.busy = False           # UI only: an action is running for this host
        self.failed = False         # UI only: the last action failed

        # UI only: [head | buttons] side by side; on narrow windows the buttons wrap
        # onto a second line under the name (set_compact), so nothing gets cut off.
        self._outer = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self._outer.setContentsMargins(14, 10, 10, 10)
        self._outer.setSpacing(6)
        self._compact = False
        head = QHBoxLayout()
        head.setSpacing(6)
        self._head = head
        layout = QHBoxLayout()
        layout.setSpacing(6)
        self._btns = layout
        self.nav_buttons = []  # UI only: arrow-key navigation order

        self.dot = QLabel()
        self.dot.setFixedSize(14, 14)
        head.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addSpacing(4)

        info = QVBoxLayout()
        info.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.name_lbl = QLabel(host.get("name", "Unnamed"))
        self.name_lbl.setObjectName("hostName")
        self.name_lbl.setWordWrap(True)
        nf = self.name_lbl.font()
        nf.setBold(True)
        nf.setPixelSize(16)
        self.name_lbl.setMinimumWidth(min(QFontMetrics(nf).horizontalAdvance(self.name_lbl.text()) + 6, 220))
        self.ip_lbl = QLabel(host.get("ip", ""))
        self.ip_lbl.setObjectName("ipPill")
        top.addWidget(self.name_lbl, 0)
        top.addWidget(self.ip_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addStretch(1)
        self.status_lbl = QLabel()
        self.status_lbl.setObjectName("hostSub")
        self.status_lbl.setWordWrap(True)
        self.error_lbl = QLabel()
        self.error_lbl.setObjectName("hostError")
        self.error_lbl.setWordWrap(True)
        self.error_lbl.hide()
        info.addLayout(top)
        info.addWidget(self.status_lbl)
        info.addWidget(self.error_lbl)
        head.addLayout(info, 1)
        self._outer.addLayout(head, 1)
        self._outer.addLayout(layout, 0)
        self._status_text = t("unknown")
        self._checked = ""

        # Action buttons (same handlers as before)
        for act, label in [("wake", t("wake")), ("shutdown", t("shutdown")),
                           ("restart", t("restart")), ("suspend", t("suspend"))]:
            btn = QPushButton(label)
            btn.setProperty("touchRole", "action")  # min width via touch_css
            if act == "wake":
                btn.setProperty("primary", True)
            btn.setToolTip(t(f"tip_{act}"))
            btn.clicked.connect(lambda _, a=act: self.app.do_action(self.host, a))
            btn.installEventFilter(self.app)
            self.nav_buttons.append(btn)
            layout.addWidget(btn)

        layout.addSpacing(6)
        # Controls
        for text, tip, slot in [("↑", "tip_up", lambda: self.app.move_host(self.host, -1)),
                                ("↓", "tip_down", lambda: self.app.move_host(self.host, 1)),
                                ("✎", "tip_edit", lambda: self.app.edit_host(self.host)),
                                ("✕", "tip_remove", lambda: self.app.remove_host(self.host))]:
            b = QPushButton(text)
            b.setProperty("touchRole", "icon")
            b.setFixedWidth(40)
            b.setToolTip(t(tip))
            b.clicked.connect(slot)
            b.installEventFilter(self.app)
            self.nav_buttons.append(b)
            layout.addWidget(b)
        layout.addStretch(1)  # compact mode: keep buttons left-aligned under the name

        self._apply_row_theme()
        self._render()

    # --- UI only: responsive layout -----------------------------------------
    def _btns_width(self) -> int:
        b = self._btns
        n = sum(1 for i in range(b.count()) if b.itemAt(i).widget())
        w = sum(b.itemAt(i).widget().sizeHint().width() for i in range(b.count()) if b.itemAt(i).widget())
        return w + b.spacing() * max(0, n - 1) + 6  # + the spacer between the groups

    def _indent(self) -> int:
        return self.dot.width() + 4 + self._head.spacing()

    def wide_width(self) -> int:
        # Width needed to show name and all buttons on one line.
        m = self._outer.contentsMargins()
        return m.left() + m.right() + self._head.minimumSize().width() + 6 + self._btns_width()

    def compact_width(self) -> int:
        # Smallest sensible width: buttons on their own line, never cut off.
        m = self._outer.contentsMargins()
        return m.left() + m.right() + max(self._head.minimumSize().width(), self._indent() + self._btns_width())

    def compact_height(self) -> int:
        m = self._outer.contentsMargins()
        bh = max(self.nav_buttons[0].sizeHint().height(), self.nav_buttons[-1].sizeHint().height())
        return m.top() + m.bottom() + self._head.sizeHint().height() + 8 + bh

    def set_compact(self, on: bool):
        if on == self._compact:
            return
        self._compact = on
        self._outer.setDirection(QBoxLayout.Direction.TopToBottom if on else QBoxLayout.Direction.LeftToRight)
        self._outer.setSpacing(8 if on else 6)
        self._btns.setContentsMargins(self._indent() if on else 0, 0, 0, 0)
        self._outer.setStretch(0, 0 if on else 1)

    def _light(self) -> bool:
        return self.app.cfg.get("settings", {}).get("theme", "Dark") == "Light"

    def _apply_row_theme(self):
        c = ui_colors(self._light())
        self.setStyleSheet(f"""
            QFrame#hostCard {{ background: {c['card']}; border: 1px solid {c['card_b']}; border-radius: 8px; }}
            QFrame#hostCard[current="true"] {{ background: {c['cur']}; border: 1px solid {c['cur_b']}; }}
            QFrame#hostCard QLabel {{ background: transparent; border: none; }}
            QFrame#hostCard QLabel#hostName {{ font-weight: bold; font-size: 16px; color: {c['name']}; }}
            QFrame#hostCard QLabel#ipPill {{ font-size: 12px; color: {c['pill_t']}; background: {c['pill']}; border-radius: 9px; padding: 1px 8px; }}
            QFrame#hostCard QLabel#hostSub {{ font-size: 13px; color: {c['sub']}; }}
            QFrame#hostCard QLabel#hostError {{ font-size: 13px; color: {c['err']}; }}
        """)
        self._render()

    def _render(self):
        """UI only: paint dot and status line from the current UI state."""
        if not hasattr(self, "dot"):
            return
        c = ui_colors(self._light())
        if self.busy:
            col = c["busy"]
        elif self.failed:
            col = c["error"]
        else:
            col = c.get(self.state, c["unknown"])
        self.dot.setStyleSheet(f"background: {col}; border-radius: 7px; border: none;")
        if self.busy:
            parts = ["⟳ " + t("working")]
        else:
            parts = [self._status_text]
            if self._checked:
                parts.append(t("checked_at", time=self._checked))
        if not self.host.get("mac"):
            parts.append(t("no_mac_short"))
        self.status_lbl.setText(" · ".join(parts))

    def set_status(self, text: str):
        self._status_text = text
        self.state = "online" if text == t("online") else ("offline" if text == t("offline") else "unknown")
        self._checked = time.strftime("%H:%M:%S")
        self.failed = False
        self._render()
        self.app._update_counts()

    def set_busy(self, on: bool):
        self.busy = on
        if on:
            self.failed = False
            self.error_lbl.hide()
        self._render()

    def set_failed(self, text: str):
        self.busy = False
        self.failed = True
        self.error_lbl.setText("⚠ " + text)
        self.error_lbl.setToolTip(text)
        self.error_lbl.show()
        self._render()

    def set_current(self, on: bool):
        if bool(self.property("current")) == on:
            return
        self.setProperty("current", on)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()


class Toast(QFrame):
    """UI only: non-blocking feedback in the main window (bottom right), fades out
    automatically; click to dismiss. kind: ok (green), error (red), info (amber)."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("toast")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(2)
        self.title = QLabel()
        self.title.setWordWrap(True)
        self.title.setObjectName("toastTitle")
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        self.detail.setObjectName("toastDetail")
        lay.addWidget(self.title)
        lay.addWidget(self.detail)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)
        self.hide()

    def show_message(self, title: str, detail: str, kind: str, light: bool, ms: int):
        c = ui_colors(light)
        bg, b, fg = {"ok": ("ok_bg", "ok_b", "ok_t"), "error": ("er_bg", "er_b", "er_t"),
                     "info": ("in_bg", "in_b", "in_t")}[kind]
        icon = {"ok": "✓", "error": "⚠", "info": "ℹ"}[kind]
        self.setStyleSheet(f"""
            QFrame#toast {{ background: {c[bg]}; border: 1px solid {c[b]}; border-radius: 8px; }}
            QFrame#toast QLabel {{ background: transparent; border: none; color: {c[fg]}; }}
            QLabel#toastTitle {{ font-size: 14px; font-weight: bold; }}
            QLabel#toastDetail {{ font-size: 13px; color: {c['dim']}; }}
        """)
        self.title.setText(f"{icon}  {title}")
        self.detail.setText(detail)
        self.detail.setVisible(bool(detail))
        self.place()
        self.show()
        self.raise_()
        self.timer.start(ms)

    def place(self):
        par = self.parentWidget()
        if not par:
            return
        w = min(380, max(220, par.width() - 28))
        self.setFixedWidth(w)
        self.adjustSize()
        bottom = getattr(par.window(), "_toast_bottom", lambda: par.height() - 14)()
        self.move(par.width() - w - 14, bottom - self.height())

    def mousePressEvent(self, ev):
        self.hide()

# ---------------------------------------------------------------------------
class HostDialog(QDialog):
    def __init__(self, host: dict | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("edit_host") if host else t("add_host"))
        self.setStyleSheet(dialog_stylesheet(parent))
        self.host = host
        layout = QFormLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        self.name_edit = QLineEdit(host.get("name", "") if host else "")
        self.ip_edit = QLineEdit(host.get("ip", "") if host else "")
        self.mac_edit = QLineEdit(host.get("mac") or "" if host else "")
        self.port_edit = QLineEdit(str(host.get("buddy_port", 59999)) if host else "59999")

        layout.addRow(t("name"), self.name_edit)
        layout.addRow(t("ip"), self.ip_edit)
        layout.addRow(t("mac"), self.mac_edit)
        layout.addRow(t("buddy_port"), self.port_edit)

        btns = QHBoxLayout()
        save_btn = QPushButton(t("save"))
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton(t("cancel"))
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(save_btn)
        btns.addWidget(cancel_btn)
        layout.addRow(btns)
        install_dialog_nav(self)
        fit_dialog_to_screen(self)

    def get_data(self) -> dict | None:
        ip = self.ip_edit.text().strip()
        if not ip:
            return None
        return {
            "id": self.host.get("id") if self.host else uuid.uuid4().hex[:8],
            "name": self.name_edit.text().strip() or ip,
            "ip": ip,
            "mac": self.mac_edit.text().strip() or None,
            "buddy_port": int(self.port_edit.text() or 59999)
        }

# ---------------------------------------------------------------------------
class OptionsDialog(QDialog):
    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("options"))
        self.setStyleSheet(dialog_stylesheet(parent))
        layout = QFormLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        self.interval = QSpinBox()
        self.interval.setRange(10, 300)
        self.interval.setValue(settings.get("status_interval", 30))
        layout.addRow(t("interval"), self.interval)

        self.auto = QCheckBox(t("auto_refresh"))
        self.auto.setChecked(settings.get("auto_status", True))
        layout.addRow(self.auto)

        self.logging = QCheckBox(t("enable_logging"))
        self.logging.setChecked(settings.get("logging", False))
        layout.addRow(self.logging)

        self.start_min = QCheckBox(t("start_min"))
        self.start_min.setChecked(settings.get("start_minimized", True))
        layout.addRow(self.start_min)

        self.autostart = QCheckBox(t("autostart"))
        self.autostart.setChecked(settings.get("autostart", False))
        layout.addRow(self.autostart)

        self.confirm = QCheckBox(t("confirm_actions"))
        self.confirm.setChecked(settings.get("confirm_actions", True))
        layout.addRow(self.confirm)

        self.tray_color = QCheckBox(t("tray_color_change"))
        self.tray_color.setChecked(settings.get("tray_color_change", True))
        layout.addRow(self.tray_color)

        # Opt-in prototype (UI/window handling only, stored in window.ini, not config.json):
        # on a Wayland desktop, run through XWayland so the window position can be restored.
        self.prefer_x11 = None
        if wayland_session():
            self.prefer_x11 = QCheckBox(t("prefer_x11"))
            self.prefer_x11.setToolTip(t("prefer_x11_tip"))
            self.prefer_x11.setChecked(prefer_x11_enabled())
            layout.addRow(self.prefer_x11)

        self.theme = QComboBox()
        self.theme.addItems(["Dark", "Light"])
        self.theme.setCurrentText(settings.get("theme", "Dark"))
        layout.addRow("Theme", self.theme)

        about_btn = QPushButton("About")
        about_btn.clicked.connect(lambda: parent.show_about() if parent else None)
        layout.addRow(about_btn)

        # CLI verification status
        verified = settings.get("cli_verified", False)
        vhash = settings.get("cli_hash", "")
        vtime = settings.get("cli_verified_at", "")
        status_text = "Verified" if verified else "Not verified"
        if vhash:
            status_text += f" ({vhash[:16]}…)"
        if vtime:
            status_text += f"\n{vtime}"
        self.verify_label = QLabel(status_text)
        self.verify_label.setStyleSheet("color: #4caf50;" if verified else "color: #888;")
        layout.addRow("CLI checksum:", self.verify_label)

        verify_btn = QPushButton("Verify checksum")
        verify_btn.clicked.connect(self._do_verify)
        layout.addRow(verify_btn)

        btns = QHBoxLayout()
        save = QPushButton(t("save"))
        save.clicked.connect(self.accept)
        cancel = QPushButton(t("cancel"))
        cancel.clicked.connect(self.reject)
        btns.addWidget(save)
        btns.addWidget(cancel)
        layout.addRow(btns)
        install_dialog_nav(self)
        fit_dialog_to_screen(self)

    def accept(self):
        # UI only: persist the opt-in X11 window mode (takes effect after a restart)
        if self.prefer_x11 is not None and self.prefer_x11.isChecked() != prefer_x11_enabled():
            try:
                st = QSettings(str(WINDOW_STATE_FILE), QSettings.Format.IniFormat)
                st.setValue("prefer_x11", "true" if self.prefer_x11.isChecked() else "false")
                st.sync()
                par = self.parent()  # shown after the "Settings saved" toast
                QTimer.singleShot(3200, lambda: notify(par, t("restart_needed"), kind="ok"))
            except Exception:
                logging.exception("window state save failed")
        super().accept()

    def _do_verify(self):
        ok, msg = verify_existing_cli()
        if ok:
            # Reload to get the just-saved timestamp and hash
            cfg = load_config()
            vhash = cfg["settings"].get("cli_hash", "")
            vtime = cfg["settings"].get("cli_verified_at", "")
            text = "Verified"
            if vhash:
                text += f" ({vhash[:16]}…)"
            if vtime:
                text += f"\n{vtime}"
            self.verify_label.setText(text)
            self.verify_label.setStyleSheet("color: #4caf50;")
            notify(self.parent(), t("checksum_verified"), kind="ok")  # UI: toast instead of popup
        else:
            self.verify_label.setText(msg)
            self.verify_label.setStyleSheet("color: #f44336;")
            notify(self.parent(), t("verify_failed"), msg, kind="error")  # UI: toast instead of popup

    def get_settings(self) -> dict:
        return {
            "status_interval": self.interval.value(),
            "auto_status": self.auto.isChecked(),
            "logging": self.logging.isChecked(),
            "start_minimized": self.start_min.isChecked(),
            "autostart": self.autostart.isChecked(),
            "confirm_actions": self.confirm.isChecked(),
            "tray_color_change": self.tray_color.isChecked(),
            "theme": self.theme.currentText()
        }

# ---------------------------------------------------------------------------
# UI only: destructive confirmations default to "No" (controller/Enter safety)
_YES_NO = QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
_NO = QMessageBox.StandardButton.No

_NAV_KEYS = (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down)


def notify(win, title: str, detail: str = "", kind: str = "ok"):
    """UI only: non-blocking feedback (toast in the main window) instead of an info popup."""
    if win is not None and hasattr(win, "show_toast"):
        win.show_toast(title, detail, kind)


class MainWindow(QMainWindow):
    def show_about(self):
        box = QMessageBox(self)
        box.setStyleSheet(dialog_stylesheet(self))
        box.setWindowTitle("About BuddyRemote")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(
            "BuddyRemote v1.0<br><br>"
            "by Diciderino<br><br>"
            "Thanks to the MoonDeck project:<br>"
            '<a href="https://github.com/FrogTheFrog/moondeck">https://github.com/FrogTheFrog/moondeck</a>'
        )
        box.exec()

    def __init__(self):
        super().__init__()
        self.cfg = load_config()
        setup_logging(self.cfg["settings"].get("logging", False))
        self.signals = Signals()
        self.signals.status_update.connect(self.on_status_update)
        self.signals.action_done.connect(self.on_action_done)
        self.action_locks: dict[str, threading.Lock] = {}
        self.host_rows: dict[str, HostRow] = {}
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.check_status)

        self.setWindowTitle(t("app_title"))
        self.apply_theme()

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Toolbar
        self.toolbar = QWidget()
        self.toolbar.setObjectName("toolbar")
        tb = QHBoxLayout(self.toolbar)
        tb.setContentsMargins(12, 8, 12, 8)
        tb.setSpacing(8)
        self.toolbar_buttons = []  # UI only: arrow-key navigation
        for text, tip, slot in [("＋  " + t("add_host"), "tip_add", self.add_host),
                                ("⟳  " + t("refresh"), "tip_refresh", self.check_status),
                                ("⚙  " + t("options"), "tip_options", self.open_options)]:
            b = QPushButton(text)
            b.setToolTip(t(tip))
            b.clicked.connect(slot)
            b.installEventFilter(self)
            self.toolbar_buttons.append(b)
            tb.addWidget(b)
        tb.addStretch()
        main_layout.addWidget(self.toolbar)

        body = QWidget()
        self._body_layout = QVBoxLayout(body)
        self._body_layout.setContentsMargins(12, 10, 12, 6)
        self._body_layout.setSpacing(6)
        main_layout.addWidget(body, 1)

        # Scroll area for hosts
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.host_widget = QWidget()
        self.host_widget.setObjectName("hostArea")
        self.host_layout = QVBoxLayout(self.host_widget)
        self.host_layout.setContentsMargins(0, 0, 0, 0)
        self.host_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.host_layout.setSpacing(8)
        scroll.setWidget(self.host_widget)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)  # rows wrap instead
        self._body_layout.addWidget(scroll, 1)
        self.scroll = scroll
        self._vp_watch = _ResizeWatcher(scroll.viewport(), self._relayout_rows)
        self._apply_host_area_theme()

        # Collapsible log (UI only; same log content as before)
        self.log_btn = QPushButton()
        self.log_btn.setObjectName("logToggle")
        self.log_btn.setToolTip(t("tip_log"))
        self.log_btn.clicked.connect(self.toggle_log)
        self.log_btn.installEventFilter(self)
        log_row = QHBoxLayout()
        log_row.addWidget(self.log_btn)
        log_row.addStretch()
        self._body_layout.addLayout(log_row)

        # Output log (read-only)
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumHeight(150)
        self._apply_output_theme()
        self._body_layout.addWidget(self.output)

        # Status bar: last message (left), counts / auto refresh / CLI (right)
        self.status_bar = QLabel("")
        self.count_lbl = QLabel("")
        self.refresh_lbl = QLabel("")
        self.cli_lbl = QLabel("")
        sb = QStatusBar()
        sb.setSizeGripEnabled(False)
        # UI only: a long message must never push the right-hand labels out of the window
        self.status_bar.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        sb.addWidget(self.status_bar, 1)
        for w in (self.count_lbl, self.refresh_lbl, self.cli_lbl):
            sb.addPermanentWidget(w)
        self.setStatusBar(sb)
        self._apply_chrome_theme()

        # Toast overlay (UI only)
        self.toast = Toast(central)

        st = QSettings(str(WINDOW_STATE_FILE), QSettings.Format.IniFormat)
        self._set_log_visible(str(st.value("log_visible", "false")).lower() == "true")

        # UI only: keyboard shortcuts for existing toolbar actions
        for seq, slot in [("F5", self.check_status), ("Ctrl+N", self.add_host),
                          ("Ctrl+,", self.open_options), ("Ctrl+L", self.toggle_log)]:
            QShortcut(QKeySequence(seq), self, activated=slot)
        QApplication.instance().focusChanged.connect(self._on_focus_changed)

        self.refresh_hosts()
        self._update_status_bar()

        # Tray icon
        self.tray = QSystemTrayIcon(self)
        self._update_tray_icon(False)
        self.tray.setToolTip("BuddyRemote")
        menu = QMenu()
        menu.addAction("Show", self.show_normal)
        menu.addSeparator()
        self.host_menu = menu.addMenu("Hosts")
        menu.addSeparator()
        menu.addAction("Quit", self.quit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.tray_activated)
        self.tray.show()
        self._update_tray_menu()

        # UI only: window size/state memory and screen fitting
        self._was_shown = False
        self._restore_window_state()
        QApplication.instance().aboutToQuit.connect(self._save_window_state)

        if self.cfg["settings"].get("auto_status", True):
            interval = self.cfg["settings"].get("status_interval", 30) * 1000
            self.status_timer.start(interval)
            QTimer.singleShot(1000, self.check_status)

        if self.cfg["settings"].get("start_minimized", True):
            QTimer.singleShot(100, self.hide)

        # First-run attribution
        if not (APP_DIR / ".attributed").exists():
            QTimer.singleShot(500, self._show_attribution)

    def apply_dark(self):
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor("#1e1e1e"))
        pal.setColor(QPalette.ColorRole.WindowText, QColor("#e0e0e0"))
        pal.setColor(QPalette.ColorRole.Base, QColor("#2a2a2a"))
        pal.setColor(QPalette.ColorRole.Text, QColor("#e0e0e0"))
        pal.setColor(QPalette.ColorRole.Button, QColor("#2d2d2d"))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor("#e0e0e0"))
        self.setPalette(pal)
        self.setStyleSheet("""
            QPushButton { background: #2d2d2d; color: #e0e0e0; border: 1px solid #444; padding: 4px 8px; border-radius: 3px; }
            QPushButton:hover { background: #3d3d3d; }
            QLineEdit, QSpinBox { background: #2a2a2a; color: #e0e0e0; border: 1px solid #444; padding: 3px; }
        """ + touch_css(False))

    def apply_light(self):
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor("#f5f5f5"))
        pal.setColor(QPalette.ColorRole.WindowText, QColor("#222222"))
        pal.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
        pal.setColor(QPalette.ColorRole.Text, QColor("#222222"))
        pal.setColor(QPalette.ColorRole.Button, QColor("#e0e0e0"))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor("#222222"))
        self.setPalette(pal)
        self.setStyleSheet("""
            QPushButton { background: #e0e0e0; color: #222; border: 1px solid #ccc; padding: 4px 8px; border-radius: 3px; }
            QPushButton:hover { background: #d0d0d0; }
            QLineEdit, QSpinBox { background: #ffffff; color: #222; border: 1px solid #ccc; padding: 3px; }
        """ + touch_css(True))

    def _apply_host_area_theme(self):
        if not hasattr(self, "host_widget"):
            return
        light = self.cfg.get("settings", {}).get("theme", "Dark") == "Light"
        if light:
            self.host_widget.setStyleSheet("QWidget#hostArea { background: #f5f5f5; }")
            self.scroll.setStyleSheet("QScrollArea { border: none; background: #f5f5f5; }"
                "QScrollBar:vertical { background: transparent; width: 10px; margin: 2px 0 2px 0; }"
                "QScrollBar::handle:vertical { background: #c4c4c4; border-radius: 4px; min-height: 32px; margin: 0 2px; }"
                "QScrollBar::handle:vertical:hover { background: #a8a8a8; }"
                "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
                "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }")
        else:
            self.host_widget.setStyleSheet("QWidget#hostArea { background: #1e1e1e; }")
            self.scroll.setStyleSheet("QScrollArea { border: none; background: #1e1e1e; }"
                "QScrollBar:vertical { background: transparent; width: 10px; margin: 2px 0 2px 0; }"
                "QScrollBar::handle:vertical { background: #4a4a4a; border-radius: 4px; min-height: 32px; margin: 0 2px; }"
                "QScrollBar::handle:vertical:hover { background: #5e5e5e; }"
                "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
                "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }")

    def _apply_output_theme(self):
        if not hasattr(self, "output"):
            return
        light = self.cfg.get("settings", {}).get("theme", "Dark") == "Light"
        if light:
            self.output.setStyleSheet("QTextEdit { background: #ffffff; color: #222; border: 1px solid #ccc; font-family: monospace; }")
        else:
            self.output.setStyleSheet("QTextEdit { background: #1a1a1a; color: #ccc; border: 1px solid #333; font-family: monospace; }")

    def _light(self) -> bool:
        return self.cfg.get("settings", {}).get("theme", "Dark") == "Light"

    def _apply_chrome_theme(self):
        """UI only: toolbar, log toggle and status bar colours."""
        if not hasattr(self, "toolbar"):
            return
        c = ui_colors(self._light())
        self.toolbar.setStyleSheet(f"QWidget#toolbar {{ border-bottom: 1px solid {c['tb_b']}; }}")
        self.log_btn.setStyleSheet(
            f"QPushButton#logToggle {{ background: transparent; border: 2px solid transparent; color: {c['bar_t']};"
            f" text-align: left; padding: 4px 8px; min-height: 26px; font-size: 13px; }}"
            f" QPushButton#logToggle:hover {{ color: {c['name']}; }}"
            f" QPushButton#logToggle:focus {{ border: 2px solid {c['cur_b']}; }}")
        self.statusBar().setStyleSheet(
            f"QStatusBar {{ background: {c['bar']}; border-top: 1px solid {c['bar_b']}; }}"
            f" QStatusBar::item {{ border: none; }}"
            f" QStatusBar QLabel {{ color: {c['bar_t']}; font-size: 13px; padding: 3px 8px; }}")

    def apply_theme(self):
        theme = self.cfg["settings"].get("theme", "Dark")
        if theme == "Light":
            self.apply_light()
        else:
            self.apply_dark()
        self._apply_output_theme()
        self._apply_host_area_theme()
        self._apply_chrome_theme()
        # refresh host rows if layout already exists
        if hasattr(self, "host_layout"):
            for i in range(self.host_layout.count()):
                item = self.host_layout.itemAt(i)
                if item and item.widget() and isinstance(item.widget(), HostRow):
                    item.widget()._apply_row_theme()

    def _update_tray_menu(self):
        """Rebuild the host submenu in the tray."""
        if not hasattr(self, "host_menu"):
            return
        self.host_menu.clear()
        hosts = self.cfg.get("hosts", [])
        if not hosts:
            self.host_menu.addAction("(no hosts)").setEnabled(False)
            return
        for h in hosts:
            name = h.get("name", h.get("ip", "?"))
            sub = self.host_menu.addMenu(name)
            sub.addAction("Wake", lambda _, host=h: self.do_action(host, "wake"))
            sub.addAction("Shutdown", lambda _, host=h: self.do_action(host, "shutdown"))
            sub.addAction("Restart", lambda _, host=h: self.do_action(host, "restart"))
            sub.addAction("Suspend", lambda _, host=h: self.do_action(host, "suspend"))

    def refresh_hosts(self):
        # clear
        while self.host_layout.count():
            item = self.host_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.host_rows.clear()

        hosts = self.cfg.get("hosts", [])
        if not hosts:
            lbl = QLabel(t("no_hosts"))
            light = self.cfg.get("settings", {}).get("theme", "Dark") == "Light"
            col = "#666" if light else "#888"
            lbl.setStyleSheet(f"color: {col}; padding: 20px; background: transparent;")
            self.host_layout.addWidget(lbl)
            self._update_tray_menu()
            self._update_counts()
            return

        for h in hosts:
            row = HostRow(h, self)
            self.host_layout.addWidget(row)
            self.host_rows[h["id"]] = row
        self._update_tray_menu()
        self._update_counts()
        self._fit_min_size()
        self._relayout_rows()
        QTimer.singleShot(0, self._ensure_focus)

    def add_host(self):
        dlg = HostDialog(None, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            data = dlg.get_data()
            if data:
                self.cfg["hosts"].append(data)
                save_config(self.cfg)
                self.refresh_hosts()
                self._update_tray_menu()
                if QMessageBox.question(self, t("pairing_title"), "Pair with this host now?") == QMessageBox.StandardButton.Yes:
                    self.start_pairing(data)

    def edit_host(self, host: dict):
        dlg = HostDialog(host, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            data = dlg.get_data()
            if data:
                for i, h in enumerate(self.cfg["hosts"]):
                    if h["id"] == host["id"]:
                        self.cfg["hosts"][i] = data
                        break
                save_config(self.cfg)
                self.refresh_hosts()
                self._update_tray_menu()

    def _fetch_and_save_mac(self, host: dict, cli_cfg_path: Path):
        """After pairing, try to get MAC from Buddy and save it."""
        try:
            rc, out, err = run_cli(["host", "list", "--json"], timeout=15, config_override=cli_cfg_path)
            if rc == 0 and out.strip():
                import re
                # Try to extract MAC from output
                m = re.search(r'([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}', out)
                if m:
                    mac = m.group(0).upper()
                    for h in self.cfg["hosts"]:
                        if h["id"] == host["id"]:
                            h["mac"] = mac
                            break
                    save_config(self.cfg)
                    logging.info("MAC auto-saved: %s", mac)
                    QTimer.singleShot(0, lambda: notify(self, t("mac_updated", mac=mac)))
        except Exception:
            logging.exception("Failed to fetch MAC")

    def remove_host(self, host: dict):
        name = host.get("name", host.get("ip"))
        if QMessageBox.question(self, t("app_title"), t("confirm_remove", name=name), _YES_NO, _NO) == QMessageBox.StandardButton.Yes:
            self.cfg["hosts"] = [h for h in self.cfg["hosts"] if h["id"] != host["id"]]
            save_config(self.cfg)
            self.refresh_hosts()

    def move_host(self, host: dict, direction: int):
        hosts = self.cfg["hosts"]
        idx = next((i for i, h in enumerate(hosts) if h["id"] == host["id"]), None)
        if idx is None:
            return
        new_idx = idx + direction
        if 0 <= new_idx < len(hosts):
            hosts[idx], hosts[new_idx] = hosts[new_idx], hosts[idx]
            save_config(self.cfg)
            self.refresh_hosts()

    def do_action(self, host: dict, action: str):
        hid = host["id"]
        name = host.get("name", host.get("ip"))

        if action == "wake" and not host.get("mac"):
            notify(self, t("no_mac"), kind="error")
            return

        if action in ("shutdown", "restart", "suspend") and self.cfg["settings"].get("confirm_actions", True):
            if QMessageBox.question(self, t("app_title"), t(f"confirm_{action}", name=name), _YES_NO, _NO) != QMessageBox.StandardButton.Yes:
                return

        if hid not in self.action_locks:
            self.action_locks[hid] = threading.Lock()
        if not self.action_locks[hid].acquire(blocking=False):
            notify(self, t("action_running"), kind="info")
            return

        def worker():
            try:
                self.signals.action_done.emit(name, False, "running")  # signal start
                rc, out, err = self._run_action(host, action)
                msg = (out or err or f"Exit {rc}").strip()
                success = rc == 0
                self.signals.action_done.emit(name, success, msg)
            except Exception as e:
                self.signals.action_done.emit(name, False, str(e))
            finally:
                self.action_locks[hid].release()

        threading.Thread(target=worker, daemon=True).start()

    def _run_action(self, host: dict, action: str) -> tuple[int, str, str]:
        ip = host["ip"]
        cli_cfg = {
            "version": 1,
            "clientId": ensure_client_id(self.cfg),
            "defaultHost": ip,
            "hosts": {
                ip: {
                    "address": ip,
                    "manualAddress": True,
                    "infoPort": 47989,
                    "buddyPort": host.get("buddy_port", 59999),
                    "hostName": host.get("name", ip),
                    "mac": host.get("mac")
                }
            }
        }
        tmp = APP_DIR / f".tmp_{uuid.uuid4().hex[:6]}.json"
        try:
            tmp.write_text(json.dumps(cli_cfg))
            return run_cli(["host", action], timeout=60, config_override=tmp)
        finally:
            tmp.unlink(missing_ok=True)

    def start_pairing(self, host: dict):
        """Start pairing. Show PIN dialog that stays open while CLI runs."""
        try:
            ip = host["ip"]
            pin = f"{random.randint(1000, 9999)}"
            self.log_output(f"Starting pairing with {ip}, PIN: {pin}")
        except Exception as e:
            return

        # Pre-check: can we reach Buddy's API?
        ok, msg = check_buddy_api(ip, host.get("buddy_port", 59999))
        if not ok:
            notify(self, t("pairing_unreachable", ip=ip, port=host.get('buddy_port', 59999)),
                   f"{msg}\n\n" + t("pairing_unreachable_hint"), kind="error")
            return
        self.log_output(f"Buddy reachable: {msg}")

        cli_cfg = {
            "version": 1,
            "clientId": ensure_client_id(self.cfg),
            "defaultHost": ip,
            "hosts": {
                ip: {
                    "address": ip,
                    "manualAddress": True,
                    "infoPort": 47989,
                    "buddyPort": host.get("buddy_port", 59999),
                    "hostName": host.get("name", ip),
                    "mac": host.get("mac")
                }
            }
        }
        tmp = APP_DIR / f".pair_{uuid.uuid4().hex[:6]}.json"
        tmp.write_text(json.dumps(cli_cfg))

        try:
            dlg = QMessageBox(self)
            dlg.setWindowTitle("Pairing")
            dlg.setText(f"Enter PIN {pin} on the host\n\nWaiting for confirmation...")
            dlg.setStandardButtons(QMessageBox.StandardButton.Cancel)
            dlg.setModal(False)
            dlg.show()
            dlg.raise_()
            QApplication.processEvents()
        except Exception as e:
            return

        result = {"done": False, "ok": False, "msg": ""}

        def worker():
            try:
                rc, out, err = run_cli(
                    ["host", "pair", ip, "--pin", pin, "--buddy-port", str(host.get("buddy_port", 59999))],
                    timeout=180,
                    config_override=tmp
                )
                result["ok"] = rc == 0
                result["msg"] = (out or err or "").strip()
                if result["ok"]:
                    self._fetch_and_save_mac(host, tmp)
            except Exception as e:
                result["msg"] = str(e)
            finally:
                result["done"] = True
                tmp.unlink(missing_ok=True)

        th = threading.Thread(target=worker, daemon=True)
        th.start()

        # Poll until done or user cancels
        def check():
            if result["done"]:
                try:
                    dlg.close()
                except Exception:
                    pass
                try:
                    if result["ok"]:
                        notify(self, t("pairing_success"), kind="ok")
                    else:
                        msg = result["msg"] or "Unknown error"
                        notify(self, t("pairing_failed"), msg[:500], kind="error")
                except Exception as e:
                    logging.exception("Dialog error")
                return
            QTimer.singleShot(500, check)

        QTimer.singleShot(500, check)

        def on_cancel():
            # Best effort: we can't easily kill the CLI, but close dialog
            dlg.close()
            result["done"] = True

        dlg.button(QMessageBox.StandardButton.Cancel).clicked.connect(on_cancel)

    def check_status(self):
        self.log_output("Checking host status...")
        def worker():
            any_online = False
            for h in self.cfg.get("hosts", []):
                online = ping_host(h["ip"], h.get("buddy_port", 59999))
                status = t("online") if online else t("offline")
                if online:
                    any_online = True
                name = h.get("name", h.get("ip"))
                logging.info("Status %s: %s", name, status)
                self.signals.status_update.emit(h["id"], status)
            self.signals.status_update.emit("__tray__", "online" if any_online else "offline")
            self.signals.status_update.emit("__log__", "Status check complete")
        threading.Thread(target=worker, daemon=True).start()

    def on_status_update(self, hid: str, status: str):
        if hid == "__log__":
            self.log_output(status)
            return
        if hid == "__tray__":
            self._update_tray_icon(status == "online")
            return
        row = self.host_rows.get(hid)
        if row:
            row.set_status(status)

    def _rows_named(self, title: str):
        """UI only: rows whose display name matches an action_done title."""
        return [r for r in self.host_rows.values() if r.host.get("name", r.host.get("ip")) == title]

    def on_action_done(self, title: str, success: bool, msg: str):
        if msg == "running":
            self.log_output(f"Running action on {title}...")
            self.status_bar.setText(f"Working...")
            for r in self._rows_named(title):
                r.set_busy(True)
            return
        self.status_bar.setText("")
        self.log_output(f"[{title}] {'OK' if success else 'FAIL'}: {msg}")
        for r in self._rows_named(title):
            if success:
                r.set_busy(False)
            else:
                r.set_failed(t("action_failed", title=title) + " " + (msg.splitlines()[0][:120] if msg else ""))
        if success and "wake" in title.lower():
            notify(self, t("wake_sent"), kind="ok")
        elif success:
            notify(self, t("action_ok", title=title), kind="ok")
        else:
            notify(self, t("action_failed", title=title), t("action_failed_hint") + f"\n\n{msg[:200]}", kind="error")

    def open_options(self):
        dlg = OptionsDialog(self.cfg["settings"], self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new = dlg.get_settings()
            theme_changed = new.get("theme") != self.cfg["settings"].get("theme")
            self.cfg["settings"].update(new)
            save_config(self.cfg)
            setup_logging(new["logging"])
            set_autostart(new["autostart"])
            if new["auto_status"]:
                self.status_timer.start(new["status_interval"] * 1000)
            else:
                self.status_timer.stop()
            self._update_status_bar()
            notify(self, t("settings_saved"), t("theme_restart") if theme_changed else "", kind="ok")

    def _make_tray_icon(self, online: bool) -> QIcon:
        pix = QPixmap(22, 22)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        use_color = self.cfg.get("settings", {}).get("tray_color_change", True)
        if use_color:
            color = QColor("#4caf50") if online else QColor("#888888")
        else:
            color = QColor("#e0e0e0")
        p.setPen(QPen(color, 2))
        p.setBrush(Qt.GlobalColor.transparent)
        p.drawEllipse(2, 2, 18, 18)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawEllipse(7, 7, 8, 8)
        p.end()
        return QIcon(pix)

    def _update_tray_icon(self, any_online: bool):
        self.tray.setIcon(self._make_tray_icon(any_online))

    def log_output(self, text: str):
        """Append a timestamped message to the output field."""
        if not text:
            return
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        self.output.append(f"[{ts}] {text.rstrip()}")
        self.output.ensureCursorVisible()
        logging.info(text.strip())

    def _show_attribution(self):
        QMessageBox.information(
            self,
            "BuddyRemote",
            "This app uses the MoonDeck CLI by FrogTheFrog.\n\n"
            "https://github.com/FrogTheFrog/moondeck\n\n"
            "Thank you for the great work!"
        )
        (APP_DIR / ".attributed").touch()

    def show_normal(self):
        self._restore_window_state()
        self.show()
        self.raise_()
        self.activateWindow()

    def tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self.show_normal()

    def quit_app(self):
        """Really quit the application (from tray)."""
        self.status_timer.stop()
        release_lock()
        QApplication.quit()

    # --- UI only: toast, status bar, log toggle ----------------------------
    def show_toast(self, title: str, detail: str = "", kind: str = "ok"):
        """Non-blocking feedback: toast + status bar + log (replaces info popups).
        While the window is hidden in the tray, the tray balloon is used instead."""
        title = title.strip()
        if "\n" in title and not detail:
            title, detail = title.split("\n", 1)
        detail = detail.strip()
        self.log_output(("ERROR: " if kind == "error" else "") + title + (f" – {detail}" if detail else ""))
        self.status_bar.setText(title)
        if not self.isVisible():
            icon = QSystemTrayIcon.MessageIcon.Critical if kind == "error" else QSystemTrayIcon.MessageIcon.Information
            self.tray.showMessage("BuddyRemote", title + (f"\n{detail}" if detail else ""), icon, 5000)
            return
        if len(detail) > 300:
            detail = detail[:300] + "…"
        self.toast.show_message(title, detail, kind, self._light(), 9000 if kind == "error" else 4500)

    def _toast_bottom(self):
        """Toast sits just above the log toggle (bottom right of the host list)."""
        cw = self.centralWidget()
        return self.scroll.mapTo(cw, self.scroll.rect().bottomLeft()).y() - 8

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "toast") and self.toast.isVisible():
            self.toast.place()

    def _update_counts(self):
        if not hasattr(self, "count_lbl"):
            return
        n = len(self.host_rows)
        on = sum(1 for r in self.host_rows.values() if r.state == "online")
        self.count_lbl.setText(t("count_hosts", n=n, online=on))

    def _update_status_bar(self):
        st = self.cfg.get("settings", {})
        if st.get("auto_status", True):
            self.refresh_lbl.setText(t("auto_refresh_every", s=st.get("status_interval", 30)))
        else:
            self.refresh_lbl.setText(t("auto_refresh_off"))
        self.cli_lbl.setText("MoonDeck CLI " + ("✓" if cli_available() else "✗"))
        self._update_counts()

    def _set_log_visible(self, on: bool):
        self.output.setVisible(on)
        if hasattr(self, "tray"):
            self._fit_min_size()
        self.log_btn.setText(("▾ " if on else "▸ ") + t("log_toggle"))
        if hasattr(self, "toast") and self.toast.isVisible():
            QTimer.singleShot(0, self.toast.place)

    def toggle_log(self):
        on = not self.output.isVisible()
        self._set_log_visible(on)
        try:
            st = QSettings(str(WINDOW_STATE_FILE), QSettings.Format.IniFormat)
            st.setValue("log_visible", "true" if on else "false")
            st.sync()
        except Exception:
            logging.exception("window state save failed")

    def _on_focus_changed(self, old, new):
        """Highlight the card that contains the keyboard focus."""
        for r in self.host_rows.values():
            try:
                r.set_current(new is not None and r.isAncestorOf(new))
            except RuntimeError:
                pass

    # --- UI only: keyboard/controller navigation -------------------------
    def _nav_grid(self):
        grid = [self.toolbar_buttons] + [r.nav_buttons for r in self.host_rows.values()] + [[self.log_btn]]
        return [row for row in grid if row]

    def _focus_first(self):
        target = next(iter(self.host_rows.values())).nav_buttons[0] if self.host_rows else self.toolbar_buttons[0]
        target.setFocus(Qt.FocusReason.TabFocusReason)
        self.scroll.ensureWidgetVisible(target)

    def _ensure_focus(self):
        if self.isVisible() and QApplication.activeModalWidget() is None:
            fw = QApplication.focusWidget()
            if fw is None or not fw.isVisible() or fw.window() is not self:
                self._focus_first()

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.KeyPress and isinstance(obj, QPushButton):
            key = ev.key()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and ev.modifiers() in (
                    Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.KeypadModifier):
                obj.click()
                return True
            if key in _NAV_KEYS and ev.modifiers() in (
                    Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.KeypadModifier):
                grid = self._nav_grid()
                for r, row in enumerate(grid):
                    if obj in row:
                        c = row.index(obj)
                        if key == Qt.Key.Key_Left:
                            c = max(0, c - 1)
                        elif key == Qt.Key.Key_Right:
                            c = min(len(row) - 1, c + 1)
                        else:
                            r = max(0, r - 1) if key == Qt.Key.Key_Up else min(len(grid) - 1, r + 1)
                            c = min(c, len(grid[r]) - 1)
                        target = grid[r][c]
                        target.setFocus(Qt.FocusReason.TabFocusReason)
                        self.scroll.ensureWidgetVisible(target)
                        return True
        return super().eventFilter(obj, ev)

    # --- UI only: window size/state ----------------------------------------
    def _available(self):
        scr = self.screen() or QApplication.primaryScreen()
        return scr.availableGeometry() if scr else None

    # UI only: cards never get wider than this (wide/maximized windows keep the
    # buttons close to the host name; cards are centered).
    CARD_MAX_EXTRA = 200

    def _relayout_rows(self):
        """UI only: pick one-line or two-line cards from the visible width and
        center the cards when the window is very wide."""
        rows = list(self.host_rows.values())
        if not rows:
            self.host_layout.setContentsMargins(0, 0, 0, 0)
            return
        vw = self.scroll.viewport().width()
        need = max(r.wide_width() for r in rows)
        cap = need + self.CARD_MAX_EXTRA
        side = max(0, (vw - cap) // 2)
        m = self.host_layout.contentsMargins()
        if m.left() != side:
            self.host_layout.setContentsMargins(side, 0, side, 0)
        compact = vw - 2 * side < need
        for r in rows:
            r.set_compact(compact)

    def _fit_min_size(self):
        """UI only: minimum size computed from the real layout (scales with font
        size and display scaling): the narrowest card with all buttons visible
        (two-line card), toolbar and status bar; height keeps one card visible."""
        avail = self._available()
        rows = list(self.host_rows.values())
        bm = self._body_layout.contentsMargins()
        chrome_w = bm.left() + bm.right() + 2 * self.scroll.frameWidth() + self.scroll.verticalScrollBar().sizeHint().width()
        card_w = max([r.compact_width() for r in rows] + [0])
        perm = sum(l.sizeHint().width() for l in (self.count_lbl, self.refresh_lbl, self.cli_lbl)) + 60
        w = max(card_w + chrome_w, self.toolbar.minimumSizeHint().width(), perm, 420)
        card_h = max([r.compact_height() for r in rows] + [80])
        h = (self.toolbar.sizeHint().height() + (self.statusBar().sizeHint().height() if self.statusBar() else 0)
             + bm.top() + bm.bottom() + 2 * self.scroll.frameWidth() + card_h
             + self._body_layout.spacing() * 2 + self.log_btn.sizeHint().height())
        if self.output.isVisible():
            h += self.output.minimumSizeHint().height() + self._body_layout.spacing()
        if avail:
            w, h = min(w, avail.width()), min(h, avail.height())
        self.setMinimumSize(w, h)

    @staticmethod
    def _is_wayland() -> bool:
        return QApplication.platformName().startswith("wayland")

    def _clamp_to_screen(self):
        """UI only: saved geometry larger than the screen is shrunk; a window whose
        title bar ended up off-screen (X11; Wayland ignores positions) is pulled back."""
        avail = self._available()
        if not avail or self.isMaximized() or self.isFullScreen():
            return
        if self.width() > avail.width() or self.height() > avail.height():
            self.resize(min(self.width(), avail.width()), min(self.height(), avail.height()))
        if self._is_wayland():
            return
        fg = self.frameGeometry()
        visible = False
        for scr in QApplication.screens():
            a = scr.availableGeometry()
            title = fg.adjusted(0, 0, 0, -(fg.height() - 40))  # top 40 px: the grab area
            if a.intersected(title).width() >= 100:
                visible = True
                break
        if not visible:
            x = avail.x() + (avail.width() - fg.width()) // 2
            y = avail.y() + (avail.height() - fg.height()) // 2
            self.move(max(avail.x(), x), max(avail.y(), y))

    def _restore_window_state(self):
        self._fit_min_size()
        st = QSettings(str(WINDOW_STATE_FILE), QSettings.Format.IniFormat)
        geo = st.value("geometry")
        if not (geo and self.restoreGeometry(geo)):
            avail = self._available()
            w, h = 900, 640
            if avail:
                w = max(min(w, int(avail.width() * 0.9)), min(self.minimumWidth(), avail.width()))
                h = max(min(h, int(avail.height() * 0.9)), min(self.minimumHeight(), avail.height()))
            self.resize(w, h)
        self._clamp_to_screen()

    def _save_window_state(self):
        if not self._was_shown:
            return
        try:
            st = QSettings(str(WINDOW_STATE_FILE), QSettings.Format.IniFormat)
            st.setValue("geometry", self.saveGeometry())
            st.sync()
        except Exception:
            logging.exception("window state save failed")

    def showEvent(self, event):
        super().showEvent(event)
        self._was_shown = True
        QTimer.singleShot(0, self._focus_first)

    def hideEvent(self, event):
        self._save_window_state()
        super().hideEvent(event)

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        self.tray.showMessage("BuddyRemote", "Running in background", QSystemTrayIcon.MessageIcon.Information, 2000)

# ---------------------------------------------------------------------------
class DownloadDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("BuddyRemote – Setup")
        self.setModal(True)
        self.resize(480, 220)
        layout = QVBoxLayout(self)
        self.label = QLabel("Preparing…")
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.label)
        self.setStyleSheet("""
            QDialog { background: #1e1e1e; }
            QLabel { color: #e0e0e0; font-size: 13px; padding: 8px; }
        """)

    def set_status(self, text: str):
        self.label.setText(text)
        QApplication.processEvents()

def main():
    prepare_packaged_dir()
    if not acquire_lock():
        print("BuddyRemote is already running.")
        sys.exit(0)

    # UI only: fractional display scaling (125 %, 150 %, ...) is used as-is instead of
    # being rounded to whole numbers. This is already the Qt 6 default; set explicitly
    # so it stays that way (all sizes in the stylesheets are device-independent px).
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    apply_platform_preference()
    app = QApplication(sys.argv)
    app.setApplicationName("BuddyRemote")
    # Apply theme to all dialogs
    cfg = load_config()
    light = cfg.get("settings", {}).get("theme", "Dark") == "Light"
    if light:
        app.setStyleSheet("""
            QDialog, QMessageBox { background: #f5f5f5; color: #222; }
            QLabel { color: #222; }
            QPushButton { background: #e0e0e0; color: #222; border: 1px solid #ccc; padding: 4px 8px; border-radius: 3px; }
            QPushButton:hover { background: #d0d0d0; }
            QLineEdit, QSpinBox, QComboBox { background: #ffffff; color: #222; border: 1px solid #ccc; padding: 3px; }
            QCheckBox { color: #222; }
            QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #888; border-radius: 3px; background: #fff; }
            QCheckBox::indicator:checked { background: #4caf50; border-color: #388e3c; }
            QCheckBox::indicator:checked:hover { background: #66bb6a; }
        """ + touch_css(True))
    else:
        app.setStyleSheet("""
            QDialog, QMessageBox { background: #1e1e1e; color: #e0e0e0; }
            QLabel { color: #e0e0e0; }
            QPushButton { background: #2d2d2d; color: #e0e0e0; border: 1px solid #444; padding: 4px 8px; border-radius: 3px; }
            QPushButton:hover { background: #3d3d3d; }
            QLineEdit, QSpinBox, QComboBox { background: #2a2a2a; color: #e0e0e0; border: 1px solid #444; padding: 3px; }
            QCheckBox { color: #e0e0e0; }
            QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #666; border-radius: 3px; background: #2a2a2a; }
            QCheckBox::indicator:checked { background: #4caf50; border-color: #388e3c; }
            QCheckBox::indicator:checked:hover { background: #66bb6a; }
        """ + touch_css(False))
    app.setApplicationDisplayName("BuddyRemote")
    app.setOrganizationName("BuddyRemote")
    app.setDesktopFileName("buddyremote")
    app.setQuitOnLastWindowClosed(False)

    # Ensure CLI is present
    if not cli_available():
        dlg = DownloadDialog()
        dlg.show()
        ok = download_cli(dlg.set_status)
        dlg.close()
        if not ok:
            QMessageBox.critical(None, "BuddyRemote", "Failed to download MoonDeck CLI.\nCheck your internet connection and try again.")
            sys.exit(1)

    win = MainWindow()
    if not win.cfg["settings"].get("start_minimized", True):
        win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    try:
        main()
    finally:
        release_lock()
