"""Controller support for the edit mode of the main window (1.4).

Two levels, like the mouse: level 1 = the host cards, level 2 = the tiles inside one
card.  A enters a card / selects a tile (a second A on the selected tile opens its
menu), X grabs and releases the card or tile at the current level (the others make
room exactly as with the mouse), B cancels a grab, closes the menu or goes back one
level (B on the cards leaves the edit mode).  LB / RB keep jumping between the rows.

The edit bar shows what the buttons do right now (glyphs of the controller used last:
A/B/X for Xbox, Switch, Steam Deck and unknown pads, cross/circle/square for
PlayStation), only while the app is being used with a controller.  Pure UI: nothing
here touches pairing, wake or shutdown."""
from PyQt6.QtCore import QEvent, QObject, QPoint, QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QKeyEvent, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QApplication, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QSizePolicy, QWidget

import tiles
from i18n import t
from theme import accent_color, ui_colors

RING_W = 3                  # px, focus ring of the current card / tile
DIM_OPACITY = 0.45          # the inactive level (other cards while editing tiles)
DIRS = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1)}

_XBOX = {"a": ("A", "#3fae49", "#ffffff"), "b": ("B", "#e0403a", "#ffffff"),
         "x": ("X", "#2f7de1", "#ffffff"), "y": ("Y", "#f2b705", "#1a1a1a")}
_PS = {"a": "#6f9fe8", "b": "#e0605a", "x": "#d987c4", "y": "#3fbf9f"}     # cross circle square triangle
_PS_SYMBOL = {"a": "✕", "b": "○", "x": "□", "y": "△"}
_BUMPERS = {"xbox": ("LB", "RB"), "ps": ("L1", "R1")}


def glyph_text(kind: str, style: str) -> str:
    """Plain text of a button glyph (tests, accessible names)."""
    if kind in ("lb", "rb", "lbrb"):
        lb, rb = _BUMPERS.get(style, _BUMPERS["xbox"])
        return {"lb": lb, "rb": rb, "lbrb": f"{lb}/{rb}"}[kind]
    if kind == "dpad":
        return "✚"
    if style == "ps":
        return _PS_SYMBOL[kind]
    return _XBOX[kind][0]


class Glyph(QWidget):
    """One controller button, painted (no font glyphs, same look everywhere): round
    coloured face buttons, the D-pad cross, LB/RB (L1/R1) pills."""
    SIZE = 24

    def __init__(self, kind: str, style: str = "xbox", light: bool = False, parent=None):
        super().__init__(parent)
        self.kind, self.style, self.light = kind, style, light
        self.setAccessibleName(glyph_text(kind, style))
        if kind == "lbrb":
            w = 2 * self._pill_w() + 4
        elif kind in ("lb", "rb"):
            w = self._pill_w()
        else:
            w = self.SIZE
        self.setFixedSize(w, self.SIZE)

    def _font(self, px):
        f = QFont(self.font())
        f.setPixelSize(px)
        f.setBold(True)
        return f

    def _pill_w(self):
        return max(QFontMetrics(self._font(11)).horizontalAdvance("RB") + 14, 30)

    def _grey(self):
        return (QColor("#d4d4d4"), QColor("#8a8a8a"), QColor("#2b2b2b")) if self.light else \
               (QColor("#3a3a3a"), QColor("#8a8a8a"), QColor("#e8e8e8"))

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self.SIZE
        r = QRectF(1, 1, s - 2, s - 2)
        if self.kind == "dpad":
            fill, edge, fg = self._grey()
            p.setPen(QPen(edge, 1.5))
            p.setBrush(fill)
            p.drawEllipse(r)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fg)
            c = r.center()
            p.drawRect(QRectF(c.x() - 2.5, c.y() - 8, 5, 16))
            p.drawRect(QRectF(c.x() - 8, c.y() - 2.5, 16, 5))
        elif self.kind in ("lb", "rb", "lbrb"):
            fill, edge, fg = self._grey()
            names = _BUMPERS.get(self.style, _BUMPERS["xbox"])
            parts = [names[0], names[1]] if self.kind == "lbrb" else [names[0 if self.kind == "lb" else 1]]
            pw = self._pill_w()
            p.setFont(self._font(11))
            for i, txt in enumerate(parts):
                pr = QRectF(i * (pw + 4) + 0.75, 3.75, pw - 1.5, s - 7.5)
                p.setPen(QPen(edge, 1.5))
                p.setBrush(fill)
                p.drawRoundedRect(pr, 8, 8)
                p.setPen(fg)
                p.drawText(pr, int(Qt.AlignmentFlag.AlignCenter), txt)
        elif self.style == "ps":
            col = QColor(_PS[self.kind])
            p.setPen(QPen(col, 2))
            p.setBrush(QColor("#e9e9e9") if self.light else QColor("#2b2b2b"))
            p.drawEllipse(r.adjusted(0.5, 0.5, -0.5, -0.5))
            c = r.center()
            pen = QPen(col, 2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            if self.kind == "a":
                p.drawLine(QPointF(c.x() - 5, c.y() - 5), QPointF(c.x() + 5, c.y() + 5))
                p.drawLine(QPointF(c.x() - 5, c.y() + 5), QPointF(c.x() + 5, c.y() - 5))
            elif self.kind == "b":
                p.drawEllipse(c, 5.5, 5.5)
            elif self.kind == "x":
                p.drawRect(QRectF(c.x() - 5, c.y() - 5, 10, 10))
            else:
                p.drawPolygon(QPolygonF([QPointF(c.x(), c.y() - 6), QPointF(c.x() + 6, c.y() + 4.5),
                                         QPointF(c.x() - 6, c.y() + 4.5)]))
        else:
            txt, bg, fg = _XBOX[self.kind]
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(bg))
            p.drawEllipse(r)
            p.setPen(QColor(fg))
            p.setFont(self._font(14))
            p.drawText(r, int(Qt.AlignmentFlag.AlignCenter), txt)
        p.end()


