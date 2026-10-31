"""BuddyRemote – Dark/Light theme: palettes, application and dialog stylesheets (incl. touch
sizes) and the colours of the main window and the edit mode."""

import sys

from PyQt6.QtGui import QColor, QPalette

# Monospace family for the log / license text ("monospace" is a fontconfig alias, Windows lacks it)
MONO_FAMILY = "Consolas" if sys.platform == "win32" else "monospace"


def touch_css(light: bool) -> str:
    """UI only: larger touch/TV-friendly controls and a clearly visible focus ring.
    The ring on buttons/checkboxes follows the navFocus property (set by InputModeController
    only in keyboard/controller mode), so it hides while the mouse is used.
    Appended after each theme stylesheet so it overrides sizes, not colors."""
    acc = "#1565c0" if light else "#4fc3f7"
    focus_bg = "#d6e6fa" if light else "#1d3b4f"
    edit = "#e65100" if light else "#ffb74d"
    edit_bg = "#fff3e0" if light else "#2b2620"
    prim, prim_b, prim_h = ("#1565c0", "#0d47a1", "#1976d2") if light else ("#1f5f8b", "#2a7ab0", "#2670a3")
    danger, danger_b, danger_h = ("#c62828", "#8e0000", "#d32f2f") if light else ("#b3261e", "#e53935", "#c62828")
    dis_bg, dis_fg, dis_b = ("#ececec", "#a6a6a6", "#dddddd") if light else ("#242424", "#5c5c5c", "#323232")
    pop_bg, pop_fg, pop_b = ("#ffffff", "#222222", "#bdbdbd") if light else ("#2a2a2a", "#e0e0e0", "#4a4a4a")
    sel_bg, sel_fg = ("#1565c0", "#ffffff") if light else ("#1f5f8b", "#ffffff")
    tip_bg, tip_fg = ("#ffffe8", "#222222") if light else ("#333333", "#f0f0f0")
    return f"""
        QWidget {{ font-size: 15px; }}
        QPushButton {{ min-height: 32px; min-width: 24px; padding: 6px 10px; border-width: 2px; border-radius: 6px; }}
        QPushButton[navFocus="true"] {{ border: 2px solid {acc}; background: {focus_bg}; }}
        QPushButton[touchRole="action"] {{ min-width: 56px; }}
        QPushButton[touchRole="icon"] {{ min-width: 24px; padding: 6px 2px; }}
        QPushButton[primary="true"] {{ background: {prim}; color: #ffffff; border: 2px solid {prim_b}; }}
        QPushButton[primary="true"]:hover {{ background: {prim_h}; }}
        QPushButton[primary="true"][navFocus="true"] {{ background: {prim_h}; border: 2px solid {acc}; }}
        QMessageBox QPushButton, QDialog QPushButton {{ min-width: 80px; }}
        QLineEdit, QSpinBox, QComboBox {{ min-height: 36px; padding: 4px 8px; border-width: 2px; border-radius: 4px; }}
        QDialog QLineEdit {{ min-width: 260px; }}
        QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border: 2px solid {acc}; }}
        QCheckBox {{ spacing: 12px; min-height: 34px; padding: 2px 6px; border: 2px solid transparent; border-radius: 6px; }}
        QCheckBox[navFocus="true"] {{ border: 2px solid {acc}; background: {focus_bg}; }}
        QCheckBox::indicator {{ width: 26px; height: 26px; }}
        QLineEdit[editMode="true"], QSpinBox[editMode="true"], QComboBox[editMode="true"] {{ border: 2px solid {edit}; background: {edit_bg}; }}
        QPushButton[danger="true"] {{ background: {danger}; color: #ffffff; border: 2px solid {danger_b}; }}
        QPushButton[danger="true"]:hover {{ background: {danger_h}; }}
        QPushButton[danger="true"][navFocus="true"], QPushButton[danger="true"]:focus {{ border: 2px solid {acc}; }}
        QPushButton:disabled, QPushButton[primary="true"]:disabled {{ background: {dis_bg}; color: {dis_fg}; border: 2px solid {dis_b}; }}
        QComboBox {{ combobox-popup: 0; }}
        QComboBox QAbstractItemView {{ background: {pop_bg}; color: {pop_fg}; border: 1px solid {pop_b};
            selection-background-color: {sel_bg}; selection-color: {sel_fg}; outline: 0; padding: 2px; }}
        QComboBox QAbstractItemView::item {{ min-height: 36px; padding: 2px 8px; color: {pop_fg}; background: {pop_bg}; }}
        QComboBox QAbstractItemView::item:hover, QComboBox QAbstractItemView::item:selected {{ background: {sel_bg}; color: {sel_fg}; }}
        QComboBox QAbstractItemView::item:disabled {{ color: {dis_fg}; }}
        QMenu {{ background: {pop_bg}; color: {pop_fg}; border: 1px solid {pop_b}; padding: 4px; }}
        QMenu::item {{ min-height: 32px; padding: 6px 28px 6px 14px; color: {pop_fg}; background: transparent; border-radius: 4px; }}
        QMenu::item:selected {{ background: {sel_bg}; color: {sel_fg}; }}
        QMenu::item:disabled {{ color: {dis_fg}; background: transparent; }}
        QMenu::separator {{ height: 1px; background: {pop_b}; margin: 4px 8px; }}
        QToolTip {{ background: {tip_bg}; color: {tip_fg}; border: 1px solid {pop_b}; padding: 4px 6px; }}
    """


