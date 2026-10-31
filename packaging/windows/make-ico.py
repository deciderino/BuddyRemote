"""Build packaging/windows/buddyremote.ico (PNG-compressed entries 16..256 px) from
packaging/linux/buddyremote.png. Needs PyQt6 (any OS):  python packaging/windows/make-ico.py"""
import struct
import sys
from pathlib import Path

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PyQt6.QtGui import QGuiApplication, QImage

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "packaging" / "linux" / "buddyremote.png"
DST = ROOT / "packaging" / "windows" / "buddyremote.ico"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)

app = QGuiApplication(sys.argv[:1] + ["-platform", "offscreen"])
img = QImage(str(SRC)).convertToFormat(QImage.Format.Format_ARGB32)
if img.isNull():
    sys.exit(f"cannot read {SRC}")
blobs = []
for s in SIZES:
    scaled = img.scaled(s, s, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    scaled.save(buf, "PNG")
    buf.close()
    blobs.append((s, bytes(ba)))
out = struct.pack("<HHH", 0, 1, len(blobs))
offset = 6 + 16 * len(blobs)
for s, data in blobs:
    out += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), offset)
    offset += len(data)
out += b"".join(d for _, d in blobs)
DST.write_bytes(out)
print(DST, len(out), "bytes")