class HintBar(QWidget):
    """Edit bar, controller mode: "where am I" label + one glyph/label pair per button
    (greyed when the button does nothing right now), wraps on narrow windows."""
    def __init__(self, flow_cls, parent=None):
        super().__init__(parent)
        self.setObjectName("padHints")
        self.lay = flow_cls(self, 20)
        self.lay.setContentsMargins(0, 0, 0, 0)
        sp = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)
        self._sig = None
        self.items = []             # (glyph kind, text, enabled) of what is shown (tests)
        self.where = ""

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self.lay.heightForWidth(w)

    def set_state(self, where: str, items, style: str, light: bool, msg: str = "", warn: bool = False):
        sig = (where, tuple(items), style, light, msg, warn)
        if sig == self._sig:
            return              # nothing changed: no rebuild (no flicker)
        self._sig = sig
        self.where, self.items = where, list(items)
        while self.lay.count():
            it = self.lay.takeAt(0)
            if it.widget() is not None:
                it.widget().hide()
                it.widget().deleteLater()
        c = ui_colors(light)
        if where:
            lab = QLabel(where)
            lab.setObjectName("padWhere")
            lab.setStyleSheet(f"color: {c['name']}; font-size: 14px; font-weight: bold; background: transparent;")
            lab.setMinimumHeight(24)
            self.lay.addWidget(lab)
        for kind, text, enabled in items:
            box = QWidget()
            box.setObjectName("padHint")
            h = QHBoxLayout(box)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(8)
            h.addWidget(Glyph(kind, style, light))
            lab = QLabel(text)
            lab.setStyleSheet(f"color: {c['name'] if enabled else c['sub']}; font-size: 14px; background: transparent;")
            h.addWidget(lab)
            if not enabled:
                eff = QGraphicsOpacityEffect(box)
                eff.setOpacity(DIM_OPACITY)
                box.setGraphicsEffect(eff)
            box.setEnabled(enabled)
            self.lay.addWidget(box)
        if msg:
            lab = QLabel(msg)
            lab.setObjectName("padMsg")
            lab.setWordWrap(True)
            col = "#e0a030" if warn else c["sub"]
            lab.setStyleSheet(f"color: {col}; font-size: 13px; background: transparent;")
            self.lay.addWidget(lab)
        self.updateGeometry()

    def texts(self) -> list:
        return [x[1] for x in self.items]


class PadRing(QWidget):
    """3 px accent ring around the current card (level 1) or tile (level 2), painted
    on top of the scroll viewport (outside the tile, so it never hides its content)."""
    def __init__(self, viewport, pe):
        super().__init__(viewport)
        self.pe = pe
        self.setObjectName("padRing")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.light = False
        viewport.installEventFilter(self)
        self.hide()

    def eventFilter(self, obj, ev):
        if obj is self.parent() and ev.type() == QEvent.Type.Resize:
            self.setGeometry(self.parent().rect())
        return False

    def paintEvent(self, ev):
        rr = self.pe.ring_rect()
        if rr is None:
            return
        rect, radius = rr
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(accent_color(self.light), RING_W))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, radius, radius)
        p.end()


