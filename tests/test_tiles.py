"""Unit tests for tiles.py (grid, collision, templates, migration). No Qt needed:
    python3 -m unittest discover -s tests -v
"""
import copy
import json
import os
import sys
import unittest
import random

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import tiles  # noqa: E402


def pack_rows(ts):
    """Test helper (the app keeps empty rows): remove completely empty rows."""
    ts = tiles.copy_tiles(ts)
    used = sorted({r for (_, r) in tiles.occupied(ts)})
    remap = {r: n for n, r in enumerate(used)}
    for a in ts:
        if tiles.is_active(a):
            a["pos"] = [a["pos"][0], remap[a["pos"][1]]]
    return ts


def no_overlap(ts):
    seen = set()
    for a in ts:
        if tiles.is_active(a):
            c = tiles.cells(a["pos"], a["groesse"])
            if c & seen:
                return False
            if not tiles.fits(a["pos"], a["groesse"]):
                return False
            seen |= c
    return True


def _gap(typ, size, c, r, v=True):
    return {"typ": typ, "sichtbar": v, "groesse": size, "pos": [c, r]}


# Test fixtures: layouts with the (optional) status tile visible on top. The grid
# tests below were written against these; they test the grid logic, not the
# shipped templates.
STATUS_LAYOUTS = {
    "standard": [
        _gap("online_status", "mittel", 0, 0),
        _gap("boot", "klein", 0, 1), _gap("shutdown", "klein", 1, 1),
        _gap("neustart", "klein", 2, 1), _gap("standby", "klein", 3, 1),
        _gap("ruhezustand", "klein", 0, 2), _gap("steam_start_stop", "klein", 1, 2),
    ],
    "minimal": [
        _gap("online_status", "breit", 0, 0),
        _gap("boot", "mittel", 0, 1), _gap("shutdown", "mittel", 2, 1),
        _gap("neustart", "klein", 0, 3, False),
        _gap("standby", "klein", 1, 3, False), _gap("ruhezustand", "klein", 2, 3, False),
        _gap("steam_start_stop", "klein", 3, 3, False),
    ],
    "server": [
        _gap("online_status", "breit", 0, 0),
        _gap("boot", "mittel", 0, 1), _gap("neustart", "klein", 2, 1), _gap("shutdown", "klein", 3, 1),
        _gap("standby", "klein", 0, 2, False), _gap("ruhezustand", "klein", 1, 2, False),
        _gap("steam_start_stop", "klein", 0, 3, False),
    ],
    "gaming": [
        _gap("online_status", "mittel", 0, 0),
        _gap("boot", "gross", 0, 1), _gap("steam_start_stop", "gross", 2, 1),
        _gap("shutdown", "klein", 0, 3), _gap("neustart", "klein", 1, 3),
        _gap("standby", "klein", 2, 3), _gap("ruhezustand", "klein", 3, 3),
    ],
}


def old(name="standard"):
    return tiles.copy_tiles(STATUS_LAYOUTS[name])


def idx(ts, typ):
    return tiles.find(ts, typ)


class Templates(unittest.TestCase):
    def test_all_templates_valid(self):
        for name, ts in tiles.TEMPLATES.items():
            with self.subTest(name):
                self.assertTrue(no_overlap(ts))
                self.assertEqual(sorted(a["typ"] for a in ts), sorted(tiles.TYPE_ORDER))
                self.assertEqual(tiles.normalize(ts), ts, "template must already be normal")

    def test_template_contents(self):
        vis = lambda n: {a["typ"] for a in tiles.TEMPLATES[n] if a["sichtbar"]}
        status = set(tiles.STATUS_TYPES)
        self.assertEqual(vis("minimal"), {"boot", "shutdown"})
        self.assertFalse(vis("server") & {"steam_status", "steam_start_stop"})
        self.assertEqual(vis("server"), {"boot", "neustart", "shutdown"})
        self.assertEqual(vis("standard"), set(tiles.TYPE_ORDER) - status)
        self.assertIn("steam_start_stop", vis("gaming"))
        for n in tiles.TEMPLATE_ORDER:            # calm status: never visible by default
            self.assertFalse(vis(n) & status, n)
            self.assertEqual(tiles.rows_used(tiles.TEMPLATES[n]),
                             tiles.rows_used([a for a in tiles.TEMPLATES[n] if a["sichtbar"]]))

    def test_template_returns_copy(self):
        a = tiles.template("minimal")
        a[0]["pos"][0] = 3
        self.assertEqual(tiles.TEMPLATES["minimal"][0]["pos"], [0, 0])

    def test_matching_template(self):
        for n in tiles.TEMPLATE_ORDER:
            self.assertEqual(tiles.matching_template(tiles.template(n)), n)
        ts, _ = tiles.set_visible(tiles.template("minimal"), idx(tiles.template("minimal"), "boot"), False)
        self.assertIsNone(tiles.matching_template(ts))

    def test_apply_template_keeps_unknown(self):
        ts = tiles.template() + [{"typ": "web_link", "url": "http://x"}]
        out = tiles.apply_template(ts, "minimal")
        self.assertIn({"typ": "web_link", "url": "http://x"}, out)
        self.assertEqual(tiles.matching_template(out), "minimal")


