"""1.4-preview2 CLI / pairing fixes against a fake MoonDeck CLI (tests/fake_moondeck_cli.tmpl,
a python script with markers in a temp dir) and a mock Buddy (stubbed check_buddy_api plus the
fake CLI's "buddy_api" file):
- R1: a custom CLI must not get a false "Buddy needs update" from the bundled CLI's API,
  and its details must not name the bundled API.
- R2: Cancel in the pairing dialog stops the CLI (no late completion, no MAC fetch, temp config
  removed, no "pairing failed" notification).
- R3: the Buddy pre-check of start_pairing runs off the GUI thread.
The fake CLI is a shebang script: POSIX only.
    QT_QPA_PLATFORM=offscreen python3 -m unittest tests.test_pairing_cli -v
"""
import ast
import shutil
import os
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_ui as U                                       # noqa: E402
from test_ui import setUpModule, tearDownModule, pump    # noqa: E402,F401

if U.HAVE_QT:
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication, QMessageBox

POSIX = os.name == "posix"


_DIRS = []


def make_cli(api, delay=0.0):
    d = tempfile.mkdtemp(prefix="br-fakecli-")
    _DIRS.append(d)
    with open(os.path.join(HERE, "fake_moondeck_cli.tmpl")) as fh:
        src = fh.read()
    src = src.replace("@DIR@", d).replace("@API@", str(api)).replace("@DELAY@", str(delay))
    src = src.replace("#!/usr/bin/env python3", "#!" + sys.executable, 1)
    p = os.path.join(d, "moondeck-cli")
    with open(p, "w") as fh:
        fh.write(src)
    os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)
    return Path(p), d


def read(d, name):
    p = os.path.join(d, name) if d else ""
    if not p or not os.path.exists(p):
        return ""
    with open(p) as fh:
        return fh.read()


def real_run_cli(be):
    """test_ui's setUpModule stubs run_cli (also in backend): rebuild the real one from source
    inside backend's own namespace (same custom-CLI state, CLI_BIN, _exec_cli)."""
    with open(be.__file__) as fh:
        tree = ast.parse(fh.read())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_cli")
    ns = {}
    exec(compile(ast.Module([node], []), be.__file__, "exec"), be.__dict__, ns)
    return ns["run_cli"]


def pid_alive(pid):
    try:
        with open(f"/proc/{pid}/status") as fh:
            return "zombie" not in fh.read().lower()
    except OSError:
        if os.path.isdir("/proc"):
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


@unittest.skipUnless(U.HAVE_QT and POSIX, "PyQt6 / POSIX fake CLI only")
class Base(U.UiTestCase):
    def setUp(self):
        super().setUp()
        self.be = U.app.backend
        self._saved = {k: getattr(U.app, k) for k in ("run_cli", "check_buddy_api", "notify")}
        self._cli_bin = self.be.CLI_BIN
        self._bci = self.be.bundled_cli_info
        self.notes = []
        U.app.notify = lambda *a, **k: self.notes.append(a)
        U.app.run_cli = real_run_cli(self.be)          # the real one: subprocess + custom-CLI logic

    def tearDown(self):
        self.be.bundled_cli_info = self._bci
        for k, v in self._saved.items():
            setattr(U.app, k, v)
        self.be.CLI_BIN = self._cli_bin
        self.be.set_custom_cli("")
        super().tearDown()
        while _DIRS:
            shutil.rmtree(_DIRS.pop(), ignore_errors=True)


class CustomCliApiTests(Base):
    def _check(self, buddy_api, bundled_api, custom_api=None, custom_broken=False):
        bundled, bd = make_cli(bundled_api)
        self.be.CLI_BIN = bundled
        cd = None
        if custom_api is not None or custom_broken:
            custom, cd = make_cli(custom_api or 0)
            if custom_broken:
                os.chmod(custom, 0o644)        # not executable: probe fails -> bundled fallback
            self.be.set_custom_cli(str(custom))
        for d in (bd, cd):
            if d:
                with open(os.path.join(d, "buddy_api"), "w") as fh:
                    fh.write(str(buddy_api))
        U.app.check_buddy_api = lambda ip, port=59999, timeout=5.0: (True, '{"version": %d}' % buddy_api)
        self.be.bundled_cli_info = lambda: {"version": "x", "buddy_api": bundled_api}
        got = []
        self.w.signals.host_status.connect(lambda hid, res: got.append(res))
        self.w._check_host(dict(self.w.cfg["hosts"][0]))
        pump(3)
        return got[-1], read(bd, "calls"), read(cd, "calls")

    def test_custom_cli_matching_buddy_no_false_mismatch(self):
        res, bcalls, ccalls = self._check(buddy_api=10, bundled_api=9, custom_api=10)
        self.assertIsNone(res.get("api_mismatch"), "false 'Buddy needs update' with a matching custom CLI")
        self.assertIn("steam status", ccalls)
        self.assertEqual(bcalls, "", "the bundled CLI ran although a working custom CLI is set")

    def test_custom_cli_older_than_buddy_warns_without_bundled_api(self):
        res, bcalls, ccalls = self._check(buddy_api=9, bundled_api=9, custom_api=8)
        mm = res.get("api_mismatch")
        self.assertIsNotNone(mm)
        self.assertIsNone(res.get("steam"))
        self.assertIsNone(mm.get("want"), "custom CLI mismatch still carries the bundled API")
        txt = self.w.host_rows["h0"].details_text()       # the row got the result via host_status
        self.assertIn(U.app.t("st_api_bad_custom"), txt)
        self.assertNotRegex(txt, r"API\s*\d", "details name the bundled CLI's API")

    def test_broken_custom_cli_falls_back_to_bundled_and_still_warns(self):
        res, _, _ = self._check(buddy_api=10, bundled_api=9, custom_broken=True)
        self.assertEqual((res.get("api_mismatch") or {}).get("dir"), "host_new")

    def test_broken_custom_cli_falls_back_to_bundled(self):
        res, bcalls, _ = self._check(buddy_api=9, bundled_api=9, custom_broken=True)
        self.assertIsNone(res.get("api_mismatch"))
        self.assertIn("steam status", bcalls)

    def test_bundled_cli_mismatch_still_names_api(self):
        res, _, _ = self._check(buddy_api=10, bundled_api=9)
        mm = res.get("api_mismatch")
        self.assertEqual(mm.get("dir"), "host_new")


