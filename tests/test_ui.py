"""Qt tests for the 1.3 main window: edit mode (enter/exit, keyboard move, undo/redo)
and the calm status (dot colour, tooltip, problem line, "Steam läuft", migration).

Runs offscreen on a copy of the app in a temporary directory (config.json lives next
to app.py), with the CLI, ping and Buddy calls stubbed out. Skipped without PyQt6.
    QT_QPA_PLATFORM=offscreen python3 -m unittest tests.test_ui -v
"""
import glob
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
import tiles  # noqa: E402

try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QEvent, Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication
    HAVE_QT = True
except Exception:      # pragma: no cover - PyQt6 missing
    HAVE_QT = False

app = qa = TMP = None
OLD_HOME = os.environ.get("HOME")


# app.py was split into modules (1.3.1); each load must import them from the copy, fresh.
SPLIT_MODULES = ("paths", "i18n", "config", "backend", "platform_util", "theme", "gamepad", "dialogs")


def purge_split_modules():
    for m in SPLIT_MODULES:
        sys.modules.pop(m, None)


class AppView:
    """app.py plus the modules split out of it: reads look in app first, then in the split
    modules; writes (stubs) go to app and to every split module that has the name."""
    def __init__(self, mod):
        object.__setattr__(self, "_mods", [mod] + [sys.modules[m] for m in SPLIT_MODULES
                                                   if m in sys.modules])

    def __getattr__(self, name):
        for m in self._mods:
            if hasattr(m, name):
                return getattr(m, name)
        raise AttributeError(name)

    def __setattr__(self, name, value):
        for i, m in enumerate(self._mods):
            if i == 0 or hasattr(m, name):
                setattr(m, name, value)


def _config():
    names = ["Gaming-PC", "Workstation", "HTPC"]
    hosts = [{"id": f"h{i}", "name": names[i], "ip": f"192.0.2.{10 + i}",
              "mac": "00:00:5E:00:53:1%d" % i, "buddy_port": 59999} for i in range(3)]
    hosts[1]["aktionen"] = tiles.template("minimal")      # tile list without layout_rev
    hosts[2]["aktionen"] = tiles.template("server")
    hosts[2]["layout_rev"] = tiles.LAYOUT_REV
    return {"version": 1, "hosts": hosts,
            "settings": {"start_minimized": False, "auto_status": True, "theme": "Dark",
                         "confirm_actions": True, "language": "de", "language_set": True,
                         "check_updates": False, "client_id": "buddyremote-test"}}


def setUpModule():
    global app, qa, TMP
    if not HAVE_QT:
        return
    TMP = tempfile.mkdtemp(prefix="br-ui-")
    for f in glob.glob(os.path.join(ROOT, "*.py")):
        shutil.copy(f, TMP)
    shutil.copytree(os.path.join(ROOT, "lang"), os.path.join(TMP, "lang"))
    os.makedirs(os.path.join(TMP, "cli"))
    open(os.path.join(TMP, ".attributed"), "w").close()
    with open(os.path.join(TMP, "config.json"), "w") as fh:
        json.dump(_config(), fh)
    os.environ["HOME"] = os.path.join(TMP, "home")
    spec = importlib.util.spec_from_file_location("br_app_ui", os.path.join(TMP, "app.py"))
    mod = importlib.util.module_from_spec(spec)
    purge_split_modules()
    sys.path.insert(0, TMP)
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(TMP)
    app = AppView(mod)
    app.run_cli = lambda *a, **k: (0, "", "")
    app.ping_icmp = lambda *a, **k: False
    app.check_buddy_api = lambda *a, **k: (False, "x")
    app.acquire_lock = lambda: True
    app.cli_available = lambda: True
    qa = QApplication.instance() or QApplication([])
    cfg = app.load_config()
    app.set_language(app.resolve_language(cfg["settings"]))
    app.apply_app_theme(qa, False)


def tearDownModule():
    if TMP:
        shutil.rmtree(TMP, ignore_errors=True)
    if OLD_HOME is not None:
        os.environ["HOME"] = OLD_HOME


def pump(n=10):
    for _ in range(n):
        qa.processEvents()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        time.sleep(0.005)


READY = {"ping": True, "buddy": True, "steam": {"running": True, "bpm": False}, "time": "12:00:01"}
WARN = {"ping": True, "buddy": False, "steam": None, "time": "12:00:02"}
OFF = {"ping": False, "buddy": False, "steam": None, "time": "12:00:03"}


@unittest.skipUnless(HAVE_QT, "PyQt6 not installed")
class UiTestCase(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(TMP, "config.json"), "w") as fh:     # every test starts from the same config
            json.dump(_config(), fh)
        for f in ("window.ini",):
            if os.path.exists(os.path.join(TMP, f)):
                os.remove(os.path.join(TMP, f))
        self.w = app.MainWindow()
        self.w.status_timer.stop()
        self.w.check_status = lambda *a, **k: None       # no background checks during a test
        self.w.resize(900, 720)
        self.w.show()
        pump()

    def tearDown(self):
        if self.w._edit_mode:
            self.w.exit_edit_mode()
        self.w.hide()
        self.w.deleteLater()
        pump()

    def host(self, hid):
        return self.w._host(hid)

    def pos(self, hid, k):
        ts = self.host(hid)["aktionen"]
        return ts[tiles.find(ts, k)]["pos"]


