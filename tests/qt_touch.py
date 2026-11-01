"""Test helper (Linux only). Real Qt touch injection for PyQt6 (which lacks QTest::touchEvent/createTouchDevice).
Calls the exported Qt C++ entry points QTest::createTouchDevice and qt_handleTouchEventv2
(the same functions C++ QTest::touchEvent uses) via ctypes, so events travel
QWindowSystemInterface -> QGuiApplication (point grabs, mouse synthesis) -> QWidgetWindow."""
import ctypes
import glob
import os

import PyQt6
from PyQt6 import sip
from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QEventPoint, QPointingDevice

_lib = ctypes.CDLL(glob.glob(os.path.join(os.path.dirname(PyQt6.__file__), "Qt6/lib/libQt6Gui.so.6"))[0])
# (raises on other platforms / Qt builds: the importing test then skips)
_create = _lib._ZN5QTest17createTouchDeviceEN12QInputDevice10DeviceTypeE6QFlagsINS0_10CapabilityEE
_create.restype = ctypes.c_void_p; _create.argtypes = [ctypes.c_int, ctypes.c_int]
_touch = _lib._Z21qt_handleTouchEventv2P7QWindowPK15QPointingDeviceRK5QListI11QEventPointE6QFlagsIN2Qt16KeyboardModifierEE
_touch.restype = ctypes.c_bool; _touch.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]

class _QList(ctypes.Structure):          # Qt6 QList<T>: {QArrayData *d; T *ptr; qsizetype size}
    _fields_ = [("d", ctypes.c_void_p), ("ptr", ctypes.c_void_p), ("size", ctypes.c_ssize_t)]

_DEV = None
def touch_device():
    global _DEV
    if _DEV is None:
        ptr = _create(2, 1 | 2)          # DeviceType::TouchScreen, Capability::Position|Area
        _DEV = (ptr, sip.wrapinstance(ptr, QPointingDevice))
    return _DEV

STATE = {"press": QEventPoint.State.Pressed, "move": QEventPoint.State.Updated,
         "stationary": QEventPoint.State.Stationary, "release": QEventPoint.State.Released}

class RealToucher:
    def __init__(self, widget, tid=0):
        self.w, self.tid = widget, tid
        self.dev_ptr, self.dev = touch_device()
    def send(self, kind, pt):
        win = self.w.window()
        scene = QPointF(self.w.mapTo(win, pt)); glob_ = QPointF(self.w.mapToGlobal(pt))
        ep = QEventPoint(self.tid, STATE[kind], scene, glob_)
        dptr = ctypes.c_void_p.from_address(sip.unwrapinstance(ep)).value   # QEventPoint = 1 d-pointer
        arr = (ctypes.c_void_p * 1)(dptr)
        lst = _QList(None, ctypes.cast(arr, ctypes.c_void_p).value, 1)
        wh = win.windowHandle()
        return _touch(sip.unwrapinstance(wh), self.dev_ptr, ctypes.addressof(lst), 0)


_mouse = _lib._Z19qt_handleMouseEventP7QWindowRK7QPointFS3_6QFlagsIN2Qt11MouseButtonEES6_N6QEvent4TypeES4_INS5_16KeyboardModifierEEi
_mouse.restype = None
_mouse.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                   ctypes.c_int, ctypes.c_int]

class RealMouse:
    """Platform-level mouse (what gamescope's touch->mouse emulation in Steam Deck Game Mode
    produces): QWindowSystemInterface -> QGuiApplication -> QWidgetWindow (implicit grab)."""
    T = {"press": 2, "release": 3, "move": 5}      # QEvent::MouseButtonPress/Release/Move
    def __init__(self, widget):
        self.w = widget; self.down = False; self.ts = 1000
    def send(self, kind, pt):
        win = self.w.window()
        local = QPointF(self.w.mapTo(win, pt)); glob_ = QPointF(self.w.mapToGlobal(pt))
        if kind == "press": self.down = True
        if kind == "release": self.down = False
        state = 1 if self.down else 0
        button = 1 if kind in ("press", "release") else 0
        self.ts += 16
        _mouse(sip.unwrapinstance(win.windowHandle()), sip.unwrapinstance(local), sip.unwrapinstance(glob_),
               state, button, self.T[kind], 0, self.ts)
