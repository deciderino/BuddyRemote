"""BuddyRemote – dialogs: keyboard/controller navigation + screen fitting for dialogs,
toast feedback helper, license viewer, options dialog and the first-run CLI setup dialog."""
import html
import logging
import os
import sys
from pathlib import Path
from PyQt6.QtWidgets import (QApplication, QAbstractButton, QCheckBox, QComboBox, QDialog, QFormLayout,
                             QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                             QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QSpinBox,
                             QVBoxLayout, QWidget)
from PyQt6.QtCore import Qt, QObject, QEvent, QUrl
from PyQt6.QtGui import QDesktopServices, QFont
from paths import APP_VERSION, APP_DIR, RES_DIR, PACKAGED
from i18n import LANGUAGES, LANGUAGE_NAMES, language_choice, t
from config import load_config
import backend
from theme import dialog_stylesheet, ui_colors


class _DialogNavFilter(QObject):
    """UI only: controller-friendly focus handling inside dialogs.
    Fields (line edits, spin boxes, combo boxes) have two states:
      navigation = focused + highlighted; arrows move focus, Enter enters edit mode
      edit mode  = amber border; keys edit the value; Enter accepts, Escape reverts.
    Mouse click or typing a character enters edit mode immediately (desktop-first).
    Enter on a field never triggers the dialog's default button."""
    _ARROWS = (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Right)
    _ENTER = (Qt.Key.Key_Return, Qt.Key.Key_Enter)
    _MODS = (Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Meta,
             Qt.Key.Key_AltGr, Qt.Key.Key_CapsLock, Qt.Key.Key_NumLock)

    def __init__(self, dlg: QDialog):
        super().__init__(dlg)
        self.dlg = dlg
        self.fields = set()
        self.saved = {}
        for w in dlg.findChildren(QWidget):
            self.register(w)

    def register(self, w):
        """Also used for widgets a dialog creates later (rebuilt tile rows)."""
        if isinstance(w, (QLineEdit, QSpinBox, QComboBox)) and not isinstance(w.parent(), (QSpinBox, QComboBox)):
            self.fields.add(w)
            w.setProperty("editMode", False)
            w.installEventFilter(self)
            if isinstance(w, QSpinBox):
                w.lineEdit().installEventFilter(self)  # mouse clicks land on the inner edit
        elif isinstance(w, QAbstractButton):
            w.installEventFilter(self)

    @staticmethod
    def _value(w):
        if isinstance(w, QLineEdit):
            return w.text()
        if isinstance(w, QSpinBox):
            return w.value()
        return w.currentIndex()

    @staticmethod
    def _restore(w, v):
        if isinstance(w, QLineEdit):
            w.setText(v)
        elif isinstance(w, QSpinBox):
            w.setValue(v)
        else:
            w.setCurrentIndex(v)

    def editing(self, w) -> bool:
        return bool(w.property("editMode"))

    def _set_edit(self, w, on: bool):
        if self.editing(w) == on:
            return
        if on:
            self.saved[w] = self._value(w)
        w.setProperty("editMode", on)
        w.style().unpolish(w)
        w.style().polish(w)
        w.update()

    def _move(self, forward: bool):
        self.dlg.focusNextPrevChild(forward)
        fw = QApplication.focusWidget()
        p = fw.parent() if fw else None
        while p is not None and p is not self.dlg:
            if isinstance(p, QScrollArea):
                p.ensureWidgetVisible(fw)
                break
            p = p.parent()

    def eventFilter(self, obj, ev):
        et = ev.type()
        field = obj if obj in self.fields else (obj.parent() if obj.parent() in self.fields else None)
        if field is None:  # buttons / checkboxes: arrows move focus, Enter on a checkbox toggles it
            if et == QEvent.Type.KeyPress and not ev.modifiers() & ~Qt.KeyboardModifier.KeypadModifier:
                if ev.key() in self._ARROWS:
                    self._move(ev.key() in (Qt.Key.Key_Down, Qt.Key.Key_Right))
                    return True
                if ev.key() in self._ENTER and isinstance(obj, QCheckBox):
                    obj.click()
                    return True
            return False
        if et == QEvent.Type.MouseButtonPress and not isinstance(field, QComboBox):
            self._set_edit(field, True)
        elif et == QEvent.Type.FocusIn and obj is field:
            if ev.reason() == Qt.FocusReason.MouseFocusReason and not isinstance(field, QComboBox):
                self._set_edit(field, True)
        elif et == QEvent.Type.FocusOut and obj is field:
            if ev.reason() != Qt.FocusReason.PopupFocusReason:
                self._set_edit(field, False)  # leaving a field keeps (accepts) its value
        elif et == QEvent.Type.KeyPress and obj is field:
            key = ev.key()
            if self.editing(field):
                if key in self._ENTER:
                    self._set_edit(field, False)
                    return True
                if key == Qt.Key.Key_Escape:
                    self._restore(field, self.saved.get(field, self._value(field)))
                    self._set_edit(field, False)
                    return True
                return False
            # navigation mode
            if key in self._ARROWS and not ev.modifiers() & ~Qt.KeyboardModifier.KeypadModifier:
                self._move(key in (Qt.Key.Key_Down, Qt.Key.Key_Right))
                return True
            if key in self._ENTER:
                self._set_edit(field, True)
                le = field if isinstance(field, QLineEdit) else (field.lineEdit() if isinstance(field, QSpinBox) else None)
                if le is not None:
                    le.deselect()
                    le.end(False)  # cursor at the end, ready to edit with arrows/keyboard
                return True
            if key in (Qt.Key.Key_Escape, Qt.Key.Key_Tab, Qt.Key.Key_Backtab) or key in self._MODS:
                return False
            self._set_edit(field, True)  # typing / Backspace / paste etc. edits right away
            return False
        return False