APP_CSS_LIGHT = """
            QDialog, QMessageBox { background: #f5f5f5; color: #222; }
            QLabel { color: #222; }
            QPushButton { background: #e0e0e0; color: #222; border: 1px solid #ccc; padding: 4px 8px; border-radius: 3px; }
            QPushButton:hover { background: #d0d0d0; }
            QLineEdit, QSpinBox, QComboBox { background: #ffffff; color: #222; border: 1px solid #ccc; padding: 3px; }
            QCheckBox { color: #222; }
            QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #888; border-radius: 3px; background: #fff; }
            QCheckBox::indicator:checked { background: #4caf50; border-color: #388e3c; }
            QCheckBox::indicator:checked:hover { background: #66bb6a; }
        """

APP_CSS_DARK = """
            QDialog, QMessageBox { background: #1e1e1e; color: #e0e0e0; }
            QLabel { color: #e0e0e0; }
            QPushButton { background: #2d2d2d; color: #e0e0e0; border: 1px solid #444; padding: 4px 8px; border-radius: 3px; }
            QPushButton:hover { background: #3d3d3d; }
            QLineEdit, QSpinBox, QComboBox { background: #2a2a2a; color: #e0e0e0; border: 1px solid #444; padding: 3px; }
            QCheckBox { color: #e0e0e0; }
            QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #666; border-radius: 3px; background: #2a2a2a; }
            QCheckBox::indicator:checked { background: #4caf50; border-color: #388e3c; }
            QCheckBox::indicator:checked:hover { background: #66bb6a; }
        """

# Every color role the app relies on, for all color groups. Without this, popups,
# menus and tooltips (own top-level windows) used the desktop palette: with a dark
# Plasma color scheme + the light app theme, combo box entries were dark-on-dark.
_PALETTES = {
    True: {"Window": "#f5f5f5", "WindowText": "#222222", "Base": "#ffffff", "AlternateBase": "#f0f0f0",
           "Text": "#222222", "Button": "#e0e0e0", "ButtonText": "#222222", "BrightText": "#ffffff",
           "Highlight": "#1565c0", "HighlightedText": "#ffffff", "ToolTipBase": "#ffffe8",
           "ToolTipText": "#222222", "PlaceholderText": "#7a7a7a", "Link": "#1565c0",
           "Light": "#ffffff", "Midlight": "#ececec", "Mid": "#b8b8b8", "Dark": "#9a9a9a", "Shadow": "#555555"},
    False: {"Window": "#1e1e1e", "WindowText": "#e0e0e0", "Base": "#2a2a2a", "AlternateBase": "#262626",
            "Text": "#e0e0e0", "Button": "#2d2d2d", "ButtonText": "#e0e0e0", "BrightText": "#ffffff",
            "Highlight": "#1f5f8b", "HighlightedText": "#ffffff", "ToolTipBase": "#333333",
            "ToolTipText": "#f0f0f0", "PlaceholderText": "#8a8a8a", "Link": "#4fc3f7",
            "Light": "#4a4a4a", "Midlight": "#3a3a3a", "Mid": "#2f2f2f", "Dark": "#151515", "Shadow": "#000000"},
}
_DISABLED = {True: {"WindowText": "#a6a6a6", "Text": "#a6a6a6", "ButtonText": "#a6a6a6",
                    "Base": "#f3f3f3", "Button": "#ececec", "Highlight": "#c8c8c8", "HighlightedText": "#7a7a7a"},
             False: {"WindowText": "#6a6a6a", "Text": "#6a6a6a", "ButtonText": "#6a6a6a",
                     "Base": "#242424", "Button": "#242424", "Highlight": "#3a3a3a", "HighlightedText": "#8a8a8a"}}


