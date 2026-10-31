"""BuddyRemote – OS integration: single instance (lock file + local server) and autostart."""

import hashlib
import logging
import os
import sys
from pathlib import Path

from PyQt6.QtCore import QLockFile
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

from paths import APP_DIR, PACKAGED, INSTANCE_LOCK


# Single instance: a QLockFile in APP_DIR (Qt detects stale locks of dead processes
# itself) plus a QLocalServer, through which a second start asks the running
# instance to show its window. Only the process holding the lock ever releases it.
_instance_lock: QLockFile | None = None
_instance_server: QLocalServer | None = None

def instance_server_name() -> str:
    try:
        user = os.getlogin()
    except OSError:
        user = os.environ.get("USER") or os.environ.get("USERNAME") or "user"
    tag = hashlib.sha1(str(APP_DIR).encode()).hexdigest()[:8]
    return f"BuddyRemote-{user}-{tag}"

def acquire_lock() -> bool:
    """True if this process is the only running instance (for this APP_DIR)."""
    global _instance_lock
    lock = QLockFile(str(INSTANCE_LOCK))
    lock.setStaleLockTime(0)   # never treat a live instance's lock as stale by age
    if lock.tryLock(200):
        _instance_lock = lock
        return True
    return False

def notify_running_instance() -> bool:
    """Ask the already running instance to bring its window to the front."""
    sock = QLocalSocket()
    sock.connectToServer(instance_server_name())
    if not sock.waitForConnected(1000):
        return False
    sock.write(b"show\n")
    sock.flush()
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True

def start_instance_server(on_show) -> bool:
    """Primary instance: listen for 'show' requests from later starts."""
    global _instance_server
    name = instance_server_name()
    QLocalServer.removeServer(name)   # leftover socket of a crashed run; we hold the lock
    server = QLocalServer()
    def _on_conn():
        while server.hasPendingConnections():
            c = server.nextPendingConnection()
            c.readyRead.connect(lambda c=c: (c.readAll(), on_show()))
            c.disconnected.connect(c.deleteLater)
    server.newConnection.connect(_on_conn)
    if not server.listen(name):
        logging.warning("Single instance server failed: %s", server.errorString())
        return False
    _instance_server = server
    return True

def release_lock():
    global _instance_lock, _instance_server
    if _instance_server is not None:
        _instance_server.close()
        _instance_server = None
    if _instance_lock is not None:
        _instance_lock.unlock()
        _instance_lock = None


def set_autostart(enabled: bool):
    d = Path.home() / ".config" / "autostart"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "buddyremote.desktop"
    launcher = os.environ.get("APPIMAGE") or (sys.executable if PACKAGED else APP_DIR / "BuddyRemote")
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