def install_dialog_nav(dlg: QDialog):
    dlg._nav_filter = _DialogNavFilter(dlg)


def fit_dialog_to_screen(dlg: QDialog):
    """UI only: if a dialog is taller than ~90% of the screen (e.g. Steam Deck at 150%),
    move its contents into a scroll area so nothing ends up off-screen."""
    scr = dlg.screen() or QApplication.primaryScreen()
    if not scr or not dlg.layout():
        return
    max_h = int(scr.availableGeometry().height() * 0.9)
    if dlg.sizeHint().height() <= max_h:
        return
    inner = QWidget()
    inner.setLayout(dlg.layout())  # reparents the existing layout and its widgets
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.Shape.NoFrame)
    sa.setWidget(inner)
    inner.setObjectName("fitInner")
    sa.setStyleSheet("QScrollArea, QWidget#qt_scrollarea_viewport, QWidget#fitInner { background: transparent; }")
    outer = QVBoxLayout(dlg)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.addWidget(sa)
    dlg.resize(inner.sizeHint().width() + sa.verticalScrollBar().sizeHint().width() + 4, max_h)


def license_files() -> list:
    """Bundled third-party license texts: AppImage usr/share/licenses/BuddyRemote
    (also bundled next to the program as "licenses"); dev run: packaging/linux/licenses
    + LICENSE from the source tree."""
    dirs = []
    if os.environ.get("APPDIR"):
        dirs.append(Path(os.environ["APPDIR"]) / "usr" / "share" / "licenses" / "BuddyRemote")
    dirs.append(RES_DIR / "licenses")
    exe = Path(sys.executable).resolve()
    dirs.append(exe.parent.parent / "share" / "licenses" / "BuddyRemote")
    for d in dirs:
        if d.is_dir():
            files = sorted(p for p in d.iterdir() if p.is_file())
            if files:
                return files
    src = Path(__file__).resolve().parent
    files = sorted((src / "packaging" / "linux" / "licenses").glob("*"))
    if (src / "LICENSE").is_file():
        files.insert(0, src / "LICENSE")
    return [p for p in files if p.is_file()]


