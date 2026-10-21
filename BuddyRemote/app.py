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
    QTextEdit, QComboBox
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QIcon, QAction, QColor, QPalette, QPixmap, QPainter, QPen

# ---------------------------------------------------------------------------
APP_DIR = Path(__file__).resolve().parent
CONFIG_FILE = APP_DIR / "config.json"
CLI_DIR = APP_DIR / "cli"
CLI_BIN = CLI_DIR / "moondeck-cli"
CLI_SCRIPT = CLI_DIR / "cli.py"  # fallback
LANG_DIR = APP_DIR / "lang"
LOCK_FILE = APP_DIR / ".lock"
LOG_FILE = APP_DIR / "buddyremote.log"

# ---------------------------------------------------------------------------
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
        """
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
        """


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
    launcher = APP_DIR / "BuddyRemote"
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
class HostRow(QFrame):
    def __init__(self, host: dict, parent_app):
        super().__init__()
        self.host = host
        self.app = parent_app
        self.setFrameShape(QFrame.Shape.StyledPanel)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)

        info = QVBoxLayout()
        self.name_lbl = QLabel(host.get("name", "Unnamed"))
        self.ip_lbl = QLabel(host.get("ip", ""))
        self.status_lbl = QLabel(t("unknown"))
        self._apply_row_theme()
        info.addWidget(self.name_lbl)
        info.addWidget(self.ip_lbl)
        info.addWidget(self.status_lbl)
        layout.addLayout(info, 1)

        # Action buttons
        for act, label in [("wake", t("wake")), ("shutdown", t("shutdown")),
                           ("restart", t("restart")), ("suspend", t("suspend"))]:
            btn = QPushButton(label)
            btn.setFixedWidth(80)
            btn.clicked.connect(lambda _, a=act: self.app.do_action(self.host, a))
            layout.addWidget(btn)

        # Controls
        for text, slot in [("↑", lambda: self.app.move_host(self.host, -1)),
                           ("↓", lambda: self.app.move_host(self.host, 1)),
                           ("✎", lambda: self.app.edit_host(self.host)),
                           ("✕", lambda: self.app.remove_host(self.host))]:
            b = QPushButton(text)
            b.setFixedWidth(28)
            b.clicked.connect(slot)
            layout.addWidget(b)

    def _apply_row_theme(self):
        light = self.app.cfg.get("settings", {}).get("theme", "Dark") == "Light"
        if light:
            self.setStyleSheet("background: #ffffff; border: 1px solid #ddd; border-radius: 6px;")
            self.name_lbl.setStyleSheet("font-weight: bold; font-size: 13px; color: #222; background: transparent;")
            self.ip_lbl.setStyleSheet("color: #555; background: transparent;")
            self.status_lbl.setStyleSheet("color: #666; background: transparent;")
        else:
            self.setStyleSheet("background: #252525; border-radius: 6px;")
            self.name_lbl.setStyleSheet("font-weight: bold; font-size: 13px; color: #fff; background: transparent;")
            self.ip_lbl.setStyleSheet("color: #aaa; background: transparent;")
            self.status_lbl.setStyleSheet("color: #888; background: transparent;")

    def set_status(self, text: str):
        self.status_lbl.setText(text)
        color = "#888"
        if text == t("online"):
            color = "#2e7d32" if self.app.cfg.get("settings", {}).get("theme") == "Light" else "#4caf50"
        elif text == t("offline"):
            color = "#c62828" if self.app.cfg.get("settings", {}).get("theme") == "Light" else "#f44336"
        self.status_lbl.setStyleSheet(f"color: {color};")