class EditModeTests(UiTestCase):
    def test_enter_and_exit(self):
        w = self.w
        self.assertFalse(w.edit_bar.isVisible())
        w.enter_edit_mode()
        pump()
        self.assertTrue(w._edit_mode)
        self.assertTrue(w.edit_bar.isVisible())
        self.assertTrue(w.edit_btn.isChecked())
        self.assertEqual(w.status_bar.text(), app.t("state_edit"))
        for row in w.host_rows.values():
            self.assertTrue(row.editing)
            self.assertTrue(row.editor.isVisible())
        QTest.keyClick(w, Qt.Key.Key_Escape)       # Esc leaves the edit mode
        pump()
        self.assertFalse(w._edit_mode)
        self.assertFalse(w.edit_bar.isVisible())
        self.assertEqual(w.status_bar.text(), app.t("state_ready"))
        for row in w.host_rows.values():
            self.assertFalse(row.editing)

    def test_toggle_and_done_button(self):
        w = self.w
        w.toggle_edit_mode()
        pump()
        self.assertTrue(w._edit_mode)
        w.edit_done_btn.click()
        pump()
        self.assertFalse(w._edit_mode)
        w.toggle_edit_mode()
        w.toggle_edit_mode()
        pump()
        self.assertFalse(w._edit_mode)

    def test_keyboard_move_undo_redo_persists(self):
        w = self.w
        w.enter_edit_mode()
        pump()
        w.edit_select("h0", "boot")
        pump()
        w.input_mode.set_nav_visible(True)      # QTest keys are "spontaneous": show the ring first
        pump()
        a, b = list(self.pos("h0", "boot")), list(self.pos("h0", "shutdown"))
        QTest.keyClick(w.host_rows["h0"].editor, Qt.Key.Key_Right)
        pump()
        self.assertEqual(self.pos("h0", "boot"), b)         # same size: swapped
        self.assertEqual(self.pos("h0", "shutdown"), a)
        with open(os.path.join(TMP, "config.json")) as fh:
            saved = json.load(fh)
        st = [x for x in saved["hosts"] if x["id"] == "h0"][0]["aktionen"]
        self.assertEqual(st[tiles.find(st, "boot")]["pos"], b, "saved at once")
        QTest.keyClick(w, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        pump()
        self.assertEqual(self.pos("h0", "boot"), a)
        QTest.keyClick(w, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
        pump()
        self.assertEqual(self.pos("h0", "boot"), b)
        w.edit_undo()
        pump()
        QTest.keyClick(w, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        pump()
        self.assertEqual(self.pos("h0", "boot"), b, "Ctrl+Shift+Z = redo")

    def test_edit_bar_operations(self):
        w = self.w
        w.enter_edit_mode()
        pump()
        w.edit_select("h0", "neustart")
        pump()
        n = len(self.host("h0")["aktionen"])
        w.edit_duplicate()
        pump()
        self.assertEqual(len(self.host("h0")["aktionen"]), n + 1)
        w.edit_undo()
        pump()
        self.assertEqual(len(self.host("h0")["aktionen"]), n)
        w.edit_select("h0", "neustart")
        w.edit_remove()
        pump()
        ts = self.host("h0")["aktionen"]
        self.assertFalse(ts[tiles.find(ts, "neustart")]["sichtbar"], "original tile is hidden, not deleted")
        w.edit_template("minimal")
        pump()
        self.assertEqual(tiles.matching_template(self.host("h0")["aktionen"]), "minimal")

    def test_card_gear_opens_connection_settings_only(self):
        dlg_cls = app.HostDialog
        seen = {}
        orig_exec = dlg_cls.exec

        def fake_exec(dlg):
            seen["title"] = dlg.windowTitle()
            seen["preview"] = getattr(dlg, "preview", None)
            seen["tpl"] = getattr(dlg, "tpl_combo", None)
            return 0
        dlg_cls.exec = fake_exec
        try:
            self.w.host_rows["h0"].conn_btn.click()
            pump()
        finally:
            dlg_cls.exec = orig_exec
        self.assertEqual(seen.get("title"), app.t("conn_title"))
        self.assertIsNone(seen.get("tpl"), "no tile editing in the connection dialog")
        self.assertEqual(card_buttons(self.w.host_rows["h0"]), ["⚙"], "↑ ↓ are gone (cards are dragged in edit mode)")


class CalmStatusTests(UiTestCase):
    def colour(self, row):
        css = row.dot.styleSheet()
        return css.split("background:")[1].split(";")[0].strip()

    def test_migration_status_tiles_hidden(self):
        """1.2 host (h0) gets the template, a list without layout_rev (h1) the current
        revision; the status tiles are hidden by default in both."""
        for hid in ("h0", "h1"):
            ts = self.host(hid)["aktionen"]
            for typ in tiles.STATUS_TYPES:
                self.assertFalse(ts[tiles.find(ts, typ)]["sichtbar"], (hid, typ))
            self.assertEqual(self.host(hid)["layout_rev"], tiles.LAYOUT_REV)
        self.assertFalse(self.w.host_rows["h0"].chip_online.isVisible())

    def test_ready(self):
        w = self.w
        w.on_host_status("h0", READY)
        pump()
        row = w.host_rows["h0"]
        c = app.ui_colors(row._light())
        self.assertEqual(self.colour(row), c["online"])
        self.assertTrue(row.steam_lbl.isVisible())
        self.assertEqual(row.steam_lbl.text(), app.t("steam_running_hdr"))
        self.assertFalse(row.hint_row.isVisible())
        tip = row.dot.toolTip()
        self.assertIn(app.t("st_ready"), tip)
        self.assertIn(app.t("st_buddy_ok", port=59999), tip)
        self.assertIn(app.t("st_checked", time="12:00:01"), tip)
        self.assertEqual(row.name_lbl.toolTip(), tip)

    def test_problem_line_only_when_buddy_silent(self):
        w = self.w
        w.on_host_status("h1", WARN)
        pump()
        row = w.host_rows["h1"]
        self.assertEqual(self.colour(row), "#f57c00" if row._light() else "#fb8c00")
        self.assertTrue(row.hint_row.isVisible())
        self.assertTrue(row.details_btn.isVisible())
        self.assertFalse(row.steam_lbl.isVisible())
        tip = row.dot.toolTip()
        self.assertIn(app.t("st_warn"), tip)
        self.assertIn(app.t("st_ping_ok", ip="192.0.2.11"), tip)
        self.assertIn(app.t("st_buddy_fail", port=59999), tip)
        # the colour rule is scoped to the dot, so the tooltip does not turn orange
        css = row.dot.styleSheet().strip()
        self.assertTrue(css.startswith("QLabel#hostDot") and css.endswith("}"), css)

    def test_off(self):
        w = self.w
        w.on_host_status("h2", OFF)
        pump()
        row = w.host_rows["h2"]
        self.assertEqual(self.colour(row), app.ui_colors(row._light())["offline"])
        self.assertFalse(row.hint_row.isVisible())
        self.assertFalse(row.steam_lbl.isVisible())
        self.assertIn(app.t("st_off"), row.dot.toolTip())

    def test_optional_status_tile_still_works(self):
        w = self.w
        ts = self.host("h0")["aktionen"]
        new, res = tiles.set_visible(ts, tiles.find(ts, "online_status"), True)
        self.assertNotEqual(res, "blocked")
        self.host("h0")["aktionen"] = new
        w.refresh_hosts()
        pump()
        w.on_host_status("h0", WARN)
        pump()
        row = w.host_rows["h0"]
        self.assertTrue(row.chip_online.isVisible())
        self.assertIn(app.t("status_pc"), row.chip_online.text())


def saved():
    with open(os.path.join(TMP, "config.json")) as fh:
        return json.load(fh)


def card_buttons(row):
    """Texts of the card's own management buttons (only ⚙ since 1.3)."""
    return [b.text() for b in row.findChildren(app.QPushButton) if b.property("mgmt")]


def ini(key):
    from PyQt6.QtCore import QSettings
    return QSettings(os.path.join(TMP, "window.ini"), QSettings.Format.IniFormat).value(key)


def drag(widget, start, end, steps=8):
    """Mouse drag with real events (press, moves, release) in widget coordinates."""
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QMouseEvent
    L, N = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton

    # like a real mouse: the path is fixed on screen, even if the widget moves while dragging
    # (edit mode opens a gap in the row, the dimmed source item shifts)
    gs, ge = widget.mapToGlobal(start), widget.mapToGlobal(end)

    def send(t, g, btn, btns):
        p = widget.mapFromGlobal(g)
        QApplication.sendEvent(widget, QMouseEvent(t, QPointF(p), QPointF(g), btn, btns, Qt.KeyboardModifier.NoModifier))
    send(QEvent.Type.MouseButtonPress, gs, L, L)
    for i in range(1, steps + 1):
        g = gs + (ge - gs) * i / steps
        send(QEvent.Type.MouseMove, g.toPoint() if hasattr(g, "toPoint") else g, N, L)
        pump(1)
    send(QEvent.Type.MouseButtonRelease, ge, L, N)
    pump(30)


class CardReorderTests(UiTestCase):
    def order(self):
        return [h["id"] for h in saved()["hosts"]]

    def test_arrows_gone_only_gear(self):
        for r in self.w.host_rows.values():
            self.assertEqual(card_buttons(r), ["⚙"])

    def test_drag_card_in_edit_mode(self):
        from PyQt6.QtCore import QPoint
        w = self.w
        w.enter_edit_mode("h0")
        pump()
        row = w.host_rows["h0"]
        last = w.host_rows["h2"]
        start = QPoint(row.width() // 2, 12)                      # card header
        end = row.mapFromGlobal(last.mapToGlobal(QPoint(last.width() // 2, last.height() - 4)))
        drag(row, start, end, steps=12)
        self.assertEqual(self.order(), ["h1", "h2", "h0"])
        self.assertEqual(list(w.host_rows), ["h1", "h2", "h0"])
        self.assertEqual([w.host_layout.itemAt(i).widget().host["id"] for i in range(3)], ["h1", "h2", "h0"])
        self.assertIsNone(w.card_drag.drag)
        w.edit_undo()
        pump()
        self.assertEqual(self.order(), ["h0", "h1", "h2"])
        w.edit_redo()
        pump()
        self.assertEqual(self.order(), ["h1", "h2", "h0"])

    def test_no_drag_outside_edit_mode(self):
        from PyQt6.QtCore import QPoint
        row = self.w.host_rows["h0"]
        last = self.w.host_rows["h2"]
        drag(row, QPoint(row.width() // 2, 12), row.mapFromGlobal(last.mapToGlobal(QPoint(20, last.height() - 4))))
        self.assertEqual(self.order(), ["h0", "h1", "h2"])

    def test_ctrl_up_down(self):
        w = self.w
        w.enter_edit_mode("h1")
        pump()
        w.host_rows["h1"].editor.setFocus()
        pump()
        QTest.keyClick(w.host_rows["h1"].editor, Qt.Key.Key_Down, Qt.KeyboardModifier.ControlModifier)
        pump()
        self.assertEqual(self.order(), ["h0", "h2", "h1"])
        QTest.keyClick(w.host_rows["h1"].editor, Qt.Key.Key_Up, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClick(w.host_rows["h1"].editor, Qt.Key.Key_Up, Qt.KeyboardModifier.ControlModifier)
        pump()
        self.assertEqual(self.order(), ["h1", "h0", "h2"])
        self.assertFalse(w.move_card("h1", -1), "already first")
        QTest.keyClick(w, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        pump()
        self.assertEqual(self.order(), ["h0", "h1", "h2"])


class LogSplitterTests(UiTestCase):
    def test_no_fixed_max_height_and_handle(self):
        w = self.w
        self.assertGreater(w.output.maximumHeight(), 1000)
        self.assertIsInstance(w.splitter, app.QSplitter)
        self.assertGreaterEqual(w.splitter.handleWidth(), 8)
        self.assertFalse(w.log_handle.resizable, "log closed: nothing to resize")
        self.assertFalse(w.log_handle.grip_visible(), "log closed: no grip")
        self.assertTrue(w.log_btn.isVisible(), "the log button sits in the handle row")
        self.assertIs(w.log_btn.parentWidget(), w.log_handle)

    def test_height_persisted_and_reset(self):
        w = self.w
        w.toggle_log()
        pump()
        self.assertTrue(w.log_handle.resizable)
        self.assertTrue(w.log_handle.grip_visible())
        self.assertGreaterEqual(w.log_handle.height(), 48, "48 px touch row")
        w.splitter.moveSplitter(w.splitter.handle(1).y() - 120, 1)
        pump()
        h = w.output.height()
        self.assertGreater(h, 200)
        w._save_log_height()
        self.assertEqual(int(ini("log_height")), w._log_h)
        w.hide()
        w2 = app.MainWindow()
        w2.status_timer.stop()
        w2.check_status = lambda *a, **k: None
        w2.resize(900, 720)
        w2.show()
        pump()
        try:
            self.assertTrue(w2.output.isVisible())
            self.assertLessEqual(abs(w2.output.height() - h), 6)
            QTest.mouseDClick(w2.log_handle, Qt.MouseButton.LeftButton)
            pump()
            self.assertLessEqual(abs(w2.output.height() - app.MainWindow.LOG_DEFAULT), 6)
            self.assertEqual(int(ini("log_height")), app.MainWindow.LOG_DEFAULT)
        finally:
            w2.hide()
            w2.deleteLater()

    def test_small_and_large_window(self):
        w = self.w
        w.toggle_log()
        w.set_log_height(400)
        for size in ((w.minimumWidth(), w.minimumHeight()), (1600, 1200), (900, 720)):
            w.resize(*size)
            pump()
            self.assertTrue(w.output.isVisible())
            self.assertGreaterEqual(w.output.height(), app.MainWindow.LOG_MIN - 2, size)
            self.assertGreater(w.scroll.height(), 40, size)


class ToolbarTests(UiTestCase):
    def test_icons_and_tooltips(self):
        w = self.w
        self.assertEqual([b.text() for b in w.toolbar_buttons], ["＋", "⟳", "✎", "☰"])
        for b in w.toolbar_buttons:
            self.assertEqual((b.width(), b.height()), (48, 48))     # icon-only, 48 px touch target
            self.assertIn("(", b.toolTip())                    # label (shortcut)
        self.assertEqual((w.tb_collapse_btn.width(), w.tb_collapse_btn.height()), (48, 48))
        for row in w.host_rows.values():                       # ⚙ glyph bigger, button stays 48 px
            self.assertEqual((row.conn_btn.width(), row.conn_btn.height()), (48, 48))
        self.assertIn("F5", w.tb_btns["refresh"].toolTip())

    def test_collapse_persist_and_shortcuts(self):
        w = self.w
        w.tb_collapse_btn.click()
        pump(40)
        time.sleep(0.25)
        pump(10)
        self.assertFalse(w.toolbar.isVisible())
        self.assertTrue(w.tb_grip.isVisible())
        self.assertEqual(w.tb_grip.width(), w.centralWidget().width())
        self.assertEqual(str(ini("toolbar_collapsed")), "true")
        QTest.keyClick(w, Qt.Key.Key_E, Qt.KeyboardModifier.ControlModifier)      # shortcut while collapsed
        pump()
        self.assertTrue(w._edit_mode)
        self.assertTrue(w.toolbar.isVisible(), "edit mode expands the bar")
        self.assertEqual(w.edit_btn.text(), "✓  " + app.t("edit_done"))
        w.exit_edit_mode()
        pump(40)
        time.sleep(0.25)
        pump(10)
        self.assertFalse(w.toolbar.isVisible(), "collapsed again after edit mode")
        w.hide()
        w2 = app.MainWindow()
        w2.check_status = lambda *a, **k: None
        w2.status_timer.stop()
        w2.show()
        pump()
        try:
            self.assertTrue(w2._tb_collapsed)
            self.assertFalse(w2.toolbar.isVisible())
            w2.tb_grip.click()
            pump(40)
            time.sleep(0.25)
            pump(10)
            self.assertTrue(w2.toolbar.isVisible())
            self.assertEqual(str(ini("toolbar_collapsed")), "false")
        finally:
            w2.hide()
            w2.deleteLater()

    def test_single_done_button(self):
        w = self.w
        w.enter_edit_mode()
        pump()
        self.assertIs(w.edit_done_btn, w.edit_btn)
        dones = [b for b in w.findChildren(app.QPushButton) if b.isVisible() and app.t("edit_done") in b.text()]
        self.assertEqual(dones, [w.edit_btn])
        self.assertFalse(w.tb_collapse_btn.isEnabled())
        w.edit_btn.click()
        pump()
        self.assertFalse(w._edit_mode)
        self.assertEqual(w.edit_btn.text(), "✎")

    def test_group_reorder_resize_not_removable(self):
        w = self.w
        w.enter_edit_mode()
        pump()
        self.assertTrue(w.tb_group_lbl.isVisible())
        w.tb_btns["add"].click()                 # edit mode: select, do not run
        pump()
        self.assertEqual(w._tb_sel, "add")
        w.tb_btns["add"].setFocus()
        QTest.keyClick(w.tb_btns["add"], Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier)
        pump()
        self.assertEqual([i["id"] for i in saved()["settings"]["toolbar"]], ["refresh", "add", "edit", "options"])
        self.assertTrue(w.set_toolbar_size("refresh", "mittel"))
        pump()
        self.assertIn(app.t("refresh"), w.tb_btns["refresh"].text())
        w.edit_undo()
        w.edit_undo()
        pump()
        self.assertEqual(w._tb_items, app.toolbar_items(None))
        # drag "options" to the front
        from PyQt6.QtCore import QPoint
        b = w.tb_btns["options"]
        first = w.tb_btns["add"]
        drag(b, QPoint(24, 24), b.mapFromGlobal(first.mapToGlobal(QPoint(4, 24))))
        self.assertEqual([i["id"] for i in w._tb_items][0], "options")
        # hide / remove: impossible -> toast, nothing changes
        before = list(w._tb_items)
        w.tb_btns["refresh"].setFocus()
        QTest.keyClick(w.tb_btns["refresh"], Qt.Key.Key_Delete)
        pump()
        self.assertTrue(w.toast.isVisible())
        self.assertIn(app.t("tb_cannot_hide"), w.toast.title.text())
        self.assertEqual(w._tb_items, before)
        self.assertFalse(w.edit_rm_btn.isEnabled())
        self.assertFalse(w.edit_dup_btn.isEnabled())
        self.assertTrue(w.edit_size_btn.isEnabled())
        # dragged out of the bar: snaps back + toast
        w.toast.hide()
        drag(b, QPoint(24, 24), QPoint(24, 260))
        self.assertEqual(w._tb_items, before)
        self.assertIn(app.t("tb_cannot_hide"), w.toast.title.text())
        self.assertEqual(len(w._tb_items), 4)


class WakeStateTests(UiTestCase):
    def wake(self, hid):
        return next(b for a, b in self.w.host_rows[hid].action_buttons if a == "wake")

    def test_three_states(self):
        w = self.w
        for state, enabled, primary in ((OFF, True, True), (WARN, False, False), (READY, False, False)):
            w.on_host_status("h0", state)
            pump()
            b = self.wake("h0")
            self.assertEqual(b.isEnabled(), enabled, state)
            self.assertEqual(bool(b.property("primary")), primary, state)
            self.assertEqual(b.toolTip(), "" if enabled else app.t("why_pc_on"), state)
        self.assertIn("PC ist bereits an", app.t("why_pc_on"))


class TooltipCleanupTests(UiTestCase):
    def test_removed_tooltips(self):
        w = self.w
        w.on_host_status("h1", WARN)
        w.on_host_status("h0", OFF)
        pump()
        row = w.host_rows["h1"]
        self.assertEqual(row.details_btn.toolTip(), "")
        self.assertEqual(row.time_lbl.toolTip(), "")
        for a, b in w.host_rows["h0"].action_buttons:
            if b.isEnabled():
                self.assertEqual(b.toolTip(), "", a)
        w.enter_edit_mode()
        pump()
        for b in w.edit_tool_buttons:
            self.assertEqual(b.toolTip(), "", b.text())
        self.assertEqual(w.edit_info.toolTip(), "")
        self.assertTrue(w.edit_info.wordWrap())
        row = w.host_rows["h1"]
        self.assertEqual(row.editor.toolTip(), "")
        self.assertTrue(w.edit_undo_btn.toolTip())
        self.assertTrue(row.conn_btn.toolTip())

    def test_duplicate_limit_is_a_toast(self):
        w = self.w
        w.enter_edit_mode("h0")
        pump()
        ts = w._edit_tiles("h0")
        k = next(tiles.key(a) for a in ts if a["typ"] == "boot")
        w.edit_select("h0", k)
        for _ in range(tiles.MAX_DUPLICATES + 2):
            w.edit_select("h0", k)
            w.edit_duplicate("h0")
            pump()
        self.assertTrue(w.toast.isVisible())
        self.assertIn(app.t("tile_dup_blocked", n=tiles.MAX_DUPLICATES), w.toast.title.text())


class NoBackupTests(UiTestCase):
    def test_no_backup_file(self):
        self.assertFalse(any("backup" in f for f in os.listdir(TMP)), os.listdir(TMP))
        cfg = app.load_config()
        self.assertEqual(cfg["hosts"][0]["layout_rev"], tiles.LAYOUT_REV)
        self.assertFalse(any("backup" in f for f in os.listdir(TMP)), os.listdir(TMP))


def press_move(widget, start, end, steps=6):
    """Mouse press + moves (no release) in widget coordinates, fixed on screen."""
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QMouseEvent
    L, N = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton
    gs, ge = widget.mapToGlobal(start), widget.mapToGlobal(end)

    def send(t, g, btn, btns):
        QApplication.sendEvent(widget, QMouseEvent(t, QPointF(widget.mapFromGlobal(g)), QPointF(g), btn, btns,
                                                   Qt.KeyboardModifier.NoModifier))
    send(QEvent.Type.MouseButtonPress, gs, L, L)
    for i in range(1, steps + 1):
        send(QEvent.Type.MouseMove, gs + (ge - gs) * i / steps, N, L)
        pump(1)
    return lambda: (send(QEvent.Type.MouseButtonRelease, ge, L, N), pump(30))


class Redesign3Tests(UiTestCase):
    """NAECHSTER-UMBAU round 3: edit mode concept 2, settings, empty start, feedback."""

    def test_rebuilt_cards_hide_old_ones_at_once(self):
        from PyQt6 import sip
        # refresh_hosts (e.g. on leaving edit mode) must not leave the old cards painted
        # until the next event-loop turn deletes them
        w = self.w
        w.enter_edit_mode()
        pump()
        old = list(w.host_rows.values())
        w.exit_edit_mode()
        self.assertTrue(all(not r.isVisible() for r in old if not sip.isdeleted(r)))
        pump()
        hw = next(iter(w.host_rows.values())).parentWidget()
        vis = [c for c in hw.findChildren(app.HostRow) if c.isVisible()]
        self.assertEqual(len(vis), len(w.host_rows))

    def test_done_keeps_accent_after_move(self):
        from PyQt6.QtCore import QPoint
        w = self.w
        w.enter_edit_mode()
        pump()
        b, first = w.tb_btns["edit"], w.tb_btns["add"]
        drag(b, QPoint(24, 24), b.mapFromGlobal(first.mapToGlobal(QPoint(4, 24))))
        self.assertEqual(w._tb_items[0]["id"], "edit")
        b = w.edit_btn
        self.assertTrue(b.property("primary"))
        self.assertFalse(b.property("tbSel"), "Fertig never gets the dark 'selected' look")
        pump()
        img = w.grab().toImage()
        want = app.QColor(app.ui_colors(w._light())["edit"])
        got = img.pixelColor(b.mapTo(w, app.QPoint(8, b.height() // 2)))
        self.assertLess(abs(got.red() - want.red()) + abs(got.green() - want.green()) + abs(got.blue() - want.blue()), 40,
                        (got.name(), want.name()))

    def test_edit_dim_labels_and_window_stays_active(self):
        w = self.w
        self.assertTrue(w.isActiveWindow())
        w.enter_edit_mode()
        pump()
        self.assertTrue(w.isActiveWindow(), "no widget flashed up as an own window")
        for x in (w.statusBar(), w.log_btn, w.tb_collapse_btn, w.host_rows["h0"].ip_lbl):
            self.assertAlmostEqual(x.graphicsEffect().opacity(), 0.4)
        self.assertEqual(w.tb_group_lbl.text(), app.t("tb_section"))
        self.assertEqual(w.edit_info.text(), app.t("edit_hint"))
        self.assertEqual(w.status_bar.text(), app.t("state_edit"))
        w.edit_select("h0", "boot")
        pump()
        self.assertEqual(w.edit_info.text(), app.t("edit_hint_selected"))
        w.exit_edit_mode()
        pump()
        self.assertIsNone(w.statusBar().graphicsEffect())
        self.assertIsNone(w.log_btn.graphicsEffect())

    def test_tile_drag_slots_focus_and_esc(self):
        w = self.w
        w.enter_edit_mode("h0")
        pump()
        ed = w.host_rows["h0"].editor
        start = list(self.pos("h0", "boot"))
        c = ed.tile_center("boot")
        release = press_move(ed, c, c + app.QPoint(0, 90))
        self.assertIsNotNone(ed._drag)
        slots = ed.drop_slots()
        self.assertEqual(list(slots[0]), start, "the original place is offered first")
        self.assertEqual(w.edit_info.text(), app.t("edit_hint_drag_tile"))
        self.assertTrue(w.drop_focus.isVisible())
        self.assertIsNotNone(w.drop_focus.keep, "the hint text stays readable")
        zone = w.drop_focus.zone
        self.assertTrue(zone.contains(ed.mapTo(w.drop_focus.parentWidget(), ed.rect().center())))
        QTest.keyClick(ed, Qt.Key.Key_Escape)
        pump()
        self.assertIsNone(ed._drag)
        self.assertFalse(w.drop_focus.isVisible())
        self.assertNotEqual(w.edit_info.text(), app.t("edit_hint_drag_tile"))
        release()
        self.assertEqual(self.pos("h0", "boot"), start)

    def test_toolbar_and_card_drag_hint_gap(self):
        from PyQt6.QtCore import QPoint
        w = self.w
        w.enter_edit_mode()
        pump()
        b, first = w.tb_btns["options"], w.tb_btns["add"]
        release = press_move(b, QPoint(24, 24), b.mapFromGlobal(first.mapToGlobal(QPoint(4, 24))))
        self.assertTrue(w.tb_drag.active)
        self.assertEqual(w.edit_info.text(), app.t("edit_hint_drag_tb"))
        self.assertIn(w._tb_group_layout, w._gap_items, "a real gap opens in the bar")
        self.assertTrue(w.drop_focus.isVisible())
        release()
        self.assertNotIn(w._tb_group_layout, w._gap_items)
        self.assertFalse(w.drop_focus.isVisible())
        self.assertEqual(w._tb_items[0]["id"], "options")
        row = w.host_rows["h0"]
        g = row.grip_lbl
        self.assertEqual(g.toolTip(), app.t("tip_card_grip"))
        last = w.host_rows["h2"]
        release = press_move(row, row.mapFromGlobal(g.mapToGlobal(g.rect().center())),
                             row.mapFromGlobal(last.mapToGlobal(QPoint(20, last.height() - 4))))
        self.assertTrue(w.card_drag.active)
        self.assertEqual(w.edit_info.text(), app.t("edit_hint_drag_card"))
        self.assertIn(w.host_layout, w._gap_items)
        release()
        self.assertNotIn(w.host_layout, w._gap_items)
        self.assertEqual([h["id"] for h in saved()["hosts"]][-1], "h0")

    def test_esc_cancels_toolbar_drag_on_pressed_button(self):
        from PyQt6.QtCore import QPoint
        w = self.w
        w.enter_edit_mode()
        pump()
        before = [i["id"] for i in w._tb_items]
        b, first = w.tb_btns["options"], w.tb_btns["add"]
        release = press_move(b, QPoint(24, 24), b.mapFromGlobal(first.mapToGlobal(QPoint(4, 24))))
        self.assertTrue(w.tb_drag.active)
        QTest.keyClick(b, Qt.Key.Key_Escape)       # the pressed button has the key
        pump(30)
        self.assertFalse(w.tb_drag.active)
        self.assertTrue(w._edit_mode, "Esc only ends the drag")
        release()
        self.assertEqual([i["id"] for i in w._tb_items], before)
        self.assertFalse(w.drop_focus.isVisible())

    def test_show_ip_off_tooltip_only(self):
        w = self.w
        w.cfg["settings"]["show_ip"] = False
        w.refresh_hosts()
        pump()
        r = w.host_rows["h0"]
        self.assertFalse(r.ip_lbl.isVisible())
        self.assertFalse(r.ip_lbl.isWindow())
        self.assertIn(app.t("st_ip", ip="192.0.2.10"), r.details_text())
        w.cfg["settings"]["show_ip"] = True
        w.refresh_hosts()
        pump()
        r = w.host_rows["h0"]
        self.assertTrue(r.ip_lbl.isVisible())
        self.assertNotIn(app.t("st_ip", ip="192.0.2.10"), r.details_text())

    def test_options_sections_and_data_dir(self):
        w = self.w
        dlg = app.OptionsDialog(w.cfg["settings"], w)
        try:
            texts = [l.text() for l in dlg.findChildren(app.QLabel)]
            for k in ("sec_display", "sec_behavior", "sec_updates", "sec_files"):
                self.assertTrue(any(app.t(k) in x for x in texts), k)
            self.assertEqual(dlg.data_dir_lbl.text(), str(app.APP_DIR))
            self.assertTrue(dlg.data_dir_lbl.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse)
            self.assertGreaterEqual(dlg.data_dir_btn.minimumSizeHint().height(), 30)
            seen = []
            orig = app.QDesktopServices.openUrl
            try:
                app.QDesktopServices.openUrl = staticmethod(lambda u: (seen.append(u), True)[1])
                self.assertTrue(dlg._open_data_dir())
                self.assertEqual(seen[0], app.QUrl.fromLocalFile(str(app.APP_DIR)))
                app.QDesktopServices.openUrl = staticmethod(lambda u: False)
                self.assertFalse(dlg._open_data_dir())
            finally:
                app.QDesktopServices.openUrl = orig
            pump()
            # said inside the dialog (a toast would sit behind the modal dialog)
            self.assertFalse(w.toast.isVisible())
            self.assertFalse(dlg.data_dir_err.isHidden())
            self.assertIn(app.t("data_dir_failed"), dlg.data_dir_err.text())
            self.assertIn(app.t("data_dir_failed_hint"), dlg.data_dir_err.text())
            err = app.ui_colors(w._light())["err"]
            self.assertIn(err, dlg.data_dir_lbl.styleSheet())      # the path in the error colour
            self.assertIn(err, dlg.data_dir_err.styleSheet())
            self.assertIn("font-weight: bold", dlg.data_dir_lbl.styleSheet())
            self.assertEqual(dlg.data_dir_lbl.text(), str(app.APP_DIR))
            try:                                       # works again: the error goes away
                app.QDesktopServices.openUrl = staticmethod(lambda u: True)
                self.assertTrue(dlg._open_data_dir())
            finally:
                app.QDesktopServices.openUrl = orig
            self.assertTrue(dlg.data_dir_err.isHidden())
            self.assertNotIn("font-weight: bold", dlg.data_dir_lbl.styleSheet())
            self.assertIn("show_ip", dlg.get_settings())
            self.assertIn("show_steam", dlg.get_settings())
        finally:
            dlg.deleteLater()

    def test_empty_start_big_add_tile(self):
        w = self.w
        called = []
        w.add_host = lambda *a: called.append(1)
        w.cfg["hosts"] = []
        w.refresh_hosts()
        pump()
        b = w.empty_add_btn
        self.assertTrue(b.isVisible())
        self.assertEqual(b.text(), app.t("add_first_host"))
        self.assertGreaterEqual(b.width(), 260)
        self.assertGreaterEqual(b.height(), 140)
        sub = w.findChild(app.QLabel, "emptySub")
        self.assertGreaterEqual(sub.geometry().top(), b.geometry().bottom(), "the text is below the tile")
        vp = w.scroll.viewport()
        cx = b.mapTo(vp, b.rect().center()).x()
        self.assertLess(abs(cx - vp.width() // 2), 30, "centred")
        b.click()
        self.assertEqual(called, [1])
        self.assertIn([b], w._nav_grid())

    def test_action_feedback_pending_then_toast(self):
        w = self.w
        r = w.host_rows["h0"]
        w.on_action_started("h0", "Gaming-PC", "wake")
        pump()
        self.assertEqual(r.pending, "wake")
        tips = [b.toolTip() for a, b in r.action_buttons if a == "wake"]
        self.assertIn(app.t("pending_wake"), tips)
        w.on_action_done("h0", "Gaming-PC", "wake", True, "")
        pump()
        self.assertEqual(r.pending, "wake", "the tile waits for the new status")
        self.assertIn(app.t("done_wake", title="Gaming-PC"), w.toast.title.text())
        r._pending_timer.timeout.emit()            # timeout (PENDING_MS) ends it
        pump()
        self.assertIsNone(r.pending)
        self.assertNotIn(app.t("pending_wake"), [b.toolTip() for a, b in r.action_buttons])
        w.on_action_started("h0", "Gaming-PC", "shutdown")
        w.on_action_done("h0", "Gaming-PC", "shutdown", False, "boom")
        pump()
        self.assertIsNone(r.pending, "failure: feedback ends at once")


def _write_cfg(cfg):
    with open(os.path.join(TMP, "config.json"), "w") as fh:
        json.dump(cfg, fh)


def _read_cfg():
    with open(os.path.join(TMP, "config.json")) as fh:
        return json.load(fh)


@unittest.skipUnless(HAVE_QT, "PyQt6 not installed")
class ConfigRobustnessTests(unittest.TestCase):
    """Review round 4: hand-edited / damaged config.json must not crash the app."""

    def tearDown(self):
        _write_cfg(_config())

    def test_non_dict_tiles_dropped_on_load(self):
        cfg = _config()
        cfg["hosts"][0]["aktionen"] = ["x", 5, None, *tiles.template("minimal"), ["boot"]]
        _write_cfg(cfg)
        data = app.load_config()
        ts = data["hosts"][0]["aktionen"]
        self.assertTrue(all(isinstance(a, dict) for a in ts))
        self.assertEqual(tiles.matching_template(ts), "minimal")
        self.assertTrue(all(isinstance(a, dict) for a in _read_cfg()["hosts"][0]["aktionen"]), "saved")

    def test_hosts_without_id_get_one(self):
        cfg = _config()
        cfg["hosts"] = ["junk", {"name": "A", "ip": "192.0.2.5"}, {"id": "", "name": "B"},
                        {"id": 7, "name": "C"}, {"id": None, "name": "D"}, *cfg["hosts"], 42]
        _write_cfg(cfg)
        data = app.load_config()
        ids = [h["id"] for h in data["hosts"]]
        self.assertEqual(len(ids), 7, "non-dict hosts dropped, the rest kept")
        self.assertTrue(all(isinstance(i, str) and i for i in ids))
        self.assertEqual(len(set(ids)), 7, "unique")
        self.assertEqual(ids[-3:], ["h0", "h1", "h2"], "existing ids untouched")
        self.assertEqual([h["name"] for h in data["hosts"][:4]], ["A", "B", "C", "D"])
        self.assertEqual([h["id"] for h in _read_cfg()["hosts"]], ids, "saved: ids stay stable")
        self.assertEqual(app.load_config()["hosts"][0]["id"], ids[0])
        self.assertEqual(data["hosts"][-1]["buddy_port"], 59999, "connection data unchanged")

    def test_hosts_not_a_list(self):
        for bad in ({"a": 1}, "x", None, 3):
            cfg = _config()
            cfg["hosts"] = bad
            _write_cfg(cfg)
            self.assertEqual(app.load_config()["hosts"], [], bad)

    def test_status_interval_coerced(self):
        for raw, want in (("45", 45), ("abc", 30), (5, 10), (9999, 300), (None, 30), (True, 30),
                          (60.0, 60), ("12.7", 12), ([1], 30), ({}, 30), (30, 30), ("", 30)):
            cfg = _config()
            cfg["settings"]["status_interval"] = raw
            _write_cfg(cfg)
            got = app.load_config()["settings"]["status_interval"]
            self.assertEqual(got, want, raw)
            self.assertIs(type(got), int, raw)

    def test_clean_config_not_rewritten(self):
        _write_cfg(_config())
        app.load_config()                       # first load: migration may save once
        before = os.path.getmtime(os.path.join(TMP, "config.json"))
        with open(os.path.join(TMP, "config.json")) as fh:
            raw = fh.read()
        time.sleep(0.02)
        data = app.load_config()
        self.assertFalse(app.sanitize_config(data))
        with open(os.path.join(TMP, "config.json")) as fh:
            self.assertEqual(fh.read(), raw)
        self.assertEqual(os.path.getmtime(os.path.join(TMP, "config.json")), before)

    def test_window_with_broken_config(self):
        cfg = _config()
        cfg["hosts"][0]["aktionen"] = ["garbage", *tiles.template("standard")]
        del cfg["hosts"][1]["id"]
        cfg["settings"]["status_interval"] = "45"
        _write_cfg(cfg)
        w = app.MainWindow()
        try:
            w.check_status = lambda *a, **k: None
            self.assertEqual(w.status_timer.interval(), 45000)
            w.show()
            pump()
            self.assertEqual(len(w.host_rows), 3)
            w.enter_edit_mode()
            pump()
            for r in w.host_rows.values():
                self.assertTrue(r.editor.isVisible())
            w.exit_edit_mode()
            w.refresh_hosts()
            pump()
        finally:
            w.status_timer.stop()
            w.hide()
            w.deleteLater()
            pump()


class Review4Tests(UiTestCase):
    """Review round 4: start minimized, card rebuild, grip, settings dialog."""

    def _tray(self, on):
        orig = app.QSystemTrayIcon.isSystemTrayAvailable
        app.QSystemTrayIcon.isSystemTrayAvailable = staticmethod(lambda: on)
        self.addCleanup(setattr, app.QSystemTrayIcon, "isSystemTrayAvailable", orig)

    def test_start_hidden_needs_hosts_and_tray(self):
        w = self.w
        w.cfg["settings"]["start_minimized"] = True
        self._tray(True)
        self.assertTrue(w.start_hidden())
        self._tray(False)
        self.assertFalse(w.start_hidden(), "no tray: the window could not be brought back")
        self._tray(True)
        hosts = w.cfg["hosts"]
        w.cfg["hosts"] = []
        self.assertFalse(w.start_hidden(), "empty start is always shown")
        w.cfg["hosts"] = hosts
        w.cfg["settings"]["start_minimized"] = False
        self.assertFalse(w.start_hidden())

    def test_start_minimized_default_off(self):
        """1.3.1: "Start minimized" is off unless the user turns it on (defaults,
        seed file, a config without the key, the Options checkbox)."""
        self.assertIs(app.DEFAULT_CONFIG["settings"]["start_minimized"], False)
        with open(os.path.join(ROOT, "packaging", "default-config.json"), encoding="utf-8") as fh:
            self.assertIs(json.load(fh)["settings"]["start_minimized"], False)
        w = self.w
        self._tray(True)
        saved = w.cfg["settings"].pop("start_minimized", None)
        try:
            self.assertFalse(w.start_hidden(), "missing key: shown")
            dlg = app.OptionsDialog(w.cfg["settings"], w)
            try:
                self.assertFalse(dlg.start_min.isChecked())
            finally:
                dlg.deleteLater()
        finally:
            w.cfg["settings"]["start_minimized"] = saved

    def test_empty_start_minimized_stays_visible(self):
        cfg = _config()
        cfg["hosts"] = []
        cfg["settings"]["start_minimized"] = True
        _write_cfg(cfg)
        self._tray(True)
        w2 = app.MainWindow()
        try:
            w2.check_status = lambda *a, **k: None
            w2.status_timer.stop()
            self.assertFalse(w2.start_hidden())
            w2.show()                                    # what main() does now
            for _ in range(30):                          # the 100 ms hide timer must not fire
                pump()
                time.sleep(0.01)
            self.assertTrue(w2.isVisible())
            self.assertIsNotNone(w2.empty_add_btn)
        finally:
            w2.hide()
            w2.deleteLater()
            pump()

    def test_rebuild_keeps_busy_and_pending(self):
        w = self.w
        w.host_rows["h0"].set_busy(True, "wake")
        r1 = w.host_rows["h1"]
        r1.set_busy(True, "shutdown")
        r1.set_busy(False, keep_pending=True)           # returned fine, feedback kept
        w.host_rows["h2"].set_failed("Zeitüberschreitung")
        w.cfg["settings"]["show_ip"] = False             # what a settings change does
        w.refresh_hosts()
        pump()
        r0, r1, r2 = (w.host_rows[h] for h in ("h0", "h1", "h2"))
        self.assertTrue(r0.busy)
        self.assertEqual(r0.pending, "wake")
        self.assertTrue(r0._pending_timer.isActive())
        # the rest of the time, not a new 90 s (coarse timer: up to 5 % slack)
        self.assertLessEqual(r0._pending_timer.remainingTime(), app.HostRow.PENDING_MS * 1.05)
        self.assertTrue(any(b.property("pending") for _, b in r0.action_buttons))
        self.assertFalse(r1.busy)
        self.assertEqual(r1.pending, "shutdown")
        self.assertTrue(r1._pending_timer.isActive())
        self.assertTrue(r2.failed)
        self.assertTrue(r2.error_lbl.isVisible())
        self.assertEqual(r2.error_lbl.text(), "⚠ Zeitüberschreitung")
        self.assertEqual(r2.error_lbl.toolTip(), "Zeitüberschreitung")
        r0.set_busy(False)                               # the action ends normally afterwards
        self.assertIsNone(r0.pending)
        self.assertFalse(r0._pending_timer.isActive())

    def test_rebuild_without_feedback_stays_calm(self):
        w = self.w
        w.refresh_hosts()
        pump()
        for r in w.host_rows.values():
            self.assertFalse(r.busy)
            self.assertIsNone(r.pending)
            self.assertFalse(r._pending_timer.isActive())
            self.assertFalse(r.error_lbl.isVisible())

    def test_card_grip_is_painted(self):
        w = self.w
        w.enter_edit_mode()
        pump()
        g = w.host_rows["h0"].grip_lbl
        self.assertIsInstance(g, app._CardGrip)
        self.assertNotIsInstance(g, app.QLabel)
        self.assertEqual(g.width(), 16)
        self.assertEqual(g.toolTip(), app.t("tip_card_grip"))
        self.assertEqual(g.cursor().shape(), Qt.CursorShape.OpenHandCursor)
        img = g.grab().toImage()
        sub = app.QColor(app.ui_colors(w._light())["sub"])
        dots = sum(1 for x in range(img.width()) for y in range(img.height())
                   if abs(img.pixelColor(x, y).red() - sub.red()) < 12
                   and abs(img.pixelColor(x, y).green() - sub.green()) < 12)
        self.assertGreater(dots, 6, "six dots drawn in the sub colour")

    def test_settings_checkboxes_48px(self):
        w = self.w
        for theme in ("Dark", "Light"):
            st = dict(w.cfg["settings"], theme=theme)
            dlg = app.OptionsDialog(st, w)
            try:
                dlg.show()
                pump()
                boxes = dlg.findChildren(app.QCheckBox)
                self.assertGreaterEqual(len(boxes), 5)
                for cb in boxes:
                    if cb.isVisible():
                        self.assertGreaterEqual(cb.height(), 48, cb.text())
            finally:
                dlg.hide()
                dlg.deleteLater()
                pump()

    def test_data_dir_error_light_theme(self):
        w = self.w
        st = dict(w.cfg["settings"], theme="Light")
        dlg = app.OptionsDialog(st, w)
        orig = app.QDesktopServices.openUrl
        try:
            app.QDesktopServices.openUrl = staticmethod(lambda u: False)
            dlg.show()
            self.assertFalse(dlg._open_data_dir())
            pump()
            self.assertTrue(dlg.data_dir_err.isVisible())
            self.assertIn(app.ui_colors(True)["err"], dlg.data_dir_err.styleSheet())
            self.assertFalse(w.toast.isVisible())
        finally:
            app.QDesktopServices.openUrl = orig
            dlg.hide()
            dlg.deleteLater()
            pump()


MM_OLD = dict(READY, steam=None, api=8, api_mismatch={"host": 8, "want": 9, "dir": "host_old"})
MM_NEW = dict(READY, steam=None, api=10, api_mismatch={"host": 10, "want": 9, "dir": "host_new"})
CLI_OK_SH = "#!/bin/sh\necho 'usage: moondeck-cli [-h]'\nexit 0\n"
CLI_BAD_SH = "#!/bin/sh\nexit 3\n"


class Release131Tests(UiTestCase):
    """1.3.1: Buddy API mismatch, custom MoonDeck CLI, combined update check."""

    def setUp(self):
        super().setUp()
        self.tmpd = tempfile.mkdtemp(prefix="br-cli-")
        self.dlgs = []
        self.urls = []
        self._open = app.QDesktopServices.openUrl
        app.QDesktopServices.openUrl = staticmethod(lambda u: self.urls.append(u.toString()) or True)

    def tearDown(self):
        app.QDesktopServices.openUrl = self._open
        app.backend.set_custom_cli("")
        self.w._options_dlg = None
        for dlg in self.dlgs:
            dlg.hide()
            dlg.deleteLater()
        pump()
        super().tearDown()
        shutil.rmtree(self.tmpd, ignore_errors=True)

    def script(self, name, body):
        path = os.path.join(self.tmpd, name)
        with open(path, "w") as fh:
            fh.write(body)
        os.chmod(path, 0o755)
        return path

    def colour(self, row):
        return row.dot.styleSheet().split("background:")[1].split(";")[0].strip()

    def steam_and_others(self, row):
        steam = [b for a, b in row.action_buttons if a == "steam"]
        other = [b for a, b in row.action_buttons if a not in ("steam", "wake")]
        return steam, other

    # --- (B) mismatch -------------------------------------------------------------
    def check_mismatch(self, res, hint_key, why_key, fix_key):
        w = self.w
        w.on_host_status("h0", res)
        pump()
        row = w.host_rows["h0"]
        c = app.ui_colors(row._light())
        self.assertEqual(self.colour(row), c["warn"])                  # orange, not green
        self.assertTrue(row.hint_row.isVisible())
        self.assertTrue(row.details_btn.isVisible())
        self.assertEqual(row.hint_lbl.text(), app.t(hint_key) + " ·")
        steam, other = self.steam_and_others(row)
        self.assertTrue(steam, "host has a Steam tile")
        for b in steam:                                                # only Steam greyed out …
            self.assertFalse(b.isEnabled())
            self.assertEqual(b.toolTip(), app.t(why_key))
        for b in other:                                                # … the rest stays usable
            self.assertTrue(b.isEnabled(), b.text())
        mm = res["api_mismatch"]
        tip = row.dot.toolTip()
        self.assertIn(app.t("st_mismatch", host=mm["host"], want=mm["want"]), tip)
        self.assertIn(app.t("st_api_bad", host=mm["host"], want=mm["want"]), tip)
        self.assertIn(app.t(fix_key), tip)
        w.on_host_status("h0", READY)                                  # fixed: back to normal
        pump()
        self.assertEqual(self.colour(row), c["online"])
        self.assertFalse(row.hint_row.isVisible())
        self.assertTrue(all(b.isEnabled() for b in steam))

    def test_mismatch_host_older(self):
        self.check_mismatch(MM_OLD, "hint_buddy_old", "why_mismatch_old", "st_api_fix_old")

    def test_mismatch_host_newer(self):
        self.check_mismatch(MM_NEW, "hint_buddy_new", "why_mismatch_new", "st_api_fix_new")

    def run_check(self, body, cli=(0, '{"running": false}', "")):
        calls = []
        old = (app.check_buddy_api, app.run_cli)
        got = []
        app.check_buddy_api = lambda *a, **k: (True, body)
        app.run_cli = lambda *a, **k: calls.append(a) or cli
        self.w.signals.host_status.connect(lambda hid, res: got.append(res))
        try:
            self.w._check_host(self.host("h0"))
            pump()
        finally:
            app.check_buddy_api, app.run_cli = old
        return got[-1], calls

    def test_check_host_reads_api_version(self):
        res, calls = self.run_check('{"version": 8}')
        self.assertEqual(res["api"], 8)
        self.assertEqual(res["api_mismatch"]["dir"], "host_old")
        self.assertEqual(calls, [], "no steam status against a mismatching Buddy")
        res, calls = self.run_check('{"version": 10}')
        self.assertEqual(res["api_mismatch"]["dir"], "host_new")
        res, calls = self.run_check('{"version": 9}')
        self.assertIsNone(res["api_mismatch"])
        self.assertEqual(len(calls), 1)

    def test_check_host_cli_needs_update(self):
        res, _ = self.run_check("not json", cli=(1, "", "MoonDeck/Buddy needs update!"))
        self.assertEqual(res["api_mismatch"]["dir"], "unknown")
        self.assertIsNone(res["steam"])
        self.w.on_host_status("h0", res)
        pump()
        row = self.w.host_rows["h0"]
        self.assertEqual(row.hint_lbl.text(), app.t("hint_buddy_mismatch") + " ·")
        self.assertIn(app.t("st_mismatch_unknown"), row.dot.toolTip())

    # --- update check ---------------------------------------------------------------
    def result(self, app_new=False, cli_new=False, manual=False, cli_ok=True):
        res = {"ok": True, "manual": manual, "version": "9.9.9" if app_new else app.APP_VERSION,
               "url": "https://example.invalid/app", "newer": app_new}
        res["cli"] = ({"ok": True, "newer": cli_new, "commit": "abc1234", "url": "https://example.invalid/cli"}
                      if cli_ok else {"ok": False, "error": "offline"})
        return res

    def test_combined_toast(self):
        w = self.w
        w.on_update_result(self.result(app_new=True, cli_new=True))
        pump()
        self.assertTrue(w.update_toast.isVisible())
        self.assertIn(app.t("update_both_title", version="9.9.9"), w.update_toast.title.text())
        self.assertEqual(w.update_toast.dl_btn.text(), app.t("update_download"))
        w.update_toast.dl_btn.click()
        self.assertEqual(self.urls, ["https://example.invalid/app"])

    def test_cli_only_toast_once(self):
        w = self.w
        w.on_update_result(self.result(cli_new=True))
        pump()
        self.assertTrue(w.update_toast.isVisible())
        self.assertIn(app.t("cli_update_title"), w.update_toast.title.text())
        self.assertIn("nightly abc1234", w.update_toast.detail.text())
        self.assertEqual(w.update_toast.dl_btn.text(), app.t("cli_release_page"))
        w.update_toast.dl_btn.click()
        self.assertEqual(self.urls, ["https://example.invalid/cli"])
        self.assertFalse(w.update_toast.isVisible())
        w._pending_update = None
        w.on_update_result(self.result(cli_new=True))                   # automatic again: quiet
        pump()
        self.assertFalse(w.update_toast.isVisible())
        w.on_update_result(self.result(cli_new=True, manual=True))      # manual: always
        pump()
        self.assertTrue(w.update_toast.isVisible())

    def test_manual_nothing_new_and_dialog_state(self):
        w = self.w
        w.on_update_result(self.result(manual=True))
        pump()
        self.assertTrue(w.toast.isVisible())
        self.assertIn(app.t("update_current_both", version=app.APP_VERSION), w.toast.title.text())
        st = w.update_state()
        self.assertEqual((st["app"], st["cli"]), ("current", "current"))
        w.on_update_result(self.result(cli_ok=False))
        self.assertEqual(w.update_state()["cli"], "error")

    # --- options ----------------------------------------------------------------------
    def dialog(self, **extra):
        dlg = app.OptionsDialog(dict(self.w.cfg["settings"], **extra), self.w)
        self.w._options_dlg = dlg
        dlg.show()
        pump()
        self.dlgs.append(dlg)
        return dlg

    def test_options_update_boxes(self):
        w = self.w
        w.on_update_result(self.result(app_new=True, cli_new=True))
        dlg = self.dialog()
        self.assertGreaterEqual(dlg.update_btn.height(), 48)
        self.assertEqual(dlg.update_btn.text(), app.t("check_updates_now"))
        self.assertIn(app.t("update_available", version="9.9.9"), dlg.upd_app_status.text())
        self.assertTrue(dlg.upd_dl_row.isVisible())
        self.assertIn(app.t("upd_cli_newer", label="nightly abc1234"), dlg.upd_cli_status.text())
        self.assertTrue(dlg.upd_cli_note.isVisible())
        dlg.refresh_updates(dict(w.update_state(), checking=True))
        self.assertFalse(dlg.update_btn.isEnabled())
        self.assertEqual(dlg.upd_app_status.text(), app.t("update_checking"))
        dlg.refresh_updates(dict(w.update_state(), app="error", cli="error"))
        self.assertEqual(dlg.upd_cli_status.text(), app.t("update_res_error"))
        self.assertTrue(dlg.update_btn.isEnabled())
        from PyQt6.QtGui import QResizeEvent
        boxes = dlg.upd_boxes
        boxes.resizeEvent(QResizeEvent(app.QSize(500, 200), boxes.size()))   # narrow: stacked
        self.assertTrue(boxes.stacked())
        boxes.resizeEvent(QResizeEvent(app.QSize(800, 200), boxes.size()))
        self.assertFalse(boxes.stacked())

    def test_options_cli_bundled_pick_reject_and_back(self):
        dlg = self.dialog()
        self.assertEqual(dlg.custom_cli_view(), "bundled")
        self.assertTrue(dlg.cli_title.text().startswith(app.t("cli_bundled_paren", label=app.backend.bundled_cli_label())))
        self.assertFalse(dlg.cli_back_btn.isVisible())
        bad = self.script("bad-cli", CLI_BAD_SH)
        dlg._pick_cli_file = lambda: bad
        dlg.cli_choose_btn.click()
        pump()
        self.assertTrue(dlg.cli_err.isVisible())                        # rejected, not taken over
        self.assertEqual(dlg.get_settings()["custom_cli"], "")
        good = self.script("good-cli", CLI_OK_SH)
        dlg._pick_cli_file = lambda: good
        dlg.cli_choose_btn.click()
        pump()
        self.assertFalse(dlg.cli_err.isVisible())
        self.assertEqual(dlg.custom_cli_view(), "active")
        self.assertEqual(dlg.cli_title.text(), "⚠ " + app.t("cli_custom_active"))
        self.assertEqual(dlg.cli_path_lbl.text(), good)
        self.assertIn(app.backend.sha256_file(good)[:8], dlg.cli_sha_lbl.text())
        self.assertTrue(dlg.cli_note.isVisible())                       # applied on save
        self.assertTrue(dlg.upd_cli_link.isVisible())                   # U3 box
        self.assertIn(app.t("cli_custom_active"), dlg.upd_cli_version.text())
        self.assertEqual(dlg.get_settings()["custom_cli"], good)
        dlg.cli_back_btn.click()
        pump()
        self.assertEqual(dlg.get_settings()["custom_cli"], "")
        self.assertEqual(dlg.custom_cli_view(), "bundled")

    def test_options_cli_failed_and_missing(self):
        bad = self.script("bad-cli", CLI_BAD_SH)
        app.backend.set_custom_cli(bad)
        app.backend.active_cli()                                       # probe -> failed
        pump()
        dlg = self.dialog(custom_cli=bad)
        self.assertEqual(dlg.custom_cli_view(), "failed")
        self.assertEqual(dlg.cli_title.text(), "⚠ " + app.t("cli_custom_failed"))
        self.assertIn(app.ui_colors(self.w._light())["err"], dlg.cli_title.styleSheet())
        self.assertFalse(dlg.cli_note.isVisible())
        gone = os.path.join(self.tmpd, "gone")
        dlg2 = self.dialog(custom_cli=gone)
        self.assertEqual(dlg2.custom_cli_view(), "missing")
        self.assertEqual(dlg2.cli_title.text(), "⚠ " + app.t("cli_custom_missing"))
        self.assertEqual(dlg2.get_settings()["custom_cli"], gone)     # the setting is kept

    # --- custom CLI at runtime ------------------------------------------------------------
    def test_failed_custom_cli_toast_and_status_bar(self):
        w = self.w
        bad = self.script("bad-cli", CLI_BAD_SH)
        app.backend.set_custom_cli(bad)
        self.assertEqual(app.backend.active_cli(), app.backend.CLI_BIN)   # falls back to bundled
        pump()
        self.assertTrue(w.toast.isVisible())
        self.assertIn(app.t("cli_custom_failed"), w.toast.title.text())
        self.assertTrue(w.toast.action_btn.isVisible())
        self.assertEqual(w.toast.action_btn.text(), app.t("toast_settings"))
        self.assertEqual(w.cli_lbl.text(), app.t("cli_custom_status"))
        self.assertIn(bad, w.cli_lbl.toolTip())
        self.assertIn(app.t("cli_custom_failed"), w.cli_lbl.toolTip())
        w.toast.hide()
        w.on_cli_state("failed", bad, "again")                            # same state: no second toast
        pump()
        self.assertFalse(w.toast.isVisible())
        app.backend.set_custom_cli("")
        w._update_status_bar()
        self.assertTrue(w.cli_lbl.text().startswith("MoonDeck CLI"))


if __name__ == "__main__":
    unittest.main()
