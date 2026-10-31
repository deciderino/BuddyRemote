"""BuddyRemote – host tiles: data model and grid layout (no Qt, unit-testable).

Every host has a list ``aktionen``; each entry is one tile on the host card::

    {"typ": "boot", "sichtbar": true, "groesse": "gross", "pos": [0, 1]}

- ``typ``      action / status type (see TYPES). Unknown types (e.g. written by a
               newer version) are kept untouched in the list, but never shown and
               never occupy grid cells.
- ``sichtbar`` hidden tiles are not shown and do not occupy cells ("hide instead
               of delete"); they keep their last position for when they come back.
- ``groesse``  one of the fixed sizes in SIZES (no free resizing).
- ``pos``      [column, row] of the top-left cell in a grid with COLS columns.
- ``dup``      only on duplicates: 1, 2, ... A duplicate is a second tile of the same
               action (e.g. "Wecken" twice). Duplicates are always visible; removing
               one deletes it, while removing an original only hides it. Status tiles
               cannot be duplicated. Every tile has a unique key (see ``key``):
               the type for originals, "type#n" for duplicates.

All functions work on plain lists of dicts and return new lists (the input is
never modified), so the edit dialog can work on a copy and Cancel just drops it.

Extension point (not implemented): custom actions, e.g. a link to a host's web
interface, would be a new ``typ`` (say "web_link") with extra keys such as
{"url": "...", "label": "..."} in the same entry. The grid / collision code below
does not care about the type; only TYPES (for defaults) and HostRow (rendering /
click handler) would need an entry. Keep such actions independent of Sunshine:
only things that work with a running MoonDeck Buddy, or plain links.
"""

COLS = 4            # grid columns per host card
MAX_ROWS = 12       # safety limit for "next free cell" and moving down

# size name -> (width, height) in cells
SIZES = {
    "klein": (1, 1),
    "mittel": (2, 1),
    "breit": (4, 1),
    "gross": (2, 2),
}
SIZE_ORDER = ("klein", "mittel", "breit", "gross")

# known tile types -> what they are. "action" is the key the main window already
# uses (do_action / button navKey); status tiles have no action.
TYPES = {
    "online_status":    {"kind": "status", "action": None},
    "boot":             {"kind": "action", "action": "wake"},
    "shutdown":         {"kind": "action", "action": "shutdown"},
    "neustart":         {"kind": "action", "action": "restart"},
    "standby":          {"kind": "action", "action": "suspend"},
    "ruhezustand":      {"kind": "action", "action": "hibernate"},
    "steam_start_stop": {"kind": "action", "action": "steam"},   # steam_launch / steam_close toggle
}
TYPE_ORDER = ("online_status", "boot", "shutdown", "neustart",
              "standby", "ruhezustand", "steam_start_stop")
# Types of earlier versions that no longer exist. Saved entries of these types are
# dropped on load (migrate_host / normalize); everything else unknown is preserved.
# "steam_status": the Steam status tile; the card header shows "▶ Steam läuft" instead
# (global switch in the settings).
REMOVED_TYPES = ("steam_status",)


def _t(typ, size, col, row, visible=True):
    return {"typ": typ, "sichtbar": visible, "groesse": size, "pos": [col, row]}


STATUS_TYPES = ("online_status",)

