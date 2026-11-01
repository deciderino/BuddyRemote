"""1.4-preview3: optional GameStream auto-discovery in "Add host".
Backend: parse_scan_output / scan_gamestream / discovery_state against fake
`moondeck-cli host scan --dry --json` output (stubbed run_cli, stubbed Buddy probe).
UI: section only when adding, searching state, result rows (ok / nobuddy / known),
picking fills name + IP only, gs_id is optional and hosts added by hand stay unchanged.
Example data only (192.0.2.x, made-up ids).
    QT_QPA_PLATFORM=offscreen python3 -m unittest tests.test_discovery -v
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_ui as U  # noqa: E402
from test_ui import pump  # noqa: E402

setUpModule, tearDownModule = U.setUpModule, U.tearDownModule

if U.HAVE_QT:
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest

SCAN_OUT = """Scanning for the hosts...
[
  {
    "address": "192.0.2.21",
    "port": 47989,
    "hostName": "Gaming-PC",
    "uniqueId": "0A1B2C3D-0000-4000-8000-000000000001"
  },
  {
    "address": "192.0.2.22",
    "port": 47989,
    "hostName": "HTPC",
    "uniqueId": "0A1B2C3D-0000-4000-8000-000000000002"
  },
  {
    "address": "192.0.2.23",
    "port": 47989,
    "hostName": "Gaming-PC",
    "uniqueId": "0A1B2C3D-0000-4000-8000-000000000001"
  }
]
"""


def _drop(dlg):
    try:
        dlg.deleteLater()
    except RuntimeError:        # already gone with the main window
        pass


def found(n, ip, gid, buddy=True):
    return {"name": n, "ip": ip, "gs_id": gid, "buddy": buddy}


@unittest.skipUnless(U.HAVE_QT, "PyQt6 not installed")
class ParseScanTests(unittest.TestCase):
    def be(self):
        return U.app.parse_scan_output.__globals__     # the backend module of the app copy

    def test_parse_with_preamble_and_duplicates(self):
        hosts = U.app.parse_scan_output(SCAN_OUT)
        self.assertEqual(hosts, [
            {"name": "Gaming-PC", "ip": "192.0.2.21", "gs_id": "0A1B2C3D-0000-4000-8000-000000000001"},
            {"name": "HTPC", "ip": "192.0.2.22", "gs_id": "0A1B2C3D-0000-4000-8000-000000000002"}])

    def test_parse_empty_and_garbage(self):
        self.assertEqual(U.app.parse_scan_output("Scanning for the hosts...\n[]\n"), [])
        self.assertIsNone(U.app.parse_scan_output(""))
        self.assertIsNone(U.app.parse_scan_output("Scanning for the hosts...\nboom"))
        self.assertIsNone(U.app.parse_scan_output("[ not json"))

    def test_parse_skips_incomplete_entries_and_name_falls_back(self):
        out = json.dumps([{"address": "192.0.2.30", "uniqueId": "id-a"},
                          {"hostName": "x", "uniqueId": "id-b"},
                          {"address": "192.0.2.31", "hostName": "y"},
                          "nonsense"])
        self.assertEqual(U.app.parse_scan_output(out),
                         [{"name": "192.0.2.30", "ip": "192.0.2.30", "gs_id": "id-a"}])

    def _scan(self, rc, out, err="", probe=lambda ip, port: ip.endswith(".21")):
        g = self.be()
        seen = {}
        orig = g["run_cli"]

        def fake(args, timeout=90, config_override=None, on_start=None):
            seen["args"], seen["cfg"], seen["timeout"] = list(args), config_override, timeout
            seen["existed"] = config_override.exists() if config_override else None
            return rc, out, err
        g["run_cli"] = fake
        try:
            res = g["scan_gamestream"](59999, probe=probe)
        finally:
            g["run_cli"] = orig
        return res, seen

    def test_scan_is_dry_and_uses_throwaway_config(self):
        (ok, hosts, err), seen = self._scan(0, SCAN_OUT)
        self.assertTrue(ok)
        self.assertEqual(err, "")
        self.assertEqual(seen["args"][:4], ["host", "scan", "--dry", "--json"])
        self.assertIn("--timeout", seen["args"])
        cfg = seen["cfg"]
        self.assertIsNotNone(cfg, "never the BuddyRemote config.json")
        self.assertNotEqual(os.path.basename(str(cfg)), "config.json")
        self.assertFalse(cfg.exists(), "temp config removed")
        self.assertEqual([(h["ip"], h["buddy"]) for h in hosts],
                         [("192.0.2.21", True), ("192.0.2.22", False)])

    def test_scan_probe_uses_buddy_port(self):
        ports = []
        (ok, hosts, _), _s = self._scan(0, SCAN_OUT, probe=lambda ip, port: ports.append(port) or True)
        self.assertTrue(ok)
        self.assertEqual(sorted(set(ports)), [59999])

    def test_scan_failure_and_probe_exception(self):
        (ok, hosts, err), _s = self._scan(1, "", "log line\nError: mdns failed")
        self.assertEqual((ok, hosts, err), (False, [], "Error: mdns failed"))
        (ok, hosts, err), _s = self._scan(0, "Scanning for the hosts...\n???")
        self.assertFalse(ok)

        def boom(ip, port):
            raise RuntimeError("x")
        (ok, hosts, _), _s = self._scan(0, SCAN_OUT, probe=boom)
        self.assertTrue(ok)
        self.assertEqual([h["buddy"] for h in hosts], [False, False])
        (ok, hosts, _), _s = self._scan(0, "Scanning for the hosts...\n[]\n")
        self.assertEqual((ok, hosts), (True, []))

    def test_discovery_state(self):
        st = U.app.discovery_state
        f = found("Gaming-PC", "192.0.2.21", "id-1")
        self.assertEqual(st(f, []), "ok")
        self.assertEqual(st(dict(f, buddy=False), []), "nobuddy")
        # host added by hand (no gs_id): same IP = already added
        self.assertEqual(st(f, [{"name": "x", "ip": "192.0.2.21"}]), "known")
        self.assertEqual(st(f, [{"name": "x", "ip": "192.0.2.99"}]), "ok")
        # host with gs_id: matched by id, even after an IP change
        self.assertEqual(st(f, [{"ip": "192.0.2.50", "gs_id": "id-1"}]), "known")
        self.assertEqual(st(f, [{"ip": "192.0.2.21", "gs_id": "id-other"}]), "ok")
        self.assertEqual(st(f, [None, "junk", {"ip": None}]), "ok")


class DiscoveryUiTests(U.UiTestCase):
    def open_add(self):
        dlg = U.app.HostDialog(None, self.w)
        dlg.show()
        pump()
        self.addCleanup(_drop, dlg)
        return dlg

    def results(self):
        return [found("Gaming-PC", "192.0.2.10", "id-0"),          # already added (by IP)
                found("Streaming-PC", "192.0.2.21", "id-1"),
                found("HTPC-2", "192.0.2.22", "id-2", buddy=False)]

    def test_section_only_when_adding(self):
        dlg = self.open_add()
        self.assertIsNotNone(dlg.search_btn)
        self.assertGreaterEqual(dlg.search_btn.minimumHeight(), 48)
        self.assertEqual(dlg.search_btn.text(), U.app.t("disc_search"))
        self.assertFalse(dlg.disc_scroll.isVisible())
        edit = U.app.HostDialog(self.w.cfg["hosts"][0], self.w)
        self.addCleanup(_drop, edit)
        self.assertIsNone(edit.search_btn, "no search in the ⚙ connection dialog")
        self.assertFalse(hasattr(edit, "disc_scroll"))

    def test_search_runs_in_background_then_rows(self):
        dlg = self.open_add()
        g = U.app.parse_scan_output.__globals__
        orig = g["scan_gamestream"]
        import threading
        gate = threading.Event()
        calls = []

        def fake(port, *a, **k):
            calls.append(port)
            gate.wait(5)
            return True, self.results(), ""
        g["scan_gamestream"] = fake
        try:
            dlg.port_edit.setText("59998")
            dlg.search_btn.click()
            pump()
            self.assertFalse(dlg.search_btn.isEnabled(), "greyed while searching")
            self.assertEqual(dlg.disc_state.text(), U.app.t("disc_running"))
            gate.set()
            for _ in range(200):
                pump(2)
                if dlg.disc_rows:
                    break
        finally:
            g["scan_gamestream"] = orig
        self.assertEqual(calls, [59998], "Buddy port from the field")
        self.assertTrue(dlg.search_btn.isEnabled())
        states = [r.state for r in dlg.disc_rows]
        self.assertEqual(states, ["known", "ok", "nobuddy"])
        for r in dlg.disc_rows:
            self.assertEqual(r.height(), 48)
        self.assertFalse(dlg.disc_rows[0].isEnabled())
        self.assertEqual(dlg.disc_rows[0].focusPolicy(), Qt.FocusPolicy.NoFocus)
        self.assertTrue(dlg.disc_rows[2].isEnabled(), "no Buddy: greyed but selectable")
        self.assertTrue(dlg.disc_rows[1].hasFocus(), "first selectable row gets the focus")
        self.assertEqual(dlg.disc_state.text(), U.app.t("disc_found", n=3))
        # controller / arrow navigation skips the disabled row and reaches the buttons
        QTest.keyClick(dlg.disc_rows[1], Qt.Key.Key_Down)
        pump()
        self.assertTrue(dlg.disc_rows[2].hasFocus())
        QTest.keyClick(dlg.disc_rows[2], Qt.Key.Key_Up)
        pump()
        self.assertTrue(dlg.disc_rows[1].hasFocus())
        QTest.keyClick(dlg.disc_rows[1], Qt.Key.Key_Up)
        pump()
        self.assertTrue(dlg.search_btn.hasFocus(), "known row is skipped")

    def test_pick_fills_name_and_ip_only_and_stores_gs_id(self):
        dlg = self.open_add()
        dlg.mac_edit.setText("")
        dlg.port_edit.setText("")
        dlg.show_discovery(True, self.results())
        dlg.disc_rows[0].click()            # disabled: nothing happens
        self.assertEqual(dlg.ip_edit.text(), "")
        dlg.disc_rows[2].click()
        self.assertEqual((dlg.name_edit.text(), dlg.ip_edit.text()), ("HTPC-2", "192.0.2.22"))
        self.assertEqual(dlg.mac_edit.text(), "", "MAC comes from pairing later")
        self.assertTrue(dlg.disc_rows[2].property("picked"))
        dlg.disc_rows[1].click()
        self.assertFalse(dlg.disc_rows[2].property("picked"))
        self.assertEqual(dlg.disc_state.text(), U.app.t("disc_taken", name="Streaming-PC"))
        data = dlg.get_data()
        self.assertEqual((data["name"], data["ip"], data["gs_id"], data["mac"], data["buddy_port"]),
                         ("Streaming-PC", "192.0.2.21", "id-1", None, 59999))
        dlg.name_edit.setText("Wohnzimmer")       # renaming keeps the id
        self.assertEqual(dlg.get_data()["gs_id"], "id-1")
        dlg.ip_edit.setText("192.0.2.77")          # another IP: not that host any more
        self.assertNotIn("gs_id", dlg.get_data())

    def test_manual_host_without_gs_id_unchanged(self):
        """Adding by hand (no search, PC without Sunshine/Apollo) works exactly as before."""
        dlg = self.open_add()
        dlg.name_edit.setText("Office-PC")
        dlg.ip_edit.setText("192.0.2.40")
        dlg.mac_edit.setText("00:00:5E:00:53:40")
        data = dlg.get_data()
        self.assertNotIn("gs_id", data)
        self.assertEqual(set(data), {"id", "name", "ip", "mac", "buddy_port", "aktionen", "layout_rev"})
        # the search found nothing / was used without picking: still no gs_id
        dlg.show_discovery(True, [])
        dlg.show_discovery(True, self.results())
        self.assertNotIn("gs_id", dlg.get_data())
        # saved and shown like any other host: same card, status and tooltip path
        self.w.cfg["hosts"].append(data)
        U.app.save_config(self.w.cfg)
        self.w.refresh_hosts()
        pump()
        self.assertIn(data["id"], self.w.host_rows)
        cfg = U.app.load_config()
        saved = next(h for h in cfg["hosts"] if h["id"] == data["id"])
        self.assertNotIn("gs_id", saved)
        # a later search shows it as already added (IP match), nothing is flagged
        f = found("Office-PC", "192.0.2.40", "id-9")
        self.assertEqual(U.app.discovery_state(f, cfg["hosts"]), "known")
        # the edit dialog keeps the host as is (no gs_id appears, unknown keys kept)
        edit = U.app.HostDialog(saved, self.w)
        self.addCleanup(_drop, edit)
        self.assertNotIn("gs_id", edit.get_data())

    def test_old_config_and_gs_id_survive_edit(self):
        hosts = U.app.load_config()["hosts"]
        self.assertTrue(all("gs_id" not in h for h in hosts), "old configs load unchanged")
        h = dict(hosts[0], gs_id="id-0")
        edit = U.app.HostDialog(h, self.w)
        self.addCleanup(_drop, edit)
        edit.name_edit.setText("Renamed")
        self.assertEqual(edit.get_data()["gs_id"], "id-0")

    def test_toast_when_nothing_found_or_error(self):
        dlg = self.open_add()
        dlg.show_discovery(True, [])
        self.assertTrue(dlg.toast.isVisible())
        self.assertIn(U.app.t("disc_none"), dlg.toast.title.text())
        self.assertEqual(dlg.toast.detail.text(), U.app.t("disc_none_detail"))
        self.assertFalse(dlg.disc_scroll.isVisible())
        self.assertTrue(dlg.search_btn.isEnabled())
        dlg.show_discovery(False, [], "Error: x")
        self.assertIn(U.app.t("disc_failed"), dlg.toast.title.text())
        self.assertGreater(dlg.toast.y(), 0)
        self.assertLess(dlg.toast.geometry().bottom(), dlg.save_btn.mapTo(dlg, dlg.save_btn.rect().topLeft()).y())

    def test_list_scrolls_from_four_results(self):
        dlg = self.open_add()
        three = [found(f"PC-{i}", f"192.0.2.{30 + i}", f"id-{i}") for i in range(3)]
        dlg.show_discovery(True, three)
        pump()
        h3 = dlg.disc_scroll.height()
        self.assertGreaterEqual(h3, 3 * 48)
        self.assertEqual(dlg.disc_scroll.verticalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        many = [found(f"PC-{i}", f"192.0.2.{30 + i}", f"id-{i}") for i in range(8)]
        dlg.show_discovery(True, many)
        pump()
        self.assertEqual(len(dlg.disc_rows), 8)
        self.assertGreater(dlg.disc_scroll.height(), h3)
        self.assertLess(dlg.disc_scroll.height(), 4 * 48, "3.5 rows visible, the rest scrolls")
        self.assertGreater(dlg.disc_list.sizeHint().height(), dlg.disc_scroll.viewport().height())
        self.assertLessEqual(dlg.sizeHint().height(), 800 * 0.9, "fits a 1280x800 screen")

    def test_late_result_after_close_is_dropped(self):
        dlg = self.open_add()
        dlg._disc_result = {}
        dlg._disc_timer.start()
        dlg.reject()
        self.assertFalse(dlg._disc_timer.isActive())

    def test_texts_in_all_languages(self):
        keys = ["disc_section", "disc_search", "disc_hint", "disc_running", "disc_found",
                "disc_buddy_ok", "disc_buddy_no", "disc_known", "disc_taken", "disc_none",
                "disc_none_detail", "disc_failed", "disc_failed_detail"]
        ldir = os.path.join(U.ROOT, "lang")
        for fn in sorted(os.listdir(ldir)):
            with open(os.path.join(ldir, fn), encoding="utf-8") as fh:
                d = json.load(fh)
            for k in keys:
                self.assertTrue(d.get(k), f"{fn}: {k}")
            self.assertIn("{n}", d["disc_found"], fn)
            self.assertIn("{name}", d["disc_taken"], fn)


if __name__ == "__main__":
    unittest.main()
