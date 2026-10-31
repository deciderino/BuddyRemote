"""BuddyRemote – app version, directories and file locations (source mode vs. packaged)."""

import os
import sys
from pathlib import Path


APP_VERSION = "1.3.1"


APP_DIR = Path(__file__).resolve().parent
# Packaging: read-only resources (lang/, default config, bundled CLI) live next to
# the code / inside the bundle; writable files go to a user dir when packaged.
RES_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
PACKAGED = bool(getattr(sys, "frozen", False) or os.environ.get("APPIMAGE"))
if PACKAGED:
    APP_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "BuddyRemote"
CONFIG_FILE = APP_DIR / "config.json"
SEED_CONFIG = RES_DIR / "packaging" / "default-config.json"   # first-start defaults
CLI_DIR = APP_DIR / "cli"          # source mode: download_cli() puts the CLI here
BUNDLED_DIR = RES_DIR / "bundled"  # packaged: CLI + version file from build-appimage.sh
LANG_DIR = RES_DIR / "lang"
INSTANCE_LOCK = APP_DIR / ".instance.lock"
LOG_FILE = APP_DIR / "buddyremote.log"
WINDOW_STATE_FILE = APP_DIR / "window.ini"  # UI only: size/maximized/position


def cli_path(packaged: bool = PACKAGED) -> Path:
    """The MoonDeck CLI that run_cli starts. Packaged: straight from the bundle (no
    copy; a cli/ copy left by 1.3 in the user dir is no longer used). Source mode:
    the one download_cli() fetched into APP_DIR/cli."""
    return BUNDLED_DIR / "moondeck-cli" if packaged else CLI_DIR / "moondeck-cli"

CLI_BIN = cli_path()

def prepare_packaged_dir():
    """Packaging only: create the user dir (config, log, lock live there)."""
    if not PACKAGED:
        return
    APP_DIR.mkdir(parents=True, exist_ok=True)