# Templates. Every template lists every known type, so nothing is ever lost:
# what a template does not need is hidden, not deleted.
# Layout revision 2 ("calm status"): the status lives in the card header (dot, tooltip,
# "Steam läuft"), so the status tiles are hidden by default and only optional extras.
TEMPLATES = {
    "standard": [
        _t("boot", "klein", 0, 0), _t("shutdown", "klein", 1, 0),
        _t("neustart", "klein", 2, 0), _t("standby", "klein", 3, 0),
        _t("ruhezustand", "klein", 0, 1), _t("steam_start_stop", "klein", 1, 1),
        _t("online_status", "mittel", 0, 2, False),
    ],
    "minimal": [
        _t("boot", "mittel", 0, 0), _t("shutdown", "mittel", 2, 0),
        _t("online_status", "mittel", 0, 1, False),
        _t("neustart", "klein", 0, 2, False), _t("standby", "klein", 1, 2, False),
        _t("ruhezustand", "klein", 2, 2, False), _t("steam_start_stop", "klein", 3, 2, False),
    ],
    "server": [
        _t("boot", "mittel", 0, 0), _t("neustart", "klein", 2, 0), _t("shutdown", "klein", 3, 0),
        _t("online_status", "mittel", 0, 1, False),
        _t("standby", "klein", 0, 2, False), _t("ruhezustand", "klein", 1, 2, False),
        _t("steam_start_stop", "klein", 2, 2, False),
    ],
    "gaming": [
        _t("boot", "gross", 0, 0), _t("steam_start_stop", "gross", 2, 0),
        _t("shutdown", "klein", 0, 2), _t("neustart", "klein", 1, 2),
        _t("standby", "klein", 2, 2), _t("ruhezustand", "klein", 3, 2),
        _t("online_status", "mittel", 0, 3, False),
    ],
}
TEMPLATE_ORDER = ("standard", "minimal", "server", "gaming")
DEFAULT_TEMPLATE = "standard"
LAYOUT_REV = 2          # host["layout_rev"]; below 2: status tiles still visible (see migrate_host)

# Templates of layout revision 1 (status tiles on top). Only used to recognise an
# unchanged template layout during the migration to revision 2.
OLD_TEMPLATES = {
    # 1.2 layout: status line, then all power buttons, then Steam
    "standard": [
        _t("online_status", "mittel", 0, 0), _t("steam_status", "mittel", 2, 0),
        _t("boot", "klein", 0, 1), _t("shutdown", "klein", 1, 1),
        _t("neustart", "klein", 2, 1), _t("standby", "klein", 3, 1),
        _t("ruhezustand", "klein", 0, 2), _t("steam_start_stop", "klein", 1, 2),
    ],
    "minimal": [
        _t("online_status", "breit", 0, 0),
        _t("boot", "mittel", 0, 1), _t("shutdown", "mittel", 2, 1),
        _t("steam_status", "mittel", 0, 2, False), _t("neustart", "klein", 0, 3, False),
        _t("standby", "klein", 1, 3, False), _t("ruhezustand", "klein", 2, 3, False),
        _t("steam_start_stop", "klein", 3, 3, False),
    ],
    "server": [
        _t("online_status", "breit", 0, 0),
        _t("boot", "mittel", 0, 1), _t("neustart", "klein", 2, 1), _t("shutdown", "klein", 3, 1),
        _t("standby", "klein", 0, 2, False), _t("ruhezustand", "klein", 1, 2, False),
        _t("steam_status", "mittel", 2, 2, False), _t("steam_start_stop", "klein", 0, 3, False),
    ],
    "gaming": [
        _t("online_status", "mittel", 0, 0), _t("steam_status", "mittel", 2, 0),
        _t("boot", "gross", 0, 1), _t("steam_start_stop", "gross", 2, 1),
        _t("shutdown", "klein", 0, 3), _t("neustart", "klein", 1, 3),
        _t("standby", "klein", 2, 3), _t("ruhezustand", "klein", 3, 3),
    ],
}


def copy_tiles(tiles):
    out = []
    for a in tiles:
        if not isinstance(a, dict):          # broken / foreign entries are kept as they are
            out.append(a)
            continue
        b = dict(a)
        if isinstance(b.get("pos"), list):
            b["pos"] = list(b["pos"])
        out.append(b)
    return out


def template(name=DEFAULT_TEMPLATE):
    return copy_tiles(TEMPLATES.get(name) or TEMPLATES[DEFAULT_TEMPLATE])


def is_removed(tile) -> bool:
    """An entry of a tile type that was removed (see REMOVED_TYPES)."""
    return isinstance(tile, dict) and tile.get("typ") in REMOVED_TYPES


def drop_removed(tiles):
    """Remove the entries of removed tile types. Rows that became empty *only* because
    a visible removed tile is gone are closed (the tiles below move up), so no hole is
    left; rows the user left empty on purpose stay empty. Returns a new list."""
    tiles = copy_tiles(tiles)
    if not any(is_removed(a) for a in tiles):
        return tiles
    def ok(a):
        return isinstance(a, dict) and _valid_pos(a.get("pos")) and a.get("groesse") in SIZES

    def rows(ts):
        out = set()
        for a in ts:
            if ok(a) and a.get("sichtbar", True) and (is_known(a) or is_removed(a)):
                out |= {r for (_, r) in cells(a["pos"], a["groesse"])}
        return out
    before = rows(tiles)
    kept = [a for a in tiles if not is_removed(a)]
    gone = sorted(before - rows(kept))
    if gone:
        for a in kept:
            if is_known(a) and ok(a):
                a["pos"] = [a["pos"][0], a["pos"][1] - sum(1 for r in gone if r < a["pos"][1])]
    return kept


