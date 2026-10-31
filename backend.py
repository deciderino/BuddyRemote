"""BuddyRemote – backend without UI: MoonDeck CLI (run, download, verify, bundled version),
ping, MoonDeck Buddy API check, Steam status parsing and the GitHub update check."""

import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
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

def bundled_cli_label() -> str:
    """Short label of the bundled CLI for the 1.3.1 UI: 'nightly 00f8c31' (packaged), 'nightly'
    (source mode / no version file)."""
    info = bundled_cli_info() or {}
    ver = str(info.get("version") or "").strip() or "nightly"
    commit = str(info.get("commit") or "").strip()[:7]
    return f"{ver} {commit}" if commit else ver


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

def _no_window() -> dict:
    """subprocess kwargs: no console window for child programs on Windows."""
    return {"creationflags": 0x08000000} if sys.platform == "win32" else {}   # CREATE_NO_WINDOW

# --- custom CLI (1.3.1) --------------------------------------------------------
# The bundled CLI (packaged: from the AppImage; source mode: the downloaded one in
# APP_DIR/cli) is the default. A custom CLI is only used when the user picked one in
# Options › Dateien (settings "custom_cli"). It is tried once per file version
# (mtime + size) with "--help"; if it does not start, or the file is gone, every call
# falls back to the bundled CLI. The setting itself is never changed here.
_cli_lock = threading.Lock()
_custom = {"path": "", "key": None, "state": "off", "reason": ""}
_cli_listener = None        # callback(state, path, reason) on every state change

def set_cli_listener(cb):
    """cb(state, path, reason); state 'ok' / 'failed' / 'missing' / 'off'. Called from the
    thread that noticed the change (the UI forwards it through a Qt signal)."""
    global _cli_listener
    _cli_listener = cb

def set_custom_cli(path: str):
    """Select the custom CLI (or '' for the bundled one); probed lazily on the next use."""
    path = str(path or "").strip()
    with _cli_lock:
        if path == _custom["path"]:
            return
        _custom.update(path=path, key=None, state="off" if not path else "unknown", reason="")

def custom_cli_path() -> str:
    return _custom["path"]

def custom_cli_state() -> tuple[str, str]:
    """('off' | 'unknown' | 'ok' | 'failed' | 'missing', reason) of the selected custom CLI.
    Lock-free on purpose (the UI thread calls it while a worker may be probing)."""
    c = dict(_custom)
    return c["state"], c["reason"]

def _file_key(p: Path):
    try:
        st = p.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size) if p.is_file() else None

def probe_cli(path, timeout: float = 15) -> tuple[bool, str]:
    """Does this file start as a MoonDeck CLI? Runs '<path> --help' (argparse usage,
    exit 0). Returns (ok, reason)."""
    p = Path(path)
    if not p.is_file():
        return False, t("cli_custom_missing_reason")
    try:
        r = subprocess.run([str(p), "--help"], cwd=str(APP_DIR) if APP_DIR.is_dir() else None,
                           capture_output=True, text=True,
                           errors="replace", timeout=timeout, env=child_env(), **_no_window())
    except subprocess.TimeoutExpired:
        return False, "Timeout"
    except OSError as e:
        return False, str(e)
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode == 0 and "usage" in out.lower():
        return True, ""
    first = out.strip().splitlines()[-1][:200] if out.strip() else ""
    return False, f"Exit {r.returncode}" + (f": {first}" if first else "")

def _set_custom_state(state: str, reason: str, key=None) -> bool:
    """Caller holds _cli_lock. True when the state changed."""
    changed = (_custom["state"], _custom["reason"]) != (state, reason)
    _custom.update(state=state, reason=reason, key=key)
    return changed

def _notify_cli(state: str, path: str, reason: str):
    if state in ("failed", "missing"):
        logging.warning("custom MoonDeck CLI %s (%s): %s – using the bundled CLI", state, path, reason)
    elif state == "ok":
        logging.info("custom MoonDeck CLI in use: %s", path)
    cb = _cli_listener
    if cb:
        try:
            cb(state, path, reason)
        except Exception:
            logging.exception("CLI listener")

