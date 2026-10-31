"""BuddyRemote – app version, directories and file locations (source mode vs. packaged)."""

import os
import sys
from pathlib import Path


# "1.4-preview": a test build before 1.4 (backend.is_newer_version: 1.4 > 1.4-preview > 1.3.1)
APP_VERSION = "1.4-preview"
IS_WINDOWS = sys.platform == "win32"


APP_DIR = Path(__file__).resolve().parent
# Packaging: read-only resources (lang/, default config, bundled CLI) live next to
# the code / inside the bundle; writable files go to a user dir when packaged.
RES_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
PACKAGED = bool(getattr(sys, "frozen", False) or os.environ.get("APPIMAGE"))


def user_data_dir(platform: str = sys.platform, env=None, home: Path | None = None) -> Path:
    """Writable per-user dir of the packaged app: Windows %APPDATA%\\BuddyRemote
    (roaming profile), else $XDG_CONFIG_HOME/BuddyRemote or ~/.config/BuddyRemote."""
    env = os.environ if env is None else env
    home = Path.home() if home is None else home
    if platform == "win32":
        base = env.get("APPDATA") or str(home / "AppData" / "Roaming")
        return Path(base) / "BuddyRemote"
    return Path(env.get("XDG_CONFIG_HOME") or home / ".config") / "BuddyRemote"

if PACKAGED:
    APP_DIR = user_data_dir()
CONFIG_FILE = APP_DIR / "config.json"
SEED_CONFIG = RES_DIR / "packaging" / "default-config.json"   # first-start defaults
CLI_DIR = APP_DIR / "cli"          # source mode: download_cli() puts the CLI here
BUNDLED_DIR = RES_DIR / "bundled"  # packaged: CLI + version file from build-appimage.sh
LANG_DIR = RES_DIR / "lang"
INSTANCE_LOCK = APP_DIR / ".instance.lock"
LOG_FILE = APP_DIR / "buddyremote.log"
WINDOW_STATE_FILE = APP_DIR / "window.ini"  # UI only: size/maximized/position


def cli_name(platform: str = sys.platform) -> str:
    """File name of the MoonDeck CLI inside the bundle / APP_DIR/cli."""
    return "moondeck-cli.exe" if platform == "win32" else "moondeck-cli"

def cli_path(packaged: bool = PACKAGED, platform: str = sys.platform) -> Path:
    """The MoonDeck CLI that run_cli starts. Packaged: straight from the bundle (no
    copy; a cli/ copy left by 1.3 in the user dir is no longer used). Source mode:
    the one download_cli() fetched into APP_DIR/cli."""
    return (BUNDLED_DIR if packaged else CLI_DIR) / cli_name(platform)

CLI_BIN = cli_path()

def prepare_packaged_dir():
    """Packaging only: create the user dir (config, log, lock live there)."""
    if not PACKAGED:
        return
    APP_DIR.mkdir(parents=True, exist_ok=True)
