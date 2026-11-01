"""1.4-preview2 input fixes, offscreen:
- touch (U1): tile hold + drag with real platform touch events (Qt's own QTest::createTouchDevice
  and qt_handleTouchEventv2 via ctypes, PyQt6 has no QTest.touchEvent), plus the mouse emulation
  gamescope uses in Steam Deck Game Mode; Linux only.
- gamepad (U2/U3): controller-only walkthroughs through the real GamepadBridge with a fake SDL
  source (the same normalized events SDLGamepadSource.poll() yields).
    QT_QPA_PLATFORM=offscreen python3 -m unittest tests.test_touch_gamepad -v
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_ui as U  # noqa: E402
from test_ui import pump, setUpModule, tearDownModule  # noqa: E402,F401

try:
    from PyQt6.QtCore import QPoint
    from PyQt6.QtWidgets import QApplication
    from qt_touch import RealMouse, RealToucher
    HAVE_TOUCH = True
except Exception:          # no PyQt6, or not the Linux Qt build the helper calls into
    HAVE_TOUCH = False


def wait(ms):
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        U.qa.processEvents()
        time.sleep(0.005)


@unittest.skipUnless(U.HAVE_QT and HAVE_TOUCH, "PyQt6 / Linux Qt touch injection not available")
class TouchTileTests(U.UiTestCase):
    def _drag(self, inj_cls, hold_ms, wobble=0, rows=2):
        """press on 'boot', optional wobble, hold, drag `rows` rows down, release."""
        w = self.w
        w.enter_edit_mode("h0"); pump()
        ed = w.host_rows["h0"].editor
        start = list(self.pos("h0", "boot"))
        c = ed.tile_center("boot")
        T = inj_cls(ed)
        T.send("press", c); pump(2)
        if wobble:
            T.send("move", c + QPoint(wobble, wobble)); pump(2)
        wait(hold_ms)
        picked = ed._drag is not None
        end = c + QPoint(0, rows * (ed.ch + ed.GAP))
        for i in range(1, 7):
            T.send("move", c + (end - c) * i / 6); pump(2)
        T.send("release", end); pump(30)
        return start, list(self.pos("h0", "boot")), picked

    def test_touch_hold_then_drag_moves_tile(self):
        s, e, picked = self._drag(RealToucher, 450)
        self.assertTrue(picked)
        self.assertNotEqual(s, e)

    def test_finger_jitter_during_hold_keeps_the_tile(self):
        # 12+12 px (manhattan 24): normal fingertip jitter on the Deck; 1.4-preview cancelled at 12
        s, e, picked = self._drag(RealToucher, 450, wobble=12)
        self.assertTrue(picked, "finger jitter during the hold cancels the pick-up")
        self.assertNotEqual(s, e)

    def test_swipe_before_hold_does_not_pick_up(self):
        # a real swipe (25+25 px before the hold elapsed) stays a swipe: nothing moves
        s, e, picked = self._drag(RealToucher, 450, wobble=25)
        self.assertFalse(picked)
        self.assertEqual(s, e)

    def test_touch_without_hold_does_not_move(self):
        s, e, picked = self._drag(RealToucher, 0)
        self.assertEqual(s, e)

    def test_game_mode_mouse_emulation_drag(self):
        s, e, picked = self._drag(RealMouse, 0)
        self.assertNotEqual(s, e)

    def test_touch_slop_value(self):
        self.assertGreaterEqual(U.app.TilePreview.TOUCH_SLOP, 30)


class FakePad:
    def __init__(self):
        self.q = [("added", 7, "Steam Deck (fake)")]

    def open(self):
        return ""

    def poll(self):
        out, self.q = self.q, []
        return out

    def close(self):
        pass


@unittest.skipUnless(U.HAVE_QT, "PyQt6 not installed")
class GamepadTests(U.UiTestCase):
    def setUp(self):
        super().setUp()
        w = self.w
        w.activateWindow(); w.raise_(); pump(5)
        self.pad = FakePad()
        self.br = w.gamepad
        self.br.src = self.pad
        self.br.devices.clear(); self.br.held.clear(); self.br.pressed.clear()
        self.br.tick(); pump(3)

    def press(self, btn):
        self.pad.q.append(("button", 7, btn, True)); self.br.tick(); pump(5)
        self.pad.q.append(("button", 7, btn, False)); self.br.tick(); pump(10)
        return QApplication.focusWidget()

    def ed_host(self, fw):
        for h, r in self.w.host_rows.items():
            if fw is not None and r.editor is fw:
                return h
        return None

    def where(self, fw):
        h = self.ed_host(fw)
        return ("editor", h) if h else (fw.property("navKey") or fw.objectName() or type(fw).__name__)

    def walk(self, btns):
        seen = []
        for b in btns:
            k = self.where(self.press(b))
            if k not in seen:
                seen.append(k)
        return seen

    def test_window_is_active(self):
        self.assertIsNotNone(QApplication.activeWindow(), "offscreen: no active window, the bridge ignores input")

    def test_move_tile_gamepad_only(self):
        w = self.w
        w.edit_btn.setFocus(); pump()
        w.input_mode.set_nav_visible(False)
        self.press("down")                 # first press only reveals the focus ring
        w.edit_btn.setFocus(); pump()
        self.press("a")                    # A on "Bearbeiten" -> edit mode
        pump(20)
        start = list(self.pos(w._edit_hid, "boot"))
        for b in ("a", "x", "right", "x"):      # into the tiles, grab, move, release
            self.press(b)
        self.assertNotEqual(start, list(self.pos("h0", "boot")), "gamepad could not move a tile")

    def test_dpad_moves_tiles_bumpers_leave_the_editor(self):
        """1.4 levels: on the card level the D-pad goes from card to card (left/right do
        nothing), the tiles are moved only after A (tiles) + X (grab); LB/RB still jump to
        the previous/next row: other cards, the edit bar, the log."""
        w = self.w
        w.enter_edit_mode(); pump(20)
        w.input_mode.set_nav_visible(True)
        w.host_rows["h0"].editor.setFocus(); pump(5)
        self.assertEqual(self.walk(["left", "right"]), [("editor", "h0")])
        self.assertEqual(self.walk(["down", "down", "up"]), [("editor", "h1"), ("editor", "h2")])
        self.assertEqual(self.ed_host(QApplication.focusWidget()), "h1")
        w.host_rows["h0"].editor.setFocus(); pump(5)
        fwd = self.walk(["rb"] * 14)
        self.assertIn(("editor", "h1"), fwd, "RB does not reach the next card's tiles")
        self.assertIn(("editor", "h2"), fwd)
        w.host_rows["h0"].editor.setFocus(); pump(5)
        self.walk(["lb"] * 2)
        self.assertIn(QApplication.focusWidget(), w.edit_top_buttons + w.edit_tool_buttons,
                      "LB x2 from the first card does not reach the edit bar")
        # the D-pad still moves a tile after jumping into the next card
        w.host_rows["h0"].editor.setFocus(); pump(5)
        self.press("rb"); self.press("rb")
        ed = QApplication.focusWidget()
        hid = self.ed_host(ed)
        self.assertEqual(hid, "h1")
        self.assertEqual(w.pad_edit.level, 1)
        self.press("a")                             # tiles of h1, the first one has the ring
        key = w.pad_edit.key; start = list(self.pos(hid, key))
        for b in ("x", "down", "down", "x"):        # (h1's first tile has no room to the right)
            self.press(b)
        self.assertNotEqual(start, list(self.pos(hid, key)))

    def test_bumpers_are_tab_in_dialogs(self):
        self.assertEqual(U.app.GamepadBridge.KEYS["rb"], U.app.Qt.Key.Key_Tab)
        self.assertEqual(U.app.GamepadBridge.KEYS["lb"], U.app.Qt.Key.Key_Backtab)

    def test_controller_hint_in_edit_bar(self):
        w = self.w
        w.enter_edit_mode(); pump(20)
        w.input_mode.set_nav_visible(True); pump(3)
        self.press("left")                                     # controller used
        self.assertTrue(w.edit_hints.isVisible())
        self.assertFalse(w.edit_info.isVisible())
        w.input_mode.set_pad_active(False); pump(3)            # mouse / touch / keyboard used
        self.assertFalse(w.edit_hints.isVisible())
        self.assertEqual(w.edit_info.text(), U.app.t("edit_hint"))
        self.press("left")
        self.assertTrue(w.edit_hints.isVisible())
        self.br.devices.clear(); w._sync_edit_bar()           # pad unplugged
        self.assertFalse(w.edit_hints.isVisible())
        self.assertEqual(w.edit_info.text(), U.app.t("edit_hint"))

    def test_restore_collapsed_bar(self):
        w = self.w
        w.set_toolbar_collapsed(True, animate=False); pump(20)
        self.assertTrue(w._tb_collapsed)
        w.input_mode.set_nav_visible(False)            # mouse used before -> ring hidden
        for b in ("down", "up", "up", "up", "a"):
            self.press(b)
        pump(30)
        self.assertFalse(w._tb_collapsed, "gamepad could not bring the control bar back")

    def test_collapse_and_restore_by_pad(self):
        w = self.w
        w.input_mode.set_nav_visible(True)
        w.tb_collapse_btn.setFocus(); pump()
        self.press("a"); pump(40)          # collapse with the pad itself
        self.assertTrue(w._tb_collapsed)
        self.assertIs(QApplication.focusWidget(), w.tb_grip, "focus not on the grip after collapsing")
        self.press("up"); self.press("a"); pump(40)
        self.assertFalse(w._tb_collapsed, "gamepad could not bring the control bar back")
        self.assertIn(QApplication.focusWidget(), w.toolbar_buttons)

    def test_no_wake_after_collapsing(self):
        """Collapsing used to leave focus on the hidden grip; the next press jumped onto the
        first card's Wake, so up + A could wake a PC instead of showing the bar."""
        w = self.w
        acts = []
        w.do_action = lambda host, a, *x, **k: acts.append(a)
        for r in w.host_rows.values():
            for b in r.findChildren(U.app.QPushButton):
                if b.property("navKey") == "wake":
                    b.clicked.connect(lambda *_: acts.append("wake"))
        w.input_mode.set_nav_visible(True)
        w.tb_collapse_btn.setFocus(); pump()
        self.press("a"); pump(40)
        fw = self.press("up")
        self.assertNotEqual(fw.property("navKey"), "wake")
        self.press("a"); pump(20)
        self.assertEqual(acts, [])

if __name__ == "__main__":
    unittest.main()