class LicenseDialog(QDialog):
    """In-app viewer: list of components (left), license text (right)."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("licenses_title"))
        self.setStyleSheet(parent.styleSheet() if parent else "")
        self.resize(860, 600)
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(10)
        hint = QLabel(t("licenses_hint"))
        hint.setWordWrap(True)
        v.addWidget(hint)
        h = QHBoxLayout()
        h.setSpacing(10)
        self.list = QListWidget()
        self.list.setMinimumWidth(260)
        self.list.setMaximumWidth(320)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        f = QFont("monospace")
        f.setStyleHint(QFont.StyleHint.Monospace)
        f.setPixelSize(12)
        self.text.setFont(f)
        h.addWidget(self.list)
        h.addWidget(self.text, 1)
        v.addLayout(h, 1)
        self.files = license_files()
        for p in self.files:
            name = p.stem if p.suffix.lower() in (".txt", ".md") else p.name
            it = QListWidgetItem(name.replace("BuddyRemote-GPL-3.0", "BuddyRemote (GPL-3.0)") if name != "LICENSE"
                                 else "BuddyRemote (LICENSE)")
            it.setToolTip(str(p))
            self.list.addItem(it)
        self.list.currentRowChanged.connect(self._show)
        if self.files:
            self.list.setCurrentRow(0)
        else:
            self.text.setPlainText(t("licenses_none"))
        close = QPushButton(t("close"))
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        v.addLayout(row)
        install_dialog_nav(self)
        fit_dialog_to_screen(self)

    def _show(self, i):
        if 0 <= i < len(self.files):
            try:
                self.text.setPlainText(self.files[i].read_text(encoding="utf-8", errors="replace"))
            except OSError as e:
                self.text.setPlainText(str(e))


class OptionsDialog(QDialog):
    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("options"))
        # checkboxes: 48 px touch target (min-height 40 + padding 2*2 + border 2*2)
        self.setStyleSheet(dialog_stylesheet(parent) + " QCheckBox { min-height: 40px; }")
        layout = QFormLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        light = settings.get("theme", "Dark") == "Light"
        cc = ui_colors(light)

        def section(key, first=False):
            if not first:
                sep = QFrame()
                sep.setFrameShape(QFrame.Shape.HLine)
                sep.setStyleSheet(f"color: {cc['card_b']}; background: {cc['card_b']}; max-height: 1px; border: none;")
                layout.addRow(sep)
            head = QLabel(t(key))
            head.setObjectName("optSection")
            head.setStyleSheet(f"font-size: 12px; font-weight: bold; letter-spacing: 1px; color: {cc['sub']};")
            layout.addRow(head)
            return head

        # --- Anzeige -------------------------------------------------------------
        section("sec_display", first=True)
        self.theme = QComboBox()
        for val in ("Dark", "Light"):          # config keeps the English value
            self.theme.addItem(t(f"theme_{val.lower()}"), val)
        self.theme.setCurrentIndex(max(0, self.theme.findData(settings.get("theme", "Dark"))))
        layout.addRow(t("theme"), self.theme)

        self.language = QComboBox()
        self.language.addItem(t("lang_auto"), "auto")
        for code in LANGUAGES:
            self.language.addItem(LANGUAGE_NAMES[code], code)
        self.language.setCurrentIndex(max(0, self.language.findData(language_choice(settings))))
        layout.addRow(t("language"), self.language)

        self.show_ip = QCheckBox(t("show_ip"))         # off: the IP is only in the tooltip
        self.show_ip.setChecked(settings.get("show_ip", True))
        layout.addRow(self.show_ip)

        self.show_steam = QCheckBox(t("show_steam"))   # "▶ Steam läuft" in the card header
        self.show_steam.setChecked(settings.get("show_steam", True))
        layout.addRow(self.show_steam)

        self.tray_color = QCheckBox(t("tray_color_change"))
        self.tray_color.setChecked(settings.get("tray_color_change", True))
        layout.addRow(self.tray_color)

        # --- Verhalten -----------------------------------------------------------
        section("sec_behavior")
        self.interval = QSpinBox()
        self.interval.setRange(10, 300)
        self.interval.setValue(settings.get("status_interval", 30))
        layout.addRow(t("interval"), self.interval)

        self.auto = QCheckBox(t("auto_refresh"))
        self.auto.setChecked(settings.get("auto_status", True))
        layout.addRow(self.auto)

        self.confirm = QCheckBox(t("confirm_actions"))
        self.confirm.setChecked(settings.get("confirm_actions", True))
        layout.addRow(self.confirm)

        self.start_min = QCheckBox(t("start_min"))
        self.start_min.setChecked(settings.get("start_minimized", False))
        layout.addRow(self.start_min)

        self.autostart = QCheckBox(t("autostart"))
        self.autostart.setChecked(settings.get("autostart", False))
        layout.addRow(self.autostart)

        # --- Updates -------------------------------------------------------------
        section("sec_updates")
        self.check_updates = QCheckBox(t("check_updates"))
        self.check_updates.setChecked(settings.get("check_updates", True))
        layout.addRow(self.check_updates)
        self.update_lbl = QLabel(parent.update_status_text() if parent and hasattr(parent, "update_status_text") else "")
        self.update_lbl.setStyleSheet(f"color: {cc['sub']}; font-size: 13px;")
        self.update_lbl.setWordWrap(True)
        layout.addRow(t("updates_row"), self.update_lbl)
        self.update_btn = QPushButton(t("check_updates_now"))
        self.update_btn.clicked.connect(lambda: parent.check_for_updates(manual=True) if parent else None)
        row = QHBoxLayout()
        row.addWidget(self.update_btn)
        row.addStretch(1)
        layout.addRow(row)

        # --- Dateien -------------------------------------------------------------
        section("sec_files")
        self.logging = QCheckBox(t("enable_logging"))
        self.logging.setChecked(settings.get("logging", False))
        layout.addRow(self.logging)
        self.data_dir_btn = QPushButton(t("open_data_dir"))
        self.data_dir_btn.setToolTip(t("tip_data_dir"))
        self.data_dir_btn.clicked.connect(self._open_data_dir)
        self.data_dir_lbl = QLabel(str(APP_DIR))       # small, selectable: copy the path by hand
        self.data_dir_lbl.setObjectName("dataDirPath")
        self.data_dir_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse
                                                  | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self.data_dir_lbl.setStyleSheet(f"color: {cc['sub']}; font-size: 11px;")
        self.data_dir_lbl.setWordWrap(True)
        self.data_dir_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        drow = QHBoxLayout()
        drow.addWidget(self.data_dir_btn)
        drow.addWidget(self.data_dir_lbl, 1)
        layout.addRow(drow)
        # opening failed: said here in the dialog (a toast would sit behind it)
        self._err_col = cc["err"]
        self._sub_col = cc["sub"]
        self.data_dir_err = QLabel()
        self.data_dir_err.setObjectName("dataDirError")
        self.data_dir_err.setWordWrap(True)
        self.data_dir_err.setStyleSheet(f"color: {cc['err']}; font-size: 13px;")
        self.data_dir_err.hide()
        layout.addRow(self.data_dir_err)

        self.verify_label = None
        if PACKAGED:
            # The AppImage ships a pinned CLI (checksum checked at build time):
            # no download / verify UI, just what is bundled.
            cli_lbl = QLabel(backend.bundled_cli_text())
            cli_lbl.setWordWrap(True)
            layout.addRow("MoonDeck CLI:", cli_lbl)
        else:
            self._add_cli_verify_rows(layout, settings)

        # --- About: only the version and the thanks to MoonDeck, licenses ----------
        section("about_title")
        layout.addRow(t("app_version"), QLabel(APP_VERSION))
        link = "#1565c0" if light else "#4fc3f7"       # readable on both themes
        thanks = QLabel(html.escape(t("about_thanks")) + ' <a href="https://github.com/FrogTheFrog/moondeck" '
                        f'style="color: {link};">MoonDeck</a>')
        thanks.setTextFormat(Qt.TextFormat.RichText)
        thanks.setOpenExternalLinks(True)
        thanks.setToolTip("https://github.com/FrogTheFrog/moondeck")
        thanks.setWordWrap(True)
        layout.addRow(thanks)
        # third-party licenses: own button, in-app viewer
        self.licenses_btn = QPushButton(t("licenses_btn"))
        self.licenses_btn.setToolTip(t("tip_licenses"))
        self.licenses_btn.clicked.connect(lambda: LicenseDialog(self).exec())
        lrow = QHBoxLayout()
        lrow.addWidget(self.licenses_btn)
        lrow.addStretch(1)
        layout.addRow(lrow)

        btns = QHBoxLayout()
        save = QPushButton(t("save"))
        save.clicked.connect(self.accept)
        cancel = QPushButton(t("cancel"))
        cancel.clicked.connect(self.reject)
        btns.addWidget(save)
        btns.addWidget(cancel)
        layout.addRow(btns)
        install_dialog_nav(self)
        fit_dialog_to_screen(self)

    def _open_data_dir(self) -> bool:
        """Opens the data folder in the system file manager (platform neutral)."""
        ok = bool(QDesktopServices.openUrl(QUrl.fromLocalFile(str(APP_DIR))))
        if ok:
            self.data_dir_err.hide()
            self.data_dir_lbl.setStyleSheet(f"color: {self._sub_col}; font-size: 11px;")
        else:
            logging.warning("could not open the data folder %s", APP_DIR)
            self.data_dir_err.setText("⚠ " + t("data_dir_failed") + "\n" + t("data_dir_failed_hint"))
            self.data_dir_err.show()
            # the path stays selectable, in the error colour
            self.data_dir_lbl.setStyleSheet(f"color: {self._err_col}; font-size: 11px; font-weight: bold;")
        return ok

    def _add_cli_verify_rows(self, layout, settings):
        """Source mode (unchanged): checksum state of the downloaded CLI + re-verify."""
        # CLI verification status
        verified = settings.get("cli_verified", False)
        vhash = settings.get("cli_hash", "")
        vtime = settings.get("cli_verified_at", "")
        status_text = t("cli_verified") if verified else t("cli_not_verified")
        if vhash:
            status_text += f" ({vhash[:16]}…)"
        if vtime:
            status_text += f"\n{vtime}"
        self.verify_label = QLabel(status_text)
        self.verify_label.setStyleSheet("color: #4caf50;" if verified else "color: #888;")
        layout.addRow(t("cli_checksum"), self.verify_label)

        verify_btn = QPushButton(t("cli_verify_btn"))
        verify_btn.clicked.connect(self._do_verify)
        layout.addRow(verify_btn)

    def _do_verify(self):
        ok, msg = backend.verify_existing_cli()
        if ok:
            # Reload to get the just-saved timestamp and hash
            cfg = load_config()
            vhash = cfg["settings"].get("cli_hash", "")
            vtime = cfg["settings"].get("cli_verified_at", "")
            text = t("cli_verified")
            if vhash:
                text += f" ({vhash[:16]}…)"
            if vtime:
                text += f"\n{vtime}"
            self.verify_label.setText(text)
            self.verify_label.setStyleSheet("color: #4caf50;")
            notify(self.parent(), t("checksum_verified"), kind="ok")  # UI: toast instead of popup
        else:
            self.verify_label.setText(msg)
            self.verify_label.setStyleSheet("color: #f44336;")
            notify(self.parent(), t("verify_failed"), msg, kind="error")  # UI: toast instead of popup

    def get_settings(self) -> dict:
        return {
            "status_interval": self.interval.value(),
            "auto_status": self.auto.isChecked(),
            "logging": self.logging.isChecked(),
            "start_minimized": self.start_min.isChecked(),
            "autostart": self.autostart.isChecked(),
            "confirm_actions": self.confirm.isChecked(),
            "tray_color_change": self.tray_color.isChecked(),
            "check_updates": self.check_updates.isChecked(),
            "show_ip": self.show_ip.isChecked(),
            "show_steam": self.show_steam.isChecked(),
            "theme": self.theme.currentData() or "Dark",
            "language": self.language.currentData(),
            "language_set": True,
        }


def notify(win, title: str, detail: str = "", kind: str = "ok"):
    """UI only: non-blocking feedback (toast in the main window) instead of an info popup."""
    if win is not None and hasattr(win, "show_toast"):
        win.show_toast(title, detail, kind)


class DownloadDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("BuddyRemote – Setup")
        self.setModal(True)
        self.resize(480, 220)
        layout = QVBoxLayout(self)
        self.label = QLabel("Preparing…")
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.label)
        self.setStyleSheet("""
            QDialog { background: #1e1e1e; }
            QLabel { color: #e0e0e0; font-size: 13px; padding: 8px; }
        """)

    def set_status(self, text: str):
        self.label.setText(text)
        QApplication.processEvents()