class Grid(unittest.TestCase):
    def test_cells_and_fits(self):
        self.assertEqual(tiles.cells([1, 2], "gross"), {(1, 2), (2, 2), (1, 3), (2, 3)})
        self.assertTrue(tiles.fits([0, 0], "breit"))
        self.assertFalse(tiles.fits([1, 0], "breit"))
        self.assertFalse(tiles.fits([3, 0], "mittel"))
        self.assertFalse(tiles.fits([-1, 0], "klein"))

    def test_hidden_and_unknown_do_not_occupy(self):
        ts = [{"typ": "boot", "sichtbar": False, "groesse": "breit", "pos": [0, 0]},
              {"typ": "zukunft", "sichtbar": True, "groesse": "breit", "pos": [0, 0]}]
        self.assertEqual(tiles.occupied(ts), set())

    def test_next_free(self):
        ts = old("minimal")     # row 0 full, row 1 full
        self.assertEqual(tiles.next_free(ts, "klein"), [0, 2])
        ts2 = [{"typ": "boot", "sichtbar": True, "groesse": "klein", "pos": [1, 0]}]
        self.assertEqual(tiles.next_free(ts2, "klein"), [0, 0])
        self.assertEqual(tiles.next_free(ts2, "mittel"), [2, 0])
        self.assertEqual(tiles.next_free(ts2, "gross"), [2, 0])
        self.assertEqual(tiles.next_free(ts2, "breit"), [0, 1])


class Move(unittest.TestCase):
    def test_move_into_free_cell(self):
        ts = old("server")      # boot (0,1) mittel, neustart (2,1), shutdown (3,1)
        out, res = tiles.move(ts, idx(ts, "neustart"), 0, 1)
        self.assertEqual(res, "ok")
        self.assertEqual(out[idx(out, "neustart")]["pos"], [2, 2])
        self.assertEqual(ts[idx(ts, "neustart")]["pos"], [2, 1], "input unchanged")

    def test_move_blocked_by_edge(self):
        ts = old("server")
        for typ, d in (("online_status", (0, -1)), ("online_status", (1, 0)), ("shutdown", (1, 0)), ("boot", (-1, 0))):
            out, res = tiles.move(ts, idx(ts, typ), *d)
            self.assertEqual(res, "blocked", typ)
            self.assertEqual(out, ts)

    def test_swap_same_size(self):
        ts = old("server")
        out, res = tiles.move(ts, idx(ts, "neustart"), 1, 0)
        self.assertEqual(res, "ok")
        self.assertEqual(out[idx(out, "neustart")]["pos"], [3, 1])
        self.assertEqual(out[idx(out, "shutdown")]["pos"], [2, 1])
        self.assertTrue(no_overlap(out))

    def test_move_blocked_by_bigger_tile(self):
        ts = old("server")
        out, res = tiles.move(ts, idx(ts, "neustart"), -1, 0)    # into boot (mittel)
        self.assertEqual(res, "blocked")
        out, res = tiles.move(ts, idx(ts, "boot"), 0, -1)         # into online_status (breit)
        self.assertEqual(res, "blocked")

    def test_move_hidden_blocked(self):
        ts = old("minimal")
        self.assertEqual(tiles.move(ts, idx(ts, "neustart"), 1, 0)[1], "blocked")

    def test_random_walk_never_overlaps(self):
        import random
        rnd = random.Random(7)
        for name in tiles.TEMPLATE_ORDER:
            ts = old(name)
            for _ in range(400):
                i = rnd.randrange(len(ts))
                op = rnd.choice(("move", "resize", "vis"))
                if op == "move":
                    ts, _ = tiles.move(ts, i, *rnd.choice(((1, 0), (-1, 0), (0, 1), (0, -1))))
                elif op == "resize":
                    ts, _ = tiles.resize(ts, i, rnd.choice(tiles.SIZE_ORDER))
                else:
                    ts, _ = tiles.set_visible(ts, i, rnd.random() < 0.6)
                self.assertTrue(no_overlap(ts), (name, op, ts))
                self.assertEqual(len(ts), len(tiles.TYPE_ORDER))