def theme_palette(light: bool) -> QPalette:
    pal = QPalette()
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive, QPalette.ColorGroup.Disabled):
        for role, col in _PALETTES[light].items():
            pal.setColor(group, getattr(QPalette.ColorRole, role), QColor(col))
    for role, col in _DISABLED[light].items():
        pal.setColor(QPalette.ColorGroup.Disabled, getattr(QPalette.ColorRole, role), QColor(col))
    return pal


def apply_app_theme(qapp, light: bool):
    """Application-wide theme: full palette (also reaches popups, menus, tooltips) and
    the stylesheet incl. touch sizes. The theme switch needs a restart (theme_restart)."""
    qapp.setPalette(theme_palette(light))
    qapp.setStyleSheet((APP_CSS_LIGHT if light else APP_CSS_DARK) + touch_css(light))


def dialog_stylesheet(parent=None) -> str:
    """Return a stylesheet for dialogs based on the current theme."""
    light = False
    if parent and hasattr(parent, "cfg"):
        light = parent.cfg.get("settings", {}).get("theme", "Dark") == "Light"
    if light:
        return """
            QDialog, QMessageBox { background: #f5f5f5; color: #222; }
            QLabel { color: #222; }
            QPushButton { background: #e0e0e0; color: #222; border: 1px solid #ccc; padding: 4px 8px; border-radius: 3px; }
            QPushButton:hover { background: #d0d0d0; }
            QLineEdit, QSpinBox, QComboBox { background: #ffffff; color: #222; border: 1px solid #ccc; padding: 3px; }
            QCheckBox { color: #222; }
            QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #888; border-radius: 3px; background: #fff; }
            QCheckBox::indicator:checked { background: #4caf50; border-color: #388e3c; }
            QCheckBox::indicator:checked:hover { background: #66bb6a; }
        """ + touch_css(True)
    else:
        return """
            QDialog, QMessageBox { background: #1e1e1e; color: #e0e0e0; }
            QLabel { color: #e0e0e0; }
            QPushButton { background: #2d2d2d; color: #e0e0e0; border: 1px solid #444; padding: 4px 8px; border-radius: 3px; }
            QPushButton:hover { background: #3d3d3d; }
            QLineEdit, QSpinBox, QComboBox { background: #2a2a2a; color: #e0e0e0; border: 1px solid #444; padding: 3px; }
            QCheckBox { color: #e0e0e0; }
            QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #666; border-radius: 3px; background: #2a2a2a; }
            QCheckBox::indicator:checked { background: #4caf50; border-color: #388e3c; }
            QCheckBox::indicator:checked:hover { background: #66bb6a; }
        """ + touch_css(False)


# UI only: colours for the main window (cards, status dots, toasts, status bar)
def ui_colors(light: bool) -> dict:
    if light:
        return dict(card="#ffffff", card_b="#dcdcdc", cur="#eaf2fc", cur_b="#1565c0", name="#222222",
                    pill="#e8e8e8", pill_t="#555555", sub="#666666", err="#c62828",
                    online="#43a047", offline="#9e9e9e", busy="#ffb300", error="#e53935", unknown="#c8c8c8",
                    bar="#ececec", bar_b="#d0d0d0", bar_t="#555555", tb_b="#d8d8d8",
                    ok_bg="#e8f5e9", ok_b="#43a047", ok_t="#1b5e20",
                    er_bg="#ffebee", er_b="#e53935", er_t="#b71c1c",
                    in_bg="#fff8e1", in_b="#ffb300", in_t="#5d4037", dim="#666666",
                    warn="#f57c00", warn_t="#c43e00", steam_t="#2e7d32", link="#1565c0", edit="#e65100",
                    edit_bg="#fff3e0")
    return dict(card="#262626", card_b="#303030", cur="#24313a", cur_b="#4fc3f7", name="#ffffff",
                pill="#333333", pill_t="#bbbbbb", sub="#9a9a9a", err="#ef9a9a",
                online="#43a047", offline="#757575", busy="#ffb300", error="#e53935", unknown="#4a4a4a",
                bar="#252525", bar_b="#333333", bar_t="#aaaaaa", tb_b="#2e2e2e",
                ok_bg="#2e3b2f", ok_b="#43a047", ok_t="#e6e6e6",
                er_bg="#3b2a2a", er_b="#e53935", er_t="#e6e6e6",
                in_bg="#3a3424", in_b="#ffb300", in_t="#e6e6e6", dim="#a8a8a8",
                warn="#fb8c00", warn_t="#ffb74d", steam_t="#81c784", link="#4fc3f7", edit="#ffb74d",
                edit_bg="#2b2620")


def accent_color(light: bool) -> QColor:
    """Accent of the edit mode (selection, valid drop zones, insertion marks)."""
    return QColor("#1565c0" if light else "#4fc3f7")