def is_known(tile) -> bool:
    return isinstance(tile, dict) and tile.get("typ") in TYPES


def is_active(tile) -> bool:
    """Shown on the card and occupying grid cells."""
    return is_known(tile) and bool(tile.get("sichtbar", True))


def cells(pos, size):
    w, h = SIZES[size]
    c, r = pos
    return {(c + dx, r + dy) for dx in range(w) for dy in range(h)}


def fits(pos, size) -> bool:
    w, h = SIZES[size]
    c, r = pos
    return 0 <= c and c + w <= COLS and 0 <= r and r + h <= MAX_ROWS


def occupied(tiles, skip=None) -> set:
    """Cells used by the visible known tiles (optionally without index ``skip``)."""
    used = set()
    for i, a in enumerate(tiles):
        if i != skip and is_active(a):
            used |= cells(a["pos"], a["groesse"])
    return used


def is_free(tiles, pos, size, skip=None) -> bool:
    return fits(pos, size) and not (cells(pos, size) & occupied(tiles, skip))


def next_free(tiles, size, skip=None, start=(0, 0)):
    """First free position for ``size`` in reading order (row by row), starting at
    ``start``; None if the grid is full."""
    used = occupied(tiles, skip)
    w, h = SIZES[size]
    for r in range(start[1], MAX_ROWS - h + 1):
        for c in range(start[0] if r == start[1] else 0, COLS - w + 1):
            if not (cells((c, r), size) & used):
                return [c, r]
    return None


def _valid_pos(p) -> bool:
    return (isinstance(p, (list, tuple)) and len(p) == 2
            and all(isinstance(v, int) and not isinstance(v, bool) for v in p))


def normalize(tiles):
    """Make a tile list safe to show: fix sizes/positions, resolve overlaps, add
    missing known types (hidden), drop duplicate known types. Entries that are no
    dict (broken, nothing usable in them) are dropped; unknown tile types (e.g. from
    a newer version) are kept exactly as they are and keep their place in the list."""
    defaults = {a["typ"]: a for a in TEMPLATES[DEFAULT_TEMPLATE]}
    out, seen = [], set()
    for a in tiles if isinstance(tiles, list) else []:
        if not isinstance(a, dict):
            continue                         # broken entry (hand-edited config): dropped
        if is_removed(a):
            continue                         # type removed in this version (REMOVED_TYPES)
        if not is_known(a):
            out.append(a)                    # unknown type (newer version): preserved as-is
            continue
        if "dup" in a and not (TYPES[a["typ"]]["kind"] == "action" and isinstance(a["dup"], int)
                               and not isinstance(a["dup"], bool) and a["dup"] >= 1):
            continue                         # broken duplicate entry
        if not a.get("sichtbar", True) and is_dup(a):
            continue                         # duplicates are never hidden, only removed
        if key(a) in seen:
            continue
        seen.add(key(a))
        b = dict(a)
        if b.get("groesse") not in SIZES:
            b["groesse"] = defaults[b["typ"]]["groesse"]
        b["sichtbar"] = bool(b.get("sichtbar", True))
        b["pos"] = list(b["pos"]) if _valid_pos(b.get("pos")) else None
        out.append(b)
    for typ in TYPE_ORDER:                   # e.g. a type added in a later version
        if typ not in seen:
            d = dict(defaults[typ])
            d["sichtbar"] = False
            d["pos"] = list(d["pos"])
            out.append(d)
    # place in list order; anything that does not fit or collides moves to the next free cell
    placed = []
    for a in out:
        if not is_known(a):
            continue
        if a["pos"] is None or not fits(a["pos"], a["groesse"]) or (
                a["sichtbar"] and cells(a["pos"], a["groesse"]) & occupied(placed)):
            spot = next_free(placed, a["groesse"]) if a["sichtbar"] else None
            if a["sichtbar"] and spot is None:
                a["sichtbar"] = False        # grid full: hide instead of overlapping
            a["pos"] = spot or [0, 0]
        placed.append(a)
    return [a for a in out if not (is_dup(a) and not a["sichtbar"])]    # no room: drop duplicate


