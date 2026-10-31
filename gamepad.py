"""BuddyRemote – input modes (focus ring for keyboard/controller vs. mouse) and native
gamepad input via SDL2, translated into the app's normal key events."""

import ctypes
import logging
import os
import time

from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QLineEdit, QAbstractSpinBox,
                             QMessageBox, QPushButton)
from PyQt6.QtCore import Qt, QTimer, QObject, QEvent
from PyQt6.QtGui import QCursor, QKeyEvent

from paths import RES_DIR


# UI only: input modes and native gamepad input.
# Nothing here calls app logic directly: the gamepad is translated into the same
# arrow/Enter/Escape key events that keyboard users already send, so the existing
# navigation, edit mode, dialogs and confirmations handle it unchanged.
_FIELD_TYPES = (QLineEdit, QAbstractSpinBox, QComboBox)
_PAD_KEYS = (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Right,
             Qt.Key.Key_Return, Qt.Key.Key_Escape)
_REVEAL_KEYS = _PAD_KEYS + (Qt.Key.Key_Enter, Qt.Key.Key_Tab, Qt.Key.Key_Backtab, Qt.Key.Key_Space)
_MOUSE_MOVE_PX = 4


class InputModeController(QObject):
    """UI only: shows the focus ring in keyboard/controller mode, hides it in mouse mode.

    - Mouse click / wheel / movement hides the ring (focus itself is kept).
    - Keyboard arrows, Tab, Enter, Space or any gamepad input show it again. If the ring was
      hidden (or nothing navigable has focus), that first press only reveals the ring and is
      swallowed, so it never moves or activates anything by surprise. Escape always passes.
    - Text fields (line edits, spin boxes, combos) keep their normal always-visible focus.
    """

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.nav_visible = True
        self.pad = None                # GamepadBridge, set by the bridge
        self._last_main = None         # logical last focus in the main window (rows get rebuilt)
        self._last_real = {}           # key -> time a real key press passed through (dedup)
        self._last_pos = QCursor.pos()
        app = QApplication.instance()
        app.installEventFilter(self)
        app.focusChanged.connect(self._focus_changed)

    # --- focus ring ------------------------------------------------------
    @staticmethod
    def _set_ring(w, on: bool):
        if not isinstance(w, (QPushButton, QCheckBox)):
            return
        try:
            if bool(w.property("navFocus")) == on:
                return
            w.setProperty("navFocus", on)
            w.style().unpolish(w)
            w.style().polish(w)
            w.update()
        except RuntimeError:
            pass

    def _focus_changed(self, old, new):
        self._set_ring(old, False)
        self._set_ring(new, self.nav_visible)
        self._remember(new)

    def set_nav_visible(self, on: bool):
        if self.nav_visible == on:
            return
        self.nav_visible = on
        if on:
            self._last_pos = QCursor.pos()
        fw = QApplication.focusWidget()
        self._set_ring(fw, on)
        self.win._on_focus_changed(None, fw)

    # --- where the ring comes back --------------------------------------
    def _remember(self, w):
        if w is None:
            return
        try:
            win = self.win
            if w in win.toolbar_buttons:
                self._last_main = ("toolbar", None, win.toolbar_buttons.index(w))
            elif w is win.log_btn:
                self._last_main = ("log", None, 0)
            else:
                for hid, row in win.host_rows.items():
                    if w in row.nav_buttons:
                        self._last_main = ("host", hid, row.nav_buttons.index(w))
                        break
        except (RuntimeError, AttributeError):
            pass

    def _main_target(self):
        win = self.win
        kind, hid, idx = self._last_main or (None, None, 0)
        try:
            if kind == "toolbar":
                return win.toolbar_buttons[idx]
            if kind == "log":
                return win.log_btn
            if kind == "host" and hid in win.host_rows:
                btns = win.host_rows[hid].nav_buttons
                usable = [b for b in btns if win._navigable(b)]
                if btns[idx] in usable:
                    return btns[idx]
                if usable:   # remembered button got disabled: nearest usable one
                    return min(usable, key=lambda b: abs(btns.index(b) - idx))
        except (IndexError, RuntimeError):
            pass
        for r in win.host_rows.values():
            for b in r.nav_buttons:
                if win._navigable(b):
                    return b
        return win.toolbar_buttons[0]

    @staticmethod
    def _focusable(w, win):
        try:
            return (w is not None and w.window() is win and w.isVisible() and w.isEnabled()
                    and bool(w.focusPolicy() & Qt.FocusPolicy.TabFocus))
        except RuntimeError:
            return False

    def _valid(self, fw, aw) -> bool:
        if fw is None or aw is None:
            return False
        try:
            if fw.window() is not aw or not fw.isVisible() or not fw.isEnabled():
                return False
            if aw is self.win:
                return any(fw in row for row in self.win._nav_grid())
            return self._focusable(fw, aw) or isinstance(fw.parentWidget(), _FIELD_TYPES)
        except RuntimeError:
            return False

    def _dialog_target(self, aw):
        if isinstance(aw, QMessageBox) and aw.defaultButton() is not None:
            return aw.defaultButton()      # confirmations: the safe default ("No")
        if self._valid(aw.focusWidget(), aw):
            return aw.focusWidget()
        w = aw.nextInFocusChain()
        for _ in range(500):
            if w is None or w is aw:
                break
            if self._focusable(w, aw):
                return w
            w = w.nextInFocusChain()
        return None

    def _ensure_focus(self, aw):
        target = self._main_target() if aw is self.win else self._dialog_target(aw)
        if target is not None:
            target.setFocus(Qt.FocusReason.TabFocusReason)
            if aw is self.win:
                self.win.scroll.ensureWidgetVisible(target)

    # --- shared by keyboard and gamepad ---------------------------------
    def handle_input(self, key) -> bool:
        """Switch to keyboard/controller mode. Returns True if the press only revealed the
        ring and must not be processed further."""
        aw = QApplication.activeWindow()
        if aw is None or QApplication.activePopupWidget() is not None:
            return False
        fw = QApplication.focusWidget()
        valid = self._valid(fw, aw)
        was_hidden = not self.nav_visible
        self.set_nav_visible(True)
        if key == Qt.Key.Key_Escape:
            if not valid:
                self._ensure_focus(aw)
            return False
        if valid and (not was_hidden or isinstance(fw, _FIELD_TYPES)
                      or isinstance(fw.parentWidget(), _FIELD_TYPES)):
            return False
        self._ensure_focus(aw)
        return True

    def last_real_key(self, key) -> float:
        return self._last_real.get(key, -1e9)

    def eventFilter(self, obj, ev):
        et = ev.type()
        if et == QEvent.Type.KeyPress:
            # only real (spontaneous) presses, once, at their first receiver
            if not ev.spontaneous() or obj is not (QApplication.focusWidget() or QApplication.activeWindow()):
                return False
            key = ev.key()
            if key == Qt.Key.Key_Enter:
                key = Qt.Key.Key_Return
            mods = ev.modifiers() & ~(Qt.KeyboardModifier.KeypadModifier | Qt.KeyboardModifier.ShiftModifier)
            if key not in _REVEAL_KEYS or mods != Qt.KeyboardModifier.NoModifier:
                return False
            if key in _PAD_KEYS and self.pad is not None and self.pad.is_duplicate(key):
                return True            # same press already arrived natively from the gamepad
            if key in _PAD_KEYS:
                self._last_real[key] = time.monotonic()
            return self.handle_input(key)
        if et in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick, QEvent.Type.Wheel):
            if ev.spontaneous() and self.nav_visible:
                self.set_nav_visible(False)
        elif et in (QEvent.Type.MouseMove, QEvent.Type.HoverMove) and self.nav_visible:
            pos = QCursor.pos()
            if (pos - self._last_pos).manhattanLength() >= _MOUSE_MOVE_PX:
                self.set_nav_visible(False)
        return False