class Resize(unittest.TestCase):
    def test_resize_in_place(self):
        ts = old("server")
        ts, _ = tiles.set_visible(ts, idx(ts, "neustart"), False)
        out, res = tiles.resize(ts, idx(ts, "shutdown"), "klein")
        self.assertEqual(res, "ok")
        # boot mittel (0,1) -> gross fits in place (row 2 is free)
        out, res = tiles.resize(ts, idx(ts, "boot"), "gross")
        self.assertEqual(res, "ok")
        self.assertEqual(out[idx(out, "boot")]["pos"], [0, 1])

    def test_resize_moves_to_next_free(self):
        ts = old("server")
        out, res = tiles.resize(ts, idx(ts, "neustart"), "mittel")   # (2,1)+(3,1) taken by shutdown
        self.assertEqual(res, "moved")
        self.assertEqual(out[idx(out, "neustart")]["pos"], [0, 2])
        self.assertTrue(no_overlap(out))

    def test_resize_invalid(self):
        ts = old()
        self.assertEqual(tiles.resize(ts, 0, "riesig")[1], "blocked")


class Visibility(unittest.TestCase):
    def test_hide_then_show_same_place(self):
        ts = old()
        i = idx(ts, "standby")
        out, _ = tiles.set_visible(ts, i, False)
        self.assertNotIn((3, 1), tiles.occupied(out))
        out, res = tiles.set_visible(out, i, True)
        self.assertEqual(res, "ok")
        self.assertEqual(out, ts)

    def test_show_when_place_taken(self):
        ts = old("minimal")
        i = idx(ts, "neustart")          # hidden at (0,3)
        ts[i]["pos"] = [0, 1]           # old place now covered by boot
        out, res = tiles.set_visible(ts, i, True)
        self.assertEqual(res, "moved")
        self.assertEqual(out[i]["pos"], [0, 2])


class Migration(unittest.TestCase):
    HOST_12 = {"id": "h0", "name": "Gaming-PC", "ip": "192.0.2.10", "mac": "00:00:5E:00:53:FF", "buddy_port": 59999}

    def test_12_host_gets_standard(self):
        h = copy.deepcopy(self.HOST_12)
        self.assertTrue(tiles.migrate_host(h))
        self.assertEqual(h["aktionen"], tiles.TEMPLATES["standard"])
        for k, v in self.HOST_12.items():
            self.assertEqual(h[k], v, "1.2 fields untouched")
        self.assertFalse(tiles.migrate_host(h), "second run is a no-op")

    def test_whole_12_config_roundtrip(self):
        cfg = {"version": 1, "settings": {"theme": "Dark"}, "hosts": [copy.deepcopy(self.HOST_12)],
               "future_key": {"x": 1}}
        for h in cfg["hosts"]:
            tiles.migrate_host(h)
        again = json.loads(json.dumps(cfg))
        self.assertEqual(again["future_key"], {"x": 1})
        self.assertFalse(tiles.migrate_host(again["hosts"][0]))

    def test_unknown_types_preserved(self):
        web = {"typ": "web_link", "sichtbar": True, "groesse": "breit", "pos": [0, 0], "url": "http://nas:8080"}
        h = dict(self.HOST_12, aktionen=[web, *tiles.template("minimal")])
        tiles.migrate_host(h)
        self.assertEqual(h["aktionen"][0], web)
        self.assertTrue(no_overlap(h["aktionen"]))
        self.assertEqual(tiles.matching_template(h["aktionen"]), "minimal")

    def test_broken_entries_fixed(self):
        h = dict(self.HOST_12, aktionen=[
            {"typ": "boot", "groesse": "riesig", "pos": "x"},
            {"typ": "boot", "sichtbar": True, "groesse": "klein", "pos": [3, 3]},      # duplicate
            {"typ": "shutdown", "sichtbar": True, "groesse": "breit", "pos": [2, 0]},   # does not fit
            {"typ": "neustart", "sichtbar": True, "groesse": "klein", "pos": [0, 0]},   # collides with boot? boot has no pos
            "garbage",
        ])
        tiles.migrate_host(h)
        a = h["aktionen"]
        self.assertTrue(no_overlap(a))
        self.assertEqual([x["typ"] for x in a if isinstance(x, dict)].count("boot"), 1)
        self.assertNotIn("garbage", a)          # no dict: nothing usable, dropped
        self.assertTrue(all(isinstance(x, dict) for x in a))
        self.assertEqual(sorted(x["typ"] for x in a if tiles.is_known(x)), sorted(tiles.TYPE_ORDER))
        added = [x for x in a if tiles.is_known(x) and x["typ"] == "ruhezustand"]
        self.assertTrue(all(not x["sichtbar"] for x in added), "missing types are added hidden")
        self.assertEqual(a[idx(a, "boot")]["groesse"], "klein")   # standard size for boot

    def test_overlapping_list_resolved(self):
        h = dict(self.HOST_12, aktionen=[
            {"typ": t, "sichtbar": True, "groesse": "gross", "pos": [0, 0]} for t in tiles.TYPE_ORDER])
        tiles.migrate_host(h)
        self.assertTrue(no_overlap(h["aktionen"]))
        self.assertTrue(all(x["sichtbar"] for x in h["aktionen"]), "every tile finds a free place")

    def test_not_a_list(self):
        h = dict(self.HOST_12, aktionen="kaputt")
        self.assertTrue(tiles.migrate_host(h))
        self.assertEqual(h["aktionen"], tiles.TEMPLATES["standard"])