def _visible_key(ts):
    return sorted((a["typ"], a["groesse"], tuple(a["pos"])) for a in ts
                  if is_active(a) and _valid_pos(a.get("pos")) and a.get("groesse") in SIZES)


def calm_status(tiles):
    """Layout revision 1 -> 2: hide the status tiles (the card header shows the status now).

    - A layout that still equals one of the old templates becomes the new version of that
      template (unknown entries are kept, at the end).
    - Any other (custom) layout keeps every position; only online_status is hidden and the
      removed steam_status tile is dropped; rows that became empty *only* because of that
      are removed (the tiles below move up), so no hole is left where the status line was. Rows the user left
      empty on purpose stay empty.
    """
    tiles = copy_tiles(tiles)
    known = [a for a in tiles if is_known(a)]
    mine = _visible_key(known)
    old_known = lambda ts: [a for a in ts if is_known(a)]    # noqa: E731 (removed types ignored)
    for name in TEMPLATE_ORDER:
        if mine and _visible_key(old_known(OLD_TEMPLATES[name])) == mine and not any(is_dup(a) for a in known):
            return template(name) + [a for a in tiles if not is_known(a) and not is_removed(a)]
    ok = [a for a in tiles if is_active(a) and _valid_pos(a.get("pos")) and a.get("groesse") in SIZES]
    gone_types = [a for a in tiles if is_removed(a) and a.get("sichtbar", True)
                  and _valid_pos(a.get("pos")) and a.get("groesse") in SIZES]
    before = {r for (_, r) in occupied(ok)} | {r for a in gone_types for (_, r) in cells(a["pos"], a["groesse"])}
    tiles = [a for a in tiles if not is_removed(a)]
    for a in tiles:
        if is_known(a) and a["typ"] in STATUS_TYPES:
            a["sichtbar"] = False
    after = {r for (_, r) in occupied([a for a in ok if is_active(a)])}
    gone = sorted(before - after)
    if gone:
        for a in ok:
            if is_active(a):
                a["pos"] = [a["pos"][0], a["pos"][1] - sum(1 for r in gone if r < a["pos"][1])]
    return tiles


def migrate_host(host: dict) -> bool:
    """1.2 -> 1.3: hosts without ``aktionen`` get the default template; existing
    lists from an older layout revision get the calm status (see calm_status), then
    every list is normalized (entries that are no dict are dropped there). Returns
    True if the host dict was changed."""
    if not isinstance(host.get("aktionen"), list):
        host["aktionen"] = template(DEFAULT_TEMPLATE)
        host["layout_rev"] = LAYOUT_REV
        return True
    changed = False
    rev = host.get("layout_rev")
    if not isinstance(rev, int) or isinstance(rev, bool) or rev < LAYOUT_REV:
        host["aktionen"] = calm_status(host["aktionen"])
        host["layout_rev"] = LAYOUT_REV
        changed = True
    if any(is_removed(a) for a in host["aktionen"]):
        host["aktionen"] = drop_removed(host["aktionen"])
        changed = True
    new = normalize(host["aktionen"])
    if new != host["aktionen"]:
        host["aktionen"] = new
        return True
    return changed


def is_dup(tile) -> bool:
    return isinstance(tile, dict) and bool(tile.get("dup"))


def key(tile) -> str:
    """Unique key of a tile: "boot" for the original, "boot#2" for a duplicate."""
    return f'{tile["typ"]}#{tile["dup"]}' if is_dup(tile) else tile["typ"]


def find(tiles, k):
    """Index of the tile with key ``k`` (a plain type finds the original)."""
    return next((i for i, a in enumerate(tiles) if is_known(a) and key(a) == k), None)


