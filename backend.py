"""BuddyRemote – backend without UI: MoonDeck CLI (run, download, verify, bundled version),
ping, MoonDeck Buddy API check, Steam status parsing and the GitHub update check."""

import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import cacerts  # system CA store lookup for HTTPS to GitHub (no Qt, nothing bundled)

from paths import APP_VERSION, APP_DIR, PACKAGED, CONFIG_FILE, CLI_DIR, BUNDLED_DIR, CLI_BIN
from i18n import t
from config import load_config, save_config


def bundled_cli_info() -> dict | None:
    """Packaged mode: {'version', 'commit', 'sha256'} written by build-appimage.sh."""
    try:
        d = json.loads((BUNDLED_DIR / "moondeck-cli.version").read_text(encoding="utf-8"))
    except Exception:
        return None
    return d if isinstance(d, dict) else None

def bundled_cli_text() -> str:
    info = bundled_cli_info() or {}
    ver = str(info.get("version") or "").strip()
    commit = str(info.get("commit") or "").strip()[:7]
    if ver and commit:
        return t("cli_bundled_full", version=ver, commit=commit)
    if ver:
        return t("cli_bundled_ver", version=ver)
    return t("cli_bundled")


def child_env(packaged: bool = PACKAGED, base: dict | None = None) -> dict:
    """Environment for external programs (MoonDeck CLI, ping). Packaged: the
    PyInstaller bootloader points LD_LIBRARY_PATH at our bundled libs; give the child
    the user's original value back (or none) so it loads its own / the system libs."""
    env = dict(os.environ if base is None else base)
    if packaged:
        orig = env.get("LD_LIBRARY_PATH_ORIG")
        if orig:
            env["LD_LIBRARY_PATH"] = orig
        else:
            env.pop("LD_LIBRARY_PATH", None)
    return env

def cli_available() -> bool:
    return CLI_BIN.is_file()

def run_cli(args: list, timeout=90, config_override: Path | None = None) -> tuple[int, str, str]:
    if not cli_available():
        return -1, "", t("cli_not_found")
    cfg = str(config_override or CONFIG_FILE)
    cmd = [str(CLI_BIN), "--config-file", cfg] + args
    logging.debug("CLI %s", cmd)
    try:
        # cwd: the writable user/app dir (never the read-only bundle)
        p = subprocess.run(cmd, cwd=str(APP_DIR), capture_output=True, text=True,
                           timeout=timeout, env=child_env())
        logging.debug("CLI rc=%s", p.returncode)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Timeout"
    except Exception as e:
        logging.exception("CLI error")
        return -1, "", str(e)

_ping_warned = False

def ping_icmp(ip: str, timeout_s: int = 1) -> bool:
    """One ICMP echo through the system ping binary (no raw sockets / root needed).
    Windows: success only with 'TTL=' in the output ('Destination host unreachable'
    replies also exit 0 there)."""
    if not ip:
        return False
    win = sys.platform == "win32"
    if win:
        cmd = ["ping", "-n", "1", "-w", str(int(timeout_s * 1000)), ip]
    elif sys.platform == "darwin":
        cmd = ["ping", "-c", "1", "-t", str(max(1, int(timeout_s))), ip]
    else:
        cmd = ["ping", "-c", "1", "-W", str(max(1, int(timeout_s))), ip]
    env = child_env()       # packaged: do not hand our bundled libs to a system binary
    kw = {"creationflags": 0x08000000} if win else {}   # CREATE_NO_WINDOW
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                           timeout=timeout_s + 4, env=env, **kw)
    except OSError as e:
        global _ping_warned
        if not _ping_warned:
            _ping_warned = True
            logging.warning("ping not usable (%s): PC state comes from Buddy only", e)
        return False
    except subprocess.SubprocessError:
        return False
    if win:
        return p.returncode == 0 and "TTL=" in (p.stdout or "").upper()
    return p.returncode == 0

def parse_steam_status(out: str) -> dict | None:
    """'steam status --json' output -> {'running': bool, 'bpm': bool} or None."""
    try:
        data = json.loads(out[out.index("{"):out.rindex("}") + 1])
    except ValueError:
        return None
    st = data.get("status", data) if isinstance(data, dict) else None
    if not isinstance(st, dict) or "running" not in st:
        return None
    return {"running": bool(st.get("running")), "bpm": bool(st.get("bpm"))}

# Update check: only reads the latest GitHub release; nothing is downloaded.
RELEASES_API = "https://api.github.com/repos/deciderino/BuddyRemote/releases/latest"

def version_tuple(v: str) -> tuple[int, ...]:
    """'v1.2' / '1.10.0' / '1.3-beta' -> (1, 2) / (1, 10) / (1, 3); trailing zeros dropped."""
    import re
    m = re.match(r"\s*[vV]?\s*(\d+(?:\.\d+)*)", v or "")
    if not m:
        return ()
    parts = [int(x) for x in m.group(1).split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)

def is_newer_version(remote: str, local: str = APP_VERSION) -> bool:
    r = version_tuple(remote)
    return bool(r) and r > version_tuple(local)

def fetch_latest_release(timeout: float = 5.0) -> dict:
    """{'version', 'url', 'name'} of the latest release; raises on any problem."""
    req = urllib.request.Request(RELEASES_API, headers={
        "User-Agent": f"BuddyRemote/{APP_VERSION} (+https://github.com/deciderino/BuddyRemote)",
        "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout, context=cacerts.https_context()) as r:
        data = json.loads(r.read().decode("utf-8", errors="replace"))
    tag = str(data.get("tag_name") or "")
    if not version_tuple(tag):
        raise ValueError(f"no version in tag {tag!r}")
    url = str(data.get("html_url") or "")
    if not url.startswith("https://github.com/"):
        url = "https://github.com/deciderino/BuddyRemote/releases/latest"
    return {"version": tag.lstrip("vV").strip(), "url": url, "name": str(data.get("name") or tag)}

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


def verify_existing_cli() -> tuple[bool, str]:
    """Re-check the already downloaded CLI against the current GitHub digest."""
    if not CLI_BIN.exists():
        return False, "CLI not found"
    try:
        API_URL = "https://api.github.com/repos/FrogTheFrog/moondeck/releases/tags/nightly"
        with urllib.request.urlopen(API_URL, timeout=15, context=cacerts.https_context()) as r:
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
    dest = CLI_BIN                       # source mode: CLI_DIR / "moondeck-cli"

    def status(msg, pause=1.2):
        if progress_cb:
            progress_cb(msg)
        time.sleep(pause)

    try:
        status(f"Preparing MoonDeck CLI\nSource: {SOURCE}\nRelease: {CLI_RELEASE}")

        status("Fetching release information...")
        with urllib.request.urlopen(API_URL, timeout=15, context=cacerts.https_context()) as r:
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
        with urllib.request.urlopen(CLI_URL, timeout=60, context=cacerts.https_context()) as r, \
                open(dest, "wb") as out:
            shutil.copyfileobj(r, out, 1 << 20)
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