def active_cli() -> Path:
    """The CLI that run_cli starts: the custom one when selected and it starts,
    otherwise the bundled one (CLI_BIN)."""
    changed = None
    with _cli_lock:
        path = _custom["path"]
        if not path:
            return CLI_BIN
        p = Path(path)
        key = _file_key(p)
        if key is None:
            if _set_custom_state("missing", t("cli_custom_missing_reason")):
                changed = ("missing", path, _custom["reason"])
        elif key != _custom["key"] or _custom["state"] in ("unknown", "missing"):
            ok, why = probe_cli(p)
            if _set_custom_state("ok" if ok else "failed", why, key):
                changed = (_custom["state"], path, why)
        state = _custom["state"]
    if changed:
        _notify_cli(*changed)
    return p if state == "ok" else CLI_BIN

def _custom_start_failed(path: Path, err: str):
    """run_cli could not start the custom CLI (it passed the probe before)."""
    with _cli_lock:
        if str(path) != _custom["path"]:
            return
        changed = _set_custom_state("failed", err, _file_key(path))
    if changed:
        _notify_cli("failed", str(path), err)

def cli_available() -> bool:
    """A CLI to run exists: the bundled one, or a selected custom file."""
    if CLI_BIN.is_file():
        return True
    path = _custom["path"]
    return bool(path) and Path(path).is_file()

def _exec_cli(cli: Path, args: list, timeout, config_override: Path | None):
    cfg = str(config_override or CONFIG_FILE)
    cmd = [str(cli), "--config-file", cfg] + args
    logging.debug("CLI %s", cmd)
    # cwd: the writable user/app dir (never the read-only bundle)
    p = subprocess.run(cmd, cwd=str(APP_DIR), capture_output=True, text=True,
                       timeout=timeout, env=child_env(), **_no_window())
    logging.debug("CLI rc=%s", p.returncode)
    return p.returncode, p.stdout, p.stderr

def run_cli(args: list, timeout=90, config_override: Path | None = None) -> tuple[int, str, str]:
    cli = active_cli()
    if not cli.is_file():
        return -1, "", t("cli_not_found")
    try:
        try:
            return _exec_cli(cli, args, timeout, config_override)
        except OSError as e:
            if cli == CLI_BIN or not CLI_BIN.is_file():
                raise
            # the custom CLI did not even start: nothing ran, the bundled one takes over
            _custom_start_failed(cli, str(e))
            return _exec_cli(CLI_BIN, args, timeout, config_override)
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
    kw = _no_window()
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

# MoonDeck Buddy API the bundled CLI speaks (moondeck lib/constants.py BUDDY_API_VERSION);
# build-appimage.sh may write it into moondeck-cli.version as "buddy_api".
BUDDY_API_DEFAULT = 9
BUDDY_NEEDS_UPDATE = "MoonDeck/Buddy needs update!"     # CLI output on an API mismatch

def expected_buddy_api() -> int:
    try:
        v = int((bundled_cli_info() or {}).get("buddy_api") or 0)
    except (TypeError, ValueError):
        v = 0
    return v if v > 0 else BUDDY_API_DEFAULT

def parse_api_version(body: str) -> int | None:
    """Body of Buddy's /apiVersion ({"version": 9}) -> 9; None if unreadable."""
    try:
        data = json.loads(body)
    except (TypeError, ValueError):
        return None
    v = data.get("version") if isinstance(data, dict) else None
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.strip().isdigit():
        return int(v.strip())
    return None

def api_mismatch(host_api: int | None, cli_output: str = "", want: int | None = None) -> dict | None:
    """{'host': n|None, 'want': m, 'dir': 'host_old' | 'host_new' | 'unknown'} when the
    Buddy API does not match what the bundled CLI expects, else None. The CLI's
    "MoonDeck/Buddy needs update!" counts as a mismatch even without a version."""
    want = expected_buddy_api() if want is None else want
    if host_api is not None:
        if host_api == want:
            return None
        return {"host": host_api, "want": want, "dir": "host_old" if host_api < want else "host_new"}
    if BUDDY_NEEDS_UPDATE in (cli_output or ""):
        return {"host": None, "want": want, "dir": "unknown"}
    return None

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


