#!/usr/bin/env python3
"""
BuddyRemote – Portable host control for MoonDeck Buddy
"""

import copy
import json
import sys
import threading
import time
import uuid
import logging
import random
from pathlib import Path

# Set process name so system monitor / KDE show "BuddyRemote" instead of python/app.py
if sys.platform.startswith("linux"):   # Windows: the exe name is BuddyRemote.exe already
    try:
        import ctypes
        import ctypes.util
        libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6")
        libc.prctl(15, b"BuddyRemote", 0, 0, 0)  # PR_SET_NAME
    except Exception:
        pass

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFrame, QScrollArea, QDialog, QFormLayout,
    QLineEdit, QMessageBox, QSystemTrayIcon, QMenu,
    QTextEdit, QComboBox, QAbstractButton, QStatusBar, QBoxLayout, QSizePolicy,
    QGridLayout,
    QLayout, QToolTip, QSplitter, QSplitterHandle, QGraphicsOpacityEffect, QStyleOption, QStyle,
    QSpacerItem
)

import tiles    # host tiles: data model, templates, grid/collision logic (no Qt)
import cacerts  # system CA store lookup for HTTPS to GitHub (no Qt, nothing bundled)
from PyQt6.QtCore import (Qt, QTimer, pyqtSignal, QObject, QEvent, QSettings, QUrl,
                          QRectF, QPointF, QPoint, QRect, QSize, QVariantAnimation, QEasingCurve,
                          QPropertyAnimation)
from PyQt6.QtGui import QIcon, QActionGroup, QColor, QPalette, QPixmap, QPainter, QPen, QShortcut, QKeySequence, QFontMetrics, QIntValidator, QDesktopServices, QFont, QInputDevice, QContextMenuEvent, QPainterPath

# split from app.py (1.3.1): version + paths, UI languages, config, backend (CLI/ping/Buddy/updates),
# OS integration (single instance, autostart), theme, input modes + gamepad, dialogs
from paths import (APP_VERSION, APP_DIR, PACKAGED, WINDOW_STATE_FILE, IS_WINDOWS, RES_DIR,
                   prepare_packaged_dir)
from i18n import resolve_language, set_language, install_qt_translations, t
from config import load_config, save_config, seed_config, ensure_client_id, setup_logging
from backend import (cli_available, run_cli, ping_icmp, check_buddy_api, parse_steam_status,
                     fetch_latest_release, release_is_update, download_cli)
from platform_util import (acquire_lock, notify_running_instance, start_instance_server, release_lock,
                           set_autostart, set_windows_app_id)
from theme import (touch_css, theme_palette, apply_app_theme, dialog_stylesheet, ui_colors,
                   accent_color, MONO_FAMILY)
from gamepad import InputModeController, GamepadBridge
from dialogs import install_dialog_nav, fit_dialog_to_screen, notify, OptionsDialog, DownloadDialog
import backend  # 1.3.1: custom CLI state, Buddy API mismatch, CLI update check

# ---------------------------------------------------------------------------
class Signals(QObject):
    host_status = pyqtSignal(str, dict)   # host_id, result of MainWindow._check_host
    update_result = pyqtSignal(dict)      # result of MainWindow.check_for_updates
    action_started = pyqtSignal(str, str, str)  # host_id, name, action
    action_done = pyqtSignal(str, str, str, bool, str)  # host_id, name, action, success, message
    cli_state = pyqtSignal(str, str, str)  # custom CLI: state ('ok'/'failed'/'missing'/'off'), path, reason

# ---------------------------------------------------------------------------


class _ResizeWatcher(QObject):
    """UI only: calls back when a widget is resized (used for responsive host cards)."""
    def __init__(self, target, callback):
        super().__init__(target)
        self._cb = callback
        target.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Resize:
            self._cb()
        return False


# Actions: power actions go through MainWindow._run_action ("host <action>"),
# Steam actions through MainWindow._run_cli_for_host.
STEAM_ACTIONS = {
    "steam_launch": ["steam", "launch"],
    "steam_close": ["steam", "close", "client"],
}
CONFIRM_ACTIONS = ("shutdown", "restart", "suspend", "hibernate", "steam_close")

class ElidedLabel(QLabel):
    """One-line label that ends in "…" instead of being cut off when it gets too narrow."""
    _elide = True

    def paintEvent(self, ev):
        r = self.contentsRect()
        txt = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, r.width())
        p = QPainter(self)
        p.setPen(self.palette().color(self.foregroundRole()))
        p.drawText(r, int(self.alignment().value), txt)
        p.end()