class PairCancelTests(Base):
    DELAY = 3.0

    def test_cancel_stops_cli(self):
        cli, d = make_cli(9, delay=self.DELAY)
        self.be.CLI_BIN = cli
        U.app.check_buddy_api = lambda *a, **k: (True, '{"version": 9}')
        self.w.start_pairing(dict(self.w.cfg["hosts"][0]))
        t0 = time.monotonic()
        while not read(d, "pair.pid") and time.monotonic() - t0 < 5:
            pump(2)
        self.assertTrue(read(d, "pair.pid"), "pairing CLI never started")
        pid = int(read(d, "pair.pid").split()[0])
        tmpcfg = read(d, "pair.cfg").strip()
        self.assertTrue(tmpcfg and os.path.exists(tmpcfg))
        dlg = next(w for w in QApplication.topLevelWidgets()
                   if isinstance(w, QMessageBox) and w.isVisible())
        dlg.button(QMessageBox.StandardButton.Cancel).click()
        t1 = time.monotonic()
        while time.monotonic() - t1 < 1.2:
            pump(2)
        self.assertFalse(pid_alive(pid), "Cancel leaves the pairing CLI running")
        self.assertFalse(os.path.exists(tmpcfg), "temp CLI config survives Cancel")
        self.assertIn("abort_pairing", read(d, "aborted"), "CLI not stopped with SIGINT (no Buddy abort)")
        while time.monotonic() - t1 < self.DELAY + 1.0:      # past the moment the PIN 'would' arrive
            pump(2)
        self.assertEqual(read(d, "late_done"), "", "pairing completed in the background after Cancel")
        self.assertNotIn("host list", read(d, "calls"), "MAC fetch after Cancel")
        self.assertEqual(self.notes, [], "Cancel shows a notification ('pairing failed')")

    def test_stop_cli_kills_after_grace(self):
        import subprocess
        p = subprocess.Popen([sys.executable, "-c",
                              "import signal,time; signal.signal(signal.SIGINT, signal.SIG_IGN); time.sleep(30)"])
        time.sleep(0.3)
        t0 = time.monotonic()
        self.be.stop_cli(p, grace=0.5)        # SIGINT ignored -> killed after the grace time
        self.assertLess(time.monotonic() - t0, 2.0)
        self.assertIsNotNone(p.wait(2))


class PrecheckThreadTests(Base):
    def test_buddy_precheck_keeps_gui_responsive(self):
        def slow(ip, port=59999, timeout=5.0):
            time.sleep(2.0)
            return False, "timed out"
        U.app.check_buddy_api = slow
        ticks = []
        tm = QTimer()
        tm.timeout.connect(lambda: ticks.append(time.monotonic()))
        tm.start(50)
        QTimer.singleShot(300, lambda: self.w.start_pairing(dict(self.w.cfg["hosts"][0])))
        t0 = time.monotonic()
        while time.monotonic() - t0 < 2.8:
            pump(1)
        tm.stop()
        gaps = [b - a for a, b in zip(ticks, ticks[1:])]
        self.assertTrue(gaps)
        self.assertLess(max(gaps), 0.5, "GUI event loop frozen during the Buddy pre-check")
        self.assertTrue(self.notes or any(isinstance(w, QMessageBox) and w.isVisible()
                                          for w in QApplication.topLevelWidgets()),
                        "unreachable Buddy not reported after the pre-check")
        for w in QApplication.topLevelWidgets():
            if isinstance(w, QMessageBox) and w.isVisible():
                w.close()


if __name__ == "__main__":
    unittest.main()