# --- edit operations (return (new_tiles, result) ; result: "ok" | "moved" | "blocked") --
def move(tiles, idx, dc, dr):
    """Move tile ``idx`` by (dc, dr) cells. Free target: moved. Target fully covered
    by exactly one other tile of the same size: the two swap. Otherwise blocked."""
    tiles = copy_tiles(tiles)
    a = tiles[idx]
    if not is_active(a):
        return tiles, "blocked"
    new = [a["pos"][0] + dc, a["pos"][1] + dr]
    if not fits(new, a["groesse"]):
        return tiles, "blocked"
    if is_free(tiles, new, a["groesse"], skip=idx):
        a["pos"] = new
        return tiles, "ok"
    target = cells(new, a["groesse"]) - cells(a["pos"], a["groesse"])
    others = [j for j, b in enumerate(tiles)
              if j != idx and is_active(b) and cells(b["pos"], b["groesse"]) & target]
    if len(others) == 1:
        b = tiles[others[0]]
        if b["groesse"] == a["groesse"] and b["pos"] == new:
            b["pos"], a["pos"] = list(a["pos"]), new
            return tiles, "ok"
    return tiles, "blocked"


def resize(tiles, idx, size):
    """Change the size. Keeps the position if the new cells are free, otherwise the
    tile goes to the next free cell. Blocked only if the grid is full."""
    if size not in SIZES:
        return copy_tiles(tiles), "blocked"
    tiles = copy_tiles(tiles)
    a = tiles[idx]
    if not is_active(a):
        a["groesse"] = size
        return tiles, "ok"
    if is_free(tiles, a["pos"], size, skip=idx):
        a["groesse"] = size
        return tiles, "ok"
    spot = next_free(tiles, size, skip=idx)
    if spot is None:
        return tiles, "blocked"
    a["groesse"], a["pos"] = size, spot
    return tiles, "moved"


def set_visible(tiles, idx, on: bool):
    """Hide (always possible) or show again: old position if still free, otherwise
    the next free cell."""
    tiles = copy_tiles(tiles)
    a = tiles[idx]
    if not on or bool(a.get("sichtbar", True)):
        a["sichtbar"] = bool(on)
        return tiles, "ok"
    if _valid_pos(a.get("pos")) and is_free(tiles, a["pos"], a["groesse"], skip=idx):
        a["sichtbar"] = True
        return tiles, "ok"
    spot = next_free(tiles, a["groesse"], skip=idx)
    if spot is None:
        return tiles, "blocked"
    a["sichtbar"], a["pos"] = True, spot
    return tiles, "moved"


def rows_used(tiles) -> int:
    used = occupied(tiles)
    return max((r for _, r in used), default=-1) + 1


def matching_template(tiles):
    """Name of the template the visible layout equals, or None (custom)."""
    def key(ts):
        return sorted((a["typ"], a["groesse"], tuple(a["pos"])) for a in ts if is_active(a))
    mine = key(tiles)
    for name in TEMPLATE_ORDER:
        if key(TEMPLATES[name]) == mine:
            return name
    return None


def apply_template(tiles, name):
    """Use a template but keep unknown entries (preserved, at the end)."""
    return template(name) + [a for a in tiles if not is_known(a)]


# --- drag & drop ---------------------------------------------------------------------
def in_grid(pos, size, max_rows=MAX_ROWS) -> bool:
    """Tile ``size`` at ``pos`` lies completely inside COLS x ``max_rows``."""
    if not _valid_pos(pos) or size not in SIZES:
        return False
    w, h = SIZES[size]
    c, r = pos
    return 0 <= c and c + w <= COLS and 0 <= r and r + h <= min(max_rows, MAX_ROWS)