if __name__ == "__main__":
    unittest.main()


class ReflowTests(unittest.TestCase):
    def setUp(self):
        self.std = old("standard")

    def _check(self, ts, max_rows=tiles.MAX_ROWS):
        seen = set()
        for a in ts:
            if tiles.is_active(a):
                self.assertTrue(tiles.in_grid(a["pos"], a["groesse"], max_rows), a)
                cs = tiles.cells(a["pos"], a["groesse"])
                self.assertFalse(cs & seen, f"overlap at {a}")
                seen |= cs

    def test_free_cell(self):
        i = tiles.find(self.std, "boot")
        new, res = tiles.reflow(self.std, i, [2, 2])
        self.assertEqual(res, "ok")
        self.assertEqual(new[i]["pos"], [2, 2])
        self._check(new)

    def test_same_size_swaps(self):
        ts = self.std
        i, j = tiles.find(ts, "boot"), tiles.find(ts, "standby")
        new, res = tiles.reflow(ts, i, ts[j]["pos"])
        self.assertEqual(res, "reflow")
        self.assertEqual(new[i]["pos"], [3, 1])
        self.assertEqual(new[j]["pos"], [0, 1])       # took the vacated cell
        self._check(new)

    def test_two_small_fill_vacated_medium(self):
        ts = self.std                                  # online_status mittel at (0,0)
        i = tiles.find(ts, "online_status")
        new, res = tiles.reflow(ts, i, [0, 1])         # onto boot + shutdown
        self.assertEqual(res, "reflow")
        self.assertEqual(new[tiles.find(new, "boot")]["pos"], [0, 0])
        self.assertEqual(new[tiles.find(new, "shutdown")]["pos"], [1, 0])
        self._check(new)

    def test_untouched_tiles_stay(self):
        i = tiles.find(self.std, "boot")
        new, _ = tiles.reflow(self.std, i, [1, 1])
        for typ in ("online_status", "neustart", "standby", "ruhezustand", "steam_start_stop"):
            self.assertEqual(new[tiles.find(new, typ)]["pos"], self.std[tiles.find(self.std, typ)]["pos"])

    def test_nearest_when_vacated_too_small(self):
        ts = self.std
        i = tiles.find(ts, "boot")                     # klein (0,1) onto mittel online_status (0,0)
        new, res = tiles.reflow(ts, i, [1, 0])
        self.assertEqual(res, "reflow")
        st = new[tiles.find(new, "online_status")]
        self.assertEqual(st["pos"], [2, 0])            # vacated cell too small: nearest free 2x1
        self._check(new)

    def test_outside_grid_rejected(self):
        i = tiles.find(self.std, "online_status")      # mittel
        for pos in ([-1, 0], [3, 0], [0, -1], [0, tiles.MAX_ROWS], [0, 3]):
            new, res = tiles.reflow(self.std, i, pos, max_rows=3)
            self.assertEqual(res, "blocked", pos)
            self.assertEqual(new, self.std)

    def test_breit_only_column_zero(self):
        ts = old("minimal")
        i = tiles.find(ts, "online_status")
        self.assertEqual(tiles.reflow(ts, i, [1, 1])[1], "blocked")
        new, res = tiles.reflow(ts, i, [0, 1])
        self.assertEqual(res, "reflow")
        self._check(new)

    def test_no_room_rejected(self):
        ts = old("standard")                # rows 0-2, row 2 has two free cells
        i = tiles.find(ts, "online_status")
        # 3 rows only: online_status onto neustart+standby -> they need 2 cells; free: (2,2),(3,2) after
        new, res = tiles.reflow(ts, i, [2, 1], max_rows=3)
        self.assertEqual(res, "reflow")
        self._check(new, 3)
        # fill the grid completely, then a gross drop cannot be resolved
        full = [tiles._t(t, "klein", k % 4, k // 4) for k, t in enumerate(tiles.TYPE_ORDER)]
        g = tiles.find(full, "boot")
        full[g]["groesse"] = "klein"
        full2, r = tiles.resize(full, g, "breit")
        self.assertNotEqual(r, "blocked")
        new, res = tiles.reflow(full2, g, [0, 0], max_rows=2)
        self.assertEqual(res, "blocked")
        self.assertEqual(new, full2)

    def test_hidden_and_unknown(self):
        ts = self.std + [{"typ": "web_link", "pos": [0, 0], "url": "x"}]
        j = tiles.find(ts, "ruhezustand")
        ts[j]["sichtbar"] = False
        self.assertEqual(tiles.reflow(ts, j, [3, 3])[1], "blocked")
        new, _ = tiles.reflow(ts, tiles.find(ts, "boot"), [2, 2])
        self.assertEqual(new[-1], {"typ": "web_link", "pos": [0, 0], "url": "x"})
        self.assertEqual(new[j], ts[j])

    def test_input_not_modified(self):
        before = tiles.copy_tiles(self.std)
        tiles.reflow(self.std, tiles.find(self.std, "boot"), [3, 1])
        self.assertEqual(self.std, before)

    def test_same_position(self):
        i = tiles.find(self.std, "boot")
        new, res = tiles.reflow(self.std, i, list(self.std[i]["pos"]))
        self.assertEqual((new, res), (self.std, "ok"))

    def test_random_drops_never_overlap(self):
        rnd = random.Random(7)
        for name in tiles.TEMPLATE_ORDER:
            ts = old(name)
            for _ in range(400):
                act = [k for k, a in enumerate(ts) if tiles.is_active(a)]
                k = rnd.choice(act)
                rows = tiles.rows_used(ts) + 1
                pos = [rnd.randint(-1, 4), rnd.randint(-1, rows)]
                new, res = tiles.reflow(ts, k, pos, max_rows=rows)
                if res == "blocked":
                    self.assertEqual(new, ts)
                else:
                    self.assertEqual(new[k]["pos"], pos)
                    self._check(new, rows)
                    # same set of visible tiles / sizes
                    self.assertEqual([(a["typ"], a["groesse"], a["sichtbar"]) for a in new],
                                     [(a["typ"], a["groesse"], a["sichtbar"]) for a in ts])
                    ts = pack_rows(new)


class DuplicateRemoveTests(unittest.TestCase):
    def test_duplicate_action(self):
        ts = old("standard")
        new, res, k = tiles.duplicate(ts, tiles.find(ts, "boot"))
        self.assertEqual((res, k), ("ok", "boot#1"))
        d = new[tiles.find(new, "boot#1")]
        self.assertEqual((d["typ"], d["groesse"], d["sichtbar"]), ("boot", "klein", True))
        self.assertTrue(no_overlap(new))
        self.assertEqual(len(new), len(ts) + 1)
        self.assertEqual(len(ts), 7)                       # input untouched

    def test_status_not_duplicable(self):
        ts = old("standard")
        self.assertEqual(tiles.duplicate(ts, tiles.find(ts, "online_status"))[1], "blocked")

    def test_hidden_not_duplicable(self):
        ts = old("minimal")
        self.assertEqual(tiles.duplicate(ts, tiles.find(ts, "neustart"))[1], "blocked")

    def test_limit_and_numbering(self):
        ts = old("standard")
        keys = []
        for _ in range(tiles.MAX_DUPLICATES):
            ts, res, k = tiles.duplicate(ts, tiles.find(ts, "boot"))
            keys.append(k)
        self.assertEqual(keys, ["boot#1", "boot#2", "boot#3"])
        self.assertEqual(tiles.duplicate(ts, tiles.find(ts, "boot"))[1], "blocked")
        ts, res = tiles.remove(ts, tiles.find(ts, "boot#2"))
        self.assertEqual(res, "removed")
        self.assertEqual(tiles.duplicate(ts, tiles.find(ts, "boot"))[2], "boot#2")   # free number reused

    def test_remove_original_only_hides(self):
        ts = old("standard")
        new, res = tiles.remove(ts, tiles.find(ts, "shutdown"))
        self.assertEqual(res, "hidden")
        self.assertEqual(len(new), len(ts))
        self.assertFalse(new[tiles.find(new, "shutdown")]["sichtbar"])
        back, res = tiles.set_visible(new, tiles.find(new, "shutdown"), True)
        self.assertTrue(back[tiles.find(back, "shutdown")]["sichtbar"])

    def test_normalize_keeps_duplicates_drops_broken(self):
        ts = old("standard")
        ts, _, _ = tiles.duplicate(ts, tiles.find(ts, "boot"))
        bad = [dict(ts[0], dup=1), {"typ": "boot", "dup": "x", "groesse": "klein", "pos": [0, 5]},
               {"typ": "boot", "dup": 2, "sichtbar": False, "groesse": "klein", "pos": [0, 5]},
               dict(ts[-1])]                          # status dup, broken, hidden dup, double key
        n = tiles.normalize(ts + bad)
        self.assertEqual([tiles.key(a) for a in n if tiles.is_dup(a)], ["boot#1"])
        self.assertEqual(n, tiles.normalize(n))
        self.assertTrue(no_overlap(n))

    def test_duplicate_falls_back_to_small(self):
        ts = old("gaming")
        for r in range(4, tiles.MAX_ROWS):           # fill everything except one cell
            for c in range(4):
                if (c, r) != (3, tiles.MAX_ROWS - 1):
                    ts.append({"typ": "x_custom", "pos": [c, r]})
        # x_custom is unknown: occupies nothing -> use real blocking instead
        ts = old("gaming")
        new, res, k = tiles.duplicate(ts, tiles.find(ts, "boot"))   # gross 2x2
        self.assertEqual(res, "ok")
        self.assertEqual(new[tiles.find(new, k)]["groesse"], "gross")
        self.assertTrue(no_overlap(new))


class ArrangeTests(unittest.TestCase):
    def test_presets(self):
        for tpl in tiles.TEMPLATE_ORDER:
            ts = old(tpl)
            vis = {tiles.key(a) for a in ts if tiles.is_active(a)}
            for p in tiles.PRESET_ORDER:
                new = tiles.apply_preset(ts, p)
                self.assertTrue(no_overlap(new), (tpl, p))
                self.assertEqual({tiles.key(a) for a in new if tiles.is_active(a)}, vis)   # visibility kept
                acts = [a for a in new if tiles.is_active(a) and tiles.TYPES[a["typ"]]["kind"] == "action"]
                if p == "kompakt":
                    self.assertTrue(all(a["groesse"] == "klein" for a in acts))
                else:
                    self.assertTrue(all(a["groesse"] in ("mittel", "gross") for a in acts))

    def test_kompakt_is_dense(self):
        new = tiles.apply_preset(old("gaming"), "kompakt")
        self.assertEqual(tiles.rows_used(new), 2)     # 1 status (mittel) + 6 klein = 8 cells

    def test_grosszuegig_layout(self):
        new = tiles.apply_preset(old("standard"), "grosszuegig")
        get = lambda k: new[tiles.find(new, k)]
        self.assertEqual((get("boot")["groesse"], get("boot")["pos"]), ("gross", [0, 1]))
        self.assertEqual((get("steam_start_stop")["groesse"], get("steam_start_stop")["pos"]), ("gross", [2, 1]))
        self.assertEqual(get("online_status")["pos"], [0, 0])

    def test_single_status_breit(self):
        new = tiles.apply_preset(old("minimal"), "grosszuegig")
        self.assertEqual(new[tiles.find(new, "online_status")]["groesse"], "breit")

    def test_hidden_untouched(self):
        ts = old("minimal")
        new = tiles.apply_preset(ts, "kompakt")
        for a, b in zip(ts, new):
            if not tiles.is_active(a):
                self.assertEqual(a, b)

    def test_auto_default_without_stats(self):
        ts = old("standard")
        mixed, _ = tiles.reflow(ts, tiles.find(ts, "boot"), [3, 2])
        new, how = tiles.auto_arrange(mixed, {})
        self.assertEqual(how, "default")
        get = lambda k: new[tiles.find(new, k)]       # default order, sizes kept, packed
        self.assertEqual([(a["typ"], a["pos"], a["groesse"]) for a in new if tiles.is_active(a)],
                         [("online_status", [0, 0], "mittel"), ("boot", [2, 0], "klein"),
                          ("shutdown", [3, 0], "klein"), ("neustart", [0, 1], "klein"),
                          ("standby", [1, 1], "klein"), ("ruhezustand", [2, 1], "klein"),
                          ("steam_start_stop", [3, 1], "klein")])
        self.assertEqual(get("boot")["groesse"], "klein")
        self.assertEqual(tiles.auto_arrange(mixed, {"boot": 0, "foo": "x"})[1], "default")

    def test_auto_by_usage(self):
        ts = old("standard")
        new, how = tiles.auto_arrange(ts, {"steam_start_stop": 10, "shutdown": 4, "boot": 1})
        self.assertEqual(how, "usage")
        get = lambda k: new[tiles.find(new, k)]
        self.assertEqual(get("online_status")["pos"], [0, 0])          # status stays on top
        self.assertEqual((get("steam_start_stop")["groesse"], get("steam_start_stop")["pos"]), ("gross", [2, 0]))
        self.assertEqual((get("shutdown")["groesse"], get("shutdown")["pos"]), ("mittel", [0, 1]))
        self.assertEqual(get("boot")["groesse"], "klein")
        self.assertLess(get("boot")["pos"][1] * 4 + get("boot")["pos"][0],
                        get("neustart")["pos"][1] * 4 + get("neustart")["pos"][0])   # used before unused
        self.assertTrue(no_overlap(new))

    def test_auto_no_gross_for_few_uses(self):
        new, _ = tiles.auto_arrange(old("standard"), {"boot": 2})
        self.assertEqual(new[tiles.find(new, "boot")]["groesse"], "mittel")

    def test_auto_with_duplicates(self):
        ts, _, k = tiles.duplicate(old("standard"), 2)
        new, _ = tiles.auto_arrange(ts, {"boot": 5})
        self.assertTrue(no_overlap(new))
        self.assertEqual(new[tiles.find(new, k)]["groesse"], "klein")

    def test_action_type(self):
        self.assertEqual(tiles.action_type("wake"), "boot")
        self.assertEqual(tiles.action_type("steam_close"), "steam_start_stop")
        self.assertEqual(tiles.action_type("steam_launch"), "steam_start_stop")
        self.assertIsNone(tiles.action_type("nope"))


class OnlineStateTests(unittest.TestCase):
    def test_priority_chain(self):
        self.assertEqual(tiles.online_state({"ping": True, "buddy": True}), "buddy")
        self.assertEqual(tiles.online_state({"ping": False, "buddy": True}), "buddy")   # buddy implies online
        self.assertEqual(tiles.online_state({"ping": True, "buddy": False}), "pc")
        self.assertEqual(tiles.online_state({"ping": False, "buddy": False}), "offline")
        self.assertEqual(tiles.online_state({"time": "x"}), "offline")
        self.assertEqual(tiles.online_state(None), "unknown")
        self.assertEqual(tiles.online_state({}), "unknown")


def _saved_and_loaded(ts):
    """What the edit dialog saves (exact copy), written as JSON and read back the way
    load_config() does it (migrate_host -> normalize)."""
    host = {"id": "x", "aktionen": json.loads(json.dumps(tiles.copy_tiles(ts))),
            "layout_rev": tiles.LAYOUT_REV}
    tiles.migrate_host(host)
    return host["aktionen"]


def _shown(ts):
    return sorted((tiles.key(a), a["groesse"], tuple(a["pos"])) for a in ts if tiles.is_active(a))


class GapLayoutPersistenceTests(unittest.TestCase):
    """Regression: layouts with empty cells / empty rows must be saved and loaded with
    the exact positions (1.3 draft packed empty rows away on save)."""
    ALL_HIDDEN = [_gap(t, "klein", 0, 9, False) for t in tiles.TYPE_ORDER]

    def layout(self, *visible):
        shown = {a["typ"] for a in visible}
        return list(visible) + [a for a in copy.deepcopy(self.ALL_HIDDEN) if a["typ"] not in shown]

    def assertRoundtrip(self, ts):
        self.assertTrue(no_overlap(ts))
        self.assertEqual(_shown(_saved_and_loaded(ts)), _shown(ts))
        again = _saved_and_loaded(_saved_and_loaded(ts))        # second restart
        self.assertEqual(_shown(again), _shown(ts))

    def test_single_tile_alone_in_row(self):
        self.assertRoundtrip(self.layout(_gap("boot", "klein", 0, 0), _gap("shutdown", "klein", 1, 0),
                                         _gap("neustart", "klein", 3, 1)))

    def test_empty_cells_between(self):
        self.assertRoundtrip(self.layout(_gap("boot", "klein", 0, 0), _gap("shutdown", "klein", 3, 0),
                                         _gap("online_status", "mittel", 1, 1)))

    def test_empty_rows_above_and_between(self):
        self.assertRoundtrip(self.layout(_gap("boot", "klein", 2, 2), _gap("shutdown", "gross", 0, 4),
                                         _gap("standby", "klein", 3, 7)))

    def test_only_tile_far_down(self):
        self.assertRoundtrip(self.layout(_gap("boot", "breit", 0, 5)))

    def test_matching_template_is_exact(self):
        std = tiles.template("standard")
        self.assertEqual(tiles.matching_template(std), "standard")
        lower = tiles.copy_tiles(std)
        for a in lower:
            a["pos"][1] += 1                  # same shape, one empty row on top
        self.assertIsNone(tiles.matching_template(lower))
        self.assertEqual(_shown(_saved_and_loaded(lower)), _shown(lower))

    def test_edit_operations_then_save(self):
        ts = tiles.template("standard")
        ops = [
            lambda s: tiles.reflow(s, idx(s, "steam_start_stop"), [3, 4]),     # drag far down
            lambda s: tiles.reflow(s, idx(s, "ruhezustand"), [2, 2]),           # gap in its row
            lambda s: tiles.move(s, idx(s, "boot"), 0, 2),                      # arrow ↓ ↓
            lambda s: tiles.resize(s, idx(s, "standby"), "mittel"),             # context menu size
            lambda s: tiles.duplicate(s, idx(s, "boot"))[:2],                   # context menu duplicate
            lambda s: tiles.set_visible(s, idx(s, "neustart"), False),          # hide
        ]
        history = [ts]
        for op in ops:
            ts, res = op(ts)
            self.assertNotEqual(res, "blocked")
            history.append(ts)
            self.assertRoundtrip(ts)
        for state in reversed(history):       # undo = going back to an earlier state
            self.assertRoundtrip(state)

    def test_auto_arrange_and_preset_then_save(self):
        base = self.layout(_gap("boot", "klein", 3, 3), _gap("shutdown", "klein", 0, 6))
        for ts in (tiles.auto_arrange(base, {"boot": 9, "shutdown": 2})[0],
                   tiles.apply_preset(base, "kompakt"), tiles.apply_preset(base, "grosszuegig")):
            self.assertRoundtrip(ts)

    def test_random_gap_layouts(self):
        rnd = random.Random(7)
        for _ in range(300):
            ts = copy.deepcopy(self.ALL_HIDDEN)
            for a in ts:
                if rnd.random() < 0.7:
                    size = rnd.choice(tiles.SIZE_ORDER)
                    w, h = tiles.SIZES[size]
                    pos = [rnd.randrange(0, tiles.COLS - w + 1), rnd.randrange(0, 8)]
                    if tiles.is_free(ts, pos, size):
                        a.update(groesse=size, pos=pos, sichtbar=True)
            self.assertRoundtrip(ts)


class SteamStatusRemovedTests(unittest.TestCase):
    """The steam_status tile of the 1.3 drafts never shipped: no such type."""

    def test_type_gone(self):
        self.assertNotIn("steam_status", tiles.TYPES)
        self.assertNotIn("steam_status", tiles.TYPE_ORDER)
        self.assertEqual(tiles.STATUS_TYPES, ("online_status",))
        for name, ts in tiles.TEMPLATES.items():
            self.assertFalse(any(a["typ"] == "steam_status" for a in ts), name)

    def test_leftover_entry_is_harmless(self):
        """A draft config entry is just an unknown type: kept, never shown, takes no cells."""
        ts = tiles.template("standard") + [_gap("steam_status", "mittel", 0, 0)]
        n = tiles.normalize(ts)
        self.assertEqual(n, ts)
        self.assertTrue(no_overlap(n))


class LayoutRevisionTests(unittest.TestCase):
    """layout_rev: every host gets the current revision; nothing else changes yet."""
    BASE = {"id": "h0", "name": "PC", "ip": "192.0.2.2", "mac": "00:00:5E:00:53:FF"}

    def host(self, aktionen, rev=None):
        h = dict(copy.deepcopy(self.BASE), aktionen=copy.deepcopy(aktionen))
        if rev is not None:
            h["layout_rev"] = rev
        return h

    def test_older_revision_only_bumped(self):
        for rev in (None, 1, "1", True):
            with self.subTest(rev=rev):
                h = self.host(old("standard"), rev)
                self.assertTrue(tiles.migrate_host(h))
                self.assertEqual(h["layout_rev"], tiles.LAYOUT_REV)
                self.assertEqual(h["aktionen"], tiles.normalize(old("standard")))
                self.assertTrue(h["aktionen"][idx(h["aktionen"], "online_status")]["sichtbar"])
                self.assertFalse(tiles.migrate_host(h), "second run is a no-op")

    def test_unknown_kept_non_dict_dropped(self):
        web = {"typ": "web_link", "sichtbar": True, "groesse": "breit", "pos": [0, 5], "url": "http://nas"}
        h = self.host([*old("gaming"), web, "garbage", 7, None, ["boot"]])
        tiles.migrate_host(h)
        self.assertIn(web, h["aktionen"])
        self.assertTrue(all(isinstance(x, dict) for x in h["aktionen"]))

    def test_normalize_drops_non_dicts_everywhere(self):
        for junk in ("x", 0, None, True, [1, 2], 3.5):
            out = tiles.normalize([junk, *tiles.template("minimal"), junk])
            self.assertTrue(all(isinstance(x, dict) for x in out), junk)
            self.assertEqual(tiles.matching_template(out), "minimal")

    def test_status_tiles_stay_optional(self):
        ts = tiles.template("standard")
        new, res = tiles.set_visible(ts, idx(ts, "online_status"), True)
        self.assertNotEqual(res, "blocked")
        self.assertTrue(new[idx(new, "online_status")]["sichtbar"])
        self.assertTrue(no_overlap(new))
        h = self.host(new, rev=tiles.LAYOUT_REV)
        self.assertFalse(tiles.migrate_host(h))