class GamepadSource:
    """Abstract gamepad event source. poll() returns a list of normalized events:
    ("added", dev, name) / ("removed", dev) / ("button", dev, name, down) / ("axis", dev, name, value)
    with button names a, b, up, down, left, right and axis names lx, ly (value -1.0 .. 1.0)."""

    def open(self) -> str:
        """Returns "" on success or a reason why gamepads are unavailable."""
        return ""

    def poll(self) -> list:
        return []

    def close(self):
        pass


class SDLGamepadSource(GamepadSource):
    """Reads controllers with SDL2's GameController API (Xbox-style layout for Xbox,
    PlayStation, Switch Pro, 8BitDo, Steam Deck, ...). Works with or without Steam."""

    def __init__(self):
        self.sdl = None
        self.pads = {}

    def open(self) -> str:
        bundled = RES_DIR / "libsdl2"  # packaging: libSDL2 shipped inside the bundle
        if bundled.is_dir() and not os.environ.get("PYSDL2_DLL_PATH"):
            os.environ["PYSDL2_DLL_PATH"] = str(bundled)
        try:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                import sdl2
        except Exception as e:
            return f"SDL2 not available ({e.__class__.__name__}: {e})"
        h = sdl2.SDL_SetHint
        h(sdl2.SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, b"1")  # we check the active window ourselves
        h(sdl2.SDL_HINT_NO_SIGNAL_HANDLERS, b"1")                # leave Ctrl+C / SIGTERM to Python/Qt
        h(sdl2.SDL_HINT_JOYSTICK_HIDAPI, b"0")                   # read-only: never reconfigure devices
        if sdl2.SDL_Init(sdl2.SDL_INIT_GAMECONTROLLER) != 0:
            return "SDL_Init failed: " + (sdl2.SDL_GetError() or b"").decode(errors="replace")
        self.sdl = sdl2
        B = sdl2
        self._buttons = {B.SDL_CONTROLLER_BUTTON_A: "a", B.SDL_CONTROLLER_BUTTON_B: "b",
                         B.SDL_CONTROLLER_BUTTON_DPAD_UP: "up", B.SDL_CONTROLLER_BUTTON_DPAD_DOWN: "down",
                         B.SDL_CONTROLLER_BUTTON_DPAD_LEFT: "left", B.SDL_CONTROLLER_BUTTON_DPAD_RIGHT: "right"}
        self._axes = {B.SDL_CONTROLLER_AXIS_LEFTX: "lx", B.SDL_CONTROLLER_AXIS_LEFTY: "ly"}
        return ""

    def poll(self) -> list:
        sdl2 = self.sdl
        if sdl2 is None:
            return []
        out = []
        ev = sdl2.SDL_Event()
        while sdl2.SDL_PollEvent(ctypes.byref(ev)):
            t = ev.type
            if t == sdl2.SDL_CONTROLLERDEVICEADDED:
                c = sdl2.SDL_GameControllerOpen(ev.cdevice.which)
                if c:
                    iid = sdl2.SDL_JoystickInstanceID(sdl2.SDL_GameControllerGetJoystick(c))
                    if iid in self.pads:
                        sdl2.SDL_GameControllerClose(c)
                    else:
                        self.pads[iid] = c
                        name = (sdl2.SDL_GameControllerName(c) or b"?").decode(errors="replace")
                        out.append(("added", iid, name))
            elif t == sdl2.SDL_CONTROLLERDEVICEREMOVED:
                c = self.pads.pop(ev.cdevice.which, None)
                if c:
                    sdl2.SDL_GameControllerClose(c)
                    out.append(("removed", ev.cdevice.which))
            elif t in (sdl2.SDL_CONTROLLERBUTTONDOWN, sdl2.SDL_CONTROLLERBUTTONUP):
                name = self._buttons.get(ev.cbutton.button)
                if name:
                    out.append(("button", ev.cbutton.which, name, t == sdl2.SDL_CONTROLLERBUTTONDOWN))
            elif t == sdl2.SDL_CONTROLLERAXISMOTION:
                name = self._axes.get(ev.caxis.axis)
                if name:
                    out.append(("axis", ev.caxis.which, name, max(-1.0, ev.caxis.value / 32767.0)))
        return out

    def close(self):
        if self.sdl is not None:
            for c in self.pads.values():
                self.sdl.SDL_GameControllerClose(c)
            self.pads.clear()
            self.sdl.SDL_Quit()
            self.sdl = None