def reflow(tiles, idx, pos, max_rows=MAX_ROWS):
    """Drop visible tile ``idx`` with its top-left cell at ``pos`` (drag & drop).

    Visible tiles under the dropped one make room, everything else stays put:
      1. a displaced tile first tries the cells the dragged tile left (so two tiles
         of the same size simply swap; two "klein" fill a vacated "mittel"),
      2. otherwise it takes the free position closest to where it was
         (Manhattan distance, ties: upper row, then left column).
    Always computed from ``tiles`` as given (the layout at drag start), so while the
    pointer moves, tiles that were pushed aside return as soon as their cells are free
    again. Hidden and unknown entries are never touched.

    Returns (new_tiles, result): "ok" (nothing else moved), "reflow" (others moved)
    or "blocked" (outside the grid of ``max_rows`` rows, hidden tile, or no room for
    a displaced tile) - blocked returns an unchanged copy, i.e. the tile goes back."""
    orig = copy_tiles(tiles)
    if not (0 <= idx < len(orig)) or not is_active(orig[idx]) or not _valid_pos(pos):
        return orig, "blocked"
    a = orig[idx]
    size = a["groesse"]
    if not in_grid(pos, size, max_rows):
        return orig, "blocked"
    pos = list(pos)
    if pos == a["pos"]:
        return orig, "ok"
    out = copy_tiles(orig)
    out[idx]["pos"] = pos
    drop = cells(pos, size)
    vacated = cells(a["pos"], size) - drop
    others = sorted((j for j, b in enumerate(out) if j != idx and is_active(b)),
                    key=lambda j: (out[j]["pos"][1], out[j]["pos"][0]))
    displaced = [j for j in others if cells(out[j]["pos"], out[j]["groesse"]) & drop]
    used = set(drop)
    for j in others:
        if j not in displaced:
            used |= cells(out[j]["pos"], out[j]["groesse"])
    rows = min(max_rows, MAX_ROWS)
    for j in displaced:
        b = out[j]
        bw, bh = SIZES[b["groesse"]]
        oc, orow = b["pos"]
        best = None
        for r in range(rows - bh + 1):
            for c in range(COLS - bw + 1):
                cs = cells((c, r), b["groesse"])
                if cs & used:
                    continue
                key = (0 if cs <= vacated else 1, abs(c - oc) + abs(r - orow), r, c)
                if best is None or key < best[0]:
                    best = (key, [c, r])
        if best is None:
            return orig, "blocked"
        b["pos"] = best[1]
        used |= cells(b["pos"], b["groesse"])
    return out, ("reflow" if displaced else "ok")


# --- duplicate / remove ---------------------------------------------------------------
MAX_DUPLICATES = 3      # per action


def can_duplicate(tiles, idx) -> bool:
    a = tiles[idx]
    if not is_active(a) or TYPES[a["typ"]]["kind"] != "action":
        return False
    if sum(1 for b in tiles if is_known(b) and b["typ"] == a["typ"] and is_dup(b)) >= MAX_DUPLICATES:
        return False
    return next_free(tiles, a["groesse"]) is not None or next_free(tiles, "klein") is not None


def duplicate(tiles, idx):
    """Second tile of the same action, same size, at the next free cell (as "klein" if
    the size does not fit anymore). Returns (new_tiles, result, new_key); result
    "ok" or "blocked" (status tile, hidden, limit reached, grid full)."""
    tiles = copy_tiles(tiles)
    if not (0 <= idx < len(tiles)) or not can_duplicate(tiles, idx):
        return tiles, "blocked", None
    a = tiles[idx]
    used = {b["dup"] for b in tiles if is_known(b) and b["typ"] == a["typ"] and is_dup(b)}
    n = next(i for i in range(1, MAX_DUPLICATES + 2) if i not in used)
    size = a["groesse"]
    spot = next_free(tiles, size)
    if spot is None:
        size, spot = "klein", next_free(tiles, "klein")
    new = {"typ": a["typ"], "sichtbar": True, "groesse": size, "pos": spot, "dup": n}
    last = max(i for i, b in enumerate(tiles) if is_known(b) and b["typ"] == a["typ"])
    tiles.insert(last + 1, new)
    return tiles, "ok", key(new)


def remove(tiles, idx):
    """Remove a tile from the card: a duplicate is deleted ("removed"), an original
    action/status tile is only hidden ("hidden") so it can be shown again."""
    tiles = copy_tiles(tiles)
    if not (0 <= idx < len(tiles)) or not is_known(tiles[idx]):
        return tiles, "blocked"
    if is_dup(tiles[idx]):
        del tiles[idx]
        return tiles, "removed"
    tiles[idx]["sichtbar"] = False
    return tiles, "hidden"


# --- automatic arrangement: presets and "by usage" ---------------------------------------
def _ordered_keys(tiles):
    """Visible tiles in default order (TYPE_ORDER), duplicates right after their original."""
    vis = [a for a in tiles if is_active(a)]
    return [key(a) for a in sorted(vis, key=lambda a: (TYPE_ORDER.index(a["typ"]), a.get("dup") or 0))]