# ---------------------------------------------------------------------------
class HostDialog(QDialog):
    def __init__(self, host: dict | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("edit_host") if host else t("add_host"))
        self.setStyleSheet(dialog_stylesheet(parent))
        self.host = host
        layout = QFormLayout(self)

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
            QMessageBox.information(self, "BuddyRemote", "Checksum verified.")
        else:
            self.verify_label.setText(msg)
            self.verify_label.setStyleSheet("color: #f44336;")
            QMessageBox.warning(self, "BuddyRemote", f"Verification failed:\n{msg}")

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
        self.resize(780, 520)
        self.setMinimumSize(640, 420)
        self.apply_theme()

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # Toolbar
        tb = QHBoxLayout()
        for text, slot in [(t("add_host"), self.add_host), (t("options"), self.open_options),
                           (t("refresh"), self.check_status)]:
            b = QPushButton(text)
            b.clicked.connect(slot)
            tb.addWidget(b)
        tb.addStretch()
        main_layout.addLayout(tb)

        # Scroll area for hosts
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.host_widget = QWidget()
        self.host_layout = QVBoxLayout(self.host_widget)
        self.host_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self.host_widget)
        main_layout.addWidget(scroll)
        self.scroll = scroll
        self._apply_host_area_theme()

        self.status_bar = QLabel("")
        self.status_bar.setStyleSheet("color: #888; padding: 4px;")
        main_layout.addWidget(self.status_bar)

        # Output log (read-only)
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumHeight(120)
        self._apply_output_theme()
        main_layout.addWidget(self.output)

        self.refresh_hosts()

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
        """)

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
        """)

    def _apply_host_area_theme(self):
        if not hasattr(self, "host_widget"):
            return
        light = self.cfg.get("settings", {}).get("theme", "Dark") == "Light"
        if light:
            self.host_widget.setStyleSheet("background: #f5f5f5;")
            self.scroll.setStyleSheet("QScrollArea { border: none; background: #f5f5f5; }")
        else:
            self.host_widget.setStyleSheet("background: #1e1e1e;")
            self.scroll.setStyleSheet("QScrollArea { border: none; background: #1e1e1e; }")

    def _apply_output_theme(self):
        if not hasattr(self, "output"):
            return
        light = self.cfg.get("settings", {}).get("theme", "Dark") == "Light"
        if light:
            self.output.setStyleSheet("QTextEdit { background: #ffffff; color: #222; border: 1px solid #ccc; font-family: monospace; }")
        else:
            self.output.setStyleSheet("QTextEdit { background: #1a1a1a; color: #ccc; border: 1px solid #333; font-family: monospace; }")

    def apply_theme(self):
        theme = self.cfg["settings"].get("theme", "Dark")
        if theme == "Light":
            self.apply_light()
        else:
            self.apply_dark()
        self._apply_output_theme()
        self._apply_host_area_theme()
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
            return

        for h in hosts:
            row = HostRow(h, self)
            self.host_layout.addWidget(row)
            self.host_rows[h["id"]] = row
        self._update_tray_menu()

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
                    QTimer.singleShot(0, lambda: QMessageBox.information(
                        self, t("app_title"), t("mac_updated", mac=mac)))
        except Exception:
            logging.exception("Failed to fetch MAC")

    def remove_host(self, host: dict):
        name = host.get("name", host.get("ip"))
        if QMessageBox.question(self, t("app_title"), t("confirm_remove", name=name)) == QMessageBox.StandardButton.Yes:
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
            QMessageBox.warning(self, t("app_title"), t("no_mac"))
            return

        if action in ("shutdown", "restart", "suspend") and self.cfg["settings"].get("confirm_actions", True):
            if QMessageBox.question(self, t("app_title"), t(f"confirm_{action}", name=name)) != QMessageBox.StandardButton.Yes:
                return

        if hid not in self.action_locks:
            self.action_locks[hid] = threading.Lock()
        if not self.action_locks[hid].acquire(blocking=False):
            QMessageBox.information(self, t("app_title"), t("action_running"))
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
            QMessageBox.critical(self, t("pairing_title"),
                f"Cannot reach Buddy at {ip}:{host.get('buddy_port', 59999)}\n\n{msg}\n\nCheck that Buddy is running and the port is open.")
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
                        QMessageBox.information(self, t("pairing_title"), t("pairing_success"))
                    else:
                        msg = result["msg"] or "Unknown error"
                        QMessageBox.critical(self, t("pairing_title"), t("pairing_failed") + "\n\n" + msg[:500])
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

    def on_action_done(self, title: str, success: bool, msg: str):
        if msg == "running":
            self.log_output(f"Running action on {title}...")
            self.status_bar.setText(f"Working...")
            return
        self.status_bar.setText("")
        self.log_output(f"[{title}] {'OK' if success else 'FAIL'}: {msg}")
        if success and "wake" in title.lower():
            QMessageBox.information(self, t("app_title"), "Wake signal sent")
        elif success:
            QMessageBox.information(self, t("app_title"), f"{title}: Done")
        else:
            QMessageBox.critical(self, t("app_title"), f"{title} failed.\n\nHost may be unreachable or Buddy is not responding.\n\n{msg[:200]}")

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
            if theme_changed:
                QMessageBox.information(self, t("app_title"), "Theme changed. Restart required.")
            QMessageBox.information(self, t("app_title"), t("settings_saved"))

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
    if not acquire_lock():
        print("BuddyRemote is already running.")
        sys.exit(0)

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
        """)
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
        """)
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