# --- MoonDeck CLI release (nightly) -------------------------------------------------
CLI_RELEASE_API = "https://api.github.com/repos/FrogTheFrog/moondeck/releases/tags/nightly"
CLI_RELEASE_PAGE = "https://github.com/FrogTheFrog/moondeck/releases/tag/nightly"

def cli_asset_name(platform: str = sys.platform) -> str:
    """Release asset of the MoonDeck CLI for this OS."""
    return "moondeck-cli-win.exe" if platform == "win32" else "moondeck-cli-linux.bin"

def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def parse_cli_release(data: dict, asset: str | None = None) -> dict:
    """GitHub release JSON -> {'digest', 'commit', 'url', 'published'} (digest '' if
    the asset has none)."""
    asset = asset or cli_asset_name()
    digest = ""
    for a in data.get("assets", []) or []:
        if a.get("name") == asset:
            digest = str(a.get("digest") or "").split(":")[-1].strip().lower()
            break
    commit = str(data.get("target_commitish") or "")
    if not all(ch in "0123456789abcdef" for ch in commit.lower()) or len(commit) < 7:
        commit = ""             # a branch name, not a commit
    url = str(data.get("html_url") or "")
    if not url.startswith("https://github.com/"):
        url = CLI_RELEASE_PAGE
    return {"digest": digest, "commit": commit[:7], "url": url,
            "published": str(data.get("published_at") or "")}

def fetch_cli_release(timeout: float = 15) -> dict:
    """parse_cli_release() of the MoonDeck nightly release; raises on any problem."""
    req = urllib.request.Request(CLI_RELEASE_API, headers={
        "User-Agent": f"BuddyRemote/{APP_VERSION} (+https://github.com/deciderino/BuddyRemote)",
        "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout, context=cacerts.https_context()) as r:
        data = json.loads(r.read().decode("utf-8", errors="replace"))
    if not isinstance(data, dict):
        raise ValueError("unexpected release data")
    return parse_cli_release(data)

def bundled_cli_digest() -> str:
    """SHA-256 of the bundled CLI (never the custom one): packaged from the version file
    (pinned at build time), else / as fallback hashed from the file."""
    info = bundled_cli_info() or {}
    d = str(info.get("sha256") or "").strip().lower()
    if PACKAGED and len(d) == 64:
        return d
    try:
        return sha256_file(CLI_BIN)
    except OSError:
        return d if len(d) == 64 else ""

def compare_cli_release(local_digest: str, rel: dict) -> dict:
    """{'ok', 'newer', 'commit', 'url'}: the nightly asset differs from the bundled CLI
    (nightly only moves forward, so 'different' means 'newer')."""
    remote = rel.get("digest", "")
    if not remote or not local_digest:
        return {"ok": False, "newer": False, "commit": rel.get("commit", ""), "url": rel.get("url", ""),
                "error": "no checksum" if not remote else "bundled CLI not found"}
    return {"ok": True, "newer": remote != local_digest.lower(), "commit": rel.get("commit", ""),
            "url": rel.get("url") or CLI_RELEASE_PAGE}

def check_cli_update(timeout: float = 10) -> dict:
    """Update check for the bundled MoonDeck CLI: reads the nightly release, downloads nothing."""
    return compare_cli_release(bundled_cli_digest(), fetch_cli_release(timeout))


def verify_existing_cli() -> tuple[bool, str]:
    """Re-check the already downloaded CLI against the current GitHub digest."""
    if not CLI_BIN.exists():
        return False, "CLI not found"
    try:
        expected = fetch_cli_release(15)["digest"]
        if not expected:
            return False, "No official checksum available"
        actual = sha256_file(CLI_BIN)
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