def arrange(tiles, order, sizes=None):
    """Re-place the visible tiles: ``order`` (tile keys) top-left to bottom-right, first
    free cell each (so smaller tiles fill gaps), optional new ``sizes`` (key -> size).
    A tile whose size no longer fits becomes "klein". Hidden/unknown entries untouched."""
    out = copy_tiles(tiles)
    sizes = sizes or {}
    placed = []
    rest = [k for k in _ordered_keys(out) if k not in order]
    for k in list(order) + rest:
        i = find(out, k)
        if i is None or not is_active(out[i]):
            continue
        a = out[i]
        size = sizes.get(k, a["groesse"])
        spot = next_free(placed, size)
        if spot is None:
            size, spot = "klein", next_free(placed, "klein")
        if spot is None:             # cannot happen with MAX_ROWS >= number of tiles
            a["sichtbar"] = False
            continue
        a["groesse"], a["pos"] = size, spot
        placed.append(a)
    return out


# Presets change sizes + arrangement only; which tiles are visible is the template's job.
PRESET_ORDER = ("kompakt", "grosszuegig")


def apply_preset(tiles, name):
    """"kompakt": status tiles mittel, all actions klein (dense).
    "grosszuegig": status mittel (breit if it is the only one), Wecken and Steam groß,
    the other actions mittel."""
    order = _ordered_keys(tiles)
    status = [k for k in order if TYPES[k.split("#")[0]]["kind"] == "status"]
    sizes = {}
    for k in order:
        typ = k.split("#")[0]
        if TYPES[typ]["kind"] == "status":
            sizes[k] = "breit" if (name == "grosszuegig" and len(status) == 1) else "mittel"
        elif name == "kompakt":
            sizes[k] = "klein"
        else:
            sizes[k] = "gross" if (typ in ("boot", "steam_start_stop") and "#" not in k) else "mittel"
    big = [k for k in order if sizes[k] == "gross"]          # big ones side by side under the status
    order = status + big + [k for k in order if k not in status and k not in big]
    return arrange(tiles, order, sizes)


def auto_arrange(tiles, usage=None):
    """Arrange by how often the actions were used (``usage``: type -> count, kept per
    host in the config). Status tiles stay on top, then the actions, most used first;
    the most used one gets "gross" (if it has >= 40 % of all uses and at least 3),
    the next one "mittel" (if used at all), the rest "klein". Duplicates follow their
    original as "klein". Without any usage data: the default order, sizes unchanged.
    Returns (new_tiles, "usage" | "default")."""
    usage = {k: v for k, v in (usage or {}).items() if isinstance(v, int) and v > 0}
    order = _ordered_keys(tiles)
    status = [k for k in order if TYPES[k.split("#")[0]]["kind"] == "status"]
    acts = [k for k in order if k not in status]
    if not any(usage.get(k.split("#")[0]) for k in acts):
        return arrange(tiles, order), "default"
    originals = sorted((k for k in acts if "#" not in k),
                       key=lambda k: (-usage.get(k, 0), TYPE_ORDER.index(k)))
    total = sum(usage.get(k, 0) for k in originals)
    sizes, ranked = {}, []
    for n, k in enumerate(originals):
        c = usage.get(k, 0)
        if n == 0 and c >= 3 and c >= 0.4 * total:
            sizes[k] = "gross"
        elif n <= 1 and c > 0:
            sizes[k] = "mittel"
        else:
            sizes[k] = "klein"
        ranked.append(k)
        for d in acts:
            if d.startswith(k + "#"):
                sizes[d] = "klein"
                ranked.append(d)
    return arrange(tiles, status + ranked, sizes), "usage"


def action_type(action: str):
    """Tile type for a main-window action key (for counting usage)."""
    if action in ("steam_launch", "steam_close"):
        action = "steam"
    return next((typ for typ, info in TYPES.items() if info["action"] == action), None)


# --- online status: one label with a priority chain -------------------------------------
def online_state(result) -> str:
    """"buddy" (MoonDeck Buddy answers, so the PC is on) > "pc" (PC answers ping, Buddy
    does not) > "offline". "unknown" without a check result."""
    if not isinstance(result, dict) or not result:
        return "unknown"
    if result.get("buddy"):
        return "buddy"
    if result.get("ping"):
        return "pc"
    return "offline"