class GamepadBridge(QObject):
    """UI only: turns gamepad input into the key events the app already understands.
    D-pad / left stick -> arrow keys (with repeat), A -> Enter, B -> Escape.
    Only acts while one of our windows is the active window."""
    TICK_MS, IDLE_MS = 16, 200
    PRESS, RELEASE = 0.5, 0.35          # stick deadzone with hysteresis
    DELAY, REPEAT = 0.35, 0.12          # auto-repeat for held directions
    DEDUPE = 0.08                       # Steam Input double-input window (seconds)
    KEYS = {"up": Qt.Key.Key_Up, "down": Qt.Key.Key_Down, "left": Qt.Key.Key_Left,
            "right": Qt.Key.Key_Right, "a": Qt.Key.Key_Return, "b": Qt.Key.Key_Escape}
    REPEATING = ("up", "down", "left", "right")

    def __init__(self, controller, source=None, clock=time.monotonic):
        super().__init__(controller)
        self.ctl = controller
        controller.pad = self
        self.src = source
        self.clock = clock
        self.devices = {}
        self.pressed = {}               # (dev, button) -> bool
        self.sticks = {}                # dev -> {"lx": v, "ly": v, "dir": name|None}
        self.held = {}                  # name -> {"next": t, "repeat": bool, "native": bool}
        self.last_sent = {}             # key -> time we injected it
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)

    def start(self) -> bool:
        if self.src is None:
            self.src = SDLGamepadSource()
        try:
            err = self.src.open()
        except Exception as e:
            err = f"{e.__class__.__name__}: {e}"
        if err:
            logging.info("Gamepad support disabled: %s", err)
            self.src = None
            return False
        self.timer.start(self.IDLE_MS)
        QApplication.instance().aboutToQuit.connect(self.stop)
        return True

    def stop(self):
        self.timer.stop()
        if self.src is not None:
            self.src.close()
            self.src = None

    # Steam Input dedup: a real key press equal to a gamepad press we just injected
    def is_duplicate(self, key) -> bool:
        if not self.devices:
            return False
        for name, h in self.held.items():
            if self.KEYS[name] == key and h["native"]:
                return True
        return self.clock() - self.last_sent.get(key, -1e9) < self.DEDUPE

    def _stick_dir(self, st):
        x, y, cur = st.get("lx", 0.0), st.get("ly", 0.0), st.get("dir")
        comp = {"left": -x, "right": x, "up": -y, "down": y}
        if cur is not None and comp[cur] >= self.RELEASE:
            return cur
        best = max(comp, key=comp.get)
        return best if comp[best] >= self.PRESS else None

    def _active_names(self):
        names = {n for (dev, n), down in self.pressed.items() if down}
        for st in self.sticks.values():
            if st.get("dir"):
                names.add(st["dir"])
        return names

    def tick(self):
        if self.src is None:
            return
        try:
            events = self.src.poll()
        except Exception:
            logging.exception("gamepad poll failed; gamepad disabled")
            self.stop()
            return
        for e in events:
            kind, dev = e[0], e[1]
            if kind == "added":
                self.devices[dev] = e[2]
                logging.info("Gamepad connected: %s", e[2])
            elif kind == "removed":
                self.devices.pop(dev, None)
                self.sticks.pop(dev, None)
                for k in [k for k in self.pressed if k[0] == dev]:
                    del self.pressed[k]
                logging.info("Gamepad disconnected")
            elif kind == "button":
                self.pressed[(dev, e[2])] = e[3]
                if e[3]:
                    self._edge(e[2])    # every physical press counts, even if already held elsewhere
            elif kind == "axis":
                st = self.sticks.setdefault(dev, {})
                st[e[2]] = e[3]
                st["dir"] = self._stick_dir(st)
        now = self.clock()
        active = self._active_names()
        for name in list(self.held):
            if name not in active:
                del self.held[name]
        for name in active:
            if name not in self.held:
                self._edge(name)
            h = self.held.get(name)
            if h and h["repeat"] and now >= h["next"]:
                h["next"] = now + self.REPEAT
                if self._inject(name) != "sent":
                    h["repeat"] = False
        want = self.TICK_MS if (self.devices and QApplication.activeWindow() is not None) else self.IDLE_MS
        if self.timer.interval() != want:
            self.timer.setInterval(want)

    def _edge(self, name):
        if name in self.held and name in self.REPEATING:
            return
        res = self._inject(name)
        self.held[name] = {"next": self.clock() + self.DELAY,
                           "repeat": res == "sent" and name in self.REPEATING,
                           "native": res in ("sent", "reveal")}

    def _inject(self, name) -> str:
        """Returns "inactive", "shadow" (Steam already sent it as a key), "reveal" or "sent"."""
        if QApplication.activeWindow() is None:
            return "inactive"
        key = self.KEYS[name]
        now = self.clock()
        if now - self.ctl.last_real_key(key) < self.DEDUPE:
            return "shadow"
        self.last_sent[key] = now
        if self.ctl.handle_input(key):
            return "reveal"
        target = QApplication.activePopupWidget() or QApplication.focusWidget() or QApplication.activeWindow()
        QApplication.postEvent(target, QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))
        QApplication.postEvent(target, QKeyEvent(QEvent.Type.KeyRelease, key, Qt.KeyboardModifier.NoModifier))
        return "sent"