class FlowLayout(QLayout):
    """UI only: lays widgets out left to right and wraps into the next line when the
    width runs out (edit toolbar, hidden-tile strip); never forces a wide window."""
    def __init__(self, parent=None, spacing: int = 6):
        super().__init__(parent)
        self._items = []
        self._space = spacing

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._do(QRect(0, 0, w, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self._items:
            if not it.isEmpty():
                s = s.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return s + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do(self, rect, test):
        m = self.contentsMargins()
        r = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = r.x(), r.y(), 0
        for it in self._items:
            if it.isEmpty():
                continue
            hint = it.sizeHint()
            if x + hint.width() > r.right() + 1 and line_h > 0:
                x, y, line_h = r.x(), y + line_h + self._space, 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._space
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y() + m.bottom()


class HostRow(QFrame):
    """One host as a card (UI only; every button calls the same handlers as before):
      header: status dot, name, IP pill, "▶ Steam läuft" (only while it runs) .. ⚙
      body:   the host's tiles (host["aktionen"], see tiles.py) in a grid with
              tiles.COLS equal columns; sizes klein 1x1, mittel 2x1, breit 4x1, gross 2x2.
    Calm status (variant B): the dot carries the state (green ready, orange PC on but
    Buddy silent, grey off); dot and name have a tooltip with ping, Buddy port and the
    last check. Only in the problem state a quiet line "Buddy antwortet nicht · ⓘ Details"
    appears. The status tile (online_status) is optional (hidden by default).
    Action tiles may appear more than once (duplicates, tiles.duplicate) and call
    MainWindow.do_action exactly like the 1.2 buttons did.
    Visible buttons that make no sense for the last status check are disabled (not
    focusable, tooltip says why) – variant A. Hidden tiles are not created at all.
    In edit mode (MainWindow.enter_edit_mode) the grid is replaced by an editable
    TilePreview drawn like the real buttons (drag and drop, keyboard), plus an
    optional strip with the hidden tiles. ⚙ opens the connection settings only.
    While an action runs, its tiles show "Wird geweckt …" etc. (pending) until the
    action returns, the status changes or PENDING_MS pass."""
    ICON = 48           # ⚙ is ICON x ICON px (touch target)
    SPACING = 6         # grid spacing between tiles
    PENDING_MS = 90000  # tile feedback ("Wird geweckt …") ends at the latest after this

    def __init__(self, host: dict, parent_app):
        super().__init__()
        self.host = host
        self.app = parent_app
        self.editing = bool(getattr(parent_app, "_edit_mode", False))
        self.setObjectName("hostCard")
        self.setProperty("current", False)
        self.setProperty("editing", self.editing)
        self.state = "unknown"      # online / offline / unknown: PC state of the last check
        self.busy = False           # an action is running for this host
        self.failed = False         # the last action failed
        self.pending = None         # action whose feedback the tiles show ("wake", …)
        self._pending_key = None    # (status_kind, steam_running) when it started
        self._pending_timer = QTimer(self)
        self._pending_timer.setSingleShot(True)
        self._pending_timer.timeout.connect(lambda: self.set_pending(None))
        self.result = None          # last status check (dict, see MainWindow._check_host)
        self.checking = False       # first check still pending ("checking…")
        self.steam_running = None   # True / False / None (unknown)
        self.nav_rows = []          # arrow-key/controller rows: header, then one per grid row
        self.nav_buttons = []       # the same buttons flat (InputModeController remembers an index)
        self.editor = None          # TilePreview in edit mode
        self.hidden_btns = []       # "+ name" buttons of the hidden tiles (edit mode)
        lp = getattr(parent_app, "long_press", None)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 10, 12)
        root.setSpacing(6)
        self._root = root

        # --- header --------------------------------------------------------------
        top = QHBoxLayout()
        top.setSpacing(8)
        self._top = top
        self.grip_lbl = None
        if self.editing:
            # ⠿ grip: the whole card is dragged by its header (MainWindow card drag)
            self.grip_lbl = _CardGrip()       # painted like the tile / toolbar grips (no font glyph)
            self.grip_lbl.setObjectName("cardGrip")
            self.grip_lbl.setToolTip(t("tip_card_grip"))
            self.grip_lbl.setFixedWidth(16)
            self.grip_lbl.setCursor(Qt.CursorShape.OpenHandCursor)
            top.addWidget(self.grip_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        self.dot = QLabel()
        self.dot.setObjectName("hostDot")
        self.dot.setFixedSize(14, 14)
        top.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignVCenter)
        self.name_lbl = QLabel(host.get("name", "Unnamed"))
        self.name_lbl.setObjectName("hostName")
        self.name_lbl.setWordWrap(True)
        nf = self.name_lbl.font()
        nf.setBold(True)
        nf.setPixelSize(16)
        self.name_lbl.setMinimumWidth(min(QFontMetrics(nf).horizontalAdvance(self.name_lbl.text()) + 6, 220))
        self.ip_lbl = QLabel(host.get("ip", ""))
        self.ip_lbl.setObjectName("ipPill")
        if not self._show_ip():            # hide only: setVisible(True) before parenting = own window
            self.ip_lbl.hide()
        if self.editing:                    # edit mode: IP and status step back (0.4)
            for w in (self.ip_lbl, self.dot):
                eff = QGraphicsOpacityEffect(w)
                eff.setOpacity(0.4)
                w.setGraphicsEffect(eff)
        top.addWidget(self.name_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(self.ip_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        self.steam_lbl = QLabel()
        self.steam_lbl.setObjectName("hostSteam")
        self.steam_lbl.hide()
        top.addSpacing(4)
        top.addWidget(self.steam_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        self.time_lbl = ElidedLabel()
        self.time_lbl.setObjectName("hostSub")
        # never widens the card; ends in "…" in narrow windows / long languages
        self.time_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        top.addWidget(self.time_lbl, 1, Qt.AlignmentFlag.AlignVCenter)
        # the only card button: connection settings (cards are reordered by drag and
        # drop in edit mode, Ctrl+Up/Down)
        b = self.conn_btn = QPushButton("⚙")
        b.setProperty("touchRole", "icon")
        b.setProperty("mgmt", True)
        b.setFixedSize(self.ICON, self.ICON)
        b.setToolTip(t("tip_conn"))
        b.setProperty("navKey", "tip_conn")
        b.clicked.connect(lambda: self.app.edit_host(self.host))
        b.installEventFilter(self.app)
        top.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(top)
        indent = self.dot.width() + top.spacing()
        if self.grip_lbl is not None:
            indent += self.grip_lbl.width() + top.spacing()

        # problem line (only "PC on, Buddy silent"): quiet, never blinks
        self.hint_row = QWidget()
        self.hint_row.setObjectName("hintRow")
        hl = QHBoxLayout(self.hint_row)
        hl.setContentsMargins(indent, 0, 0, 0)
        hl.setSpacing(4)
        self.hint_lbl = QLabel(t("hint_problem") + " ·")
        self.hint_lbl.setObjectName("hostWarn")
        self.details_btn = QPushButton(t("hint_details"))
        self.details_btn.setObjectName("hintLink")
        self.details_btn.setProperty("hintLink", True)
        self.details_btn.setFlat(True)
        self.details_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.details_btn.setProperty("navKey", "hint_details")
        self.details_btn.clicked.connect(self.show_details)
        self.details_btn.installEventFilter(self.app)
        hl.addWidget(self.hint_lbl)
        hl.addWidget(self.details_btn)
        hl.addStretch(1)
        self.hint_row.hide()
        self.details_btn.hide()
        root.addWidget(self.hint_row)
        self.error_lbl = QLabel()
        self.error_lbl.setObjectName("hostError")
        self.error_lbl.setWordWrap(True)
        self.error_lbl.setContentsMargins(indent, 0, 0, 0)
        self.error_lbl.hide()
        root.addWidget(self.error_lbl)

        # --- tile grid -------------------------------------------------------------
        # The chip always exists (also when its tile is hidden) so _render can stay
        # simple; when hidden it just has no parent and is never shown.
        self.chip_online = QLabel()
        self.chip_online.setObjectName("chip")
        self.chip_online.setTextFormat(Qt.TextFormat.RichText)
        self.chip_online.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.steam_btns = []        # the Steam toggle (and its duplicates)
        self.action_buttons = []    # (action, button); action "wake", "shutdown", …, "steam"
        self._tiles = []            # (widget, tile dict) of the shown tiles
        self.grid = QGridLayout()
        self.grid.setContentsMargins(indent, 2, 0, 0)
        self.grid.setSpacing(self.SPACING)
        for c in range(tiles.COLS):
            self.grid.setColumnStretch(c, 1)
        by_row = {}
        self.empty_lbl = None
        if self.editing:
            self._build_editor(root, indent)
        else:
            for tile in host.get("aktionen") or tiles.template():
                if not tiles.is_active(tile):
                    continue           # hidden, or a type this version does not know
                w = self._make_tile(tile)
                if w is None:
                    continue
                (c, r), (cw, rh) = tile["pos"], tiles.SIZES[tile["groesse"]]
                self.grid.addWidget(w, r, c, rh, cw)
                self._tiles.append((w, tile))
                if isinstance(w, QPushButton):
                    by_row.setdefault(r, []).append((c, w))
                    if lp:
                        lp.watch(w)
            root.addLayout(self.grid)
            if not self._tiles:
                self.empty_lbl = QLabel(t("tiles_all_hidden"))
                self.empty_lbl.setObjectName("hostSub")
                self.empty_lbl.setWordWrap(True)
                self.empty_lbl.setContentsMargins(indent, 0, 0, 0)
                root.addWidget(self.empty_lbl)

        if self.editing:
            self.nav_rows = [[self.conn_btn], [self.details_btn], [self.editor], self.hidden_btns]
            self.nav_buttons = [self.editor] + self.hidden_btns + [self.details_btn, self.conn_btn]
        else:
            self.nav_rows = ([[self.conn_btn], [self.details_btn]]
                             + [[w for _, w in sorted(by_row[r], key=lambda x: x[0])] for r in sorted(by_row)])
            self.nav_buttons = ([b for row in self.nav_rows[2:] for b in row]
                                + [self.details_btn, self.conn_btn])
        if lp:
            for w in (self, self.dot, self.name_lbl):
                lp.watch(w)

        self._apply_row_theme()
        cached = self.app.host_state.get(host.get("id")) if hasattr(self.app, "host_state") else None
        if cached:
            self.result = cached
        else:
            self.checking = self.app.cfg.get("settings", {}).get("auto_status", True)
        self._render()
        self._lock_rows()

    # --- edit mode -----------------------------------------------------------------
    def _build_editor(self, root, indent):
        """Edit mode: the editable grid (same cell height and gap as the real buttons)
        and, when "show hidden" is on, a strip of the hidden tiles to show them again."""
        app = self.app
        hid = self.host.get("id")
        box = QWidget()
        box.setObjectName("editBox")
        self.edit_box = box
        bl = QVBoxLayout(box)
        bl.setContentsMargins(indent, 2, 0, 0)
        bl.setSpacing(6)
        sec = QLabel(t("tiles_section"))
        sec.setObjectName("editSection")
        bl.addWidget(sec)
        self.editor = TilePreview(self._light(), editable=True, card=True)
        self.editor.setProperty("navKey", "editor")
        self.editor.dropped.connect(lambda new, k, res: app.edit_drop(hid, new, k, res))
        self.editor.rejected.connect(lambda k: app.edit_message(t("tile_drop_rejected"), "warn"))
        self.editor.picked.connect(lambda k: app.edit_select(hid, k))
        self.editor.menu_requested.connect(lambda k, gp: app.edit_menu(hid, k, gp))
        self.editor.key_action.connect(lambda op: app.edit_key(hid, op))
        self.editor.focused.connect(lambda: app.edit_focus_card(hid))
        self.editor.drag_changed.connect(lambda on: app.edit_drag_state("tile" if on else None, self))
        bl.addWidget(self.editor)
        self.hidden_box = QWidget()
        self.hidden_box.setObjectName("hiddenStrip")
        self.hidden_flow = FlowLayout(self.hidden_box, spacing=6)
        self.hidden_flow.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(self.hidden_box)
        root.addWidget(box)
        self.update_editor()

    def update_editor(self):
        """Edit mode: show the current tiles of the host (after every change/undo)."""
        if self.editor is None:
            return
        app = self.app
        hid = self.host.get("id")
        ts = self.host.get("aktionen") or tiles.template()
        sel = app._edit_sel[1] if app._edit_sel and app._edit_sel[0] == hid else None
        self.editor.set_tiles(ts, sel)
        # hidden-tile strip
        while self.hidden_flow.count():
            it = self.hidden_flow.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.hidden_btns.clear()
        hidden = [x for x in ts if x.get("typ") in tiles.TYPES and not x.get("sichtbar") and not tiles.is_dup(x)]
        show = bool(app._edit_show_hidden) and bool(hidden)
        if show:
            lbl = QLabel(t("edit_hidden_label"))
            lbl.setObjectName("hostSub")
            self.hidden_flow.addWidget(lbl)
            for x in hidden:
                b = QPushButton("+ " + tile_text(x))
                b.setProperty("hiddenTile", True)
                b.setToolTip(t("tip_tile_show"))
                b.setProperty("navKey", "show_" + x["typ"])
                b.clicked.connect(lambda _, k=tiles.key(x): app.edit_show_tile(hid, k))
                b.installEventFilter(app)
                self.hidden_flow.addWidget(b)
                self.hidden_btns.append(b)
        self.hidden_box.setVisible(show)
        self.nav_rows[3:] = [self.hidden_btns]
        self.nav_buttons[:] = [self.editor] + self.hidden_btns + [self.details_btn, self.conn_btn]
        self._lock_widths()

    def _edit_col_need(self) -> int:
        """Edit mode: the column width the real buttons would need (no widgets exist)."""
        f = QFont(self.font())
        f.setPixelSize(15)
        fb = QFont(f)
        fb.setPixelSize(17)
        fb.setBold(True)
        col_min = 0
        for tile in self.host.get("aktionen") or []:
            if not tiles.is_active(tile):
                continue
            fm = QFontMetrics(fb if tile["groesse"] == "gross" else f)
            if tile["typ"] == "steam_start_stop":
                w = max(fm.horizontalAdvance(t("steam_launch")), fm.horizontalAdvance(t("steam_close")))
            else:
                w = fm.horizontalAdvance("● " + tile_label(tile["typ"]) if tiles.TYPES[tile["typ"]]["kind"] == "status"
                                         else t(tiles.TYPES[tile["typ"]]["action"]))
            need = max(w + 24, 80)
            span = tiles.SIZES[tile["groesse"]][0]
            col_min = max(col_min, -(-(need - (span - 1) * self.SPACING) // span))
        return col_min

    def show_details(self, *_):
        """ⓘ Details (and a long press on dot/name): the same text as the tooltip."""
        w = self.details_btn if self.details_btn.isVisible() else self.dot
        pos = w.mapToGlobal(QPoint(0, w.height() + 2))
        QToolTip.showText(pos, self.details_text(), w, QRect(), 10000)

    def _make_tile(self, tile: dict):
        """Widget for one tile. To add a new tile type (e.g. a web-interface link, see
        the extension point in tiles.py) add it to tiles.TYPES and build it here."""
        typ, size = tile["typ"], tile["groesse"]
        info = tiles.TYPES[typ]
        if info["kind"] == "status":
            w = QWidget()
            w.setObjectName("statusTile")
            vertical = tiles.SIZES[size][0] == 1 or size == "gross"
            box = QBoxLayout(QBoxLayout.Direction.TopToBottom if vertical else QBoxLayout.Direction.LeftToRight, w)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(4 if vertical else 6)
            ch = self.chip_online
            box.addWidget(ch, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            box.addStretch(1)
            return w
        act = info["action"]
        if act == "steam":
            btn = QPushButton(t("steam_launch"))
            btn.clicked.connect(lambda: self.app.do_action(
                self.host, "steam_close" if self.steam_running else "steam_launch"))
            self.steam_btns.append(btn)
        else:
            btn = QPushButton(t(act))
            btn.clicked.connect(lambda _, a=act: self.app.do_action(self.host, a))
        if act == "wake":
            btn.setProperty("primary", True)       # _apply_enabled drops it while the PC is on
        btn.setProperty("navKey", act if not tiles.is_dup(tile) else f"{act}#{tile['dup']}")
        btn.setProperty("touchRole", "action")
        btn.setProperty("tileSize", size)
        btn.setProperty("pending", False)
        btn.setProperty("baseText", btn.text())
        btn.setMinimumWidth(1)      # the column minimum (_lock_widths) decides, not a long pending text
        btn.setSizePolicy(QSizePolicy.Policy.Expanding,
                          QSizePolicy.Policy.Expanding if size == "gross" else QSizePolicy.Policy.Fixed)
        btn.installEventFilter(self.app)
        self.action_buttons.append((act, btn))
        return btn

    # --- layout ------------------------------------------------------------------
    def _lock_widths(self):
        """All grid columns get the same minimum width: wide enough that no tile text
        is cut off (the Steam toggle counts with its longer label, so it does not jump)."""
        self.ensurePolished()
        if self.editing:
            col_min = self._edit_col_need()
            if self.editor is not None:
                self.editor.setMinimumWidth(tiles.COLS * col_min + (tiles.COLS - 1) * self.SPACING)
            for c in range(tiles.COLS):
                self.grid.setColumnMinimumWidth(c, col_min)
            return
        col_min = 0
        for w, tile in self._tiles:
            w.ensurePolished()
            span = tiles.SIZES[tile["groesse"]][0]
            need = w.sizeHint().width()
            if isinstance(w, QPushButton):
                # measured with the normal label(s), never with a pending text
                fm = w.fontMetrics()
                extra = need - fm.horizontalAdvance(w.text())
                if w in self.steam_btns:
                    need = max(fm.horizontalAdvance(t("steam_launch")), fm.horizontalAdvance(t("steam_close"))) + extra
                else:
                    need = fm.horizontalAdvance(w.property("baseText") or w.text()) + extra
            if isinstance(w, QPushButton):
                need = max(need, 48)
                if tile["groesse"] == "gross":
                    w.setMinimumHeight(2 * w.sizeHint().height() + self.SPACING)
            col_min = max(col_min, -(-(need - (span - 1) * self.SPACING) // span))
        for c in range(tiles.COLS):
            self.grid.setColumnMinimumWidth(c, col_min)
        self._lock_rows()

    def _lock_rows(self):
        """QGridLayout gives a row without widgets zero height. Empty rows between or
        above tiles are part of the saved layout, so they get one tile height."""
        used = set()
        btn_h = 48
        for w, tile in self._tiles:
            (_, r), (_, rh) = tile["pos"], tiles.SIZES[tile["groesse"]]
            used |= set(range(r, r + rh))
            if isinstance(w, QPushButton) and tile["groesse"] != "gross":
                btn_h = max(btn_h, w.sizeHint().height())
        for r in range(max(used, default=-1) + 1):
            self.grid.setRowMinimumHeight(r, 0 if r in used else btn_h)

    def _line1_width(self) -> int:
        t1 = self._top
        icons = self.ICON
        steam = (self.steam_lbl.sizeHint().width() + t1.spacing()) if not self.steam_lbl.isHidden() else 0
        ip = (self.ip_lbl.sizeHint().width() + t1.spacing()) if self._show_ip() else 0
        grip = (self.grip_lbl.width() + t1.spacing()) if self.grip_lbl is not None else 0
        return (grip + self.dot.width() + t1.spacing() + self.name_lbl.minimumWidth() + t1.spacing()
                + ip + 4 + steam + 60 + t1.spacing() + icons)

    def wide_width(self) -> int:
        """Smallest width with every tile text readable (= also the minimum width)."""
        self._lock_widths()
        m = self._root.contentsMargins()
        g = self.grid.contentsMargins()
        grid_w = g.left() + g.right() + tiles.COLS * self.grid.columnMinimumWidth(0) + (tiles.COLS - 1) * self.SPACING
        return m.left() + m.right() + max(self._line1_width(), grid_w)

    def min_card_height(self) -> int:
        self._lock_widths()
        return self.minimumSizeHint().height()

    # --- theme / state -------------------------------------------------------------
    def _light(self) -> bool:
        return self.app.cfg.get("settings", {}).get("theme", "Dark") == "Light"

    def _show_ip(self) -> bool:
        return bool(self.app.cfg.get("settings", {}).get("show_ip", True))

    def _show_steam(self) -> bool:
        return bool(self.app.cfg.get("settings", {}).get("show_steam", True))

    def _apply_row_theme(self):
        c = ui_colors(self._light())
        # edit mode (concept 2): every card looks the same (no dashed / current frame);
        # the lifted shadow is painted by the card list (_HostArea)
        self.setStyleSheet(f"""
            QFrame#hostCard {{ background: {c['card']}; border: 1px solid {c['card_b']}; border-radius: 8px; }}
            QFrame#hostCard[current="true"] {{ background: {c['cur']}; border: 1px solid {c['cur_b']}; }}
            QFrame#hostCard[editing="true"] {{ background: {c['card']}; border: 1px solid {c['card_b']}; }}
            QFrame#hostCard QLabel {{ background: transparent; border: none; }}
            QFrame#hostCard QLabel#editSection {{ font-size: 12px; font-weight: bold; color: {c['edit']}; }}
            QFrame#hostCard QWidget#statusTile, QFrame#hostCard QWidget#hintRow,
            QFrame#hostCard QWidget#hiddenStrip, QFrame#hostCard QWidget#editBox {{ background: transparent; }}
            QFrame#hostCard QLabel#hostName {{ font-weight: bold; font-size: 16px; color: {c['name']}; }}
            QFrame#hostCard QLabel#ipPill {{ font-size: 12px; color: {c['pill_t']}; background: {c['pill']}; border-radius: 9px; padding: 1px 8px; }}
            QFrame#hostCard QLabel#hostSub {{ font-size: 13px; color: {c['sub']}; }}
            QFrame#hostCard QLabel#hostSteam {{ font-size: 13px; color: {c['steam_t']}; }}
            QFrame#hostCard QLabel#hostWarn {{ font-size: 13px; color: {c['warn_t']}; }}
            QFrame#hostCard QPushButton#hintLink {{ font-size: 13px; color: {c['link']}; background: transparent;
                border: 2px solid transparent; padding: 0px 4px; min-height: 22px; min-width: 0px; text-decoration: underline; }}
            QFrame#hostCard QPushButton#hintLink[navFocus="true"] {{ border: 2px solid {c['cur_b']}; }}
            QFrame#hostCard QLabel#hostError {{ font-size: 13px; color: {c['err']}; }}
            QFrame#hostCard QLabel#chip {{ font-size: 13px; color: {c['pill_t']}; background: {c['pill']}; border-radius: 10px; padding: 2px 10px; }}
            QFrame#hostCard QPushButton[mgmt="true"] {{ font-size: 30px; padding: 0px 0px 3px 0px; min-width: 44px; max-width: 44px; min-height: 41px; max-height: 41px; }}
            QFrame#hostCard QPushButton[tileSize="gross"] {{ font-size: 17px; font-weight: bold; }}
            QFrame#hostCard QPushButton[pending="true"] {{ border: 2px solid {c['cur_b']}; }}
            QFrame#hostCard QPushButton[hiddenTile="true"] {{ font-size: 13px; min-height: 22px; padding: 4px 10px; border-style: dashed; }}
        """)
        if self.editor is not None:
            self.editor.light = self._light()
        self._render()

    def _auto(self) -> bool:
        return self.app.cfg.get("settings", {}).get("auto_status", True)

    def _chip(self, label: QLabel, col: str, text: str):
        label.setText(f'<span style="color:{col}">●</span>&nbsp;{text}')

    def status_kind(self) -> str:
        """ready / warn / off / checking / unknown: what the dot shows (calm status)."""
        r = self.result
        if not r:
            return "checking" if self.checking else "unknown"
        if r.get("buddy"):
            return "ready"
        return "warn" if r.get("ping") else "off"

    def mismatch(self) -> dict | None:
        """Buddy answers but speaks another API than the bundled CLI (1.3.1): only a
        warning; Steam is greyed out, everything else stays usable."""
        r = self.result
        return r.get("api_mismatch") if r and r.get("buddy") else None

    @staticmethod
    def mismatch_text(mm: dict, kind: str) -> str:
        """kind: hint / why / fix; text by direction (host older / newer / unknown)."""
        d = {"host_old": "old", "host_new": "new"}.get(mm.get("dir"), "unknown")
        key = {"hint": {"old": "hint_buddy_old", "new": "hint_buddy_new", "unknown": "hint_buddy_mismatch"},
               "why": {"old": "why_mismatch_old", "new": "why_mismatch_new", "unknown": "why_mismatch_unknown"},
               "fix": {"old": "st_api_fix_old", "new": "st_api_fix_new", "unknown": "st_api_fix_unknown"}}
        return t(key[kind][d])

    def details_text(self) -> str:
        """Tooltip of dot and name (and ⓘ Details): state, ping, Buddy port, last check."""
        r = self.result
        kind = self.status_kind()
        mm = self.mismatch()
        lines = [t({"ready": "st_ready", "warn": "st_warn", "off": "st_off",
                    "checking": "status_checking", "unknown": "status_unknown"}[kind])]
        if mm:
            lines = [t("st_mismatch", host=mm["host"], want=mm["want"]) if mm.get("host") is not None
                     else t("st_mismatch_unknown")]
        ip = self.host.get("ip", "")
        if ip and not self._show_ip():
            lines.append(t("st_ip", ip=ip))       # IP hidden in the header: only here
        port = self.host.get("buddy_port", 59999)
        if r:
            buddy, ping = bool(r.get("buddy")), bool(r.get("ping"))
            lines.append(t("st_ping_ok", ip=ip) if ping else
                         (t("st_ping_blocked", ip=ip) if buddy else t("st_ping_fail", ip=ip)))
            lines.append(t("st_buddy_ok", port=port) if buddy else t("st_buddy_fail", port=port))
            if mm:
                lines.append(t("st_api_bad", host=mm["host"], want=mm["want"]) if mm.get("host") is not None
                             else t("st_api_bad_unknown", want=mm["want"]))
                lines.append(self.mismatch_text(mm, "fix"))
            steam = r.get("steam") if buddy else None
            if steam and steam.get("running"):
                lines.append(t("steam_bpm_hdr") if steam.get("bpm") else t("steam_running_hdr"))
            if kind == "warn":
                lines.append(t("st_buddy_hint"))
            if r.get("time"):
                lines.append(t("st_checked", time=r["time"]))
        if not self._auto():
            lines.append(t("st_auto_off"))
        if not self.host.get("mac"):
            lines.append(t("no_mac_short"))
        return "\n".join(lines)

    def _render(self):
        """Paint dot, chips, hint and button states from the current UI state."""
        if not hasattr(self, "nav_buttons") or not hasattr(self, "_tiles"):
            return
        c = ui_colors(self._light())
        grey = "#b0b0b0" if self._light() else "#8a8a8a"
        r = self.result
        pc_on = buddy = False
        steam = None
        if r:
            buddy = bool(r.get("buddy"))
            pc_on = bool(r.get("ping")) or buddy
            steam = r.get("steam") if buddy else None
        # optional online tile: one state, priority Buddy reachable > PC online (ping) > offline
        online = tiles.online_state(r)
        if online == "unknown":
            key = "checking" if self.checking else "unknown"
            self._chip(self.chip_online, grey, t(f"status_{key}"))
        else:
            col = {"buddy": c["online"], "pc": c["warn"], "offline": c["offline"]}[online]
            self._chip(self.chip_online, col, t(f"status_{online}"))
        self.steam_running = (bool(steam.get("running")) if steam is not None else None)
        self.state = ("online" if pc_on else "offline") if r else "unknown"
        # dot: the status itself (calm status, variant B)
        if self.busy:
            col = c["cur_b"]          # accent blue: action running
        elif self.failed:
            col = c["error"]
        elif pc_on and buddy and self.mismatch():
            col = c["warn"]          # orange: Buddy answers, but the version does not match
        elif pc_on and buddy:
            col = c["online"]
        elif pc_on:
            col = c["warn"]          # orange: PC up, Buddy not answering
        elif r:
            col = c["offline"]
        else:
            col = c["unknown"]
        self.dot.setStyleSheet(f"QLabel#hostDot {{ background: {col}; border-radius: 7px; border: none; }}")   # scoped: the tooltip must not inherit it
        details = "" if self.editing else self.details_text()
        self.dot.setToolTip(details)
        self.name_lbl.setToolTip(details)
        self.chip_online.setToolTip(self.details_text())
        self.ip_lbl.setVisible(self._show_ip())
        # "▶ Steam läuft" only while Steam runs (and the global switch is on)
        if steam and steam.get("running") and self._show_steam():
            self.steam_lbl.setText(t("steam_bpm_hdr") if steam.get("bpm") else t("steam_running_hdr"))
            self.steam_lbl.show()
        else:
            self.steam_lbl.hide()
        # busy text / no MAC (header); the check time lives in the tooltip
        parts = []
        if self.pending:
            parts.append("⟳ " + t(f"pending_{self.pending}"))
        elif self.busy:
            parts.append("⟳ " + t("state_working"))
        if not self.host.get("mac"):
            parts.append(t("no_mac_short"))
        self.time_lbl.setText(" · ".join(parts))
        problem = bool(r) and pc_on and not buddy
        mm = self.mismatch()
        self.hint_lbl.setText((self.mismatch_text(mm, "hint") if mm else t("hint_problem")) + " ·")
        self.hint_row.setVisible(problem or bool(mm))
        self.details_btn.setVisible(problem or bool(mm))
        # Steam toggle label
        closing = bool(self.steam_running)
        for b in self.steam_btns:
            b.setProperty("baseText", t("steam_close") if closing else t("steam_launch"))
        self._render_pending()
        self._apply_enabled(r, pc_on, buddy)
        if self.editor is not None:
            wp = not (bool(r) and pc_on)
            if self.editor.wake_primary != wp:
                self.editor.wake_primary = wp
                self.editor.update()

    def _apply_enabled(self, r, pc_on: bool, buddy: bool):
        """Variant A: everything visible; inapplicable actions disabled + not focusable.
        Without a result (first check pending, or automatic checks off) all stay enabled."""
        gate = bool(r) and self._auto()
        mm = self.mismatch()
        want = {}
        for act, b in self.action_buttons:
            if act == "wake":
                # "Wecken" is only highlighted while the PC may be off: never once the last
                # check saw it on (also with automatic checks off, where it stays usable)
                prim = not (bool(r) and pc_on)
                if bool(b.property("primary")) != prim:
                    b.setProperty("primary", prim)
                    b.style().unpolish(b)
                    b.style().polish(b)
                    b.update()
            if not gate:
                ok, why = True, ""
            elif act == "wake":
                ok, why = not pc_on, t("why_pc_on")
            elif act == "steam" and mm:
                ok, why = False, self.mismatch_text(mm, "why")   # other actions stay clickable
            else:
                ok, why = buddy, t("why_no_buddy")
            want[b] = ok
            if not b.property("pending"):
                b.setToolTip("" if ok else why)  # tiles have no tooltip, only the reason when greyed out
        for b, ok in want.items():        # enable first, so focus can move onto them
            if ok:
                b.setEnabled(True)
                b.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        fw = self.window().focusWidget()
        if fw in want and not want[fw]:
            # move the focus to the nearest button that stays usable before disabling
            idx = self.nav_buttons.index(fw)
            usable = [b for b in self.nav_buttons if want.get(b, True)]
            if usable:
                tgt = min(usable, key=lambda b: abs(self.nav_buttons.index(b) - idx))
                tgt.setFocus(Qt.FocusReason.TabFocusReason)
        for b, ok in want.items():
            if not ok:
                b.setEnabled(False)
                b.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def _pending_state(self):
        return (self.status_kind(), self.steam_running)

    def _pending_match(self, act: str) -> bool:
        p = self.pending
        return bool(p) and (act == p or (act == "steam" and p in ("steam_launch", "steam_close")))

    def _render_pending(self):
        """Tiles of the running action show "Wird geweckt …" (elided to the tile, the
        full text as tooltip). No animation; they stay clickable: while the action
        still runs, the action lock in MainWindow.do_action answers with the "already
        running" toast; after it returned (feedback kept until the status changes) a
        click sends the action again."""
        for act, b in self.action_buttons:
            on = self._pending_match(act)
            base = b.property("baseText") or b.text()
            if on:
                full = t(f"pending_{self.pending}")
                avail = b.width() - 24
                text = b.fontMetrics().elidedText(full, Qt.TextElideMode.ElideRight, avail) if avail > 40 else full
                b.setToolTip(full)
            else:
                text = base
            if b.text() != text:
                b.setText(text)
            if bool(b.property("pending")) != on:
                b.setProperty("pending", on)
                if not on:
                    b.setToolTip("")
                b.style().unpolish(b)
                b.style().polish(b)
                b.update()

    def set_pending(self, action):
        """Tile feedback for a running action (None ends it)."""
        self.pending = action or None
        if self.pending:
            self._pending_key = self._pending_state()
            self._pending_timer.start(self.PENDING_MS)
        else:
            self._pending_key = None
            self._pending_timer.stop()
        self._render()

    def set_result(self, result: dict):
        self.result = result
        self.checking = False
        self.failed = False
        self.error_lbl.hide()
        if self.pending and self._pending_key is not None:
            # the status changed (PC woke up, Steam started …): the feedback has done its job
            old = self._pending_key
            self._render()
            if old[0] in ("checking", "unknown"):
                self._pending_key = self._pending_state()     # first result: the new reference
            elif self._pending_state() != old:
                self.set_pending(None)
        self._render()
        self.app._update_counts()

    def set_busy(self, on: bool, action=None, keep_pending: bool = False):
        """keep_pending: the action returned fine, the tile keeps "Wird geweckt …" until
        the status changes (set_result) or PENDING_MS runs out."""
        self.busy = on
        if on:
            self.failed = False
            self.error_lbl.hide()
            if action:
                self.set_pending(action)
                return
        elif self.pending and not keep_pending:
            self.set_pending(None)
            return
        self._render()

    def ui_state(self) -> dict:
        """Action feedback of this card (refresh_hosts carries it over to the new card)."""
        t_left = self._pending_timer.remainingTime() if self._pending_timer.isActive() else -1
        return {"busy": self.busy, "pending": self.pending, "pending_key": self._pending_key,
                "pending_left": t_left, "failed": self.failed,
                "error": self.error_lbl.text() if self.failed else ""}

    def restore_ui_state(self, st: dict):
        self.busy = bool(st.get("busy"))
        self.failed = bool(st.get("failed"))
        if self.failed:
            self.error_lbl.setText(st.get("error", ""))
            self.error_lbl.setToolTip(st.get("error", "")[2:])
            self.error_lbl.show()
        left = st.get("pending_left", -1)
        if st.get("pending") and (left > 0 or self.busy):
            self.pending = st["pending"]
            self._pending_key = st.get("pending_key")
            self._pending_timer.start(min(left, self.PENDING_MS) if left > 0 else self.PENDING_MS)
        self._render()

    def set_failed(self, text: str):
        self.busy = False
        self.failed = True
        self.pending = None
        self._pending_key = None
        self._pending_timer.stop()
        self.error_lbl.setText("⚠ " + text)
        self.error_lbl.setToolTip(text)
        self.error_lbl.show()
        self._render()

    def set_current(self, on: bool):
        if bool(self.property("current")) == on:
            return
        self.setProperty("current", on)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()


class _CardLongPress(QObject):
    """UI only: touch long press (~350 ms) on a host card. On an action tile or the
    card background it starts the edit mode; on the status dot or the host name it
    shows the status details (the tooltip a mouse gets on hover). A mouse press on
    the card background in edit mode picks that card for the edit toolbar."""
    HOLD_MS = 350
    SLOP = 14

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(self.HOLD_MS)
        self.timer.timeout.connect(self._fire)
        self._obj = None
        self._gpos = None
        self._fired = None

    def watch(self, w):
        w.installEventFilter(self)

    @staticmethod
    def is_touch(ev) -> bool:
        try:
            dev = ev.device()
            if dev is not None and dev.type() == QInputDevice.DeviceType.TouchScreen:
                return True
        except Exception:
            pass
        try:
            return ev.source() != Qt.MouseEventSource.MouseEventNotSynthesized
        except Exception:
            return False

    @staticmethod
    def row_of(obj):
        w = obj
        while w is not None and not isinstance(w, HostRow):
            w = w.parentWidget() if isinstance(w, QWidget) else None
        return w

    def eventFilter(self, obj, ev):
        et = ev.type()
        try:
            if et == QEvent.Type.MouseButtonPress and ev.button() == Qt.MouseButton.LeftButton:
                row = self.row_of(obj)
                if row is not None:
                    if self.win._edit_mode and obj is row:
                        self.win.edit_focus_card(row.host.get("id"))
                    if self.is_touch(ev):
                        self._obj, self._gpos = obj, ev.globalPosition().toPoint()
                        self._fired = None
                        self.timer.start()
            elif et == QEvent.Type.MouseMove and self._obj is not None and self.timer.isActive():
                if (ev.globalPosition().toPoint() - self._gpos).manhattanLength() > self.SLOP:
                    self.cancel()
            elif et == QEvent.Type.MouseButtonRelease:
                self.timer.stop()
                self._obj = None
                if self._fired is obj:
                    self._fired = None
                    return True          # the hold was the gesture: no click
        except RuntimeError:
            pass
        return False

    def cancel(self):
        self.timer.stop()
        self._obj = None

    def _fire(self):
        obj, self._obj = self._obj, None
        if obj is None:
            return
        try:
            row = self.row_of(obj)
        except RuntimeError:
            return
        if row is None:
            return
        if obj in (row.dot, row.name_lbl):
            if not self.win._edit_mode:
                QToolTip.showText(self._gpos, row.details_text(), obj, QRect(), 10000)
                self._fired = obj
            return
        if self.win._edit_mode:
            return
        if isinstance(obj, QPushButton):
            obj.setDown(False)
        self._fired = obj
        hid = row.host.get("id")
        QTimer.singleShot(0, lambda: self.win.enter_edit_mode(hid))


class Toast(QFrame):
    """UI only: non-blocking feedback in the main window (bottom right), fades out
    automatically; click to dismiss. kind: ok (green), error (red), info (amber)."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("toast")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(14, 10, 10, 10)
        outer.setSpacing(10)
        lay = QVBoxLayout()
        lay.setSpacing(2)
        self.title = QLabel()
        self.title.setWordWrap(True)
        self.title.setObjectName("toastTitle")
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        self.detail.setObjectName("toastDetail")
        lay.addWidget(self.title)
        lay.addWidget(self.detail)
        outer.addLayout(lay, 1)
        # optional action (e.g. "Undo" after deleting a host); part of the arrow-key grid
        self.action_btn = QPushButton()
        self.action_btn.setObjectName("toastBtn")
        self.action_btn.setMinimumHeight(48)
        self.action_btn.clicked.connect(self._run_action)
        self.action_btn.hide()
        outer.addWidget(self.action_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self._action = None
        self.buttons = [self.action_btn]
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)
        self.hide()

    def _run_action(self):
        cb, self._action = self._action, None
        self.hide()
        if cb:
            cb()

    def hideEvent(self, ev):
        super().hideEvent(ev)
        if self.action_btn.hasFocus():
            win = self.window()
            QTimer.singleShot(0, getattr(win, "_ensure_focus", lambda: None))

    def show_message(self, title: str, detail: str, kind: str, light: bool, ms: int, action=None):
        """action: optional (label, callback) shown as a button in the toast."""
        c = ui_colors(light)
        bg, b, fg = {"ok": ("ok_bg", "ok_b", "ok_t"), "error": ("er_bg", "er_b", "er_t"),
                     "info": ("in_bg", "in_b", "in_t")}[kind]
        icon = {"ok": "✓", "error": "⚠", "info": "ℹ"}[kind]
        self.setStyleSheet(f"""
            QFrame#toast {{ background: {c[bg]}; border: 1px solid {c[b]}; border-radius: 8px; }}
            QFrame#toast QLabel {{ background: transparent; border: none; color: {c[fg]}; }}
            QLabel#toastTitle {{ font-size: 14px; font-weight: bold; }}
            QLabel#toastDetail {{ font-size: 13px; color: {c['dim']}; }}
            QPushButton#toastBtn {{ min-width: 80px; border: 2px solid {c[b]}; }}
        """)
        self.title.setText(f"{icon}  {title}")
        self.detail.setText(detail)
        self.detail.setVisible(bool(detail))
        self._action = action[1] if action else None
        self.action_btn.setText(action[0] if action else "")
        self.action_btn.setVisible(bool(action))
        self.place()
        self.show()
        self.raise_()
        self.timer.start(ms)

    def place(self):
        par = self.parentWidget()
        if not par:
            return
        w = min(380, max(220, par.width() - 28))
        self.setFixedWidth(w)
        self.adjustSize()
        # wrapped title + detail next to the action button: adjustSize alone can
        # underestimate the height (detail clipped), so ask the layout for width w
        h = self.layout().totalHeightForWidth(w) if self.layout().hasHeightForWidth() else -1
        if h > self.height():
            self.resize(w, h)
        bottom = getattr(par.window(), "_toast_bottom", lambda: par.height() - 14)()
        self.move(par.width() - w - 14, bottom - self.height())

    def mousePressEvent(self, ev):
        self.hide()

class UpdateToast(QFrame):
    """Blue info toast (bottom right) for a new release: [Download] opens the
    release page in the browser, ✕ closes. Stays about 30 s."""
    def __init__(self, parent, on_download):
        super().__init__(parent)
        self.setObjectName("utoast")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 10, 10)
        lay.setSpacing(10)
        txt = QVBoxLayout()
        txt.setSpacing(2)
        self.title = QLabel()
        self.title.setObjectName("toastTitle")
        self.title.setWordWrap(True)
        self.detail = QLabel()
        self.detail.setObjectName("toastDetail")
        self.detail.setWordWrap(True)
        txt.addWidget(self.title)
        txt.addWidget(self.detail)
        lay.addLayout(txt, 1)
        self.dl_btn = QPushButton(t("update_download"))
        self.dl_btn.setObjectName("toastBtn")
        self.dl_btn.clicked.connect(on_download)
        self.x_btn = QPushButton("✕")
        self.x_btn.setObjectName("toastX")
        self.x_btn.setToolTip(t("close"))
        self.x_btn.setFixedSize(48, 48)
        self.x_btn.clicked.connect(self.hide)
        lay.addWidget(self.dl_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self.x_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self.buttons = [self.dl_btn, self.x_btn]
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)
        self.hide()

    def show_update(self, version: str, light: bool, ms: int = 30000, cli: str | None = None):
        """version: new BuddyRemote version ('' = none); cli: label of a newer MoonDeck CLI
        (None = none). Both at once: one combined toast."""
        if light:
            bg, b, fg, dim, btn, btn_b = "#e3f2fd", "#1565c0", "#0d47a1", "#37474f", "#1565c0", "#0d47a1"
        else:
            bg, b, fg, dim, btn, btn_b = "#1b2d3a", "#4fc3f7", "#e6e6e6", "#a8c4d4", "#1f5f8b", "#2a7ab0"
        self.setStyleSheet(f"""
            QFrame#utoast {{ background: {bg}; border: 1px solid {b}; border-radius: 8px; }}
            QFrame#utoast QLabel {{ background: transparent; border: none; color: {fg}; }}
            QLabel#toastTitle {{ font-size: 14px; font-weight: bold; }}
            QLabel#toastDetail {{ font-size: 13px; color: {dim}; }}
            QPushButton#toastBtn {{ background: {btn}; color: #fff; border: 2px solid {btn_b}; min-width: 80px; }}
            QPushButton#toastBtn:focus {{ border: 2px solid #ffffff; }}
            QPushButton#toastX {{ background: transparent; color: {dim}; border: 2px solid transparent; min-width: 0px; min-height: 0px; padding: 0px; font-size: 16px; }}
            QPushButton#toastX:focus {{ border: 2px solid {b}; }}
        """)
        if version and cli is not None:
            title, detail = (t("update_both_title", version=version),
                             t("update_both_detail", current=APP_VERSION))
        elif version:
            title, detail = t("update_available", version=version), t("update_detail", current=APP_VERSION)
        else:
            title, detail = t("cli_update_title"), t("cli_update_detail", label=cli or "nightly")
        self.title.setText("ℹ  " + title)
        self.detail.setText(detail)
        self.dl_btn.setText(t("update_download") if version else t("cli_release_page"))
        self.place()
        self.show()
        self.raise_()
        self.timer.start(ms)

    def place(self):
        par = self.parentWidget()
        if not par:
            return
        w = min(460, max(260, par.width() - 28))
        self.setFixedWidth(w)
        self.adjustSize()
        bottom = getattr(par.window(), "_toast_base_bottom", lambda: par.height() - 14)()
        self.move(par.width() - w - 14, bottom - self.height())

    def hideEvent(self, ev):
        super().hideEvent(ev)
        win = self.window()
        if hasattr(win, "toast") and win.toast.isVisible():
            win.toast.place()          # the normal toast moves back down

# ---------------------------------------------------------------------------
def tile_label(typ: str) -> str:
    """Display name of a tile type (edit dialog, preview)."""
    if typ in ("online_status", "steam_start_stop"):
        return t(f"tile_{typ}")
    return t(tiles.TYPES[typ]["action"])


def tile_text(a) -> str:
    """Label of one tile in the preview / menus; duplicates are numbered (Wecken 2)."""
    return tile_label(a["typ"]) + (f' {a["dup"] + 1}' if tiles.is_dup(a) else "")


class _CardGrip(QWidget):
    """The ⠿ grip in the card header (edit mode), painted with paint_grip like the
    tiles and toolbar icons: no font glyph, so it looks the same on every platform."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(16, 24)

    def paintEvent(self, ev):
        light = False
        win = self.window()
        if hasattr(win, "_light"):
            light = win._light()
        col = QColor(ui_colors(light)["sub"])
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint_grip(p, self.width() / 2 - 2.5, self.height() / 2, col, r=1.8, step=5)
        p.end()


def paint_grip(p: QPainter, x: float, cy: float, col: QColor, r: float = 1.6, step: float = 5):
    """The ⠿ grip of everything movable in edit mode: 2 columns x 3 rows of dots."""
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(col)
    for i in range(3):
        for j in range(2):
            p.drawEllipse(QPointF(x + j * step, cy - step + i * step), r, r)
    p.restore()


def paint_lifted(p: QPainter, rc, radius: float = 6, strength: float = 1.0):
    """Calm "lifted" look of movable things in edit mode: a soft static shadow below /
    right, painted only outside the element (no animation, no QGraphicsEffect)."""
    rc = QRectF(rc)
    inner = QPainterPath()
    inner.addRoundedRect(rc, radius, radius)
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    for i, a in enumerate((34, 22, 12)):
        o = QPainterPath()
        o.addRoundedRect(rc.translated(0, 2 + i).adjusted(-1 - i, -i * 0.3, 1 + i, 1 + i), radius + i, radius + i)
        p.setBrush(QColor(0, 0, 0, int(a * strength)))
        p.drawPath(o.subtracted(inner))
    p.restore()


class TilePreview(QWidget):
    """Tile grid of a host card.

    Read-only (adding a host): just a picture of the template.
    Editable, card=True (the edit mode of the main window, drawn like the real buttons
    with the same cell height and gap as the card grid):
      - mouse: drag a tile, it snaps to the grid cells; a click selects it;
      - touch: press and hold (~350 ms) to pick a tile up, move the finger, lift to drop;
      - keyboard / gamepad: Tab, Enter or Space select the next tile, the arrow keys
        move the selected one, Delete hides/removes it, the Menu key opens the menu;
      - right click: context menu (size, duplicate, remove) - everything in it is also
        in the edit toolbar of the main window.
    While dragging, tiles.reflow() (Qt-free, unit tested) decides where the other tiles
    go; they glide there in ~160 ms with a slight overshoot (OutBack). The dragged tile
    is a ghost under the pointer; only this grid shows drop slots (dotted): the target
    "hier ablegen", the free places and the "ursprünglicher Platz" (red = not allowed).
    Every tile has the ⠿ grip and a calm static lifted shadow (edit mode concept 2). Invalid drops (outside the grid or no room)
    are rejected and the tile springs back. One extra empty row below the layout is
    offered as drop space. The host cards are reordered by MainWindow.card_drag
    (header / empty card area), not by this grid.
    Tiles are identified by tiles.key() ("boot", "boot#1" for a duplicate)."""
    CELL_H = 30
    CELL_H_EDIT = 48            # 48 px high touch target per cell in edit mode
    GAP = 4
    ANIM_MS = 160
    OVERSHOOT = 1.25            # OutBack: short, slightly springy, not sluggish
    HOLD_MS = 350               # touch: press-and-hold to pick a tile up
    TOUCH_SLOP = 12             # px a finger may wobble before the hold is cancelled

    dropped = pyqtSignal(list, str, str)     # new tiles, dragged key, "ok" | "reflow"
    rejected = pyqtSignal(str)               # dragged key (drop not allowed, went back)
    picked = pyqtSignal(str)                 # a tile was clicked / tapped (no drag)
    menu_requested = pyqtSignal(str, QPoint)  # right click on a tile: key, global pos
    key_action = pyqtSignal(str)             # card mode: left/right/up/down/remove
    focused = pyqtSignal()                   # card mode: got the keyboard focus
    drag_changed = pyqtSignal(bool)          # a drag started (True) / ended (False)

    def __init__(self, light: bool, parent=None, editable: bool = False, card: bool = False):
        super().__init__(parent)
        self.light = light
        self.wake_primary = True    # card mode: "Wecken" drawn highlighted only while the PC may be off
        self.editable = editable
        self.card = card and editable
        if self.card:
            self.GAP = HostRow.SPACING   # same gap as the real card grid
        self.tiles = []             # committed layout (from the main window)
        self.view = []              # what is shown now (= tiles, or the reflow while dragging)
        self.selected = None
        self.ch = self.CELL_H_EDIT if editable else self.CELL_H
        self._rects = {}            # key -> QRectF target
        self._from = {}             # key -> QRectF animation start
        self._t = 1.0
        self._press = None          # (key, QPointF press pos, QPointF offset in tile)
        self._drag = None           # dict while dragging
        self._touch = None          # dict while a finger is down
        self._rows_fixed = None     # grid rows frozen during a drag
        self.anim = QVariantAnimation(self)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setDuration(self.ANIM_MS)
        curve = QEasingCurve(QEasingCurve.Type.OutBack)
        curve.setOvershoot(self.OVERSHOOT)
        self.anim.setEasingCurve(curve)
        self.anim.valueChanged.connect(self._on_anim)
        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.setInterval(self.HOLD_MS)
        self._hold.timeout.connect(self._on_hold)
        self.setMinimumWidth(4 * 64 + 3 * self.GAP)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # the dialog preview takes no focus; the edit-mode card is keyboard operable
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus if self.card else Qt.FocusPolicy.NoFocus)
        if editable:
            self.setMouseTracking(True)
            self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)

    # --- geometry -----------------------------------------------------------------
    def rows(self) -> int:
        if self._rows_fixed:
            return self._rows_fixed
        n = tiles.rows_used(self.tiles)
        return max(1, min(tiles.MAX_ROWS, n + 1 if self.editable else n))

    def _cw(self) -> float:
        return (self.width() - (tiles.COLS - 1) * self.GAP) / tiles.COLS

    def cell_rect(self, col, row, w=1, h=1) -> QRectF:
        cw, ch, g = self._cw(), self.ch, self.GAP
        return QRectF(col * (cw + g), row * (ch + g), w * cw + (w - 1) * g, h * ch + (h - 1) * g)

    def tile_rect(self, a) -> QRectF:
        w, h = tiles.SIZES[a["groesse"]]
        return self.cell_rect(a["pos"][0], a["pos"][1], w, h)

    def tile_center(self, k) -> QPoint:
        """Centre of a tile in widget coordinates (used by tests and the context menu)."""
        i = tiles.find(self.tiles, k)
        return self.tile_rect(self.tiles[i]).center().toPoint()

    def _shown_rect(self, k) -> QRectF | None:
        """Current (possibly animating) rect of a tile."""
        to = self._rects.get(k)
        if to is None:
            return None
        fr = self._from.get(k, to)
        q = self._t
        return QRectF(fr.x() + (to.x() - fr.x()) * q, fr.y() + (to.y() - fr.y()) * q,
                      fr.width() + (to.width() - fr.width()) * q, fr.height() + (to.height() - fr.height()) * q)

    def _fix_height(self):
        self.setFixedHeight(int(self.rows() * (self.ch + self.GAP) - self.GAP))

    # --- layout / animation -----------------------------------------------------------
    def set_tiles(self, tile_list, selected=None):
        self.tiles = tile_list
        self.selected = selected
        if not self._drag:
            self._fix_height()
            self._show(tile_list)
        self.update()

    def _show(self, view, start_from: dict | None = None):
        """Animate every tile from where it is drawn now to its place in ``view``."""
        new = {tiles.key(a): self.tile_rect(a) for a in view if tiles.is_active(a)}
        changed = new != self._rects or start_from
        cur = {k: self._shown_rect(k) for k in new if k in self._rects}
        if start_from:
            cur.update(start_from)
        self.view = view
        if not changed:
            return
        first = not self._rects
        self._from = {k: cur.get(k, r) for k, r in new.items()}
        self._rects = new
        self.anim.stop()
        if first or not self.isVisible():
            self._t = 1.0
        else:
            self._t = 0.0
            self.anim.start()

    def _on_anim(self, v):
        self._t = float(v)
        self.update()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._rects = {tiles.key(a): self.tile_rect(a) for a in self.view if tiles.is_active(a)}
        self._from = dict(self._rects)

    # --- pointer input (edit mode only) ---------------------------------------------------
    def _tile_at(self, pt: QPointF):
        for a in self.tiles:
            if tiles.is_active(a) and self.tile_rect(a).contains(pt):
                return a
        return None

    def _snap(self, pt: QPointF):
        """Grid cell for the dragged tile's top-left corner (nearest cell)."""
        d = self._drag
        tl = pt - d["offset"]
        step_x, step_y = self._cw() + self.GAP, self.ch + self.GAP
        return [int(round(tl.x() / step_x)), int(round(tl.y() / step_y))]

    def _begin_press(self, pt: QPointF) -> bool:
        a = self._tile_at(pt)
        if a is None:
            return False
        self._press = (tiles.key(a), QPointF(pt), pt - self.tile_rect(a).topLeft())
        return True

    def mousePressEvent(self, ev):
        if not self.editable or ev.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(ev)
        if self._begin_press(ev.position()):
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        ev.accept()

    def mouseMoveEvent(self, ev):
        if not self.editable:
            return super().mouseMoveEvent(ev)
        pt = ev.position()
        if self._press and not self._drag:
            if (pt - self._press[1]).manhattanLength() >= QApplication.startDragDistance():
                self._start_drag()
        if self._drag:
            self._drag["pt"] = QPointF(pt)
            self._update_drag()
        else:
            hover = self._tile_at(pt) is not None
            self.setCursor(Qt.CursorShape.OpenHandCursor if hover else Qt.CursorShape.ArrowCursor)
        ev.accept()

    def mouseReleaseEvent(self, ev):
        if not self.editable or ev.button() != Qt.MouseButton.LeftButton:
            return super().mouseReleaseEvent(ev)
        press, self._press = self._press, None
        if self._drag:
            self._finish_drag()
        elif press:
            self.picked.emit(press[0])
        self.setCursor(Qt.CursorShape.OpenHandCursor if self._tile_at(ev.position()) else Qt.CursorShape.ArrowCursor)
        ev.accept()

    def contextMenuEvent(self, ev):
        if not self.editable or self._drag:
            return super().contextMenuEvent(ev)
        if (ev.reason() == QContextMenuEvent.Reason.Keyboard and self.selected
                and tiles.find(self.tiles, self.selected) is not None):
            a = self.tiles[tiles.find(self.tiles, self.selected)]
            self.menu_requested.emit(self.selected, self.mapToGlobal(self.tile_center(self.selected)))
            ev.accept()
            return
        a = self._tile_at(QPointF(ev.pos()))
        if a is not None:
            self.menu_requested.emit(tiles.key(a), ev.globalPos())
        ev.accept()

    def _event(self, ev):
        """Touch: press and hold picks a tile up, the finger drags it, lifting drops it.
        A short tap selects. Touch events are accepted, so Qt does not also synthesize
        mouse events for them."""
        et = ev.type()
        if self.editable and et in (QEvent.Type.TouchBegin, QEvent.Type.TouchUpdate,
                                    QEvent.Type.TouchEnd, QEvent.Type.TouchCancel):
            pts = ev.points()
            pt = QPointF(self.mapFromGlobal(pts[0].globalPosition().toPoint())) if pts else None
            if et == QEvent.Type.TouchBegin:
                self._touch = None
                if pt is not None and self._begin_press(pt):
                    self._touch = {"start": QPointF(pt), "moved": False}
                    self._hold.start()
            elif et == QEvent.Type.TouchUpdate and pt is not None:
                if self._drag:
                    self._drag["pt"] = QPointF(pt)
                    self._update_drag()
                elif self._touch and (pt - self._touch["start"]).manhattanLength() > self.TOUCH_SLOP:
                    self._touch["moved"] = True        # moved before the hold: not a pick-up
                    self._hold.stop()
                    self._press = None
            elif et == QEvent.Type.TouchEnd:
                self._hold.stop()
                if self._drag:
                    if pt is not None:
                        self._drag["pt"] = QPointF(pt)
                        self._update_drag()
                    self._press = None
                    self._finish_drag()
                elif self._touch and not self._touch["moved"] and self._press:
                    k = self._press[0]
                    self._press = None
                    self.picked.emit(k)
                self._touch = None
            else:                                       # TouchCancel
                self._hold.stop()
                self._touch = None
                self.cancel_drag()
            ev.accept()
            return True
        return super().event(ev)

    def _on_hold(self):
        if self._press and not self._drag:
            self._start_drag()
            self._update_drag()                         # ghost + highlight right away (lift feedback)

    def _start_drag(self):
        k, pt, offset = self._press
        idx = tiles.find(self.tiles, k)
        self._rows_fixed = self.rows()
        self._drag = {"key": k, "idx": idx, "offset": offset, "pt": QPointF(pt), "start": copy.deepcopy(self.tiles),
                      "pos": list(self.tiles[idx]["pos"]), "valid": True, "result": "ok", "new": self.tiles,
                      "inside": True}
        self.selected = k
        self.grabKeyboard()             # Esc cancels the drag (the preview itself takes no focus)
        self.update()
        self.drag_changed.emit(True)

    # --- keyboard (card mode) -------------------------------------------------------------
    def order(self) -> list:
        """Keys of the shown tiles in reading order (row, then column)."""
        act = [a for a in self.tiles if tiles.is_active(a)]
        return [tiles.key(a) for a in sorted(act, key=lambda a: (a["pos"][1], a["pos"][0]))]

    def _step(self, d: int, wrap: bool):
        """Select the next/previous tile; False at the end (without wrap)."""
        keys = self.order()
        if not keys:
            return False
        if self.selected not in keys:
            k = keys[0] if d > 0 else keys[-1]
        else:
            i = keys.index(self.selected) + d
            if not 0 <= i < len(keys):
                if not wrap:
                    return False
                i %= len(keys)
            k = keys[i]
        self.picked.emit(k)
        return True

    def event(self, ev):
        if (self.card and ev.type() == QEvent.Type.KeyPress and not self._drag
                and ev.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab)
                and not ev.modifiers() & ~(Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.KeypadModifier)):
            back = ev.key() == Qt.Key.Key_Backtab or bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            if self._step(-1 if back else 1, wrap=False):
                return True
            # past the last/first tile: the focus leaves the card editor as usual
        return self._event(ev)

    def keyPressEvent(self, ev):
        if self._drag and ev.key() == Qt.Key.Key_Escape:
            self.cancel_drag()
            ev.accept()
            return
        if self.card and not self._drag and not ev.modifiers() & ~Qt.KeyboardModifier.KeypadModifier:
            key = ev.key()
            arrows = {Qt.Key.Key_Left: "left", Qt.Key.Key_Right: "right", Qt.Key.Key_Up: "up", Qt.Key.Key_Down: "down"}
            if key in arrows:
                if self.selected is None or tiles.find(self.tiles, self.selected) is None:
                    self._step(1, wrap=True)       # first press: pick the first tile
                else:
                    self.key_action.emit(arrows[key])
                ev.accept()
                return
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
                self._step(1, wrap=True)
                ev.accept()
                return
            if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.selected:
                self.key_action.emit("remove")
                ev.accept()
                return
            if key == Qt.Key.Key_Menu and self.selected and tiles.find(self.tiles, self.selected) is not None:
                self.menu_requested.emit(self.selected, self.mapToGlobal(self.tile_center(self.selected)))
                ev.accept()
                return
        super().keyPressEvent(ev)

    def focusInEvent(self, ev):
        super().focusInEvent(ev)
        if self.card:
            self.focused.emit()
            self.update()

    def focusOutEvent(self, ev):
        super().focusOutEvent(ev)
        self.update()

    def cancel_drag(self):
        """Abort a running drag: everything goes back to where it was, nothing is emitted."""
        self._hold.stop()
        if not self._drag:
            return
        d = self._drag
        from_rect = self._drag_rect()
        self._drag = None
        self._press = None
        self._rows_fixed = None
        self.releaseKeyboard()
        self._fix_height()
        self._show(d["start"], start_from={d["key"]: from_rect})
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()
        self.drag_changed.emit(False)

    def hideEvent(self, ev):
        self.cancel_drag()
        super().hideEvent(ev)

    def _update_drag(self):
        d = self._drag
        pos = self._snap(d["pt"])
        inside = self.rect().adjusted(-int(self._cw() / 2), -self.ch // 2,
                                      int(self._cw() / 2), self.ch // 2).contains(d["pt"].toPoint())
        if inside:
            new, res = tiles.reflow(d["start"], d["idx"], pos, max_rows=self.rows())
        else:
            new, res = d["start"], "blocked"
        valid = res != "blocked"
        if (pos, valid, inside) != (d["pos"], d["valid"], d["inside"]):
            d.update(pos=pos, valid=valid, inside=inside, result=res, new=new if valid else d["start"])
            self._show(d["new"])        # others reflow (or go back while invalid)
        self.update()

    def drop_slots(self) -> list:
        """While dragging: the places the tile could go without pushing anything aside
        (the original place first, then free ones in reading order, never overlapping
        each other). Drawn as dotted slots; the target is added by paintEvent."""
        d = self._drag
        if not d:
            return []
        a = d["start"][d["idx"]]
        size = a["groesse"]
        h = tiles.SIZES[size][1]
        used = tiles.occupied([x for x in d["new"] if tiles.key(x) != d["key"]])
        taken, out = set(), []
        origin = tuple(a["pos"])
        rows = self.rows()
        for c, r in [origin] + [(c, r) for r in range(rows) for c in range(tiles.COLS)]:
            cl = tiles.cells([c, r], size)
            if not tiles.fits([c, r], size) or r + h > rows or cl & used or cl & taken:
                continue
            out.append((c, r))
            taken |= cl
        return out

    def _drag_rect(self) -> QRectF:
        d = self._drag
        a = d["start"][d["idx"]]
        r = self.tile_rect(a)
        r.moveTopLeft(d["pt"] - d["offset"])
        return r

    def _finish_drag(self):
        d = self._drag
        from_rect = self._drag_rect()
        self._drag = None
        self._rows_fixed = None
        self.releaseKeyboard()
        if d["valid"] and d["result"] in ("ok", "reflow") and d["new"] != d["start"]:
            self.tiles = d["new"]
            self._fix_height()
            self._show(d["new"], start_from={d["key"]: from_rect})     # glide into the target cells
            self.dropped.emit(copy.deepcopy(d["new"]), d["key"], d["result"])
        else:
            self._fix_height()
            self._show(d["start"], start_from={d["key"]: from_rect})   # same place / spring back
            if not d["valid"]:
                self.rejected.emit(d["key"])
        self.update()
        self.drag_changed.emit(False)

    # --- paint --------------------------------------------------------------------------
    def paintEvent(self, ev):
        if self.card:
            return self._paint_card()
        c = ui_colors(self.light)
        acc = "#1565c0" if self.light else "#4fc3f7"
        bad = "#c62828" if self.light else "#e53935"
        btn, btn_t = ("#e0e0e0", "#222222") if self.light else ("#3a3a3a", "#e0e0e0")
        prim = "#1565c0" if self.light else "#1f5f8b"
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        drag = self._drag
        used = tiles.occupied(self.view)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(c["card_b"] if self.light else "#4a4a4a"), 1, Qt.PenStyle.DashLine))
        for r in range(self.rows()):
            for col in range(tiles.COLS):
                if drag or (col, r) not in used:
                    p.drawRoundedRect(self.cell_rect(col, r).adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
        f = self.font()
        f.setPixelSize(12 if self.editable else 11)
        p.setFont(f)
        fm = QFontMetrics(f)
        def draw_tile(a, rc, sel=False, alpha=255, dashed=False):
            status = tiles.TYPES[a["typ"]]["kind"] == "status"
            fill = QColor(c["pill"] if status else (prim if a["typ"] == "boot" else btn))
            fg = QColor(c["pill_t"] if status else ("#ffffff" if a["typ"] == "boot" else btn_t))
            fill.setAlpha(alpha)
            fg.setAlpha(min(255, alpha + 60))
            p.setBrush(fill)
            if sel:
                p.setPen(QPen(QColor(acc), 2, Qt.PenStyle.DashLine if dashed else Qt.PenStyle.SolidLine))
            else:
                p.setPen(QPen(fill, 1))
            p.drawRoundedRect(rc.adjusted(1, 1, -1, -1), 5, 5)
            p.setPen(fg)
            txt = ("● " if status else "") + tile_text(a)
            p.drawText(rc, Qt.AlignmentFlag.AlignCenter,
                       fm.elidedText(txt, Qt.TextElideMode.ElideRight, int(rc.width()) - 6))

        for a in self.view:
            if not tiles.is_active(a) or (drag and tiles.key(a) == drag["key"]):
                continue
            rc = self._shown_rect(tiles.key(a)) or self.tile_rect(a)
            draw_tile(a, rc, sel=(not drag and tiles.key(a) == self.selected))
        if drag:
            a = drag["start"][drag["idx"]]
            if drag["inside"]:
                # target cells light up (each cell, clipped to the grid): accent / red
                col = QColor(acc if drag["valid"] else bad)
                fill = QColor(col)
                fill.setAlpha(90 if drag["valid"] else 110)
                p.setBrush(fill)
                p.setPen(QPen(col, 2))
                for cc, rr in sorted(tiles.cells(drag["pos"], a["groesse"])):
                    if 0 <= cc < tiles.COLS and 0 <= rr < self.rows():
                        p.drawRoundedRect(self.cell_rect(cc, rr).adjusted(1, 1, -1, -1), 4, 4)
            # the dragged tile: semi-transparent ghost following the pointer
            rc = self._drag_rect()
            p.setBrush(QColor(0, 0, 0, 40))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(rc.translated(3, 4).adjusted(1, 1, -1, -1), 5, 5)
            draw_tile(a, rc, sel=True, alpha=150, dashed=not drag["valid"])
        p.end()

    def _paint_card(self):
        """Edit mode (card): tiles drawn like the real buttons, each with the ⠿ grip and
        a static lifted shadow; while dragging only drop slots of this grid light up."""
        light = self.light
        c = ui_colors(light)
        acc = accent_color(light)
        bad = QColor("#c62828" if light else "#e53935")
        if light:
            b_fill, b_line, b_txt, p_fill = QColor("#ececec"), QColor("#c8c8c8"), QColor("#222222"), QColor("#1565c0")
        else:
            b_fill, b_line, b_txt, p_fill = QColor("#333333"), QColor("#4a4a4a"), QColor("#e6e6e6"), QColor("#1f5f8b")
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        f = QFont(self.font())
        f.setPixelSize(15)
        fb = QFont(f)
        fb.setPixelSize(17)
        fb.setBold(True)
        fs = QFont(self.font())
        fs.setPixelSize(11)
        drag = self._drag

        def label(a):
            if tiles.TYPES[a["typ"]]["kind"] == "status":
                return "● " + tile_text(a)
            act = tiles.TYPES[a["typ"]]["action"]
            txt = t("steam_launch") if act == "steam" else t(act)
            return txt + (f' {a["dup"] + 1}' if tiles.is_dup(a) else "")

        def tile(a, rc, alpha=1.0, border=None, grip_col=None, shadow=1.0):
            status = tiles.TYPES[a["typ"]]["kind"] == "status"
            prim = a["typ"] == "boot" and self.wake_primary
            r = QRectF(rc).adjusted(2, 1, -2, -3)            # raised a little: room for the shadow
            if shadow:
                paint_lifted(p, r, 6, shadow)
            fill = QColor(c["pill"]) if status else QColor(p_fill if prim else b_fill)
            fill.setAlphaF(alpha)
            p.setBrush(fill)
            p.setPen(QPen(p_fill.lighter(120) if prim else b_line, 1))
            p.drawRoundedRect(r, 6, 6)
            if border is not None:
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(border)
                p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
            fg = QColor("#ffffff" if prim else (c["pill_t"] if status else b_txt))
            gc = QColor(grip_col) if grip_col is not None else QColor(fg)
            if grip_col is None:
                gc.setAlphaF(0.45)
            paint_grip(p, r.x() + 11, r.center().y(), gc)
            fg.setAlphaF(min(1.0, alpha + 0.1))
            big = a["groesse"] == "gross"
            p.setFont(fb if big else f)
            p.setPen(fg)
            p.drawText(r, Qt.AlignmentFlag.AlignCenter,
                       QFontMetrics(fb if big else f).elidedText(label(a), Qt.TextElideMode.ElideRight, int(r.width()) - 44))

        if drag:
            a = drag["start"][drag["idx"]]
            cw, chh = tiles.SIZES[a["groesse"]]
            target = tuple(drag["pos"]) if drag["inside"] else None
            origin = tuple(a["pos"])
            slots = self.drop_slots()
            if target is not None and drag["valid"] and target not in slots:
                slots.append(target)
            for cc, rr in slots:
                rc = self.cell_rect(cc, rr, cw, chh).adjusted(2, 1, -2, -3)
                tgt = (cc, rr) == target and drag["valid"]
                fl = QColor(acc)
                fl.setAlphaF(0.18 if tgt else 0.06)
                p.setBrush(fl)
                p.setPen(QPen(acc, 2 if tgt else 1.5, Qt.PenStyle.DotLine))
                p.drawRoundedRect(rc, 6, 6)
                if tgt or (cc, rr) == origin:
                    p.setFont(fs)
                    p.setPen(acc)
                    p.drawText(rc.adjusted(0, 0, 0, -3), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                               t("slot_here") if tgt else t("slot_origin"))
            if target is not None and not drag["valid"]:
                fl = QColor(bad)
                fl.setAlphaF(0.30)
                p.setBrush(fl)
                p.setPen(QPen(bad, 2))
                for cc, rr in sorted(tiles.cells(drag["pos"], a["groesse"])):
                    if 0 <= cc < tiles.COLS and 0 <= rr < self.rows():
                        p.drawRoundedRect(self.cell_rect(cc, rr).adjusted(2, 1, -2, -3), 6, 6)
        for a in self.view:
            if not tiles.is_active(a) or (drag and tiles.key(a) == drag["key"]):
                continue
            rc = self._shown_rect(tiles.key(a)) or self.tile_rect(a)
            if not drag and tiles.key(a) == self.selected:
                tile(a, rc, border=QPen(acc, 3), grip_col=acc)
            else:
                tile(a, rc, shadow=0.6 if drag else 1.0)
        if drag:
            a = drag["start"][drag["idx"]]
            rc = self._drag_rect()
            p.setBrush(QColor(0, 0, 0, 60))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(rc.translated(5, 8).adjusted(2, 1, -2, -3), 6, 6)
            col = acc if drag["valid"] else bad
            tile(a, rc, alpha=0.9, border=QPen(col, 2, Qt.PenStyle.SolidLine if drag["valid"] else Qt.PenStyle.DashLine),
                 grip_col=col, shadow=0)
        if self.hasFocus() and not drag:
            win = self.window()
            im = getattr(win, "input_mode", None)
            if im is None or im.nav_visible:
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(acc, 1, Qt.PenStyle.DotLine))
                p.drawRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
        p.end()


class HostDialog(QDialog):
    """Add a host / connection settings of a host.
    Adding: connection fields + tile template (read-only preview).
    Editing (⚙ on the card): connection only - name, IP, MAC, Buddy port and
    "Delete host…" (confirmation with a red button). The tiles are arranged in the
    edit mode of the main window (✎ Bearbeiten / Ctrl+E), not here; editing keeps
    host["aktionen"] exactly as it is."""
    DELETE = 2          # exec() result: the user confirmed deleting the host

    def __init__(self, host: dict | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("conn_title") if host else t("add_host"))
        self.setStyleSheet(dialog_stylesheet(parent))
        self.host = host
        self._light = bool(parent and hasattr(parent, "cfg") and parent.cfg.get("settings", {}).get("theme", "Dark") == "Light")
        light = self._light
        self._tiles = tiles.template()       # adding only
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)
        top = QHBoxLayout()
        top.setSpacing(18)
        left = QVBoxLayout()
        left.setSpacing(10)
        layout = QFormLayout()
        layout.setSpacing(12)
        left.addLayout(layout)
        top.addLayout(left, 1)
        outer.addLayout(top)

        self.name_edit = QLineEdit(host.get("name", "") if host else "")
        self.ip_edit = QLineEdit(host.get("ip", "") if host else "")
        self.mac_edit = QLineEdit(host.get("mac") or "" if host else "")
        self.port_edit = QLineEdit(str(host.get("buddy_port", 59999)) if host else "59999")
        self.port_edit.setValidator(QIntValidator(1, 65535, self.port_edit))
        self.port_edit.setPlaceholderText("59999")
        self.port_error = QLabel(t("port_invalid"))
        self.port_error.setStyleSheet(f"color: {ui_colors(light)['err']};")
        self.port_error.setWordWrap(True)
        self.port_error.setVisible(False)
        self.port_edit.textChanged.connect(lambda _: self.port_error.setVisible(False))
        layout.addRow(t("name"), self.name_edit)
        layout.addRow(t("ip"), self.ip_edit)
        layout.addRow(t("mac"), self.mac_edit)
        layout.addRow(t("buddy_port"), self.port_edit)
        layout.addRow("", self.port_error)

        self.preview = None
        self.tpl_combo = None
        if host is None:
            # adding: the template is the only tile choice (finer changes later in edit mode)
            self.tpl_combo = QComboBox()
            for name in tiles.TEMPLATE_ORDER:
                self.tpl_combo.addItem(t(f"tpl_{name}"), name)
            self.tpl_combo.setCurrentIndex(tiles.TEMPLATE_ORDER.index(tiles.DEFAULT_TEMPLATE))
            self.tpl_combo.setToolTip(t("tip_template"))
            self.tpl_combo.currentIndexChanged.connect(lambda _: self._apply_template())
            layout.addRow(t("tiles_template"), self.tpl_combo)
            side = QVBoxLayout()
            side.setSpacing(6)
            pv_lbl = QLabel(t("tiles_preview"))
            pv_lbl.setObjectName("dlgSection")
            side.addWidget(pv_lbl)
            self.preview = TilePreview(light, editable=False)
            side.addWidget(self.preview)
            self.tpl_state = QLabel()
            self.tpl_state.setObjectName("dlgHint")
            self.tpl_state.setWordWrap(True)
            side.addWidget(self.tpl_state)
            side.addStretch(1)
            top.addLayout(side, 1)
        else:
            hint = QLabel(t("conn_tiles_hint"))
            hint.setObjectName("dlgHint")
            hint.setWordWrap(True)
            left.addWidget(hint)

        # --- buttons --------------------------------------------------------------
        btns = QHBoxLayout()
        if host is not None:
            self.delete_btn = QPushButton(t("delete_host"))
            self.delete_btn.setProperty("danger", True)
            self.delete_btn.setToolTip(t("tip_remove"))
            self.delete_btn.clicked.connect(self._confirm_delete)
            btns.addWidget(self.delete_btn)
            btns.addStretch(1)
        self.save_btn = QPushButton(t("save"))
        self.save_btn.clicked.connect(self.accept)
        self.cancel_btn = QPushButton(t("cancel"))
        self.cancel_btn.clicked.connect(self.reject)
        btns.addWidget(self.save_btn)
        btns.addWidget(self.cancel_btn)
        outer.addLayout(btns)
        self.setStyleSheet(self.styleSheet() + f"""
            QLabel#dlgSection {{ font-size: 12px; font-weight: bold; letter-spacing: 1px; color: {ui_colors(light)['sub']}; }}
            QLabel#dlgHint {{ font-size: 13px; color: {ui_colors(light)['sub']}; }}
        """)
        self._sync()
        install_dialog_nav(self)
        fit_dialog_to_screen(self)

    def _apply_template(self):
        """Adding: the chosen template replaces the preview (nothing to undo yet)."""
        self._tiles = tiles.apply_template(self._tiles, self.tpl_combo.currentData())
        self._sync()

    def _sync(self):
        if self.preview is None:
            return
        self.preview.set_tiles(self._tiles)
        cur = tiles.matching_template(self._tiles)
        self.tpl_state.setText(t("tiles_current", name=t(f"tpl_{cur}") if cur else t("tpl_custom")))

    def _confirm_delete(self):
        name = (self.host or {}).get("name") or (self.host or {}).get("ip", "")
        box = QMessageBox(self)
        box.setWindowTitle(t("delete_host_title"))
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(t("confirm_remove", name=name))
        box.setInformativeText(t("delete_host_detail"))
        box.setStyleSheet(dialog_stylesheet(self.parent()))
        delete = box.addButton(t("delete_confirm_btn"), QMessageBox.ButtonRole.DestructiveRole)
        delete.setProperty("danger", True)
        delete.style().unpolish(delete)     # the button was already polished by addButton()
        delete.style().polish(delete)
        cancel = box.addButton(t("cancel"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)        # Enter / A on the controller never deletes by accident
        box.setEscapeButton(cancel)
        box.exec()
        if box.clickedButton() is delete:
            self.done(self.DELETE)

    def _port(self) -> int | None:
        """Buddy port from the field: empty = default 59999, None = invalid."""
        txt = self.port_edit.text().strip()
        if not txt:
            return 59999
        try:
            port = int(txt)
        except ValueError:
            return None
        return port if 1 <= port <= 65535 else None

    def accept(self):
        if self._port() is None:
            self.port_error.setVisible(True)
            self.port_edit.setFocus()
            self.port_edit.selectAll()
            return
        super().accept()

    def get_data(self) -> dict | None:
        ip = self.ip_edit.text().strip()
        if not ip:
            return None
        data = dict(self.host) if self.host else {}    # keeps keys this version does not know
        data.update({
            "id": self.host.get("id") if self.host else uuid.uuid4().hex[:8],
            "name": self.name_edit.text().strip() or ip,
            "ip": ip,
            "mac": self.mac_edit.text().strip() or None,
            "buddy_port": self._port() or 59999,
        })
        if self.host is None:
            # the chosen template, exact positions, current layout revision
            data["aktionen"] = tiles.copy_tiles(self._tiles)
            data["layout_rev"] = tiles.LAYOUT_REV
        return data

# ---------------------------------------------------------------------------
# UI only: destructive confirmations default to "No" (controller/Enter safety)
_YES_NO = QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
_NO = QMessageBox.StandardButton.No

_NAV_KEYS = (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down)


# ---------------------------------------------------------------------------


# --- UI only: main toolbar items ("App-Steuerung") ------------------------------------
# id -> (glyph, label key, tooltip key). The four items can be moved and resized
# (klein = icon only, mittel = icon + label) in edit mode, but never hidden or removed.
TOOLBAR_ITEMS = {
    "add": ("＋", "add_host", "tip_add"),
    "refresh": ("⟳", "refresh", "tip_refresh"),
    "edit": ("✎", "edit_mode", "tip_edit_mode"),
    "options": ("☰", "options", "tip_options"),
}
TOOLBAR_ORDER = ["add", "refresh", "edit", "options"]
TOOLBAR_SIZES = ("klein", "mittel")


def toolbar_items(raw) -> list:
    """settings["toolbar"] cleaned up: every item exactly once (unknown ids dropped,
    missing ones appended), size klein/mittel."""
    out, seen = [], set()
    for it in raw if isinstance(raw, list) else []:
        if isinstance(it, dict) and it.get("id") in TOOLBAR_ITEMS and it["id"] not in seen:
            seen.add(it["id"])
            out.append({"id": it["id"], "groesse": it.get("groesse") if it.get("groesse") in TOOLBAR_SIZES else "klein"})
    out += [{"id": i, "groesse": "klein"} for i in TOOLBAR_ORDER if i not in seen]
    return out


class _EscWhileDragging(QObject):
    """UI only: while a drag runs, Esc cancels it wherever the keyboard focus is (a pressed
    QPushButton would otherwise swallow the key)."""
    def __init__(self, parent, on_esc):
        super().__init__(parent)
        self.on_esc = on_esc

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.KeyPress and ev.key() == Qt.Key.Key_Escape:
            self.on_esc()
            return True
        return False


class _ReorderDrag(QObject):
    """UI only: drag and drop to reorder a row of widgets (the host cards, vertical, or
    the toolbar items, horizontal). Mouse: press and move; touch: hold ~350 ms, then
    move. While dragging a translucent ghost follows the pointer and an accent line
    marks the drop gap; on release the ghost slides into its new place.
    source(obj) -> the item widget an event belongs to (or None), items() -> the items
    in their current order, container() -> the widget that hosts ghost and line,
    commit(src, index) -> applies the new order, outside(src) -> called when the item
    is dropped far away from the row (toolbar: cannot be removed).
    Edit mode concept 2: gap(index | None) opens a real gap in the row at the drop
    place (a dotted slot with an insertion marker is drawn there), on_state(bool)
    reports drag start / end (drop focus + hint text)."""
    HOLD_MS = 350
    SLOP = 14
    OUT_DIST = 70

    def __init__(self, win, horizontal, source, items, container, commit, outside=None, scroll=None,
                 gap=None, on_state=None):
        super().__init__(win)
        self.win = win
        self.horizontal = horizontal
        self.source, self.items, self.container = source, items, container
        self.commit, self.outside, self.scroll = commit, outside, scroll
        self.gap, self.on_state = gap, on_state
        self._gap_idx = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(self.HOLD_MS)
        self.timer.timeout.connect(self._hold)
        self._p = None          # pending press: dict(src, gpos, touch)
        self.drag = None        # dict while dragging
        self._anim = None

    def watch(self, w):
        w.installEventFilter(self)

    @property
    def active(self) -> bool:
        return self.drag is not None

    def eventFilter(self, obj, ev):
        et = ev.type()
        try:
            if et == QEvent.Type.MouseButtonPress and ev.button() == Qt.MouseButton.LeftButton:
                if self.drag is None:
                    src = self.source(obj)
                    if src is not None:
                        self._p = {"src": src, "gpos": ev.globalPosition().toPoint(),
                                   "touch": _CardLongPress.is_touch(ev)}
                        if self._p["touch"]:
                            self.timer.start()
            elif et == QEvent.Type.MouseMove:
                g = ev.globalPosition().toPoint()
                if self.drag is not None:
                    self.move_to(g)
                    return True
                if self._p is not None:
                    d = (g - self._p["gpos"]).manhattanLength()
                    if self._p["touch"]:
                        if d > self.SLOP:          # finger moved before the hold: a scroll/swipe
                            self.timer.stop()
                            self._p = None
                    elif d >= max(8, QApplication.startDragDistance()):
                        self.begin(self._p["src"], self._p["gpos"])
                        self.move_to(g)
                        return True
            elif et == QEvent.Type.MouseButtonRelease:
                self.timer.stop()
                self._p = None
                if self.drag is not None:
                    self.drop(ev.globalPosition().toPoint())
                    if isinstance(obj, QAbstractButton):
                        obj.setDown(False)
                    return True              # the drag was the gesture: no click
        except RuntimeError:
            self._p = None
        return False

    def _hold(self):
        p, self._p = self._p, None
        if p is not None and self.drag is None:
            self.begin(p["src"], p["gpos"])

    # --- the drag itself -----------------------------------------------------------
    def _rect(self, w) -> QRect:
        c = self.container()
        return QRect(w.mapTo(c, QPoint(0, 0)), w.size())

    def begin(self, src, gpos):
        if self.drag is not None or src is None:
            return
        self.finish_anim()
        c = self.container()
        c.layout().activate() if c.layout() else None
        pm = src.grab()
        faded = QPixmap(pm.size())
        faded.setDevicePixelRatio(pm.devicePixelRatio())
        faded.fill(Qt.GlobalColor.transparent)
        p = QPainter(faded)
        p.setOpacity(0.96)
        p.drawPixmap(0, 0, pm)
        p.end()
        ghost = QLabel(c)
        ghost.setObjectName("dragGhost")
        ghost.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        ghost.setPixmap(faded)
        ghost.setStyleSheet("background: transparent; border: none;")
        r = self._rect(src)
        ghost.setGeometry(r)
        ghost.show()
        ghost.raise_()
        line = _DropSlot(c, self.horizontal, self.win._light())
        line.show()
        eff = QGraphicsOpacityEffect(src)
        eff.setOpacity(0.3)
        src.setGraphicsEffect(eff)
        self.drag = {"src": src, "ghost": ghost, "line": line, "off": src.mapFromGlobal(gpos),
                     "start": r.topLeft(), "index": None, "out": False}
        self._esc = _EscWhileDragging(self, self.cancel)
        QApplication.instance().installEventFilter(self._esc)
        if self.on_state:
            self.on_state(True)
        self.move_to(gpos)

    def _others(self, src):
        return [w for w in self.items() if w is not src and not w.isHidden()]

    def move_to(self, gpos):
        d = self.drag
        if d is None:
            return
        c = self.container()
        if self.scroll is not None and not self.horizontal:       # scroll while near the edge
            vp = self.scroll.viewport()
            y = vp.mapFromGlobal(gpos).y()
            bar = self.scroll.verticalScrollBar()
            if y < 28:
                bar.setValue(bar.value() - 14)
            elif y > vp.height() - 28:
                bar.setValue(bar.value() + 14)
        p = c.mapFromGlobal(gpos)
        src_r = self._rect(d["src"])
        top_left = p - d["off"]
        if self.horizontal:
            d["ghost"].move(top_left.x(), src_r.y())
            d["out"] = self.outside is not None and abs(p.y() - src_r.center().y()) > self.OUT_DIST
        else:
            d["ghost"].move(src_r.x(), top_left.y())
        d["ghost"].raise_()
        others = self._others(d["src"])
        pos = p.x() if self.horizontal else p.y()     # the pointer/finger decides, not the ghost centre
        idx = sum(1 for w in others if (self._rect(w).center().x() if self.horizontal
                                         else self._rect(w).center().y()) < pos)
        d["index"] = idx
        line = d["line"]
        if d["out"] or not others:
            self._set_gap(None)
            line.hide()
            return
        if self.gap is not None:
            self._set_gap(idx)
            slot = self._slot_rect(others, idx)
            line.setGeometry(slot)
            line.show()
            line.raise_()
            d["ghost"].raise_()
            return
        if idx < len(others):
            r = self._rect(others[idx])
            a = (r.left() if self.horizontal else r.top()) - 5
        else:
            r = self._rect(others[-1])
            a = (r.right() if self.horizontal else r.bottom()) + 4
        a = max(a, 1)
        if self.horizontal:
            line.setGeometry(a - 1, r.top(), 4, r.height())
        else:
            line.setGeometry(r.left(), a - 1, r.width(), 4)
        line.show()
        line.raise_()

    def _set_gap(self, idx):
        if self.gap is None or idx == self._gap_idx:
            return
        self._gap_idx = idx
        try:
            self.gap(idx)
            c = self.container()
            for w in [c] + list(self.items()):
                p = w.parentWidget() if w is not c else w
                if p is not None and p.layout():
                    p.layout().activate()
        except RuntimeError:
            pass

    def _slot_rect(self, others, idx) -> QRect:
        """The dotted slot inside the gap the drop would land in."""
        sp = 8
        if self.horizontal:
            ref = self._rect(others[min(idx, len(others) - 1)])
            g = _DropSlot.GAP_H
            x = ref.left() - sp - g if idx < len(others) else ref.right() + 1 + sp
            return QRect(x, ref.top(), g, ref.height())
        ref = self._rect(others[min(idx, len(others) - 1)])
        g = _DropSlot.GAP_V
        y = ref.top() - sp - g if idx < len(others) else ref.bottom() + 1 + sp
        return QRect(ref.left(), y, ref.width(), g)

    def drop(self, gpos):
        d = self.drag
        if d is None:
            return
        self.move_to(gpos)
        self._set_gap(None)
        src = d["src"]
        if d["out"]:
            if self.outside:
                self.outside(src)
            self._land(d, self._rect(src).topLeft())
            return
        self.commit(src, d["index"])
        try:
            c = self.container()
            if c.layout():
                c.layout().activate()
            for w in [src] + list(self.items()):
                p = w.parentWidget()
                if p is not None and p.layout():
                    p.layout().activate()
            target = self._rect(src).topLeft()
        except RuntimeError:
            target = d["start"]
        self._land(d, target)

    def cancel(self):
        d = self.drag
        if d is not None:
            self._land(d, d["start"])

    def _land(self, d, target):
        """Slide the ghost into place, then clean up."""
        self.drag = None
        esc = getattr(self, "_esc", None)
        if esc is not None:
            QApplication.instance().removeEventFilter(esc)
            esc.deleteLater()
            self._esc = None
        self._set_gap(None)
        if self.on_state:
            self.on_state(False)
        try:
            d["line"].hide()
            if d["src"].graphicsEffect() is not None:
                d["src"].graphicsEffect().setOpacity(0.0)
        except RuntimeError:
            pass
        anim = QPropertyAnimation(d["ghost"], b"pos", self)
        anim.setDuration(170)
        anim.setStartValue(d["ghost"].pos())
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve(QEasingCurve.Type.OutCubic))
        anim.finished.connect(lambda dd=d: self._cleanup(dd))
        self._anim = (anim, d)
        anim.start()

    def finish_anim(self):
        if self._anim is not None:
            anim, d = self._anim
            anim.stop()
            self._cleanup(d)

    def _cleanup(self, d):
        if self._anim is not None and self._anim[1] is d:
            self._anim = None
        for k in ("ghost", "line"):
            try:
                d[k].hide()
                d[k].deleteLater()
            except RuntimeError:
                pass
        try:
            d["src"].setGraphicsEffect(None)
        except RuntimeError:
            pass


class _DropSlot(QWidget):
    """UI only (edit mode): the dotted slot in the gap a toolbar icon (vertical marker)
    or a host card (horizontal line) would be dropped into. Static, no animation."""
    GAP_H = 56          # toolbar gap width
    GAP_V = 48          # card list gap height

    def __init__(self, parent, horizontal, light):
        super().__init__(parent)
        self.setObjectName("dropLine")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.horizontal = horizontal
        self.acc = accent_color(light)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        fill = QColor(self.acc)
        fill.setAlphaF(0.12 if self.horizontal else 0.10)
        p.setBrush(fill)
        p.setPen(QPen(self.acc, 1.5, Qt.PenStyle.DotLine))
        p.drawRoundedRect(r, 8, 8)
        pen = QPen(self.acc, 3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(self.acc)
        if self.horizontal:          # vertical insertion marker with end dots
            x = r.left() + 6
            p.drawLine(QPointF(x, r.top() + 6), QPointF(x, r.bottom() - 6))
            p.setPen(Qt.PenStyle.NoPen)
            for y in (r.top() + 6, r.bottom() - 6):
                p.drawEllipse(QPointF(x, y), 4, 4)
        else:                        # horizontal insertion line at the top of the gap
            y = r.top() + 2
            p.drawLine(QPointF(r.left() + 8, y), QPointF(r.right() - 8, y))
            p.setPen(Qt.PenStyle.NoPen)
            for x in (r.left() + 8, r.right() - 8):
                p.drawEllipse(QPointF(x, y), 4, 4)
        p.end()


class _DropFocus(QWidget):
    """UI only (edit mode, while dragging): calms everything except the one valid drop
    zone (window colour at 72 % on top), the zone gets a soft accent frame."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("dropFocus")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.zone = None            # QRect in our coordinates
        self.keep = None            # QRect that stays readable (the hint text), no frame
        self.light = False
        self.hide()

    def paintEvent(self, ev):
        if self.zone is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        hole = QPainterPath()
        hole.addRoundedRect(QRectF(self.zone), 10, 10)
        full = QPainterPath()
        full.addRect(QRectF(self.rect()))
        wc = QColor(QApplication.palette().window().color())
        wc.setAlphaF(0.72)
        veil = full.subtracted(hole)
        if self.keep is not None:               # the hint text stays readable
            keep = QPainterPath()
            keep.addRect(QRectF(self.keep))
            veil = veil.subtracted(keep)
        p.fillPath(veil, wc)
        acc = accent_color(self.light)
        glow = QColor(acc)
        glow.setAlphaF(0.25)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(glow, 6))
        p.drawRoundedRect(QRectF(self.zone).adjusted(-3, -3, 3, 3), 12, 12)
        p.setPen(QPen(acc, 2))
        p.drawRoundedRect(QRectF(self.zone), 10, 10)
        p.end()


class _TbButton(QPushButton):
    """Toolbar item; in edit mode it shows the ⠿ grip in its top left corner."""
    grip = None             # QColor while in edit mode

    def paintEvent(self, ev):
        super().paintEvent(ev)
        if self.grip is not None:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            paint_grip(p, 6, 10, self.grip, r=1.2, step=3.5)
            p.end()


class _TbGroup(QFrame):
    """The App-Steuerung group; in edit mode its items get the calm lifted shadow."""
    lifted = False

    def paintEvent(self, ev):
        super().paintEvent(ev)
        if not self.lifted:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for b in self.findChildren(QPushButton):
            if b.isVisible() and b.graphicsEffect() is None:
                paint_lifted(p, QRectF(b.geometry()), 8)
        p.end()


class _HostArea(QWidget):
    """The host card list; in edit mode the cards get the calm lifted shadow."""
    lifted = False

    def paintEvent(self, ev):
        opt = QStyleOption()
        opt.initFrom(self)
        p = QPainter(self)
        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget, opt, p, self)
        if self.lifted:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            for r in self.findChildren(HostRow):
                if r.isVisible() and r.parentWidget() is self and r.graphicsEffect() is None:
                    paint_lifted(p, QRectF(r.geometry()), 10)
        p.end()


class _LogHandle(QSplitterHandle):
    """UI only: the divider between host list and log, a 48 px row (touch target) with
    "▸ Log (Strg+L)" on the left. Only while the log is open (resizable) it can be
    dragged, and a small grip sits directly on the top edge of the log text field;
    double click resets the log height."""
    HEIGHT = 48

    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.on_reset = None
        self.resizable = False
        self.setCursor(Qt.CursorShape.ArrowCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 6)
        lay.setSpacing(0)
        self._lay = lay

    def set_button(self, btn):
        self._lay.addWidget(btn, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._lay.addStretch(1)

    def set_resizable(self, on: bool):
        self.resizable = bool(on)
        self.setCursor(Qt.CursorShape.SplitVCursor if on else Qt.CursorShape.ArrowCursor)
        self.update()

    def grip_visible(self) -> bool:
        """The grip is painted only while the log is open (tests, screenshots)."""
        return self.resizable and self.isVisible()

    def sizeHint(self):
        s = super().sizeHint()
        return QSize(s.width(), self.HEIGHT)

    def mousePressEvent(self, ev):
        if self.resizable:
            super().mousePressEvent(ev)
        else:
            ev.accept()

    def mouseMoveEvent(self, ev):
        if self.resizable:
            super().mouseMoveEvent(ev)
        else:
            ev.accept()

    def mouseReleaseEvent(self, ev):
        if self.resizable:
            super().mouseReleaseEvent(ev)
        else:
            ev.accept()

    def mouseDoubleClickEvent(self, ev):
        if self.resizable and self.on_reset:
            self.on_reset()
        ev.accept()

    def paintEvent(self, ev):
        if not self.resizable:
            return
        light = self.window().cfg.get("settings", {}).get("theme", "Dark") == "Light" if hasattr(self.window(), "cfg") else False
        c = ui_colors(light)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = QColor(c["cur_b"] if self.underMouse() else c["sub"])
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        w = 44
        p.drawRoundedRect(QRectF((self.width() - w) / 2, self.height() - 5, w, 4), 2, 2)   # on the log's top edge
        p.end()


class _LogSplitter(QSplitter):
    def createHandle(self):
        return _LogHandle(self.orientation(), self)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = load_config()
        setup_logging(self.cfg["settings"].get("logging", False))
        self.signals = Signals()
        self.signals.host_status.connect(self.on_host_status)
        self.signals.update_result.connect(self.on_update_result)
        self._pending_update: dict | None = None   # found while the window was hidden
        self._update_running = False
        self._options_dlg = None
        self._checking: set[str] = set()      # host ids with a check in flight
        self._checking_lock = threading.Lock()
        self.signals.action_started.connect(self.on_action_started)
        self.signals.action_done.connect(self.on_action_done)
        # custom MoonDeck CLI (Options › Dateien): state changes come from any thread
        self.signals.cli_state.connect(self.on_cli_state)
        self._cli_toast_for = None          # (state, path) the A4 toast was shown for
        backend.set_cli_listener(self.signals.cli_state.emit)
        backend.set_custom_cli(self.cfg["settings"].get("custom_cli", ""))
        QTimer.singleShot(1500, self._probe_custom_cli)
        self.action_locks: dict[str, threading.Lock] = {}
        self.host_rows: dict[str, HostRow] = {}
        self.host_state: dict[str, dict] = {}   # last status check per host id (survives refresh_hosts)
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.check_status)
        # edit mode (4c): arrange the tiles directly in the cards
        self._edit_mode = False
        self._editing = False
        self._edit_hid = None
        self._edit_sel = None               # (host id, tile key) or None
        self._edit_undo: list = []          # (host id, tiles before, selection, message)
        self._edit_redo: list = []
        self._edit_show_hidden = False
        self._menu = None
        self.long_press = _CardLongPress(self)
        # edit mode: cards are reordered by drag and drop (header / empty card area)
        self._edit_drag = None              # "tile" / "tb" / "card" while dragging (drop focus + hint)
        self._gap_items = {}                # layout -> spacer item of the open drag gap
        self.card_drag = _ReorderDrag(self, False, self._card_drag_source,
                                      lambda: list(self.host_rows.values()),
                                      lambda: self.host_widget, self._card_drag_commit, scroll=None,
                                      gap=self._card_gap,
                                      on_state=lambda on: self.edit_drag_state("card" if on else None))

        self.setWindowTitle(t("app_title"))
        self.apply_theme()

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Toolbar ("App-Steuerung"): icon buttons ＋ ⟳ ✎ ☰ (tooltip = label + shortcut),
        # order/size editable in edit mode, never hidden; ⌃ slides the bar up, the slim
        # grip ⌄ brings it back (state in window.ini). Shortcuts work either way.
        self._tb_items = toolbar_items(self.cfg["settings"].get("toolbar"))
        self._tb_sel = None                 # edit mode: selected toolbar item id
        self.toolbar = QWidget()
        self.toolbar.setObjectName("toolbar")
        tb = QHBoxLayout(self.toolbar)
        tb.setContentsMargins(12, 8, 12, 8)
        tb.setSpacing(8)
        self.tb_group = _TbGroup()
        self.tb_group.setObjectName("tbGroup")
        self._tb_group_layout = gl = QHBoxLayout(self.tb_group)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setSpacing(8)
        self.tb_group_lbl = QLabel(t("tb_section"))     # edit mode: section label above the bar
        self.tb_group_lbl.setObjectName("tbGroupLbl")
        self.tb_group_lbl.hide()
        self.tb_btns = {}
        for iid in TOOLBAR_ORDER:
            glyph, label, tip = TOOLBAR_ITEMS[iid]
            b = _TbButton(glyph)
            b.setProperty("tbItem", True)
            b.setProperty("navKey", "tb_" + iid)
            b.setToolTip(t(tip))
            b.clicked.connect(lambda _=False, i=iid: self._tb_clicked(i))
            b.installEventFilter(self)
            self.tb_btns[iid] = b
        self.toolbar_buttons = [self.tb_btns[i] for i in TOOLBAR_ORDER]   # fixed order (InputModeController)
        tb.addWidget(self.tb_group)
        tb.addStretch()
        self.tb_collapse_btn = QPushButton("⌃")
        self.tb_collapse_btn.setObjectName("tbCollapse")
        self.tb_collapse_btn.setToolTip(t("tb_collapse"))
        self.tb_collapse_btn.setProperty("navKey", "tb_collapse")
        self.tb_collapse_btn.clicked.connect(lambda: self.set_toolbar_collapsed(True))
        self.tb_collapse_btn.installEventFilter(self)
        tb.addWidget(self.tb_collapse_btn)
        self.edit_btn = self.tb_btns["edit"]
        self.edit_btn.setCheckable(True)
        self.edit_done_btn = self.edit_btn      # one "✓ Fertig": the ✎ item turns into it in edit mode
        self.tb_grip = QPushButton("⌄")
        self.tb_grip.setObjectName("tbGrip")
        self.tb_grip.setToolTip(t("tb_expand"))
        self.tb_grip.setProperty("navKey", "tb_grip")
        self.tb_grip.clicked.connect(lambda: self.set_toolbar_collapsed(False))
        self.tb_grip.installEventFilter(self)
        self.tb_grip.hide()
        self._tb_collapsed = False
        self._tb_anim = None
        self.tb_drag = _ReorderDrag(self, True, self._tb_drag_source,
                                    lambda: [self.tb_btns[it["id"]] for it in self._tb_items],
                                    lambda: self.toolbar, self._tb_drag_commit, self._tb_drag_outside,
                                    gap=self._tb_gap,
                                    on_state=lambda on: self.edit_drag_state("tb" if on else None))
        for b in self.tb_btns.values():
            self.tb_drag.watch(b)
        self._tb_layout()
        main_layout.addWidget(self.tb_group_lbl)
        main_layout.addWidget(self.toolbar)
        main_layout.addWidget(self.tb_grip)
        main_layout.addWidget(self._build_edit_bar())

        body = QWidget()
        self._body_layout = QVBoxLayout(body)
        self._body_layout.setContentsMargins(12, 10, 12, 6)
        self._body_layout.setSpacing(6)
        main_layout.addWidget(body, 1)

        # Scroll area for hosts
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.host_widget = _HostArea()
        self.host_widget.setObjectName("hostArea")
        self.host_layout = QVBoxLayout(self.host_widget)
        self.host_layout.setContentsMargins(0, 0, 0, 0)
        self.host_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.host_layout.setSpacing(8)
        scroll.setWidget(self.host_widget)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)  # rows wrap instead
        self.scroll = scroll
        self._vp_watch = _ResizeWatcher(scroll.viewport(), self._relayout_rows)
        self.card_drag.scroll = scroll
        self._apply_host_area_theme()

        # Collapsible log (UI only; same log content as before). Its height is set with
        # the divider above it (mouse + touch), saved in window.ini; double click resets.
        self.log_btn = QPushButton()
        self.log_btn.setObjectName("logToggle")
        self.log_btn.setToolTip(t("tip_log"))
        self.log_btn.clicked.connect(self.toggle_log)
        self.log_btn.installEventFilter(self)

        # Output log (read-only)
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setMinimumHeight(self.LOG_MIN)
        self._apply_output_theme()
        self.log_panel = QWidget()
        self.log_panel.setObjectName("logPanel")
        lp_l = QVBoxLayout(self.log_panel)
        lp_l.setContentsMargins(0, 0, 0, 0)
        lp_l.setSpacing(0)
        lp_l.addWidget(self.output)
        self.splitter = _LogSplitter(Qt.Orientation.Vertical)
        self.splitter.setObjectName("logSplitter")
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(_LogHandle.HEIGHT)   # the row "▸ Log" + grip is the handle
        self.splitter.addWidget(scroll)
        self.splitter.addWidget(self.log_panel)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.log_handle = self.splitter.handle(1)
        self.log_handle.set_button(self.log_btn)
        self.log_handle.on_reset = self.reset_log_height
        self.splitter.splitterMoved.connect(self._on_log_split_moved)
        self._log_save_timer = QTimer(self)
        self._log_save_timer.setSingleShot(True)
        self._log_save_timer.setInterval(400)
        self._log_save_timer.timeout.connect(self._save_log_height)
        self._body_layout.addWidget(self.splitter, 1)

        # Status bar: current state (left: Bereit / Aktion läuft / Bearbeiten aktiv),
        # counts / auto refresh / CLI (right). Action feedback = toasts + log only.
        self.status_bar = QLabel(t("state_ready"))
        self.count_lbl = QLabel("")
        self.refresh_lbl = QLabel("")
        self.cli_lbl = QLabel("")
        sb = QStatusBar()
        sb.setSizeGripEnabled(False)
        # UI only: a long message must never push the right-hand labels out of the window
        self.status_bar.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        sb.addWidget(self.status_bar, 1)
        for w in (self.count_lbl, self.refresh_lbl, self.cli_lbl):
            sb.addPermanentWidget(w)
        self.setStatusBar(sb)
        self._apply_chrome_theme()

        self.drop_focus = _DropFocus(central)
        # Toast overlay (UI only)
        self.toast = Toast(central)
        self.update_toast = UpdateToast(central, self._open_update_page)
        for b in self.update_toast.buttons + self.toast.buttons:
            b.installEventFilter(self)

        st = QSettings(str(WINDOW_STATE_FILE), QSettings.Format.IniFormat)
        try:
            self._log_h = max(self.LOG_MIN, int(st.value("log_height", self.LOG_DEFAULT)))
        except (TypeError, ValueError):
            self._log_h = self.LOG_DEFAULT
        self._set_log_visible(str(st.value("log_visible", "false")).lower() == "true")
        if str(st.value("toolbar_collapsed", "false")).lower() == "true":
            self.set_toolbar_collapsed(True, animate=False, save=False)

        # UI only: keyboard shortcuts for existing toolbar actions
        for seq, slot in [("F5", self.check_status), ("Ctrl+N", self.add_host),
                          ("Ctrl+,", self.open_options), ("Ctrl+L", self.toggle_log)]:
            QShortcut(QKeySequence(seq), self, activated=slot)
        QShortcut(QKeySequence("Ctrl+E"), self, activated=self.toggle_edit_mode)
        self._edit_shortcuts = []
        for seq, fn in [("Ctrl+Z", self.edit_undo), ("Ctrl+Y", self.edit_redo), ("Ctrl+Shift+Z", self.edit_redo),
                        ("Ctrl+Up", lambda: self._ctrl_arrow(-1, False)), ("Ctrl+Down", lambda: self._ctrl_arrow(1, False)),
                        ("Ctrl+Left", lambda: self._ctrl_arrow(-1, True)), ("Ctrl+Right", lambda: self._ctrl_arrow(1, True))]:
            sc = QShortcut(QKeySequence(seq), self, activated=lambda f=fn: self._edit_shortcut(f))
            sc.setEnabled(False)
            self._edit_shortcuts.append(sc)
        QApplication.instance().focusChanged.connect(self._on_focus_changed)
        # UI only: focus ring mouse/keyboard modes + native gamepad input (SDL2, optional)
        self.input_mode = InputModeController(self)
        self.gamepad = GamepadBridge(self.input_mode)
        QTimer.singleShot(0, self.gamepad.start)

        self.refresh_hosts()
        self._update_status_bar()

        # Tray icon
        self.tray = QSystemTrayIcon(self)
        self._update_tray_icon(False)
        self.tray.setToolTip("BuddyRemote")
        menu = QMenu()
        menu.addAction(t("tray_show"), self.show_normal)
        menu.addSeparator()
        self.host_menu = menu.addMenu(t("tray_hosts"))
        menu.addSeparator()
        menu.addAction(t("tray_quit"), self.quit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.tray_activated)
        self.tray.show()
        self._update_tray_menu()

        # UI only: window size/state memory and screen fitting
        self._was_shown = False
        self._restore_window_state()
        QApplication.instance().aboutToQuit.connect(self._save_window_state)

        if self.cfg["settings"].get("auto_status", True):
            interval = self.cfg["settings"].get("status_interval", 30) * 1000
            self.status_timer.start(interval)
            QTimer.singleShot(1000, self.check_status)

        if self.cfg["settings"].get("check_updates", True):
            QTimer.singleShot(4000, self.check_for_updates)

        if self.start_hidden():
            QTimer.singleShot(100, self.hide)

        # First-run attribution
        if not (APP_DIR / ".attributed").exists():
            QTimer.singleShot(500, self._show_attribution)

    def apply_dark(self):
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor("#1e1e1e"))
        pal.setColor(QPalette.ColorRole.WindowText, QColor("#e0e0e0"))
        pal.setColor(QPalette.ColorRole.Base, QColor("#2a2a2a"))
        pal.setColor(QPalette.ColorRole.Text, QColor("#e0e0e0"))
        pal.setColor(QPalette.ColorRole.Button, QColor("#2d2d2d"))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor("#e0e0e0"))
        self.setPalette(pal)
        self.setStyleSheet("""
            QPushButton { background: #2d2d2d; color: #e0e0e0; border: 1px solid #444; padding: 4px 8px; border-radius: 3px; }
            QPushButton:hover { background: #3d3d3d; }
            QLineEdit, QSpinBox { background: #2a2a2a; color: #e0e0e0; border: 1px solid #444; padding: 3px; }
        """ + touch_css(False))

    def apply_light(self):
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor("#f5f5f5"))
        pal.setColor(QPalette.ColorRole.WindowText, QColor("#222222"))
        pal.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
        pal.setColor(QPalette.ColorRole.Text, QColor("#222222"))
        pal.setColor(QPalette.ColorRole.Button, QColor("#e0e0e0"))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor("#222222"))
        self.setPalette(pal)
        self.setStyleSheet("""
            QPushButton { background: #e0e0e0; color: #222; border: 1px solid #ccc; padding: 4px 8px; border-radius: 3px; }
            QPushButton:hover { background: #d0d0d0; }
            QLineEdit, QSpinBox { background: #ffffff; color: #222; border: 1px solid #ccc; padding: 3px; }
        """ + touch_css(True))

    def _apply_host_area_theme(self):
        if not hasattr(self, "host_widget"):
            return
        light = self.cfg.get("settings", {}).get("theme", "Dark") == "Light"
        if light:
            self.host_widget.setStyleSheet("QWidget#hostArea { background: #f5f5f5; }")
            self.scroll.setStyleSheet("QScrollArea { border: none; background: #f5f5f5; }"
                "QScrollBar:vertical { background: transparent; width: 10px; margin: 2px 0 2px 0; }"
                "QScrollBar::handle:vertical { background: #c4c4c4; border-radius: 4px; min-height: 32px; margin: 0 2px; }"
                "QScrollBar::handle:vertical:hover { background: #a8a8a8; }"
                "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
                "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }")
        else:
            self.host_widget.setStyleSheet("QWidget#hostArea { background: #1e1e1e; }")
            self.scroll.setStyleSheet("QScrollArea { border: none; background: #1e1e1e; }"
                "QScrollBar:vertical { background: transparent; width: 10px; margin: 2px 0 2px 0; }"
                "QScrollBar::handle:vertical { background: #4a4a4a; border-radius: 4px; min-height: 32px; margin: 0 2px; }"
                "QScrollBar::handle:vertical:hover { background: #5e5e5e; }"
                "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
                "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }")

    def _apply_output_theme(self):
        if not hasattr(self, "output"):
            return
        light = self.cfg.get("settings", {}).get("theme", "Dark") == "Light"
        if light:
            self.output.setStyleSheet("QTextEdit { background: #ffffff; color: #222; border: 1px solid #ccc; font-family: " + MONO_FAMILY + "; }")
        else:
            self.output.setStyleSheet("QTextEdit { background: #1a1a1a; color: #ccc; border: 1px solid #333; font-family: " + MONO_FAMILY + "; }")

    def _light(self) -> bool:
        return self.cfg.get("settings", {}).get("theme", "Dark") == "Light"

    def _apply_chrome_theme(self):
        """UI only: toolbar, log toggle and status bar colours."""
        if not hasattr(self, "tb_grip"):
            return
        light = self._light()
        c = ui_colors(light)
        done_t = "#ffffff" if light else "#1a1a1a"
        edit = self._edit_mode
        self._tb_group_layout.setContentsMargins(*((10, 6, 10, 9) if edit else (0, 0, 0, 0)))
        self.tb_group.lifted = edit
        self.tb_group_lbl.setStyleSheet(
            f"QLabel#tbGroupLbl {{ color: {c['edit']}; font-size: 12px; font-weight: bold; background: transparent;"
            f" padding: 6px 0px 0px 16px; }}")
        self.toolbar.setStyleSheet(
            f"QWidget#toolbar {{ border-bottom: 1px solid {c['tb_b']}; }}"
            + (f" QFrame#tbGroup {{ border: 1px solid {c['bar_b']}; border-radius: 10px; background: {c['edit_bg']}; }}"
               if edit else " QFrame#tbGroup { border: none; background: transparent; }")
            + f" QPushButton[tbItem=\"true\"][tbSel=\"true\"] {{ border: 2px solid {c['edit']}; background: {c['edit_bg']}; }}"
            f" QPushButton[tbItem=\"true\"][tbSize=\"klein\"] {{ font-size: 22px; padding: 0px 0px 2px 0px;"
            f" min-width: 44px; max-width: 44px; min-height: 42px; max-height: 42px; }}"
            f" QPushButton[tbItem=\"true\"][tbSize=\"mittel\"] {{ font-size: 15px; padding: 0px 14px; min-height: 44px; max-height: 44px; }}"
            f" QPushButton[tbItem=\"true\"][primary=\"true\"] {{ background: {c['edit']}; color: {done_t}; border: 2px solid {c['edit']};"
            f" font-weight: bold; padding: 0px 16px; }}"
            f" QPushButton[tbItem=\"true\"][primary=\"true\"][navFocus=\"true\"] {{ border: 2px solid {c['cur_b']}; }}"
            f" QPushButton#tbCollapse {{ font-size: 22px; padding: 0px 0px 0px 0px; min-width: 44px; max-width: 44px;"
            f" min-height: 44px; max-height: 44px; background: transparent; border: 2px solid transparent; color: {c['bar_t']}; }}"
            f" QPushButton#tbCollapse:hover {{ color: {c['name']}; border: 2px solid {c['tb_b']}; }}"
            f" QPushButton#tbCollapse:disabled {{ color: {c['tb_b']}; }}"
            f" QPushButton#tbCollapse[navFocus=\"true\"] {{ border: 2px solid {c['cur_b']}; }}")
        self.tb_grip.setStyleSheet(
            f"QPushButton#tbGrip {{ min-height: 23px; max-height: 23px; padding: 0px; font-size: 16px; border: none;"
            f" border-bottom: 1px solid {c['tb_b']}; border-radius: 0px; background: {c['bar']}; color: {c['bar_t']}; }}"
            f" QPushButton#tbGrip:hover {{ color: {c['name']}; background: {c['cur']}; }}"
            f" QPushButton#tbGrip[navFocus=\"true\"] {{ border: 2px solid {c['cur_b']}; }}")
        self.log_btn.setStyleSheet(
            f"QPushButton#logToggle {{ background: transparent; border: 2px solid transparent; color: {c['bar_t']};"
            f" text-align: left; padding: 4px 8px; min-height: 34px; font-size: 13px; }}"
            f" QPushButton#logToggle:hover {{ color: {c['name']}; }}"
            f" QPushButton#logToggle[navFocus=\"true\"] {{ border: 2px solid {c['cur_b']}; }}")
        self.statusBar().setStyleSheet(
            f"QStatusBar {{ background: {c['bar']}; border-top: 1px solid {c['bar_b']}; }}"
            f" QStatusBar::item {{ border: none; }}"
            f" QStatusBar QLabel {{ color: {c['bar_t']}; font-size: 13px; padding: 3px 8px; }}")

    def apply_theme(self):
        theme = self.cfg["settings"].get("theme", "Dark")
        QApplication.instance().setPalette(theme_palette(theme == "Light"))
        if theme == "Light":
            self.apply_light()
        else:
            self.apply_dark()
        self._apply_output_theme()
        self._apply_host_area_theme()
        self._apply_chrome_theme()
        self._apply_edit_bar_theme()
        # refresh host rows if layout already exists
        if hasattr(self, "host_layout"):
            for i in range(self.host_layout.count()):
                item = self.host_layout.itemAt(i)
                if item and item.widget() and isinstance(item.widget(), HostRow):
                    item.widget()._apply_row_theme()

    def _update_tray_menu(self):
        """Rebuild the host submenu in the tray."""
        if not hasattr(self, "host_menu"):
            return
        self.host_menu.clear()
        hosts = self.cfg.get("hosts", [])
        if not hosts:
            self.host_menu.addAction(t("tray_no_hosts")).setEnabled(False)
            return
        for h in hosts:
            name = h.get("name", h.get("ip", "?"))
            sub = self.host_menu.addMenu(name)
            for act in ("wake", "shutdown", "restart", "suspend", "hibernate"):
                sub.addAction(t(act), lambda _, host=h, a=act: self.do_action(host, a))

    def refresh_hosts(self):
        # running actions keep their feedback ("Wird geweckt …", busy, error) over the rebuild
        keep = {hid: r.ui_state() for hid, r in self.host_rows.items()}
        # clear
        self._gap_items.pop(self.host_layout, None)
        while self.host_layout.count():
            item = self.host_layout.takeAt(0)
            if item.widget():
                item.widget().hide()          # gone at once, not only on the next loop turn
                item.widget().deleteLater()
        self.host_rows.clear()

        self.card_drag.finish_anim()
        hosts = self.cfg.get("hosts", [])
        if not hosts:
            # empty start: one large "＋ Ersten Host hinzufügen" tile in the middle
            self.host_layout.setAlignment(Qt.AlignmentFlag(0))
            c = ui_colors(self._light())
            box = QWidget()
            box.setObjectName("emptyBox")
            bl = QVBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(10)
            self.empty_add_btn = QPushButton(t("add_first_host"))
            self.empty_add_btn.setObjectName("emptyAdd")
            self.empty_add_btn.setProperty("navKey", "empty_add")
            self.empty_add_btn.setMinimumSize(260, 140)
            self.empty_add_btn.clicked.connect(self.add_host)
            self.empty_add_btn.installEventFilter(self)
            lbl = QLabel(t("no_hosts"))
            lbl.setObjectName("emptySub")
            lbl.setWordWrap(True)
            lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            box.setStyleSheet(
                f"QWidget#emptyBox {{ background: transparent; }}"
                f" QPushButton#emptyAdd {{ font-size: 18px; font-weight: bold; border: 2px dashed {c['cur_b']};"
                f" border-radius: 14px; background: {c['card']}; color: {c['name']}; padding: 0px 28px;"
                f" min-width: 200px; min-height: 136px; max-height: 136px; }}"
                f" QPushButton#emptyAdd:hover {{ background: {c['cur']}; }}"
                f" QPushButton#emptyAdd[navFocus=\"true\"] {{ border: 3px solid {c['cur_b']}; }}"
                f" QLabel#emptySub {{ color: {c['sub']}; font-size: 13px; background: transparent; }}")
            bl.addWidget(self.empty_add_btn, 0, Qt.AlignmentFlag.AlignHCenter)
            bl.addWidget(lbl)
            for x in (box, self.empty_add_btn, lbl):     # size hints with the style sheet above
                x.ensurePolished()
            bl.invalidate()
            box.setMinimumHeight(box.sizeHint().height())   # the stretches must not squeeze it
            self.host_layout.addStretch(1)
            self.host_layout.addWidget(box, 0, Qt.AlignmentFlag.AlignHCenter)
            self.host_layout.addStretch(1)
            self._update_tray_menu()
            self._update_counts()
            return
        self.empty_add_btn = None
        self.host_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        for h in hosts:
            row = HostRow(h, self)
            self.host_layout.addWidget(row)
            self.host_rows[h["id"]] = row
            if h["id"] in keep:
                row.restore_ui_state(keep[h["id"]])
            self.card_drag.watch(row)
            if self._edit_mode:                 # header / empty area: grab to reorder
                row.setCursor(Qt.CursorShape.OpenHandCursor)
        self._update_tray_menu()
        self._update_counts()
        self._fit_min_size()
        self._relayout_rows()
        QTimer.singleShot(0, self._ensure_focus)

    def add_host(self):
        dlg = HostDialog(None, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            data = dlg.get_data()
            if data:
                self.cfg["hosts"].append(data)
                save_config(self.cfg)
                self.refresh_hosts()
                self._update_tray_menu()
                self.check_hosts(data["id"])
                if QMessageBox.question(self, t("pairing_title"), t("pair_now")) == QMessageBox.StandardButton.Yes:
                    self.start_pairing(data)

    def edit_host(self, host: dict):
        """⚙: connection settings only (name, IP, MAC, Buddy port, delete with
        confirmation). The tiles are arranged in edit mode (✎ Bearbeiten)."""
        dlg = HostDialog(host, self)
        res = dlg.exec()
        if res == HostDialog.DELETE:
            self.remove_host(host)
            return
        if res != QDialog.DialogCode.Accepted:
            return
        data = dlg.get_data()
        if data:
            for i, h in enumerate(self.cfg["hosts"]):
                if h["id"] == host["id"]:
                    self.cfg["hosts"][i] = data
                    break
            save_config(self.cfg)
            conn_changed = any(data.get(k) != host.get(k) for k in ("ip", "buddy_port", "mac"))
            if conn_changed:
                self.host_state.pop(host["id"], None)   # IP/port may have changed
            self.refresh_hosts()
            self._update_tray_menu()
            self._sync_edit_bar()
            if conn_changed:
                self.check_hosts(data.get("id", host["id"]))

    def _count_usage(self, hid: str, action: str):
        """How often each tile action ran, per host (host["nutzung"], for "Auto-arrange")."""
        typ = tiles.action_type(action)
        if typ is None:
            return
        for h in self.cfg.get("hosts", []):
            if h.get("id") == hid:
                use = h.setdefault("nutzung", {})
                if not isinstance(use, dict):
                    use = h["nutzung"] = {}
                use[typ] = int(use.get(typ, 0) or 0) + 1
                save_config(self.cfg)
                return

    # --- edit mode (4c): tiles are arranged directly in the cards ---------------------
    EDIT_UNDO_LIMIT = 100

    def _build_edit_bar(self):
        """Slim bar below the toolbar, only in edit mode: hint / last message, undo, redo,
        Fertig; second line (wraps): tools for the selected tile and the current card."""
        bar = QFrame()
        bar.setObjectName("editBar")
        v = QVBoxLayout(bar)
        v.setContentsMargins(12, 6, 12, 6)
        v.setSpacing(6)
        r1 = QHBoxLayout()
        r1.setSpacing(8)
        self.edit_icon = QLabel("✎")
        self.edit_icon.setObjectName("editIcon")
        self.edit_icon.setMinimumHeight(48)
        self.edit_info = QLabel(t("edit_hint"))
        self.edit_info.setObjectName("editInfo")
        self.edit_info.setWordWrap(True)          # never cut off: wraps onto a second line
        self.edit_info.setMinimumWidth(120)
        self.edit_info.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.edit_undo_btn = QPushButton("↶")
        self.edit_undo_btn.setToolTip(t("tip_undo"))
        self.edit_undo_btn.clicked.connect(self.edit_undo)
        self.edit_redo_btn = QPushButton("↷")
        self.edit_redo_btn.setToolTip(t("tip_redo"))
        self.edit_redo_btn.clicked.connect(self.edit_redo)
        for b in (self.edit_undo_btn, self.edit_redo_btn):
            b.setProperty("touchRole", "icon")
            b.setProperty("navKey", "edit_undo" if b is self.edit_undo_btn else "edit_redo")
            b.setObjectName("editHistory")    # 48 x 48 touch target, see _apply_edit_bar_theme
        # "✓ Fertig" is the ✎ item of the toolbar (always shown in edit mode): one Fertig only
        r1.addWidget(self.edit_icon, 0, Qt.AlignmentFlag.AlignTop)
        r1.addWidget(self.edit_info, 1)
        r1.addWidget(self.edit_undo_btn, 0, Qt.AlignmentFlag.AlignTop)
        r1.addWidget(self.edit_redo_btn, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(r1)

        self.edit_tools = QWidget()
        self.edit_tools.setObjectName("editTools")
        flow = FlowLayout(self.edit_tools, 8)
        flow.setContentsMargins(0, 0, 0, 0)
        self.edit_size_btn = QPushButton(t("edit_size") + "  ▾")
        self.edit_size_btn.clicked.connect(self._edit_size_menu)
        self.edit_dup_btn = QPushButton(t("tile_duplicate"))
        self.edit_dup_btn.clicked.connect(lambda: self.edit_duplicate())
        self.edit_rm_btn = QPushButton(t("tile_hide"))
        self.edit_rm_btn.clicked.connect(lambda: self.edit_remove())
        self.edit_hidden_btn = QPushButton(t("edit_show_hidden", n=0))
        self.edit_hidden_btn.setCheckable(True)
        self.edit_hidden_btn.clicked.connect(self.toggle_show_hidden)
        self.edit_tpl_btn = QPushButton(t("edit_template") + "  ▾")
        self.edit_tpl_btn.clicked.connect(self._edit_template_menu)
        self.edit_arr_btn = QPushButton(t("edit_arrange") + "  ▾")
        self.edit_arr_btn.clicked.connect(self._edit_arrange_menu)
        # "Auto-anordnen" is the last entry of the Anordnung ▾ menu (keeps the bar to one line)
        self.edit_tool_buttons = [self.edit_size_btn, self.edit_dup_btn, self.edit_rm_btn,
                                  self.edit_hidden_btn, self.edit_tpl_btn, self.edit_arr_btn]
        for b in self.edit_tool_buttons:
            flow.addWidget(b)
        v.addWidget(self.edit_tools)
        self.edit_top_buttons = [self.edit_undo_btn, self.edit_redo_btn]
        for b in self.edit_top_buttons + self.edit_tool_buttons:
            b.installEventFilter(self)
        self._edit_msg = ("", "info")
        bar.hide()
        self.edit_bar = bar
        return bar

    def _apply_edit_bar_theme(self):
        if not hasattr(self, "edit_bar"):
            return
        c = ui_colors(self._light())
        kind = getattr(self, "_edit_msg", ("", "info"))[1]
        self.edit_bar.setStyleSheet(
            f"QFrame#editBar {{ background: {c['edit_bg']}; border-bottom: 2px solid {c['edit']}; }}"
            f" QLabel#editIcon {{ color: {c['edit']}; font-size: 18px; font-weight: bold; background: transparent; }}"
            f" QLabel#editInfo {{ color: {c['warn_t'] if kind == 'warn' else c['name']}; font-size: 14px; background: transparent; }}"
            f" QWidget#editTools {{ background: transparent; }}"
            f" QPushButton#editHistory {{ font-size: 18px; padding: 0px; min-width: 48px; max-width: 48px; min-height: 48px; max-height: 48px; }}"
            f" QPushButton:checked {{ border: 2px solid {c['edit']}; }}")

    # helpers
    def _host(self, hid):
        return next((h for h in self.cfg.get("hosts", []) if h.get("id") == hid), None)

    def _edit_tiles(self, hid) -> list:
        h = self._host(hid)
        ts = h.get("aktionen") if h else None
        return tiles.copy_tiles(ts) if isinstance(ts, list) else tiles.template()

    def _edit_key_of(self, hid):
        s = self._edit_sel
        return s[1] if s and s[0] == hid else None

    def _edit_rows_update(self, *hids):
        for hid in (hids or tuple(self.host_rows)):
            r = self.host_rows.get(hid)
            if r is not None and r.editor is not None:
                r.update_editor()
        self._fit_min_size()
        self._relayout_rows()
        self._mark_current()

    def _mark_current(self):
        self._on_focus_changed(None, QApplication.focusWidget())

    # enter / leave
    def toggle_edit_mode(self):
        if self._edit_mode:
            self.exit_edit_mode()
        else:
            self.enter_edit_mode()

    def enter_edit_mode(self, hid=None):
        if QApplication.activeModalWidget() is not None:
            return
        if self._edit_mode:
            if hid:
                self.edit_focus_card(hid, focus=True)
            return
        hosts = self.cfg.get("hosts", [])
        self._edit_mode = True
        self._editing = True
        self._edit_hid = hid if self._host(hid) else (hosts[0]["id"] if hosts else None)
        self._edit_sel = None
        self._edit_undo.clear()
        self._edit_redo.clear()
        self._edit_msg = ("", "info")
        self.edit_btn.setChecked(True)
        for sc in self._edit_shortcuts:
            sc.setEnabled(True)
        self._tb_sel = None
        if self._tb_collapsed:                  # edit mode: the bar comes back (with Fertig)
            self.set_toolbar_collapsed(False, animate=False, save=False)
            self._tb_auto_expanded = True
        self.tb_group_lbl.show()
        self.tb_collapse_btn.setEnabled(False)
        self._edit_dim(True)
        self._tb_restyle()
        self.edit_bar.show()
        self._apply_edit_bar_theme()
        self._update_state_lbl()
        self.refresh_hosts()
        self._sync_edit_bar()
        target = self._edit_hid
        QTimer.singleShot(0, lambda: self._focus_editor(target))

    def exit_edit_mode(self):
        if not self._edit_mode:
            return
        for r in self.host_rows.values():
            if r.editor is not None:
                r.editor.cancel_drag()
        if self._menu is not None:
            try:
                self._menu.close()
            except RuntimeError:
                pass
        self._edit_mode = False
        self._editing = False
        self._edit_sel = None
        self.card_drag.cancel()
        self.tb_drag.cancel()
        self.edit_btn.setChecked(False)
        for sc in self._edit_shortcuts:
            sc.setEnabled(False)
        self._tb_sel = None
        self.tb_group_lbl.hide()
        self.tb_collapse_btn.setEnabled(True)
        self._edit_dim(False)
        self.edit_drag_state(None)
        self._tb_restyle()
        self.edit_bar.hide()
        self._apply_edit_bar_theme()
        self._update_state_lbl()
        self.refresh_hosts()
        if getattr(self, "_tb_auto_expanded", False):      # was collapsed before edit mode
            self._tb_auto_expanded = False
            self.set_toolbar_collapsed(True, save=False)
        QTimer.singleShot(0, lambda: (self.tb_grip if self._tb_collapsed else self.edit_btn)
                          .setFocus(Qt.FocusReason.OtherFocusReason))

    def _edit_dim(self, on: bool):
        """Edit mode concept 2: what cannot be arranged steps back (opacity 0.4)."""
        for w in (self.tb_collapse_btn, self.log_btn, self.statusBar()):
            if on:
                eff = QGraphicsOpacityEffect(w)
                eff.setOpacity(0.4)
                w.setGraphicsEffect(eff)
            else:
                w.setGraphicsEffect(None)
        self.host_widget.lifted = on
        self.host_widget.update()

    def edit_drag_state(self, kind, row=None):
        """A drag started (kind "tile" / "tb" / "card") or ended (None): only the valid
        drop zone stays bright, the hint says where the thing can go."""
        self._edit_drag = kind if self._edit_mode else None
        f = self.drop_focus
        zone = None
        if self._edit_drag == "tile" and row is not None and getattr(row, "edit_box", None) is not None:
            w, pad = row.edit_box, 6
        elif self._edit_drag == "tb":
            w, pad = self.tb_group, 6
        elif self._edit_drag == "card":
            w, pad = self.scroll.viewport(), -2
        else:
            w = None
        if w is not None:
            par = f.parentWidget()
            tl = w.mapTo(par, QPoint(0, 0))
            zone = QRect(tl, w.size()).adjusted(-pad, -pad, pad, pad).intersected(par.rect().adjusted(2, 2, -2, -2))
        if zone is None:
            f.zone = None
            f.hide()
        else:
            f.light = self._light()
            f.setGeometry(f.parentWidget().rect())
            f.zone = zone
            hint = getattr(self, "edit_info", None)
            f.keep = (QRect(hint.mapTo(f.parentWidget(), QPoint(0, 0)), hint.size()).adjusted(-4, -4, 4, 4)
                      if hint is not None and hint.isVisible() else None)
            f.show()
            f.raise_()
            for d in (self.tb_drag.drag, self.card_drag.drag):     # the ghost stays on top
                if d is not None:
                    d["ghost"].raise_()
            f.update()
        self._sync_edit_bar()

    def _open_gap(self, lay, pos, size, horizontal):
        """Opens a gap of `size` px at layout index `pos` (None: closes it)."""
        old = self._gap_items.pop(lay, None)
        if old is not None:
            i = lay.indexOf(old)
            if i >= 0:
                lay.takeAt(i)
        if pos is None:
            return
        sp = QSpacerItem(size if horizontal else 0, 0 if horizontal else size,
                         QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        lay.insertItem(pos, sp)
        self._gap_items[lay] = sp

    @staticmethod
    def _gap_pos(lay, others, idx):
        if idx < len(others):
            return lay.indexOf(others[idx])
        return lay.indexOf(others[-1]) + 1

    def _tb_gap(self, idx):
        d = self.tb_drag.drag
        others = [self.tb_btns[it["id"]] for it in self._tb_items
                  if d is None or self.tb_btns[it["id"]] is not d["src"]]
        lay = self._tb_group_layout
        self._open_gap(lay, None if idx is None or not others else self._gap_pos(lay, others, idx),
                       _DropSlot.GAP_H, True)
        self.tb_group.update()

    def _card_gap(self, idx):
        d = self.card_drag.drag
        others = [r for r in self.host_rows.values() if (d is None or r is not d["src"]) and not r.isHidden()]
        lay = self.host_layout
        self._open_gap(lay, None if idx is None or not others else self._gap_pos(lay, others, idx),
                       _DropSlot.GAP_V, False)
        self.host_widget.update()

    def _focus_editor(self, hid):
        r = self.host_rows.get(hid)
        if self._edit_mode and r is not None and r.editor is not None:
            r.editor.setFocus(Qt.FocusReason.OtherFocusReason)
            self.scroll.ensureWidgetVisible(r)

    # selection / focus
    def edit_focus_card(self, hid, focus: bool = False):
        if not self._edit_mode or self._host(hid) is None:
            return
        if hid != self._edit_hid:
            old = self._edit_sel[0] if self._edit_sel else None
            self._edit_hid = hid
            if old and old != hid:
                self._edit_sel = None
                self._edit_rows_update(old)
        if focus:
            self._focus_editor(hid)
        self._sync_edit_bar()
        self._mark_current()

    def edit_select(self, hid, k):
        if not self._edit_mode:
            return
        old = self._edit_sel[0] if self._edit_sel else None
        self._edit_hid = hid
        self._edit_sel = (hid, k) if k else None
        self._edit_msg = ("", "info")
        self._edit_rows_update(*{x for x in (old, hid) if x})
        r = self.host_rows.get(hid)
        if r is not None and r.editor is not None and not r.editor.hasFocus():
            r.editor.setFocus(Qt.FocusReason.MouseFocusReason)
        self._sync_edit_bar()

    def edit_message(self, msg: str, kind: str = "info"):
        self._edit_msg = (msg or "", kind)
        self._apply_edit_bar_theme()
        self._sync_edit_bar()

    def _sync_edit_bar(self):
        if not self._edit_mode:
            return
        if self._host(self._edit_hid) is None:
            hosts = self.cfg.get("hosts", [])
            self._edit_hid = hosts[0]["id"] if hosts else None
        host = self._host(self._edit_hid)
        ts = self._edit_tiles(self._edit_hid) if host else []
        k = self._edit_key_of(self._edit_hid)
        idx = tiles.find(ts, k) if k else None
        a = ts[idx] if idx is not None else None
        msg, _kind = self._edit_msg
        on = a is not None and tiles.is_active(a)
        tb_sel = self._tb_sel is not None
        drag = getattr(self, "_edit_drag", None)
        if drag:
            hint = t(f"edit_hint_drag_{drag}")
        elif msg:
            hint = msg
        elif on or tb_sel:
            hint = t("edit_hint_selected")
        else:
            hint = t("edit_hint")
        self.edit_info.setText(hint)
        self.edit_size_btn.setEnabled(on or tb_sel)
        # the duplicate limit is reported with a toast when tried (no tooltip)
        self.edit_dup_btn.setEnabled(on and tiles.TYPES.get(a["typ"], {}).get("kind") == "action")
        self.edit_rm_btn.setEnabled(on)          # toolbar items: never (App-Steuerung)
        self.edit_rm_btn.setText(t("tile_remove") if a is not None and tiles.is_dup(a) else t("tile_hide"))
        n = sum(1 for x in ts if tiles.is_known(x) and not tiles.is_active(x))     # this card
        self.edit_hidden_btn.setText(t("edit_show_hidden", n=n))
        self.edit_hidden_btn.setChecked(self._edit_show_hidden)
        for b in (self.edit_tpl_btn, self.edit_arr_btn, self.edit_hidden_btn):
            b.setEnabled(host is not None)
        self.edit_undo_btn.setEnabled(bool(self._edit_undo))
        self.edit_redo_btn.setEnabled(bool(self._edit_redo))
        fw = QApplication.focusWidget()
        if fw is not None and not fw.isEnabled():        # keep the keyboard focus usable
            nxt = next((b for b in self.edit_tool_buttons + self.edit_top_buttons if self._navigable(b)), None)
            if nxt is not None:
                nxt.setFocus(Qt.FocusReason.TabFocusReason)

    # changes (saved at once, every step can be undone)
    def _edit_commit(self, hid, new, sel=..., msg: str = "", kind: str = "info"):
        host = self._host(hid)
        if host is None:
            return
        old = host.get("aktionen") if isinstance(host.get("aktionen"), list) else tiles.template()
        if new != old:
            self._edit_undo.append((hid, tiles.copy_tiles(old), self._edit_sel, msg))
            del self._edit_undo[:-self.EDIT_UNDO_LIMIT]
            self._edit_redo.clear()
            host["aktionen"] = tiles.copy_tiles(new)
            save_config(self.cfg)
        prev = self._edit_sel[0] if self._edit_sel else None
        self._edit_hid = hid
        if sel is not ...:
            self._edit_sel = (hid, sel) if sel else None
        self._edit_msg = (msg or "", kind)
        self._apply_edit_bar_theme()
        self._edit_rows_update(*{x for x in (prev, hid) if x})
        self._sync_edit_bar()

    def _edit_step(self, src, dst, done_key):
        if not self._edit_mode:
            return
        while src:
            e = src.pop()
            if isinstance(e, dict):              # card order / toolbar step
                if e["kind"] == "order":
                    cur = self._host_order()
                    ids = [i for i in e["order"] if i in cur] + [i for i in cur if i not in e["order"]]
                    dst.append({"kind": "order", "order": cur})
                    self._reorder_hosts(ids, undo=False)
                else:
                    dst.append({"kind": "toolbar", "items": copy.deepcopy(self._tb_items)})
                    self._tb_set_items(e["items"])
                    self._tb_restyle()
                self._edit_msg = (t(done_key), "info")
                self._apply_edit_bar_theme()
                self._sync_edit_bar()
                self._mark_current()
                return
            hid, tl, sel, msg = e
            host = self._host(hid)
            if host is None:                    # host deleted meanwhile
                continue
            for r in self.host_rows.values():
                if r.editor is not None:
                    r.editor.cancel_drag()
            dst.append((hid, tiles.copy_tiles(host.get("aktionen") or []), self._edit_sel, msg))
            host["aktionen"] = tl
            save_config(self.cfg)
            self._edit_hid = hid
            self._edit_sel = sel if sel and sel[0] == hid and tiles.find(tl, sel[1]) is not None else None
            self._edit_msg = (t(done_key), "info")
            self._apply_edit_bar_theme()
            self._edit_rows_update()
            self._sync_edit_bar()
            return

    def edit_undo(self):
        self._edit_step(self._edit_undo, self._edit_redo, "undo_done")

    def edit_redo(self):
        self._edit_step(self._edit_redo, self._edit_undo, "redo_done")

    def _edit_shortcut(self, fn):
        """Ctrl+Z / Ctrl+Y only act on the tiles (never while a text field has the focus)."""
        if isinstance(QApplication.focusWidget(), QLineEdit) or QApplication.activeModalWidget() is not None:
            return
        fn()

    def _edit_target(self, hid=None):
        hid = hid or self._edit_hid
        k = self._edit_key_of(hid)
        ts = self._edit_tiles(hid)
        idx = tiles.find(ts, k) if k else None
        return hid, k, ts, idx

    def edit_drop(self, hid, new, k, res):
        self._edit_commit(hid, new, k, t("tile_reflowed") if res == "reflow" else "")

    _DIRS = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1)}

    def edit_key(self, hid, op):
        if op in self._DIRS:
            self._edit_op(hid, tiles.move, *self._DIRS[op])
        elif op == "remove":
            self.edit_remove(hid)

    def _edit_op(self, hid, fn, *args):
        hid, k, ts, idx = self._edit_target(hid)
        if idx is None or not tiles.is_active(ts[idx]):
            return
        new, res = fn(ts, idx, *args)
        if res == "blocked":
            msg, kind = (t("tile_blocked") if fn is tiles.move else t("tile_full")), "warn"
        elif res == "moved":
            msg, kind = t("tile_moved"), "info"
        else:
            msg, kind = "", "info"
        self._edit_commit(hid, new, k, msg, kind)

    def edit_resize(self, size, hid=None):
        self._edit_op(hid or self._edit_hid, tiles.resize, size)

    def edit_duplicate(self, hid=None):
        hid, k, ts, idx = self._edit_target(hid)
        if idx is None:
            return
        new, res, nk = tiles.duplicate(ts, idx)
        if res == "blocked":
            self.show_toast(t("tile_dup_blocked", n=tiles.MAX_DUPLICATES), kind="info")
        else:
            self._edit_commit(hid, new, nk, t("tile_dup_ok"))

    def edit_remove(self, hid=None):
        hid, k, ts, idx = self._edit_target(hid)
        if idx is None or not tiles.is_active(ts[idx]):
            return
        new, res = tiles.remove(ts, idx)
        if res == "removed":
            self._edit_commit(hid, new, None, t("tile_removed"))
        elif res == "hidden":
            self._edit_commit(hid, new, None, t("tile_hidden"))

    def edit_show_tile(self, hid, k):
        ts = self._edit_tiles(hid)
        idx = tiles.find(ts, k)
        if idx is None:
            return
        new, res = tiles.set_visible(ts, idx, True)
        if res == "blocked":
            self._edit_commit(hid, ts, ..., t("tile_full"), "warn")
        else:
            self._edit_commit(hid, new, k, t("tile_moved") if res == "moved" else "")

    def toggle_show_hidden(self):
        self._edit_show_hidden = not self._edit_show_hidden
        self._edit_rows_update()
        self._sync_edit_bar()

    def edit_template(self, name, hid=None):
        hid = hid or self._edit_hid
        if self._host(hid) is None:
            return
        self._edit_commit(hid, tiles.apply_template(self._edit_tiles(hid), name), None,
                          t("tpl_applied", name=t(f"tpl_{name}")))

    def edit_preset(self, name, hid=None):
        hid = hid or self._edit_hid
        if self._host(hid) is None:
            return
        self._edit_commit(hid, tiles.apply_preset(self._edit_tiles(hid), name), None,
                          t("preset_applied", name=t(f"preset_{name}")))

    def edit_auto(self, hid=None):
        hid = hid or self._edit_hid
        host = self._host(hid)
        if host is None:
            return
        use = host.get("nutzung") if isinstance(host.get("nutzung"), dict) else {}
        new, mode = tiles.auto_arrange(self._edit_tiles(hid), use)
        self._edit_commit(hid, new, None, t("tiles_auto_usage") if mode == "usage" else t("tiles_auto_default"))

    # menus (toolbar ▾ buttons and the optional right-click menu)
    def _popup(self, menu, anchor=None, gpos=None):
        menu.setStyleSheet(dialog_stylesheet(self))
        self._menu = menu                       # kept for tests / screenshots
        if gpos is None:
            gpos = anchor.mapToGlobal(QPoint(0, anchor.height()))
        menu.popup(gpos)

    def _add_size_actions(self, menu, a):
        grp = QActionGroup(menu)
        for sz in tiles.SIZE_ORDER:
            act = menu.addAction(t(f"size_{sz}"))
            act.setCheckable(True)
            act.setChecked(a is not None and a["groesse"] == sz)
            grp.addAction(act)
            act.triggered.connect(lambda _=False, s=sz: self.edit_resize(s))

    def _edit_size_menu(self):
        if self._tb_sel is not None:
            menu = QMenu(self)
            self._add_tb_size_actions(menu, self._tb_sel)
            self._popup(menu, self.edit_size_btn)
            return
        hid, k, ts, idx = self._edit_target()
        if idx is None:
            return
        menu = QMenu(self)
        self._add_size_actions(menu, ts[idx])
        self._popup(menu, self.edit_size_btn)

    def _edit_template_menu(self):
        if self._host(self._edit_hid) is None:
            return
        cur = tiles.matching_template(self._edit_tiles(self._edit_hid))
        menu = QMenu(self)
        grp = QActionGroup(menu)
        for name in tiles.TEMPLATE_ORDER:
            act = menu.addAction(t(f"tpl_{name}"))
            act.setCheckable(True)
            act.setChecked(cur == name)
            grp.addAction(act)
            act.triggered.connect(lambda _=False, n=name: self.edit_template(n))
        self._popup(menu, self.edit_tpl_btn)

    def _edit_arrange_menu(self):
        if self._host(self._edit_hid) is None:
            return
        menu = QMenu(self)
        for name in tiles.PRESET_ORDER:
            menu.addAction(t(f"preset_{name}")).triggered.connect(lambda _=False, n=name: self.edit_preset(n))
        menu.addSeparator()
        auto = menu.addAction(t("tiles_auto"))
        auto.setToolTip(t("tip_tiles_auto"))
        auto.triggered.connect(lambda: self.edit_auto())
        self._popup(menu, self.edit_arr_btn)

    def edit_menu(self, hid, k, gpos):
        """Right-click / long-press menu on a tile (extra: everything is also in the edit bar)."""
        ts = self._edit_tiles(hid)
        idx = tiles.find(ts, k)
        if idx is None:
            return
        self.edit_select(hid, k)
        a = ts[idx]
        menu = QMenu(self)
        self._add_size_actions(menu.addMenu(t("tile_size_menu")), a)
        dup = menu.addAction(t("tile_duplicate"))
        dup.setEnabled(tiles.is_active(a) and tiles.TYPES.get(a["typ"], {}).get("kind") == "action")
        dup.triggered.connect(lambda: self.edit_duplicate(hid))
        menu.addSeparator()
        rm = menu.addAction(t("tile_remove") if tiles.is_dup(a) else t("tile_hide"))
        rm.triggered.connect(lambda: self.edit_remove(hid))
        self._popup(menu, gpos=gpos)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Escape and (self.card_drag.active or self.tb_drag.active):
            self.card_drag.cancel()
            self.tb_drag.cancel()
            ev.accept()
            return
        if self._edit_mode and ev.key() == Qt.Key.Key_Escape:
            self.exit_edit_mode()
            ev.accept()
            return
        super().keyPressEvent(ev)


    def _update_state_lbl(self):
        """Status bar, left: only the current state (feedback for actions = toasts + log)."""
        if not hasattr(self, "status_bar"):
            return
        if getattr(self, "_editing", False):
            txt = t("state_edit")
        elif getattr(self, "_busy_hosts", None):
            txt = t("state_working")
        else:
            txt = t("state_ready")
        self.status_bar.setText(txt)

    def _fetch_and_save_mac(self, host: dict, cli_cfg_path: Path):
        """After pairing, try to get MAC from Buddy and save it."""
        try:
            rc, out, err = run_cli(["host", "list", "--json"], timeout=15, config_override=cli_cfg_path)
            if rc == 0 and out.strip():
                import re
                # Try to extract MAC from output
                m = re.search(r'([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}', out)
                if m:
                    mac = m.group(0).upper()
                    for h in self.cfg["hosts"]:
                        if h["id"] == host["id"]:
                            h["mac"] = mac
                            break
                    save_config(self.cfg)
                    logging.info("MAC auto-saved: %s", mac)
                    QTimer.singleShot(0, lambda: notify(self, t("mac_updated", mac=mac)))
        except Exception:
            logging.exception("Failed to fetch MAC")

    def remove_host(self, host: dict):
        """Remove a host (already confirmed in the edit dialog). The toast offers
        Undo for a few seconds; only the BuddyRemote entry is removed."""
        hosts = self.cfg["hosts"]
        idx = next((i for i, h in enumerate(hosts) if h["id"] == host["id"]), None)
        if idx is None:
            return
        removed = hosts.pop(idx)
        save_config(self.cfg)
        state = self.host_state.pop(host["id"], None)
        self.refresh_hosts()
        self._update_tray_menu()
        self._update_tray_icon(any(s.get("buddy") for s in self.host_state.values()))
        name = removed.get("name", removed.get("ip"))

        def undo():
            if any(h.get("id") == removed["id"] for h in self.cfg["hosts"]):
                return
            self.cfg["hosts"].insert(min(idx, len(self.cfg["hosts"])), removed)
            save_config(self.cfg)
            if state:
                self.host_state[removed["id"]] = state
            self.refresh_hosts()
            self._update_tray_menu()
            self.show_toast(t("host_restored", name=name))
            self.check_hosts(removed["id"])
        self.show_toast(t("host_deleted", name=name), kind="info", action=(t("undo"), undo), ms=8000)

    # --- UI only: card order (edit mode: drag and drop, Ctrl+Up/Down) ----------
    def _host_order(self) -> list:
        return [h.get("id") for h in self.cfg.get("hosts", [])]

    def _reorder_hosts(self, order: list, undo: bool = True) -> bool:
        """New card order (list of host ids); saved at once, undoable in edit mode.
        The cards are only re-inserted (no rebuild), so the focus stays put."""
        hosts = self.cfg.get("hosts", [])
        old = self._host_order()
        if order == old or sorted(map(str, order)) != sorted(map(str, old)):
            return False
        by_id = {h.get("id"): h for h in hosts}
        self.cfg["hosts"] = [by_id[i] for i in order]
        save_config(self.cfg)
        if undo and self._edit_mode:
            self._edit_undo.append({"kind": "order", "order": old})
            del self._edit_undo[:-self.EDIT_UNDO_LIMIT]
            self._edit_redo.clear()
        self._apply_host_order()
        self._update_tray_menu()
        return True

    def _apply_host_order(self):
        rows = self.host_rows
        if set(rows) != set(self._host_order()):
            self.refresh_hosts()
            return
        new = {}
        for hid in self._host_order():
            r = rows[hid]
            self.host_layout.removeWidget(r)
            self.host_layout.addWidget(r)
            new[hid] = r
        rows.clear()
        rows.update(new)
        self.host_layout.activate()
        self._relayout_rows()

    def move_card(self, hid, direction: int) -> bool:
        order = self._host_order()
        if hid not in order:
            return False
        i = order.index(hid)
        j = i + direction
        if not 0 <= j < len(order):
            return False
        order[i], order[j] = order[j], order[i]
        if not self._reorder_hosts(order):
            return False
        if self._edit_mode:
            self._edit_hid = hid
            self._edit_msg = (t("card_moved"), "info")
            self._apply_edit_bar_theme()
            self._sync_edit_bar()
            self._mark_current()
            r = self.host_rows.get(hid)
            if r is not None:
                QTimer.singleShot(0, lambda: self.scroll.ensureWidgetVisible(r) if r.isVisible() else None)
        return True

    def _card_drag_source(self, obj):
        if self._edit_mode and isinstance(obj, HostRow) and len(self.host_rows) > 1:
            return obj
        return None

    def _card_drag_commit(self, row, index):
        hid = row.host.get("id")
        order = [i for i in self._host_order() if i != hid]
        order.insert(max(0, min(index, len(order))), hid)
        if self._reorder_hosts(order):
            self._edit_hid = hid
            self._edit_msg = (t("card_moved"), "info")
            self._apply_edit_bar_theme()
            self._sync_edit_bar()
            self._mark_current()

    def _focused_host(self):
        fw = QApplication.focusWidget()
        for hid, r in self.host_rows.items():
            try:
                if fw is not None and (fw is r or r.isAncestorOf(fw)):
                    return hid
            except RuntimeError:
                pass
        return self._edit_hid

    def _ctrl_arrow(self, d: int, horizontal: bool):
        """Edit mode: Ctrl+Up/Down moves the focused/selected card, Ctrl+Left/Right the
        focused/selected toolbar item."""
        if not self._edit_mode or isinstance(QApplication.focusWidget(), QLineEdit) \
                or QApplication.activeModalWidget() is not None:
            return
        if horizontal:
            iid = self._tb_focus_id() or self._tb_sel
            if iid is not None:
                self.move_toolbar_item(iid, d)
            return
        hid = self._focused_host()
        if hid is not None:
            self.move_card(hid, d)

    # --- UI only: main toolbar ("App-Steuerung") ---------------------------------
    def _tb_layout(self):
        """Puts the toolbar items in their saved order and size."""
        gl = self._tb_group_layout
        while gl.count():
            gl.takeAt(0)
        self._gap_items.pop(gl, None)
        for it in self._tb_items:
            b = self.tb_btns[it["id"]]
            gl.addWidget(b)
            self._tb_style_btn(it["id"], it["groesse"])
        gl.activate()

    def _tb_style_btn(self, iid, size=None):
        b = self.tb_btns[iid]
        size = size or next((it["groesse"] for it in self._tb_items if it["id"] == iid), "klein")
        glyph, label, _tip = TOOLBAR_ITEMS[iid]
        if iid == "edit" and self._edit_mode:
            b.setText("✓  " + t("edit_done"))          # the one "Fertig"
            b.setToolTip(t("tip_edit_done"))
            b.setProperty("tbSize", "mittel")
            b.setProperty("primary", True)
        else:
            b.setText(glyph if size == "klein" else f"{glyph}  {t(label)}")
            b.setToolTip(t(_tip))
            b.setProperty("tbSize", size)
            b.setProperty("primary", False)
        # never on "✓ Fertig": it keeps its accent look even right after being moved
        b.setProperty("tbSel", self._edit_mode and self._tb_sel == iid and iid != "edit")
        if self._edit_mode:
            prim = iid == "edit"
            g = QColor("#ffffff" if prim and self._light() else "#1a1a1a" if prim else ui_colors(self._light())["name"])
            g.setAlphaF(0.75 if prim else 0.45)
            b.grip = g
        else:
            b.grip = None
        b.style().unpolish(b)
        b.style().polish(b)
        b.update()

    def _tb_restyle(self):
        for it in self._tb_items:
            self._tb_style_btn(it["id"], it["groesse"])
        self._apply_chrome_theme()

    def _tb_clicked(self, iid):
        if self._edit_mode:
            if iid == "edit":
                self.exit_edit_mode()
                return
            self._tb_select(iid)                  # edit mode: select instead of run
            return
        {"add": self.add_host, "refresh": self.check_status, "edit": self.toggle_edit_mode,
         "options": self.open_options}[iid]()

    def _tb_select(self, iid):
        self._tb_sel = iid
        self._edit_msg = (t("tb_selected", name=t(TOOLBAR_ITEMS[iid][1])), "info") if iid else ("", "info")
        self._tb_restyle()
        self._apply_edit_bar_theme()
        self._sync_edit_bar()

    def _tb_focus_id(self):
        fw = QApplication.focusWidget()
        return next((i for i, b in self.tb_btns.items() if b is fw), None)

    def _tb_commit(self, items, msg_key="tb_moved", iid=None):
        items = toolbar_items(items)
        if items == self._tb_items:
            return False
        if self._edit_mode:
            self._edit_undo.append({"kind": "toolbar", "items": copy.deepcopy(self._tb_items)})
            del self._edit_undo[:-self.EDIT_UNDO_LIMIT]
            self._edit_redo.clear()
        self._tb_set_items(items)
        if self._edit_mode:
            self._tb_sel = iid if iid is not None else self._tb_sel
            self._edit_msg = (t(msg_key), "info")
            self._tb_restyle()
            self._apply_edit_bar_theme()
            self._sync_edit_bar()
        return True

    def _tb_set_items(self, items):
        fw = QApplication.focusWidget()
        self._tb_items = toolbar_items(items)
        self.cfg["settings"]["toolbar"] = copy.deepcopy(self._tb_items)
        save_config(self.cfg)
        self._tb_layout()
        if fw is not None and fw in self.tb_btns.values():
            fw.setFocus(Qt.FocusReason.OtherFocusReason)
        self._fit_min_size()

    def move_toolbar_item(self, iid, d: int) -> bool:
        ids = [it["id"] for it in self._tb_items]
        if iid not in ids:
            return False
        i = ids.index(iid)
        j = i + d
        if not 0 <= j < len(ids):
            return False
        items = copy.deepcopy(self._tb_items)
        items[i], items[j] = items[j], items[i]
        return self._tb_commit(items, iid=iid)

    def set_toolbar_size(self, iid, size) -> bool:
        items = copy.deepcopy(self._tb_items)
        for it in items:
            if it["id"] == iid:
                it["groesse"] = size
        return self._tb_commit(items, "tb_resized", iid=iid)

    def _add_tb_size_actions(self, menu, iid):
        cur = next((it["groesse"] for it in self._tb_items if it["id"] == iid), "klein")
        grp = QActionGroup(menu)
        for size in TOOLBAR_SIZES:
            act = menu.addAction(t(f"tb_size_{size}"))
            act.setCheckable(True)
            act.setChecked(cur == size)
            grp.addAction(act)
            act.triggered.connect(lambda _=False, z=size: self.set_toolbar_size(iid, z))

    def toolbar_menu(self, iid, gpos=None):
        """Edit mode, right click / long press on a toolbar item: size; hiding is shown
        but disabled (the App-Steuerung cannot be removed)."""
        if not self._edit_mode:
            return
        self._tb_select(iid)
        menu = QMenu(self)
        if iid != "edit":
            self._add_tb_size_actions(menu.addMenu(t("tile_size_menu")), iid)
        mv = menu.addMenu(t("tb_move_menu"))
        ids = [it["id"] for it in self._tb_items]
        left = mv.addAction("←  " + t("tb_move_left"))
        left.setEnabled(ids.index(iid) > 0)
        left.triggered.connect(lambda: self.move_toolbar_item(iid, -1))
        right = mv.addAction("→  " + t("tb_move_right"))
        right.setEnabled(ids.index(iid) < len(ids) - 1)
        right.triggered.connect(lambda: self.move_toolbar_item(iid, 1))
        menu.addSeparator()
        hide = menu.addAction(t("tile_hide") + "  —  " + t("tb_cannot_hide_short"))
        hide.setEnabled(False)
        self._popup(menu, self.tb_btns[iid], gpos=gpos)

    def toolbar_cannot_hide(self):
        self.show_toast(t("tb_cannot_hide"), kind="info")

    def _tb_drag_source(self, obj):
        if self._edit_mode and not self._tb_collapsed:
            return next((b for b in self.tb_btns.values() if b is obj), None)
        return None

    def _tb_drag_commit(self, btn, index):
        iid = next(i for i, b in self.tb_btns.items() if b is btn)
        items = [it for it in copy.deepcopy(self._tb_items) if it["id"] != iid]
        me = next(it for it in self._tb_items if it["id"] == iid)
        items.insert(max(0, min(index, len(items))), dict(me))
        self._tb_commit(items, iid=iid)

    def _tb_drag_outside(self, btn):
        self.toolbar_cannot_hide()

    # collapse / expand (state in window.ini; shortcuts keep working)
    def set_toolbar_collapsed(self, on: bool, animate: bool = True, save: bool = True):
        if on and self._edit_mode:              # edit mode keeps the bar (and Fertig) visible
            self.show_toast(t("tb_collapse_edit"), kind="info")
            return
        on = bool(on)
        if on == self._tb_collapsed and (self._tb_anim is None):
            return
        self._tb_collapsed = on
        if self._tb_anim is not None:
            self._tb_anim.stop()
            self._tb_anim = None
        full = max(self.toolbar.sizeHint().height(), self.toolbar.minimumSizeHint().height())
        if on:
            had_focus = self.toolbar.isAncestorOf(QApplication.focusWidget()) if QApplication.focusWidget() else False
            if animate and self.isVisible():
                anim = QPropertyAnimation(self.toolbar, b"maximumHeight", self)
                anim.setDuration(160)
                anim.setStartValue(self.toolbar.height() or full)
                anim.setEndValue(0)
                anim.setEasingCurve(QEasingCurve(QEasingCurve.Type.InOutCubic))
                anim.finished.connect(self._tb_collapse_done)
                self._tb_anim = anim
                anim.start()
            else:
                self._tb_collapse_done()
            if had_focus:
                self.tb_grip.setFocus(Qt.FocusReason.OtherFocusReason)
        else:
            self.tb_grip.hide()
            self.toolbar.setMaximumHeight(0)
            self.toolbar.show()
            if animate and self.isVisible():
                anim = QPropertyAnimation(self.toolbar, b"maximumHeight", self)
                anim.setDuration(160)
                anim.setStartValue(0)
                anim.setEndValue(full)
                anim.setEasingCurve(QEasingCurve(QEasingCurve.Type.InOutCubic))
                anim.finished.connect(self._tb_expand_done)
                self._tb_anim = anim
                anim.start()
            else:
                self._tb_expand_done()
        self._fit_min_size()
        if save:
            try:
                st = QSettings(str(WINDOW_STATE_FILE), QSettings.Format.IniFormat)
                st.setValue("toolbar_collapsed", "true" if on else "false")
                st.sync()
            except Exception:
                logging.exception("window state save failed")
        if hasattr(self, "toast") and self.toast.isVisible():
            QTimer.singleShot(200, self.toast.place)

    def _tb_collapse_done(self):
        self._tb_anim = None
        self.toolbar.hide()
        self.toolbar.setMaximumHeight(16777215)
        self.tb_grip.show()
        self._fit_min_size()

    def _tb_expand_done(self):
        self._tb_anim = None
        self.toolbar.setMaximumHeight(16777215)
        self.toolbar.show()
        self._fit_min_size()
        if self.tb_grip.hasFocus() or QApplication.focusWidget() is None:
            self.tb_btns[self._tb_items[0]["id"]].setFocus(Qt.FocusReason.OtherFocusReason)

    # --- UI only: log height (splitter) --------------------------------------------
    LOG_DEFAULT = 150
    LOG_MIN = 60

    def _log_open(self) -> bool:
        return not self.output.isHidden()

    def _apply_log_height(self):
        if not hasattr(self, "splitter"):
            return
        total = sum(self.splitter.sizes()) or max(1, self.splitter.height() - self.splitter.handleWidth())
        if self._log_open():
            self.log_panel.setMaximumHeight(16777215)
            self.log_panel.setMinimumHeight(self.LOG_MIN)
            self.log_handle.set_resizable(True)
            want = self._log_h
            sizes = [max(1, total - want), want]
        else:
            self.log_panel.setMinimumHeight(0)
            self.log_panel.setMaximumHeight(0)
            self.log_handle.set_resizable(False)
            sizes = [max(1, total), 0]
        self.splitter.setSizes(sizes)
        self.log_handle.update()

    def _on_log_split_moved(self, pos, index):
        if not self._log_open():
            return
        self._log_h = max(self.LOG_MIN, self.output.height())
        self._log_save_timer.start()

    def _save_log_height(self):
        try:
            st = QSettings(str(WINDOW_STATE_FILE), QSettings.Format.IniFormat)
            st.setValue("log_height", int(self._log_h))
            st.sync()
        except Exception:
            logging.exception("window state save failed")

    def reset_log_height(self):
        """Double click on the divider: back to the default height."""
        self._log_h = self.LOG_DEFAULT
        self._apply_log_height()
        self._save_log_height()

    def set_log_height(self, h: int):
        self._log_h = max(self.LOG_MIN, int(h))
        self._apply_log_height()
        self._save_log_height()

    def do_action(self, host: dict, action: str):
        hid = host["id"]
        name = host.get("name", host.get("ip"))

        if action == "wake" and not host.get("mac"):
            notify(self, t("no_mac"), kind="error")
            return

        if action in CONFIRM_ACTIONS and self.cfg["settings"].get("confirm_actions", True):
            if QMessageBox.question(self, t("app_title"), t(f"confirm_{action}", name=name), _YES_NO, _NO) != QMessageBox.StandardButton.Yes:
                return

        if hid not in self.action_locks:
            self.action_locks[hid] = threading.Lock()
        if not self.action_locks[hid].acquire(blocking=False):
            notify(self, t("action_running"), kind="info")
            return

        def worker():
            try:
                self.signals.action_started.emit(hid, name, action)
                if action in STEAM_ACTIONS:
                    rc, out, err = self._run_cli_for_host(host, STEAM_ACTIONS[action], timeout=60)
                else:
                    rc, out, err = self._run_action(host, action)
                msg = (out or err or f"Exit {rc}").strip()
                success = rc == 0
                self.signals.action_done.emit(hid, name, action, success, msg)
            except Exception as e:
                self.signals.action_done.emit(hid, name, action, False, str(e))
            finally:
                self.action_locks[hid].release()

        threading.Thread(target=worker, daemon=True).start()

    def _run_action(self, host: dict, action: str) -> tuple[int, str, str]:
        ip = host["ip"]
        cli_cfg = {
            "version": 1,
            "clientId": ensure_client_id(self.cfg),
            "defaultHost": ip,
            "hosts": {
                ip: {
                    "address": ip,
                    "manualAddress": True,
                    "infoPort": 47989,
                    "buddyPort": host.get("buddy_port", 59999),
                    "hostName": host.get("name", ip),
                    "mac": host.get("mac")
                }
            }
        }
        tmp = APP_DIR / f".tmp_{uuid.uuid4().hex[:6]}.json"
        try:
            tmp.write_text(json.dumps(cli_cfg))
            return run_cli(["host", action], timeout=60, config_override=tmp)
        finally:
            tmp.unlink(missing_ok=True)

    def _cli_config_for(self, host: dict) -> dict:
        """Same temporary CLI config as _run_action builds (kept separate so the
        existing power/pairing path stays untouched)."""
        ip = host["ip"]
        return {
            "version": 1,
            "clientId": ensure_client_id(self.cfg),
            "defaultHost": ip,
            "hosts": {
                ip: {
                    "address": ip,
                    "manualAddress": True,
                    "infoPort": 47989,
                    "buddyPort": host.get("buddy_port", 59999),
                    "hostName": host.get("name", ip),
                    "mac": host.get("mac")
                }
            }
        }

    def _run_cli_for_host(self, host: dict, args: list, timeout: int = 60) -> tuple[int, str, str]:
        """Run any other MoonDeck CLI command (steam launch/close/status) for one host."""
        tmp = APP_DIR / f".tmp_{uuid.uuid4().hex[:6]}.json"
        try:
            tmp.write_text(json.dumps(self._cli_config_for(host)))
            return run_cli(args, timeout=timeout, config_override=tmp)
        finally:
            tmp.unlink(missing_ok=True)

    def start_pairing(self, host: dict):
        """Start pairing. Show PIN dialog that stays open while CLI runs."""
        try:
            ip = host["ip"]
            pin = f"{random.randint(1000, 9999)}"
            self.log_output(f"Starting pairing with {ip}, PIN: {pin}")
        except Exception as e:
            return

        # Pre-check: can we reach Buddy's API?
        ok, msg = check_buddy_api(ip, host.get("buddy_port", 59999))
        if not ok:
            notify(self, t("pairing_unreachable", ip=ip, port=host.get('buddy_port', 59999)),
                   f"{msg}\n\n" + t("pairing_unreachable_hint"), kind="error")
            return
        self.log_output(f"Buddy reachable: {msg}")

        cli_cfg = {
            "version": 1,
            "clientId": ensure_client_id(self.cfg),
            "defaultHost": ip,
            "hosts": {
                ip: {
                    "address": ip,
                    "manualAddress": True,
                    "infoPort": 47989,
                    "buddyPort": host.get("buddy_port", 59999),
                    "hostName": host.get("name", ip),
                    "mac": host.get("mac")
                }
            }
        }
        tmp = APP_DIR / f".pair_{uuid.uuid4().hex[:6]}.json"
        tmp.write_text(json.dumps(cli_cfg))

        try:
            dlg = QMessageBox(self)
            dlg.setWindowTitle(t("pairing_title"))
            dlg.setText(t("pairing_pin", pin=pin) + "\n\n" + t("pairing_waiting"))
            dlg.setStandardButtons(QMessageBox.StandardButton.Cancel)
            dlg.setModal(False)
            dlg.show()
            dlg.raise_()
            QApplication.processEvents()
        except Exception as e:
            return

        result = {"done": False, "ok": False, "msg": ""}

        def worker():
            try:
                rc, out, err = run_cli(
                    ["host", "pair", ip, "--pin", pin, "--buddy-port", str(host.get("buddy_port", 59999))],
                    timeout=180,
                    config_override=tmp
                )
                result["ok"] = rc == 0
                result["msg"] = (out or err or "").strip()
                if result["ok"]:
                    self._fetch_and_save_mac(host, tmp)
            except Exception as e:
                result["msg"] = str(e)
            finally:
                result["done"] = True
                tmp.unlink(missing_ok=True)

        th = threading.Thread(target=worker, daemon=True)
        th.start()

        # Poll until done or user cancels
        def check():
            if result["done"]:
                try:
                    dlg.close()
                except Exception:
                    pass
                try:
                    if result["ok"]:
                        notify(self, t("pairing_success"), kind="ok")
                    else:
                        msg = result["msg"] or "Unknown error"
                        notify(self, t("pairing_failed"), msg[:500], kind="error")
                except Exception as e:
                    logging.exception("Dialog error")
                return
            QTimer.singleShot(500, check)

        QTimer.singleShot(500, check)

        def on_cancel():
            # Best effort: we can't easily kill the CLI, but close dialog
            dlg.close()
            result["done"] = True

        dlg.button(QMessageBox.StandardButton.Cancel).clicked.connect(on_cancel)

    def check_status(self, *_signal_args):
        """Timer, Refresh button and F5: check every host."""
        self.check_hosts(None)

    def check_hosts(self, only: str | None = None):
        """Check all hosts (or one id) concurrently; each host in its own thread:
        ICMP ping and Buddy API at the same time, then - only if Buddy answers -
        'steam status'. Results arrive through Signals.host_status."""
        hosts = [h for h in self.cfg.get("hosts", []) if only is None or h.get("id") == only]
        if not hosts:
            return
        if only is None:
            self.log_output("Checking host status...")
        ensure_client_id(self.cfg)    # once on the GUI thread, not inside the workers
        for h in hosts:
            row = self.host_rows.get(h["id"])
            if row and row.result is None and not row.checking:
                row.checking = True
                row._render()
            with self._checking_lock:
                if h["id"] in self._checking:
                    continue          # previous check of this host still running
                self._checking.add(h["id"])
            threading.Thread(target=self._check_host, args=(dict(h),), daemon=True).start()

    def _check_host(self, h: dict):
        res = {"ping": False, "buddy": False, "steam": None, "time": ""}
        try:
            box = {}
            tp = threading.Thread(target=lambda: box.update(ping=ping_icmp(h.get("ip", ""))), daemon=True)
            tp.start()
            ok, body = check_buddy_api(h.get("ip", ""), h.get("buddy_port", 59999), timeout=2.0)
            res["buddy"] = ok
            # 1.3.1: Buddy API vs. the one the bundled CLI speaks (only a warning)
            res["api"] = backend.parse_api_version(body) if ok else None
            mm = backend.api_mismatch(res["api"]) if ok else None
            tp.join(8)
            res["ping"] = bool(box.get("ping"))
            if res["buddy"] and not mm:
                rc, out, err = self._run_cli_for_host(
                    h, ["steam", "status", "--json", "--buddy-timeout", "2"], timeout=15)
                res["steam"] = parse_steam_status(out) if rc == 0 else None
                if rc != 0:
                    logging.debug("steam status %s rc=%s %s", h.get("name"), rc, (err or out)[:200])
                mm = backend.api_mismatch(None, f"{out or ''}\n{err or ''}")
                if mm:
                    res["steam"] = None
            res["api_mismatch"] = mm
        except Exception:
            logging.exception("status check %s", h.get("name"))
        res["time"] = time.strftime("%H:%M:%S")
        logging.info("Status %s: ping=%s buddy=%s steam=%s%s", h.get("name", h.get("ip")),
                     res["ping"], res["buddy"], res["steam"],
                     f" api_mismatch={res['api_mismatch']}" if res.get("api_mismatch") else "")
        self.signals.host_status.emit(h["id"], res)

    def on_host_status(self, hid: str, res: dict):
        with self._checking_lock:
            self._checking.discard(hid)
        if not any(h.get("id") == hid for h in self.cfg.get("hosts", [])):
            return                    # host was removed meanwhile
        self.host_state[hid] = res
        row = self.host_rows.get(hid)
        if row:
            row.set_result(res)
        # tray: online as soon as Buddy answers on any host
        self._update_tray_icon(any(s.get("buddy") for s in self.host_state.values()))
        if not self._checking:
            self.log_output("Status check complete")

    def on_action_started(self, hid: str, title: str, action: str):
        self.log_output(f"Running {action} on {title}...")
        self._busy_hosts = getattr(self, "_busy_hosts", set()) | {hid}
        self._update_state_lbl()
        self._count_usage(hid, action)
        r = self.host_rows.get(hid)
        if r:
            r.set_busy(True, action)          # tile: "Wird geweckt …" etc.

    def on_action_done(self, hid: str, title: str, action: str, success: bool, msg: str):
        getattr(self, "_busy_hosts", set()).discard(hid)
        self._update_state_lbl()
        self.log_output(f"[{title}] {action} {'OK' if success else 'FAIL'}: {msg}")
        r = self.host_rows.get(hid)
        if r:
            if success:
                # with auto refresh the tile waits for the new status (or the timeout)
                r.set_busy(False, keep_pending=self.cfg["settings"].get("auto_status", True))
            else:
                r.set_failed(t(f"failed_{action}", title=title) + " " + (msg.splitlines()[0][:120] if msg else ""))
        # the state changes after an action (PC boots / shuts down, Steam starts):
        # re-check this host a bit later, and once more when it has settled
        if self.cfg["settings"].get("auto_status", True):
            for delay in (3000, 15000):
                QTimer.singleShot(delay, lambda h=hid: self.check_hosts(h))
        if success:                                 # "{Host}: {Aktion} gesendet"
            notify(self, t(f"done_{action}", title=title), kind="ok")
        else:
            hint = t("hibernate_failed_hint") if action == "hibernate" else t("action_failed_hint")
            mm = (r.mismatch() if r else None) or backend.api_mismatch(None, msg or "")
            if mm:                                  # Buddy speaks another API: say what to update
                hint = t("hint_buddy_mismatch") + " – " + HostRow.mismatch_text(mm, "fix")
            notify(self, t(f"failed_{action}", title=title), hint + f"\n\n{msg[:200]}", kind="error")

    def open_options(self):
        dlg = OptionsDialog(self.cfg["settings"], self)
        self._options_dlg = dlg          # live "last checked" while it is open
        accepted = dlg.exec() == QDialog.DialogCode.Accepted
        self._options_dlg = None
        if accepted:
            new = dlg.get_settings()
            cli_changed = new.get("custom_cli", "") != self.cfg["settings"].get("custom_cli", "")
            theme_changed = new.get("theme") != self.cfg["settings"].get("theme")
            lang_changed = resolve_language(new) != resolve_language(self.cfg["settings"])
            looks_changed = any(new.get(k, True) != self.cfg["settings"].get(k, True) for k in ("show_ip", "show_steam"))
            self.cfg["settings"].update(new)
            save_config(self.cfg)
            setup_logging(new["logging"])
            set_autostart(new["autostart"])
            if new["auto_status"]:
                self.status_timer.start(new["status_interval"] * 1000)
            else:
                self.status_timer.stop()
            if looks_changed:
                self.refresh_hosts()      # IP pill / Steam label change the card widths
            else:
                for r in self.host_rows.values():
                    r._render()           # button enablement depends on auto_status
            if cli_changed:
                backend.set_custom_cli(new.get("custom_cli", ""))
                self._cli_toast_for = None
                self._probe_custom_cli()
            self._update_status_bar()
            hints = ([t("theme_restart")] if theme_changed else []) + ([t("language_restart")] if lang_changed else [])
            notify(self, t("settings_saved"), "\n".join(hints), kind="ok")

    def _make_tray_icon(self, online: bool) -> QIcon:
        pix = QPixmap(22, 22)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        use_color = self.cfg.get("settings", {}).get("tray_color_change", True)
        if use_color:
            color = QColor("#4caf50") if online else QColor("#888888")
        else:
            color = QColor("#e0e0e0")
        p.setPen(QPen(color, 2))
        p.setBrush(Qt.GlobalColor.transparent)
        p.drawEllipse(2, 2, 18, 18)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawEllipse(7, 7, 8, 8)
        p.end()
        return QIcon(pix)

    def _update_tray_icon(self, any_online: bool):
        self.tray.setIcon(self._make_tray_icon(any_online))

    def log_output(self, text: str):
        """Append a timestamped message to the output field."""
        if not text:
            return
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        self.output.append(f"[{ts}] {text.rstrip()}")
        self.output.ensureCursorVisible()
        logging.info(text.strip())

    def _show_attribution(self):
        QMessageBox.information(self, "BuddyRemote", t("attribution"))
        (APP_DIR / ".attributed").touch()

    def show_normal(self):
        self._restore_window_state()
        self.show()
        self.raise_()
        self.activateWindow()

    def bring_to_front(self):
        """Another start of BuddyRemote asked us to show the window."""
        if self.isMinimized():
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        if self.isVisible():
            self.raise_()
            self.activateWindow()
        else:
            self.show_normal()

    def tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self.show_normal()

    def quit_app(self):
        """Really quit the application (from tray)."""
        self.status_timer.stop()
        release_lock()
        QApplication.quit()

    # --- UI only: toast, status bar, log toggle ----------------------------
    def show_toast(self, title: str, detail: str = "", kind: str = "ok", action=None, ms: int | None = None):
        """Non-blocking feedback: toast + log (replaces info popups; the status bar only shows the state).
        While the window is hidden in the tray, the tray balloon is used instead."""
        title = title.strip()
        if "\n" in title and not detail:
            title, detail = title.split("\n", 1)
        detail = detail.strip()
        self.log_output(("ERROR: " if kind == "error" else "") + title + (f" – {detail}" if detail else ""))
        if not self.isVisible():
            icon = QSystemTrayIcon.MessageIcon.Critical if kind == "error" else QSystemTrayIcon.MessageIcon.Information
            self.tray.showMessage("BuddyRemote", title + (f"\n{detail}" if detail else ""), icon, 5000)
            return
        if len(detail) > 300:
            detail = detail[:300] + "…"
        self.toast.show_message(title, detail, kind, self._light(),
                                ms or (9000 if kind == "error" else 4500), action=action)

    def _toast_base_bottom(self):
        cw = self.centralWidget()
        return self.scroll.mapTo(cw, self.scroll.rect().bottomLeft()).y() - 8

    def _toast_bottom(self):
        """Toast sits just above the log toggle (bottom right of the host list),
        stacked above the update toast while that one is shown."""
        b = self._toast_base_bottom()
        if hasattr(self, "update_toast") and self.update_toast.isVisible():
            b = self.update_toast.y() - 8
        return b

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "update_toast") and self.update_toast.isVisible():
            self.update_toast.place()
        if hasattr(self, "toast") and self.toast.isVisible():
            self.toast.place()

    # --- update check (reads the latest GitHub release; never downloads) ----------
    def check_for_updates(self, manual: bool = False):
        """One check for BuddyRemote and the bundled MoonDeck CLI (at startup and on
        "Jetzt prüfen"). Only reports; nothing is downloaded."""
        if self._update_running:
            return
        self._update_running = True
        self._refresh_options_updates()

        def worker():
            try:
                rel = fetch_latest_release(timeout=5.0)
                res = {"ok": True, "manual": manual, **rel, "newer": release_is_update(rel)}
            except Exception as e:
                cert = cacerts.is_cert_problem(e)
                no_ca = isinstance(getattr(e, "reason", e), cacerts.NoCAStoreError)
                logging.warning("Update check failed (%s; CA store: %s): %r", "certificate problem"
                                if cert else "connection problem", cacerts.describe(), e)
                res = {"ok": False, "manual": manual, "error": str(e)[:300], "cert": cert, "no_ca": no_ca}
            try:        # the bundled CLI against the nightly asset (a custom CLI is not compared)
                res["cli"] = backend.check_cli_update(timeout=10)
            except Exception as e:
                logging.warning("MoonDeck CLI update check failed: %r", e)
                res["cli"] = {"ok": False, "error": str(e)[:300]}
            self.signals.update_result.emit(res)
        threading.Thread(target=worker, daemon=True).start()

    def on_update_result(self, res: dict):
        self._update_running = False
        cli = res.get("cli") or {"ok": False, "error": "not checked"}
        app_new = bool(res.get("ok") and res.get("newer"))
        cli_new = bool(cli.get("ok") and cli.get("newer"))
        st = QSettings(str(WINDOW_STATE_FILE), QSettings.Format.IniFormat)
        st.setValue("update/last_checked", time.strftime("%Y-%m-%dT%H:%M:%S"))
        st.setValue("update/last_result", ("newer:" + res["version"]) if app_new
                    else ("current" if res.get("ok") else "error"))
        st.setValue("update/cli_result", ("newer:" + str(cli.get("commit") or "")) if cli_new
                    else ("current" if cli.get("ok") else "error"))
        # the CLI-only toast of the automatic check: once per nightly build, not at every start
        cli_seen = str(st.value("update/cli_notified", "") or "")
        if cli_new and (res.get("manual") or app_new):
            st.setValue("update/cli_notified", str(cli.get("commit") or ""))
        st.sync()
        self._refresh_options_updates()
        if cli.get("ok"):
            self.log_output("MoonDeck CLI check: " + (f"newer nightly {cli.get('commit')}" if cli_new
                                                      else "bundled CLI is current"))
        else:
            self.log_output(f"MoonDeck CLI check failed: {cli.get('error', '')}")
        if not res.get("ok"):
            # details (cause + CA store in use) go to the log; the toast stays short
            self.log_output(f"Update check failed: {res.get('error', '')} "
                            f"[CA store: {cacerts.describe()}]")
            if res.get("manual"):   # the automatic check stays silent
                notify(self, t("update_failed"),
                       t("update_failed_no_ca") if res.get("no_ca") else t("update_failed_detail"),
                       kind="error")
            if not cli_new:
                return
        else:
            self.log_output(f"Update check: latest {res['version']}, running {APP_VERSION}")
        if cli_new and not app_new and not res.get("manual") and cli_seen == str(cli.get("commit") or ""):
            cli_new = False                     # already announced this build
        elif cli_new and not app_new:
            st.setValue("update/cli_notified", str(cli.get("commit") or ""))
            st.sync()
        if app_new or cli_new:
            self._pending_update = {
                "version": res["version"] if app_new else "", "url": res.get("url", ""),
                "cli": ("nightly " + str(cli.get("commit") or "")).strip() if cli_new else None,
                "cli_url": cli.get("url") or backend.CLI_RELEASE_PAGE}
            if self.isVisible():
                self._show_update_toast()
            else:
                msg = (t("update_both_title", version=res["version"]) if app_new and cli_new else
                       t("update_available", version=res["version"]) if app_new else t("cli_update_title"))
                self.tray.showMessage("BuddyRemote", msg, QSystemTrayIcon.MessageIcon.Information, 8000)
        elif res.get("manual") and res.get("ok"):
            notify(self, t("update_current_both", version=APP_VERSION) if cli.get("ok")
                   else t("update_current", version=APP_VERSION), kind="ok")

    def _show_update_toast(self):
        if not self._pending_update:
            return
        p = self._pending_update
        self.update_toast.show_update(p.get("version", ""), self._light(), cli=p.get("cli"))
        if self.toast.isVisible():
            self.toast.place()

    def _open_update_page(self):
        p = self._pending_update or {}
        if p.get("version") or not p.get("cli"):
            url = p.get("url") or "https://github.com/deciderino/BuddyRemote/releases/latest"
        else:                                   # only the CLI is newer: its release page
            url = p.get("cli_url") or backend.CLI_RELEASE_PAGE
        QDesktopServices.openUrl(QUrl(url))
        self.update_toast.hide()

    def update_state(self) -> dict:
        """For Options › Updates: running check, last check, results of both boxes."""
        st = QSettings(str(WINDOW_STATE_FILE), QSettings.Format.IniFormat)
        checked = bool(st.value("update/last_checked", ""))
        return {"checking": self._update_running, "last": self.update_status_text(),
                "app": str(st.value("update/last_result", "") or "") if checked else "",
                "cli": str(st.value("update/cli_result", "") or "") if checked else ""}

    def _refresh_options_updates(self):
        dlg = self._options_dlg
        if dlg is not None and hasattr(dlg, "refresh_updates"):
            dlg.refresh_updates(self.update_state())

    def update_status_text(self) -> str:
        st = QSettings(str(WINDOW_STATE_FILE), QSettings.Format.IniFormat)
        when = str(st.value("update/last_checked", "") or "")
        if not when:
            return t("update_never")
        try:
            tm = time.strptime(when, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            return t("update_never")
        if time.strftime("%Y-%m-%d", tm) == time.strftime("%Y-%m-%d"):
            day = t("today") + " " + time.strftime("%H:%M", tm)
        else:
            day = time.strftime(t("date_fmt"), tm)
        return t("upd_last_checked", when=day)

    # --- custom MoonDeck CLI ------------------------------------------------------
    def _probe_custom_cli(self):
        """Check a configured custom CLI in the background (its --help); the result
        arrives via the cli_state signal. Bundled only: nothing to do."""
        if backend.custom_cli_path():
            threading.Thread(target=backend.active_cli, daemon=True).start()
        else:
            self._update_status_bar()

    def on_cli_state(self, state: str, path: str, reason: str):
        """Custom CLI changed state. failed/missing: the bundled CLI takes over, the
        setting stays; one amber toast per change (with "Einstellungen")."""
        if hasattr(self, "cli_lbl"):
            self._update_status_bar()
        dlg = self._options_dlg
        if dlg is not None and hasattr(dlg, "_render_cli_block"):
            dlg._render_cli_block()
        if state in ("failed", "missing"):
            logging.warning("custom MoonDeck CLI %s (%s): %s – using the bundled CLI", state, path, reason)
            if self._cli_toast_for == (state, path):
                return
            self._cli_toast_for = (state, path)
            title = t("cli_custom_failed") if state == "failed" else t("cli_custom_missing")
            self.show_toast(title, t("cli_toast_detail", path=path), kind="info",
                            action=(t("toast_settings"), self._open_options_from_toast), ms=15000)
        elif state == "ok":
            self._cli_toast_for = None

    def _open_options_from_toast(self):
        self.toast.hide()
        if self._options_dlg is None:
            self.open_options()

    def _update_counts(self):
        if not hasattr(self, "count_lbl"):
            return
        n = len(self.host_rows)
        on = sum(1 for r in self.host_rows.values() if r.state == "online")
        self.count_lbl.setText(t("count_hosts", n=n, online=on))

    def _update_status_bar(self):
        st = self.cfg.get("settings", {})
        if st.get("auto_status", True):
            self.refresh_lbl.setText(t("auto_refresh_every", s=st.get("status_interval", 30)))
        else:
            self.refresh_lbl.setText(t("auto_refresh_off"))
        path = backend.custom_cli_path()
        if path:        # custom CLI chosen: always visible, also while it works
            state, reason = backend.custom_cli_state()
            tip = t("cli_custom_status_tip", path=path)
            if state in ("failed", "missing"):
                tip += "\n" + (t("cli_custom_failed") if state == "failed" else t("cli_custom_missing")) \
                    + (f" ({reason})" if reason else "")
            self.cli_lbl.setText(t("cli_custom_status"))
            self.cli_lbl.setToolTip(tip)
        else:
            self.cli_lbl.setText("MoonDeck CLI " + ("✓" if cli_available() else "✗"))
            self.cli_lbl.setToolTip("")
        self._update_counts()

    def _set_log_visible(self, on: bool):
        self.output.setVisible(on)
        self._apply_log_height()
        if hasattr(self, "tray"):
            self._fit_min_size()
        self.log_btn.setText(("▾ " if on else "▸ ") + t("log_toggle"))
        if hasattr(self, "toast") and self.toast.isVisible():
            QTimer.singleShot(0, self.toast.place)

    def toggle_log(self):
        on = not self.output.isVisible()
        self._set_log_visible(on)
        try:
            st = QSettings(str(WINDOW_STATE_FILE), QSettings.Format.IniFormat)
            st.setValue("log_visible", "true" if on else "false")
            st.sync()
        except Exception:
            logging.exception("window state save failed")

    def _on_focus_changed(self, old, new):
        """Highlight the card that contains the keyboard focus (hidden in mouse mode)."""
        visible = getattr(self, "input_mode", None) is None or self.input_mode.nav_visible
        for hid, r in self.host_rows.items():
            try:
                if self._edit_mode:         # edit mode: the card the edit bar works on
                    r.set_current(hid == self._edit_hid)
                    continue
                r.set_current(visible and new is not None and r.isAncestorOf(new))
            except RuntimeError:
                pass

    # --- UI only: keyboard/controller navigation -------------------------
    @staticmethod
    def _navigable(b) -> bool:
        try:
            return b.isEnabled() and b.isVisibleTo(b.window())
        except RuntimeError:
            return False

    def _nav_grid(self):
        """Arrow-key/controller grid: one row per toolbar, host card and log button.
        Disabled buttons are skipped (not focusable)."""
        if self._tb_collapsed:
            grid = [[self.tb_grip]]
        else:
            grid = [[self.tb_btns[it["id"]] for it in self._tb_items] + [self.tb_collapse_btn]]
        if self._edit_mode:
            grid += [self.edit_top_buttons, self.edit_tool_buttons]
        grid += [row for r in self.host_rows.values() for row in r.nav_rows]
        if getattr(self, "empty_add_btn", None) is not None and not self.host_rows:
            grid.append([self.empty_add_btn])
        if self.toast.isVisible() and self.toast.action_btn.isVisible():
            grid.append(self.toast.buttons)
        if self.update_toast.isVisible():
            grid.append(self.update_toast.buttons)
        grid.append([self.log_btn])
        grid = [[b for b in row if self._navigable(b)] for row in grid]
        return [row for row in grid if row]

    def _focus_first(self):
        target = None
        for r in self.host_rows.values():
            target = next((b for b in r.nav_buttons if self._navigable(b)), None)
            if target:
                break
        target = target or (self.tb_grip if self._tb_collapsed else self.tb_btns[self._tb_items[0]["id"]])
        target.setFocus(Qt.FocusReason.TabFocusReason)
        self.scroll.ensureWidgetVisible(target)

    @staticmethod
    def _center_x(w) -> int:
        return w.mapToGlobal(w.rect().center()).x()

    def _ensure_focus(self):
        if self.isVisible() and QApplication.activeModalWidget() is None:
            fw = QApplication.focusWidget()
            if fw is None or not fw.isVisible() or fw.window() is not self:
                self._focus_first()

    def eventFilter(self, obj, ev):
        iid = obj.property("navKey") if isinstance(obj, QPushButton) else None
        if self._edit_mode and isinstance(iid, str) and iid.startswith("tb_") and iid[3:] in TOOLBAR_ITEMS:
            if ev.type() == QEvent.Type.ContextMenu:
                self.toolbar_menu(iid[3:], gpos=ev.globalPos())
                return True
            if ev.type() == QEvent.Type.KeyPress:
                if ev.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                    self._tb_select(iid[3:])
                    self.toolbar_cannot_hide()
                    return True
                if ev.key() == Qt.Key.Key_Menu:
                    self.toolbar_menu(iid[3:])
                    return True
        if ev.type() == QEvent.Type.KeyPress and isinstance(obj, QPushButton):
            key = ev.key()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and ev.modifiers() in (
                    Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.KeypadModifier):
                obj.click()
                return True
            if key in _NAV_KEYS and ev.modifiers() in (
                    Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.KeypadModifier):
                grid = self._nav_grid()
                for r, row in enumerate(grid):
                    if obj in row:
                        c = row.index(obj)
                        if key == Qt.Key.Key_Left:
                            c = max(0, c - 1)
                        elif key == Qt.Key.Key_Right:
                            c = min(len(row) - 1, c + 1)
                        else:
                            nr = max(0, r - 1) if key == Qt.Key.Key_Up else min(len(grid) - 1, r + 1)
                            if nr != r:
                                # card to card: the same button if usable there, else the
                                # usable button closest in x (also toolbar <-> cards)
                                nk = obj.property("navKey")
                                same = [i for i, b in enumerate(grid[nr]) if nk and b.property("navKey") == nk]
                                if same:
                                    c = same[0]
                                else:
                                    ref = self._center_x(obj)
                                    c = min(range(len(grid[nr])), key=lambda i: abs(self._center_x(grid[nr][i]) - ref))
                            r = nr
                        target = grid[r][c]
                        target.setFocus(Qt.FocusReason.TabFocusReason)
                        self.scroll.ensureWidgetVisible(target)
                        return True
        return super().eventFilter(obj, ev)

    # --- UI only: window size/state ----------------------------------------
    def _available(self):
        scr = self.screen() or QApplication.primaryScreen()
        return scr.availableGeometry() if scr else None

    # UI only: cards never get wider than this (wide/maximized windows keep the
    # buttons close to the host name; cards are centered).
    CARD_MAX_EXTRA = 200

    def _relayout_rows(self):
        """UI only: center the cards when the window is very wide."""
        rows = list(self.host_rows.values())
        if not rows:
            self.host_layout.setContentsMargins(0, 0, 0, 0)
            return
        vw = self.scroll.viewport().width()
        need = max(r.wide_width() for r in rows)
        cap = need + self.CARD_MAX_EXTRA
        side = max(0, (vw - cap) // 2)
        m = self.host_layout.contentsMargins()
        if m.left() != side:
            self.host_layout.setContentsMargins(side, 0, side, 0)

    def _fit_min_size(self):
        """UI only: minimum size computed from the real layout (scales with font
        size and display scaling): the narrowest card with every tile text readable,
        toolbar and status bar; height keeps one card visible."""
        avail = self._available()
        rows = list(self.host_rows.values())
        bm = self._body_layout.contentsMargins()
        chrome_w = bm.left() + bm.right() + 2 * self.scroll.frameWidth() + self.scroll.verticalScrollBar().sizeHint().width()
        card_w = max([r.wide_width() for r in rows] + [0])
        perm = sum(l.sizeHint().width() for l in (self.count_lbl, self.refresh_lbl, self.cli_lbl)) + 60
        w = max(card_w + chrome_w, self.toolbar.minimumSizeHint().width(), perm, 420)
        card_h = max([r.min_card_height() for r in rows] + [80])
        h = ((self.tb_grip.sizeHint().height() if self._tb_collapsed else self.toolbar.sizeHint().height())
             + (self.edit_bar.heightForWidth(w) if self._edit_mode and self.edit_bar.hasHeightForWidth()
                else self.edit_bar.sizeHint().height() if self._edit_mode else 0)
             + (self.statusBar().sizeHint().height() if self.statusBar() else 0)
             + bm.top() + bm.bottom() + 2 * self.scroll.frameWidth() + card_h
             + self.splitter.handleWidth())
        if self._log_open():
            h += self.LOG_MIN
        if avail:
            w, h = min(w, avail.width()), min(h, avail.height())
        self.setMinimumSize(w, h)

    @staticmethod
    def _is_wayland() -> bool:
        return QApplication.platformName().startswith("wayland")

    def _clamp_to_screen(self):
        """UI only: saved geometry larger than the screen is shrunk; a window whose
        title bar ended up off-screen (X11; Wayland ignores positions) is pulled back."""
        avail = self._available()
        if not avail or self.isMaximized() or self.isFullScreen():
            return
        if self.width() > avail.width() or self.height() > avail.height():
            self.resize(min(self.width(), avail.width()), min(self.height(), avail.height()))
        if self._is_wayland():
            return
        fg = self.frameGeometry()
        visible = False
        for scr in QApplication.screens():
            a = scr.availableGeometry()
            title = fg.adjusted(0, 0, 0, -(fg.height() - 40))  # top 40 px: the grab area
            if a.intersected(title).width() >= 100:
                visible = True
                break
        if not visible:
            x = avail.x() + (avail.width() - fg.width()) // 2
            y = avail.y() + (avail.height() - fg.height()) // 2
            self.move(max(avail.x(), x), max(avail.y(), y))

    def _restore_window_state(self):
        self._fit_min_size()
        st = QSettings(str(WINDOW_STATE_FILE), QSettings.Format.IniFormat)
        geo = st.value("geometry")
        if not (geo and self.restoreGeometry(geo)):
            avail = self._available()
            w, h = 900, 640
            if avail:
                w = max(min(w, int(avail.width() * 0.9)), min(self.minimumWidth(), avail.width()))
                h = max(min(h, int(avail.height() * 0.9)), min(self.minimumHeight(), avail.height()))
            self.resize(w, h)
        self._clamp_to_screen()

    def _save_window_state(self):
        if not self._was_shown:
            return
        try:
            st = QSettings(str(WINDOW_STATE_FILE), QSettings.Format.IniFormat)
            st.setValue("geometry", self.saveGeometry())
            st.sync()
        except Exception:
            logging.exception("window state save failed")

    def showEvent(self, event):
        super().showEvent(event)
        self._was_shown = True
        QTimer.singleShot(0, self._focus_first)
        if self._pending_update and not self.update_toast.isVisible():
            QTimer.singleShot(300, self._show_update_toast)   # found while hidden in the tray

    def hideEvent(self, event):
        self._save_window_state()
        super().hideEvent(event)

    def start_hidden(self) -> bool:
        """"Start minimized" only when the window can be brought back and there is
        something to show: a system tray exists and at least one host is set up (the
        empty start with its "Ersten Host hinzufügen" tile is always visible)."""
        return (bool(self.cfg["settings"].get("start_minimized", False))
                and bool(self.cfg.get("hosts"))
                and QSystemTrayIcon.isSystemTrayAvailable())

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        self.tray.showMessage("BuddyRemote", t("running_in_background"), QSystemTrayIcon.MessageIcon.Information, 2000)

# ---------------------------------------------------------------------------

def main():
    prepare_packaged_dir()
    seed_config()

    # UI only: fractional display scaling (125 %, 150 %, ...) is used as-is instead of
    # being rounded to whole numbers. This is already the Qt 6 default; set explicitly
    # so it stays that way (all sizes in the stylesheets are device-independent px).
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    set_windows_app_id()
    app = QApplication(sys.argv)
    app.setApplicationName("BuddyRemote")
    if IS_WINDOWS:   # Linux: the icon comes from the .desktop file / AppImage
        icon = RES_DIR / "packaging" / "buddyremote.png"
        if icon.is_file():
            app.setWindowIcon(QIcon(str(icon)))
    if not acquire_lock():
        if notify_running_instance():
            print("BuddyRemote is already running - showing its window.")
        else:
            print("BuddyRemote is already running.")
        sys.exit(0)
    # Apply theme to all dialogs
    cfg = load_config()
    lang_code = resolve_language(cfg.get("settings", {}))
    set_language(lang_code)
    install_qt_translations(app, lang_code)
    light = cfg.get("settings", {}).get("theme", "Dark") == "Light"
    apply_app_theme(app, light)
    app.setApplicationDisplayName("BuddyRemote")
    app.setOrganizationName("BuddyRemote")
    app.setDesktopFileName("buddyremote")
    app.setQuitOnLastWindowClosed(False)

    # Ensure CLI is present
    if PACKAGED:
        # Packaged: the CLI is run straight from the bundle (cli_path); never download.
        if not cli_available():
            QMessageBox.warning(None, "BuddyRemote",
                                t("cli_bundled_missing_win" if IS_WINDOWS else "cli_bundled_missing"))
    elif not cli_available():
        dlg = DownloadDialog()
        dlg.show()
        ok = download_cli(dlg.set_status)
        dlg.close()
        if not ok:
            QMessageBox.critical(None, "BuddyRemote", t("cli_download_failed"))
            sys.exit(1)

    win = MainWindow()
    start_instance_server(win.bring_to_front)
    if not win.start_hidden():
        win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    try:
        main()
    finally:
        release_lock()
