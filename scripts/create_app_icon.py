"""Draw the project's original shield/sword emblem; no models, stock artwork or extra packages."""

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main():
    from PySide6.QtCore import QBuffer, QIODevice, QPointF, Qt
    from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPen

    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    root = Path(__file__).resolve().parents[1] / "src/rpg_vkr/ui/assets"
    images = []
    for size in (16, 32, 48, 64, 128, 256):
        image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        p = QPainter(image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(size / 256, size / 256)
        shield = QPainterPath(QPointF(28, 32))
        shield.lineTo(128, 12)
        shield.lineTo(228, 32)
        shield.lineTo(216, 157)
        shield.cubicTo(203, 204, 151, 231, 128, 244)
        shield.cubicTo(105, 231, 53, 204, 40, 157)
        shield.closeSubpath()
        p.setPen(QPen(QColor("#d4af60"), 9))
        p.setBrush(QColor("#142a34"))
        p.drawPath(shield)
        blade = QPainterPath(QPointF(128, 43))
        for point in ((143, 70), (136, 152), (120, 152), (113, 70)):
            blade.lineTo(*point)
        blade.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#e4edf0"))
        p.drawPath(blade)
        p.setBrush(QColor("#d4af60"))
        p.drawRoundedRect(90, 150, 76, 12, 5, 5)
        p.drawRoundedRect(121, 160, 14, 39, 4, 4)
        p.drawEllipse(QPointF(128, 207), 12, 12)
        p.setBrush(QColor("#71c6c8"))
        for x in (70, 186):
            star = QPainterPath(QPointF(x, 72))
            for point in ((x + 6, 84), (x, 96), (x - 6, 84)):
                star.lineTo(*point)
            star.closeSubpath()
            p.drawPath(star)
        p.end()
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        images.append((size, bytes(buffer.data())))
        if size == 256:
            image.save(str(root / "DND-NCFU.png"))
    offset = 6 + 16 * len(images)
    entries = []
    for size, data in images:
        entries.append(
            struct.pack(
                "<BBBBHHII",
                size if size < 256 else 0,
                size if size < 256 else 0,
                0,
                0,
                1,
                32,
                len(data),
                offset,
            )
        )
        offset += len(data)
    (root / "DND-NCFU.ico").write_bytes(
        struct.pack("<HHH", 0, 1, len(images))
        + b"".join(entries)
        + b"".join(data for _, data in images)
    )
    return 0 if app else 1


if __name__ == "__main__":
    raise SystemExit(main())
