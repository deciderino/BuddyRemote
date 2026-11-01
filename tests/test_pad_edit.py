"""1.4: controller edit mode (card / tile levels, A/X/B, grab and cancel), the button
hints in the edit bar (Variante B: only while the controller is used, glyphs per pad
type) and the "not tested with BuddyRemote" note for an own MoonDeck CLI. Offscreen,
through the real GamepadBridge with a fake SDL source.
    QT_QPA_PLATFORM=offscreen python3 -m unittest tests.test_pad_edit -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_ui as U  # noqa: E402
from test_touch_gamepad import FakePad  # noqa: E402
from test_ui import pump, setUpModule, tearDownModule  # noqa: E402,F401

import gamepad  # noqa: E402
import padedit  # noqa: E402

try:
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtGui import QCursor
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication
except Exception:
    pass


class PadStyleTests(unittest.TestCase):
    """SDL_GameControllerGetType first, the name as fallback; Switch / unknown = Xbox."""
    def test_sdl_type(self):
        ps = (4, 5, 6)       # SDL_CONTROLLER_TYPE_PS3/PS4/PS5 in SDL 2.0.14+
        self.assertEqual(gamepad.pad_style(5, "whatever", ps), "ps")
        self.assertEqual(gamepad.pad_style(1, "Xbox 360 Controller", ps), "xbox")
        self.assertEqual(gamepad.pad_style(7, "Nintendo Switch Pro Controller", ps), "xbox")
        self.assertEqual(gamepad.pad_style(0, "Unknown", ps), "xbox")

    def test_name_fallback(self):
        for n in ("PS4 Controller", "DualSense Wireless Controller", "Sony Interactive Entertainment",
                  "PLAYSTATION(R)3 Controller"):
            self.assertEqual(gamepad.pad_style(None, n), "ps", n)
        for n in ("Steam Deck", "Xbox Wireless Controller", "Nintendo Switch Pro Controller", ""):
            self.assertEqual(gamepad.pad_style(None, n), "xbox", n)

    def test_glyph_texts(self):
        self.assertEqual([padedit.glyph_text(k, "xbox") for k in "abx"], ["A", "B", "X"])
        self.assertEqual([padedit.glyph_text(k, "ps") for k in "abx"], ["✕", "○", "□"])
        self.assertEqual(padedit.glyph_text("lbrb", "xbox"), "LB/RB")
        self.assertEqual(padedit.glyph_text("lbrb", "ps"), "L1/R1")


@unittest.skipUnless(U.HAVE_QT, "PyQt6 not installed")
class PadEditTests(U.UiTestCase):
    def setUp(self):
        super().setUp()
        w = self.w
        w.activateWindow(); w.raise_(); pump(5)
        self.pad = FakePad()
        self.br = w.gamepad
        self.br.src = self.pad
        self.br.devices.clear(); self.br.held.clear(); self.br.pressed.clear()
        self.br.styles.clear(); self.br.last_dev = None
        self.br.tick(); pump(3)
        w.enter_edit_mode("h0"); pump(20)
        w.input_mode.set_nav_visible(True)
        w.host_rows["h0"].editor.setFocus(); pump(5)
        self.pe = w.pad_edit

    def press(self, btn, dev=7):
        self.pad.q.append(("button", dev, btn, True)); self.br.tick(); pump(5)
        self.pad.q.append(("button", dev, btn, False)); self.br.tick(); pump(10)
        return QApplication.focusWidget()

    def order(self):
        return [h["id"] for h in self.w.cfg["hosts"]]

    def hint_texts(self):
        return self.w.edit_hints.texts()

    def t(self, k, **kw):
        return U.app.t(k, **kw)

    # --- levels ---------------------------------------------------------------
    def test_a_enters_tiles_b_goes_back_and_leaves(self):
        w, pe = self.w, self.pe
        self.press("left")                       # pad used: level 1 on Gaming-PC
        self.assertEqual((pe.level, pe.hid), (1, "h0"))
        self.assertEqual(w.edit_hints.where, self.t("pad_where_cards"))
        self.press("a")
        self.assertEqual(pe.level, 2)
        self.assertEqual(pe.key, w.host_rows["h0"].editor.order()[0])
        self.assertEqual(w.edit_hints.where, self.t("pad_where_tiles", host="Gaming-PC"))
        self.assertTrue(pe.ring.isVisible())
        # the other cards (inactive level) are greyed, this one is not
        self.assertTrue(w.host_rows["h1"].property("padDim"))
        self.assertFalse(w.host_rows["h0"].property("padDim"))
        self.press("b")
        self.assertEqual(pe.level, 1)
        self.assertFalse(w.host_rows["h1"].property("padDim"))
        self.assertTrue(w._edit_mode)
        self.press("b")                          # B on the card level: edit mode ends
        self.assertFalse(w._edit_mode)

    def test_dpad_in_tiles_moves_the_focus_not_the_tile(self):
        pe = self.pe
        self.press("left"); self.press("a")
        before = [list(a["pos"]) for a in self.host("h0")["aktionen"]]
        k0 = pe.key
        self.press("right")
        self.assertNotEqual(pe.key, k0)
        self.press("left")
        self.assertEqual(pe.key, k0)
        self.assertEqual(before, [list(a["pos"]) for a in self.host("h0")["aktionen"]])
        self.assertEqual(self.ed_focus(), "h0")

    def ed_focus(self):
        fw = QApplication.focusWidget()
        return next((h for h, r in self.w.host_rows.items() if r.editor is fw), None)

    def test_a_selects_then_opens_menu_b_closes_it(self):
        w, pe = self.w, self.pe
        self.press("left"); self.press("a")
        self.press("a")                          # select
        self.assertEqual(w._edit_sel, ("h0", pe.key))
        self.assertIn(self.t("pad_menu"), self.hint_texts())
        self.press("a")                          # second A on the selected tile: menu
        pump(10)
        self.assertTrue(pe.menu_open())
        self.assertEqual(w.edit_hints.where,
                         self.t("pad_where_menu", host="Gaming-PC", tile=pe._tile_name("h0", pe.key)))
        self.press("b")                          # closes the menu, stays on the tiles
        pump(10)
        self.assertFalse(pe.menu_open())
        self.assertEqual(pe.level, 2)
        self.assertEqual(w.edit_hints.where, self.t("pad_where_tiles", host="Gaming-PC"))

    def test_moving_on_drops_the_selection(self):
        w = self.w
        self.press("left"); self.press("a"); self.press("a")
        self.assertIsNotNone(w._edit_sel)
        self.press("right")
        self.assertIsNone(w._edit_sel)

    # --- grab (X) -------------------------------------------------------------
    def test_tile_grab_move_release_and_undo(self):
        w, pe = self.w, self.pe
        self.press("left"); self.press("a")
        k = pe.key
        start = list(self.pos("h0", k))
        self.press("x")
        self.assertIsNotNone(pe.grab)
        self.assertIsNotNone(w.host_rows["h0"].editor._drag)
        self.assertEqual(w.edit_hints.where,
                         self.t("pad_where_grab_tile", host="Gaming-PC", tile=pe._tile_name("h0", k)))
        self.assertEqual(self.hint_texts(), [self.t("pad_move"), self.t("pad_release"), self.t("pad_cancel")])
        self.assertFalse(pe.ring.isVisible())
        self.press("rb")                         # bumpers do nothing while holding
        self.assertIsNotNone(pe.grab)
        self.press("down")
        self.press("x")
        self.assertIsNone(pe.grab)
        self.assertIsNone(w.host_rows["h0"].editor._drag)
        moved = list(self.pos("h0", k))
        self.assertNotEqual(start, moved)
        w.edit_undo(); pump(5)
        self.assertEqual(start, list(self.pos("h0", k)))
        w.edit_redo(); pump(5)
        self.assertEqual(moved, list(self.pos("h0", k)))

    def test_tile_grab_cancel(self):
        w, pe = self.w, self.pe
        self.press("left"); self.press("a")
        k = pe.key
        before = [list(a["pos"]) for a in self.host("h0")["aktionen"]]
        self.press("x"); self.press("down"); self.press("right")
        self.press("b")
        self.assertIsNone(pe.grab)
        self.assertIsNone(w.host_rows["h0"].editor._drag)
        self.assertEqual(before, [list(a["pos"]) for a in self.host("h0")["aktionen"]])
        self.assertEqual(pe.level, 2)
        self.assertEqual(pe.key, k)
        self.assertTrue(w._edit_mode)

    def test_card_grab_move_release_and_undo(self):
        w, pe = self.w, self.pe
        self.press("left")
        self.press("x")
        self.assertIsNotNone(pe.grab)
        self.assertTrue(w.card_drag.active)
        self.assertEqual(w.edit_hints.where, self.t("pad_where_grab_card", host="Gaming-PC"))
        self.press("down")
        self.press("x")
        pump(30)
        self.assertFalse(w.card_drag.active)
        self.assertEqual(self.order(), ["h1", "h0", "h2"])
        self.assertEqual(self.ed_focus(), "h0")
        w.edit_undo(); pump(10)
        self.assertEqual(self.order(), ["h0", "h1", "h2"])

    def test_card_grab_to_the_end_and_back(self):
        """Moving the gap down to the end and back up (one gap in the layout, never a
        QBoxLayout index warning)."""
        w = self.w
        self.press("left")
        self.press("x"); self.press("down"); self.press("down")
        lay = w.host_widget.layout()
        gaps = [i for i in range(lay.count()) if lay.itemAt(i).spacerItem() is not None
                and lay.itemAt(i).spacerItem().sizeHint().height() == U.app._DropSlot.GAP_V]
        self.assertEqual(len(gaps), 1)
        self.press("up"); self.press("x"); pump(30)
        self.assertEqual(self.order(), ["h1", "h0", "h2"])
        self.press("x"); self.press("down"); self.press("x"); pump(30)
        self.assertEqual(self.order(), ["h1", "h2", "h0"])

    def test_card_grab_cancel(self):
        w, pe = self.w, self.pe
        self.press("left")
        self.press("x"); self.press("down"); self.press("down")
        self.press("b")
        pump(30)
        self.assertFalse(w.card_drag.active)
        self.assertIsNone(pe.grab)
        self.assertEqual(self.order(), ["h0", "h1", "h2"])
        self.assertTrue(w._edit_mode)

    def test_mouse_ends_a_grab(self):
        w, pe = self.w, self.pe
        self.press("left"); self.press("a")
        before = [list(a["pos"]) for a in self.host("h0")["aktionen"]]
        self.press("x"); self.press("down")
        w.input_mode.set_pad_active(False); pump(5)
        self.assertIsNone(pe.grab)
        self.assertIsNone(w.host_rows["h0"].editor._drag)
        self.assertEqual(before, [list(a["pos"]) for a in self.host("h0")["aktionen"]])

    # --- hints ----------------------------------------------------------------
    def test_level_hints(self):
        w = self.w
        self.press("left")
        self.assertEqual(self.hint_texts(), [self.t("pad_edit_tiles"), self.t("pad_grab_card"),
                                             self.t("pad_done"), self.t("pad_rows")])
        self.assertEqual([x[0] for x in w.edit_hints.items], ["a", "x", "b", "lbrb"])
        self.press("a")
        self.assertEqual(self.hint_texts(), [self.t("pad_select"), self.t("pad_grab"),
                                             self.t("pad_back"), self.t("pad_rows")])

    def test_hints_only_in_pad_mode(self):
        w = self.w
        self.assertFalse(w.edit_hints.isVisible())           # entered with the mouse
        self.press("left")
        self.assertTrue(w.edit_hints.isVisible())
        win = w.windowHandle()
        im = w.input_mode
        # mouse jitter (< 4 px): the hints stay
        im._last_pos = QCursor.pos() - QPoint(2, 1)
        QTest.mouseMove(win, QPoint(100, 100)); pump(3)
        self.assertTrue(im.pad_active)
        self.assertTrue(w.edit_hints.isVisible())
        # a real move (>= 4 px): hints gone at once
        im._last_pos = QCursor.pos() - QPoint(30, 0)
        QTest.mouseMove(win, QPoint(120, 100)); pump(3)
        self.assertFalse(im.pad_active)
        self.assertFalse(w.edit_hints.isVisible())
        # a real mouse click: hints gone at once
        self.press("left")
        self.assertTrue(w.edit_hints.isVisible())
        QTest.mouseClick(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(5, 5)); pump(3)
        self.assertFalse(im.pad_active)
        self.assertFalse(w.edit_hints.isVisible())
        self.assertTrue(w.edit_info.isVisible())

    def test_keyboard_ends_pad_mode(self):
        w = self.w
        im = w.input_mode
        self.press("left")
        self.assertTrue(im.pad_active)
        QTest.keyClick(w.windowHandle(), Qt.Key.Key_Shift); pump(3)
        QTest.qWait(220)
        pump(3)
        self.assertFalse(im.pad_active)
        self.assertFalse(w.edit_hints.isVisible())

    def test_steam_key_followed_by_pad_keeps_pad_mode(self):
        """Steam Input sends a key and the native button: not a keyboard user."""
        w = self.w
        im = w.input_mode
        self.press("left")
        QTest.keyClick(w.windowHandle(), Qt.Key.Key_Down)
        self.press("down")
        QTest.qWait(220); pump(3)
        self.assertTrue(im.pad_active)
        self.assertTrue(w.edit_hints.isVisible())

    def test_no_hints_outside_edit_mode(self):
        w = self.w
        w.exit_edit_mode(); pump(5)
        self.press("left")
        self.assertFalse(w.edit_hints.isVisible())
        self.assertFalse(w.edit_bar.isVisible())

    def test_ps_glyphs(self):
        w = self.w
        self.pad.q.append(("added", 8, "DualSense Wireless Controller", "ps")); self.br.tick(); pump(3)
        self.press("left", dev=8)
        self.assertEqual(self.br.style(), "ps")
        names = [g.accessibleName() for g in w.edit_hints.findChildren(U.app.Glyph)]
        self.assertIn("✕", names)
        self.assertIn("L1/R1", names)
        self.press("left", dev=7)                # the Deck again: Xbox letters
        self.assertEqual(self.br.style(), "xbox")
        names = [g.accessibleName() for g in w.edit_hints.findChildren(U.app.Glyph)
                 if g.isVisibleTo(w.edit_hints)]
        self.assertIn("A", names)
        self.assertNotIn("✕", names)

    def test_old_three_field_added_event(self):
        self.pad.q.append(("added", 9, "PS4 Controller")); self.br.tick(); pump(3)
        self.assertEqual(self.br.styles[9], "ps")

    def test_x_outside_edit_mode_does_nothing(self):
        w = self.w
        w.exit_edit_mode(); pump(5)
        w.edit_btn.setFocus(); pump(3)
        self.press("x")
        self.assertFalse(w._edit_mode)
        self.assertIs(QApplication.focusWidget(), w.edit_btn)


@unittest.skipUnless(U.HAVE_QT, "PyQt6 not installed")
class CliUntestedTests(U.UiTestCase):
    def test_update_toast_has_the_note_and_the_release_link(self):
        w = self.w
        ut = w.findChild(U.app.UpdateToast) if hasattr(U.app, "UpdateToast") else None
        self.assertIsNotNone(ut)
        ut.show_update("", False, cli="nightly-2026-10-30")
        self.assertIn(U.app.t("cli_untested_update"), ut.detail.text())
        self.assertEqual(ut.dl_btn.text(), U.app.t("cli_release_page"))
        ut.show_update("1.5", False)
        self.assertNotIn(U.app.t("cli_untested_update"), ut.detail.text())

    def test_options_shows_the_note_for_an_own_cli(self):
        import tempfile
        dlg = U.app.OptionsDialog(self.w.cfg["settings"], self.w)
        self.assertFalse(dlg.cli_untested.isVisibleTo(dlg))
        f = tempfile.NamedTemporaryFile(delete=False)
        f.close()
        dlg._custom_cli = f.name
        dlg._render_cli_block()
        self.assertTrue(dlg.cli_untested.isVisibleTo(dlg))
        self.assertIn(U.app.t("cli_untested"), dlg.cli_untested.text())
        dlg._use_bundled_cli()
        self.assertFalse(dlg.cli_untested.isVisibleTo(dlg))
        dlg.deleteLater(); os.unlink(f.name)
