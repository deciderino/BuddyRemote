"""BuddyRemote – config.json (defaults, load/sanitize/save, first-start seed, client ID) and logging."""

import json
import logging
import shutil
import uuid

import tiles

from paths import CONFIG_FILE, SEED_CONFIG, LOG_FILE


def seed_config():
    """First start: copy the shipped defaults (packaging/default-config.json, also inside
    the bundle) to config.json. The user's config.json itself is not part of the repo."""
    if not CONFIG_FILE.exists() and SEED_CONFIG.is_file():
        shutil.copyfile(SEED_CONFIG, CONFIG_FILE)


def setup_logging(enabled: bool):
    handlers = [logging.FileHandler(LOG_FILE, encoding="utf-8")] if enabled else [logging.NullHandler()]
    logging.basicConfig(level=logging.DEBUG if enabled else logging.WARNING,
                        format="%(asctime)s [%(levelname)s] %(message)s",
                        handlers=handlers, force=True)


DEFAULT_CONFIG = {
    "version": 1,
    "settings": {
        "status_interval": 30,
        "auto_status": True,
        "logging": False,
        "start_minimized": False,
        "language": "auto",
        "autostart": False,
        "confirm_actions": True,
        "tray_color_change": True,
        "check_updates": True,
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
        changed = sanitize_config(data)
        # 1.2 -> 1.3: every host gets its tile list ("aktionen"); a 1.2 config gets
        # the standard template (no automatic backup copy). Unknown keys/types are kept.
        for h in data["hosts"]:
            changed |= tiles.migrate_host(h)
        if changed:
            try:
                save_config(data)
            except Exception:
                logging.exception("config migration save failed")
        return data
    except Exception:
        logging.exception("config load failed")
        return json.loads(json.dumps(DEFAULT_CONFIG))

# numeric settings: key -> (fallback, minimum, maximum); the ranges of the settings dialog
NUMERIC_SETTINGS = {"status_interval": (30, 10, 300)}


def sanitize_config(data: dict) -> bool:
    """Hand-edited / damaged configs (UI robustness, the connection data stays as it is):
    - hosts that are no dict are dropped (nothing usable in them),
    - hosts without a usable id get a new one (the cards and usage counts need it),
    - numeric settings become int within the dialog range (fallback: the default).
    Returns True if something was changed (then the config is saved)."""
    changed = False
    if not isinstance(data.get("hosts"), list):
        data["hosts"] = []
        changed = True
    hosts = [h for h in data["hosts"] if isinstance(h, dict)]
    if len(hosts) != len(data["hosts"]):
        logging.warning("config: %d host entries without data dropped", len(data["hosts"]) - len(hosts))
        data["hosts"] = hosts
        changed = True
    used = {h.get("id") for h in hosts if isinstance(h.get("id"), str) and h.get("id")}
    for h in hosts:
        hid = h.get("id")
        if not isinstance(hid, str) or not hid:
            new = uuid.uuid4().hex[:8]
            while new in used:
                new = uuid.uuid4().hex[:8]
            used.add(new)
            h["id"] = new
            logging.warning("config: host %r got the id %s", h.get("name", ""), new)
            changed = True
    st = data["settings"]
    for k, (default, lo, hi) in NUMERIC_SETTINGS.items():
        v = st.get(k, default)
        try:
            if isinstance(v, bool):
                raise ValueError
            n = int(float(v)) if isinstance(v, str) else int(v)
        except (TypeError, ValueError, OverflowError):
            n = default
        n = max(lo, min(hi, n))
        if n != v or type(v) is not int:
            st[k] = n
            changed = True
    return changed


def save_config(cfg: dict):
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    tmp.replace(CONFIG_FILE)


def ensure_client_id(cfg: dict) -> str:
    """Generate and store a unique client ID if missing."""
    cid = cfg["settings"].get("client_id", "")
    if not cid:
        cid = f"buddyremote-{uuid.uuid4().hex[:8]}"
        cfg["settings"]["client_id"] = cid
        save_config(cfg)
    return cid
