"""Original tiny painted category icons; no icon packs or font dependencies."""

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF


def category_icon(category):
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#243944"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(2, 2, 60, 60, 12, 12)
    painter.setPen(QPen(QColor("#d7b37a"), 3))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if category == "people":
        painter.drawEllipse(24, 13, 16, 18)
        painter.drawArc(16, 31, 32, 30, 0, 180 * 16)
    elif category == "items":
        painter.drawLine(18, 46, 44, 18)
        painter.drawLine(22, 31, 35, 44)
        painter.drawPolygon(QPolygonF([QPointF(44, 18), QPointF(44, 27), QPointF(35, 18)]))
    elif category == "places":
        painter.drawRect(18, 24, 28, 26)
        for x in (18, 30, 42):
            painter.drawRect(x, 16, 5, 8)
        painter.drawLine(30, 38, 30, 50)
    elif category == "factions":
        painter.drawLine(20, 14, 20, 50)
        painter.drawPolygon(QPolygonF([QPointF(20, 15), QPointF(48, 19), QPointF(20, 33)]))
    elif category == "creatures":
        for x, y in ((19, 23), (31, 16), (43, 23)):
            painter.drawEllipse(x - 3, y, 6, 9)
        painter.drawEllipse(23, 34, 20, 14)
    else:
        painter.drawRect(18, 15, 29, 36)
        for y in (25, 33, 41):
            painter.drawLine(24, y, 41, y)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)