class PadEdit(QObject):
    """State machine of the controller edit mode; MainWindow forwards controller
    buttons (and the keys Steam Input sends for them) to handle()."""
    def __init__(self, win, label_fn):
        super().__init__(win)
        self.win = win
        self.label_fn = label_fn            # tile -> visible name
        self.level = 1                      # 1 = cards, 2 = tiles of self.hid
        self.hid = None
        self.key = None                     # focused tile (level 2)
        self.grab = None                    # {"kind": "tile"|"card", ...} while X holds something
        self.ring = PadRing(win.scroll.viewport(), self)
        win.scroll.verticalScrollBar().valueChanged.connect(self.update_ring)
        win.host_widget.installEventFilter(self)

    # --- state ------------------------------------------------------------
    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.Type.Resize, QEvent.Type.Move, QEvent.Type.LayoutRequest):
            self.update_ring()
        return False

    def active(self) -> bool:
        """Controller edit mode is on: edit mode + the app is used with a controller."""
        w = self.win
        return bool(w._edit_mode and w._pad_nav())

    def reset(self):
        self.level, self.hid, self.key, self.grab = 1, None, None, None
        self.sync_visuals()

    def _rows(self):
        return [(h, r) for h, r in self.win.host_rows.items()
                if r.editor is not None and not r.isHidden()]

    def _row(self, hid=None):
        return self.win.host_rows.get(hid or self.hid)

    def focus_card(self):
        """Host id of the card whose tile grid has the keyboard focus (else None)."""
        fw = QApplication.focusWidget()
        for h, r in self.win.host_rows.items():
            if r.editor is not None and fw is r.editor:
                return h
        return None

    def menu_open(self) -> bool:
        m = getattr(self.win, "_menu", None)
        try:
            return m is not None and m.isVisible()
        except RuntimeError:            # deleted QMenu
            return False

    def current_card(self):
        h = self.focus_card()
        if h is None and self.menu_open() and self.hid in self.win.host_rows:
            h = self.hid
        return h

    def on_editor_focus(self, hid):
        if hid != self.hid:
            self.level, self.hid, self.key = 1, hid, None

    def _alive(self) -> bool:
        g = self.grab
        if g is None:
            return False
        if g["kind"] == "card":
            return self.win.card_drag.active
        r = self._row(g["hid"])
        return r is not None and r.editor is not None and r.editor._drag is not None

    def on_drag_end(self):
        if self.grab is not None and not self._alive():
            self.grab = None

    def cancel_grab(self):
        """Pad mode ended (mouse / touch / keyboard): put a held card or tile back."""
        g, self.grab = self.grab, None
        if g is None:
            return
        if g["kind"] == "card":
            if self.win.card_drag.active:
                self.win.card_drag.cancel()
        else:
            r = self._row(g["hid"])
            if r is not None and r.editor is not None and r.editor._drag is not None:
                r.editor.cancel_drag()

    def _fix_key(self):
        r = self._row()
        keys = r.editor.order() if r is not None and r.editor is not None else []
        if self.key not in keys:
            sel = self.win._edit_key_of(self.hid)
            self.key = sel if sel in keys else (keys[0] if keys else None)
        return keys

    # --- input --------------------------------------------------------------
    def handle(self, name: str) -> bool:
        """One controller button (a, b, x, up, down, left, right, lb, rb); True = used."""
        w = self.win
        if not w._edit_mode:
            return False
        if self.grab is not None and not self._alive():
            self.grab = None
        if self.grab is not None:
            if self.grab["kind"] == "tile":
                self._tile_grab_input(name)
            else:
                self._card_grab_input(name)
            w._sync_edit_bar()
            return True
        hid = self.focus_card()
        if hid is None:
            return False
        self.on_editor_focus(hid)
        if name in ("lb", "rb"):
            return False                    # rows of the window: MainWindow.nav_jump()
        used = self._level1(name) if self.level == 1 else self._level2(name)
        w._sync_edit_bar()
        return used

    def _level1(self, name):
        w = self.win
        if name in ("up", "down"):
            self._card_step(-1 if name == "up" else 1)
        elif name == "a":
            if self._fix_key_reset():
                self.level = 2
                self._show_key()
        elif name == "x":
            self._grab_card()
        elif name == "b":
            w.exit_edit_mode()
        return True                         # left/right: nothing on the card level

    def _fix_key_reset(self):
        self.key = None
        return bool(self._fix_key())

    def _level2(self, name):
        w = self.win
        keys = self._fix_key()
        if not keys:
            self.level = 1
            return True
        sel = w._edit_key_of(self.hid)
        if name in DIRS:
            nk = self._neighbour(name)
            if nk is not None and nk != self.key:
                if sel is not None:
                    w.edit_select(self.hid, None)       # moving on drops the selection
                self.key = nk
                self._show_key()
        elif name == "a":
            if sel == self.key:
                self._open_menu()
            else:
                w.edit_select(self.hid, self.key)
        elif name == "x":
            self._grab_tile()
        elif name == "b":
            if sel is not None:
                w.edit_select(self.hid, None)
            self.level = 1
            w._focus_editor(self.hid)
        return True

    def _card_step(self, d):
        w = self.win
        ids = [h for h, _ in self._rows()]
        if self.hid not in ids:
            return
        j = ids.index(self.hid) + d
        if 0 <= j < len(ids):
            w._focus_editor(ids[j])
            self.on_editor_focus(ids[j])
            return
        # past the first / last card: the next row of the window (edit bar, log ...)
        grid = w._nav_grid()
        row = self._row()
        mine = {id(x) for r in row.nav_rows for x in r}
        idx = [i for i, r in enumerate(grid) if any(id(x) in mine for x in r)]
        if not idx:
            return
        i = (min(idx) - 1) if d < 0 else (max(idx) + 1)
        while 0 <= i < len(grid) and any(id(x) in mine for x in grid[i]):
            i += d
        if not 0 <= i < len(grid) or not grid[i]:
            return
        cx = row.mapToGlobal(row.rect().center()).x()
        tgt = min(grid[i], key=lambda b: abs(b.mapToGlobal(b.rect().center()).x() - cx))
        tgt.setFocus(Qt.FocusReason.TabFocusReason)
        if w.scroll.isAncestorOf(tgt):
            w.scroll.ensureWidgetVisible(tgt)

    def _rects(self):
        ed = self._row().editor
        return {tiles.key(a): ed.tile_rect(a) for a in ed.tiles if tiles.is_active(a)}

    def _neighbour(self, name):
        rects = self._rects()
        cur = rects.get(self.key)
        if cur is None:
            return None
        horiz = name in ("left", "right")
        c0 = cur.center()
        best, best_score = None, None
        for k, r in rects.items():
            if k == self.key:
                continue
            c = r.center()
            dx, dy = c.x() - c0.x(), c.y() - c0.y()
            prim = {"left": -dx, "right": dx, "up": -dy, "down": dy}[name]
            if prim <= 1:
                continue
            if horiz:
                overlap = min(r.bottom(), cur.bottom()) - max(r.top(), cur.top()) > 1
            else:
                overlap = min(r.right(), cur.right()) - max(r.left(), cur.left()) > 1
            score = (0 if overlap else 1, prim + 2 * (abs(dy) if horiz else abs(dx)))
            if best_score is None or score < best_score:
                best, best_score = k, score
        return best

    def _show_key(self):
        r = self._row()
        if r is None or r.editor is None or self.key is None:
            return
        ed = r.editor
        i = tiles.find(ed.tiles, self.key)
        if i is None:
            return
        rc = ed.tile_rect(ed.tiles[i])
        c = ed.mapTo(self.win.host_widget, rc.center().toPoint())
        self.win.scroll.ensureVisible(c.x(), c.y(), 0, int(rc.height() / 2) + 12)

    def _open_menu(self):
        w = self.win
        ed = self._row().editor
        w.edit_menu(self.hid, self.key, ed.mapToGlobal(ed.tile_center(self.key)))
        m = getattr(w, "_menu", None)
        if m is not None:
            # first entry highlighted like with the keyboard (setActiveAction() would open
            # the size submenu at once)
            QApplication.postEvent(m, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down,
                                                Qt.KeyboardModifier.NoModifier))
            m.aboutToHide.connect(lambda: QTimer.singleShot(0, self._after_menu))

    def _after_menu(self):
        w = self.win
        if w._edit_mode and self.hid in w.host_rows:
            if self.focus_card() is None and QApplication.activePopupWidget() is None:
                w._focus_editor(self.hid)
        w._sync_edit_bar()

    # --- grab (X) -------------------------------------------------------------
    def _grab_tile(self):
        ed = self._row().editor
        i = tiles.find(ed.tiles, self.key)
        if i is None or ed._drag is not None:
            return
        a = ed.tiles[i]
        rc = ed.tile_rect(a)
        c = rc.center()
        self.grab = {"kind": "tile", "hid": self.hid, "key": self.key,
                     "pos": list(a["pos"]), "size": a["groesse"]}
        ed._press = (self.key, QPointF(c), QPointF(c - rc.topLeft()))
        ed._start_drag()
        ed._update_drag()

    def _tile_grab_input(self, name):
        g = self.grab
        ed = self._row(g["hid"]).editor
        if name in DIRS:
            dc, dr = DIRS[name]
            w_, h_ = tiles.SIZES[g["size"]]
            col = max(0, min(tiles.COLS - w_, g["pos"][0] + dc))
            row = max(0, min(ed.rows() - h_, g["pos"][1] + dr))
            if [col, row] != g["pos"]:
                g["pos"] = [col, row]
                d = ed._drag
                d["pt"] = ed.cell_rect(col, row).topLeft() + d["offset"]
                ed._update_drag()
                rc = ed.cell_rect(col, row, w_, h_)
                c = ed.mapTo(self.win.host_widget, rc.center().toPoint())
                self.win.scroll.ensureVisible(c.x(), c.y(), 0, int(rc.height() / 2) + 12)
        elif name == "x":
            self.grab = None
            ed._finish_drag()
        elif name == "b":
            self.grab = None
            ed.cancel_drag()

    def _grab_card(self):
        w = self.win
        rows = self._rows()
        if len(rows) < 2 or w.card_drag.active:
            return
        row = self._row()
        g = row.mapToGlobal(row.rect().center())
        self.grab = {"kind": "card", "hid": self.hid,
                     "idx": [h for h, _ in rows].index(self.hid), "g": g}
        w.card_drag.begin(row, g)
        if not w.card_drag.active:
            self.grab = None

    def _card_grab_input(self, name):
        w = self.win
        cd = w.card_drag
        g = self.grab
        if name in ("up", "down"):
            src = cd.drag["src"]
            others = cd._others(src)
            n = len(others)
            idx = max(0, min(n, g["idx"] + (-1 if name == "up" else 1)))
            if idx == g["idx"]:
                return
            g["idx"] = idx
            box = cd.container()
            cd.move_to(self._card_point(idx))         # opens the gap (the others make room)
            g["g"] = self._card_point(idx)
            cd.move_to(g["g"])
            slot = cd._slot_rect(cd._others(src), idx)
            ghost = cd.drag.get("ghost")
            top, h = slot.top(), src.height()
            if ghost is not None:                     # the card sits in its new place
                h = ghost.height()
                if idx >= n:                          # last place: no room below the list
                    top = max(0, slot.bottom() - h)
                ghost.move(ghost.x(), top)
            if box is w.host_widget:
                w.scroll.ensureVisible(cd._rect(src).center().x(), top + h // 2, 0, h // 2 + 12)
        elif name == "x":
            self.grab = None
            cd.drop(self._card_point(g["idx"]))     # from the geometry now (the gap may have moved)
            QTimer.singleShot(0, lambda h=g["hid"]: self.win._focus_editor(h))
        elif name == "b":
            self.grab = None
            cd.cancel()
            QTimer.singleShot(0, lambda h=g["hid"]: self.win._focus_editor(h))

    def _card_point(self, idx):
        """A global point _ReorderDrag maps to insert index idx: it counts the other cards
        whose centre lies above the point, so take the middle between two centres."""
        cd = self.win.card_drag
        src = cd.drag["src"]
        others = cd._others(src)
        cy = [cd._rect(o).center().y() for o in others]
        if not cy:
            y = cd._rect(src).center().y()
        elif idx <= 0:
            y = cy[0] - 1
        elif idx >= len(cy):
            y = cy[-1] + 1
        else:
            y = (cy[idx - 1] + cy[idx]) // 2 + 1
        return cd.container().mapToGlobal(QPoint(cd._rect(src).center().x(), y))

    # --- what the edit bar shows -------------------------------------------------
    def _host_name(self, hid):
        h = self.win._host(hid) or {}
        return h.get("name") or h.get("ip") or "?"

    def _tile_name(self, hid, k):
        r = self._row(hid)
        if r is None or r.editor is None:
            return k or ""
        i = tiles.find(r.editor.tiles, k)
        return self.label_fn(r.editor.tiles[i]) if i is not None else (k or "")

    def hints(self):
        """(where, [(glyph kind, text, enabled), ...]) for the current state."""
        jump = ("lbrb", t("pad_rows"), True)
        g = self.grab
        if g is not None:
            if g["kind"] == "tile":
                where = t("pad_where_grab_tile", host=self._host_name(g["hid"]),
                          tile=self._tile_name(g["hid"], g["key"]))
            else:
                where = t("pad_where_grab_card", host=self._host_name(g["hid"]))
            return where, [("dpad", t("pad_move"), True), ("x", t("pad_release"), True),
                           ("b", t("pad_cancel"), True)]
        if self.menu_open():
            return (t("pad_where_menu", host=self._host_name(self.hid), tile=self._tile_name(self.hid, self.key)),
                    [("dpad", t("pad_choose"), True), ("a", t("pad_apply"), True), ("b", t("pad_close"), True)])
        hid = self.focus_card()
        if hid is not None and (hid != self.hid or self.level == 1):
            r = self._row(hid)
            has_tiles = bool(r.editor.order()) if r is not None and r.editor is not None else False
            return t("pad_where_cards"), [("a", t("pad_edit_tiles"), has_tiles),
                                          ("x", t("pad_grab_card"), len(self._rows()) > 1),
                                          ("b", t("pad_done"), True), jump]
        if hid is not None:
            sel = self.win._edit_key_of(hid)
            return (t("pad_where_tiles", host=self._host_name(hid)),
                    [("a", t("pad_menu") if sel and sel == self.key else t("pad_select"), True),
                     ("x", t("pad_grab"), True), ("b", t("pad_back"), True), jump])
        return "", [("dpad", t("pad_choose"), True), ("a", t("pad_press"), True),
                    ("b", t("pad_done"), True), jump]

    # --- visuals ---------------------------------------------------------------
    def ring_rect(self):
        if not self.active() or self.grab is not None:
            return None
        hid = self.current_card()
        r = self._row(hid)
        if r is None or r.editor is None:
            return None
        vp = self.ring.parentWidget()
        if self.level == 2 and hid == self.hid and self.key is not None:
            ed = r.editor
            sr = ed._shown_rect(self.key)
            if sr is None:
                i = tiles.find(ed.tiles, self.key)
                if i is None:
                    return None
                sr = ed.tile_rect(ed.tiles[i])
            off = QPointF(ed.mapTo(vp, QPoint(0, 0)))
            d = RING_W / 2 + 2
            return sr.adjusted(2, 1, -2, -3).translated(off).adjusted(-d, -d, d, d), 6 + d
        tl = QPointF(r.mapTo(vp, QPoint(0, 0)))
        h = RING_W / 2
        return QRectF(tl, QPointF(tl.x() + r.width(), tl.y() + r.height())).adjusted(h, h, -h, -h), 8

    def update_ring(self, *_):
        if self.ring.isVisible():
            self.ring.update()

    def sync_visuals(self, light: bool = None):
        """Focus ring + dimmed inactive level (other cards while editing tiles)."""
        w = self.win
        on = self.active()
        if on and self.grab is not None and not self._alive():
            self.grab = None
        cur = self.current_card() if on else None
        dim = on and self.grab is None and self.level == 2 and cur is not None and cur == self.hid
        for h, r in w.host_rows.items():
            want = dim and h != self.hid
            mine = bool(r.property("padDim"))
            if want and not mine:
                eff = QGraphicsOpacityEffect(r)
                eff.setOpacity(DIM_OPACITY)
                r.setGraphicsEffect(eff)
                r.setProperty("padDim", True)
            elif mine and not want:
                if isinstance(r.graphicsEffect(), QGraphicsOpacityEffect) and \
                        r.graphicsEffect().opacity() == DIM_OPACITY:
                    r.setGraphicsEffect(None)
                r.setProperty("padDim", False)
        if light is not None:
            self.ring.light = light
        show = self.ring_rect() is not None
        if show:
            self.ring.setGeometry(self.ring.parentWidget().rect())
            self.ring.raise_()
        self.ring.setVisible(show)
        self.ring.update()
