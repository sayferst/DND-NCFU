"""Lightweight shared fantasy design tokens; no game state or remote assets."""

from string import Template

from PySide6.QtGui import QColor, QFont, QPalette

DARK = {
    "bg": "#101b24",
    "panel": "#182832",
    "field": "#10212a",
    "text": "#e6dfcf",
    "muted": "#a9b7bb",
    "border": "#3d5056",
    "gold": "#d8b578",
    "hover": "#30464c",
}
LIGHT = {
    "bg": "#ede7da",
    "panel": "#f7f2e7",
    "field": "#fffaf0",
    "text": "#252c2e",
    "muted": "#566366",
    "border": "#b7ab94",
    "gold": "#795b2b",
    "hover": "#e2d5ba",
}


def apply_theme(widget, theme="Системная"):
    colors = LIGHT if theme == "Светлая" else DARK
    palette = QPalette(widget.palette())
    for role, token in (
        (QPalette.ColorRole.Window, "bg"),
        (QPalette.ColorRole.Base, "field"),
        (QPalette.ColorRole.Button, "panel"),
        (QPalette.ColorRole.WindowText, "text"),
        (QPalette.ColorRole.Text, "text"),
        (QPalette.ColorRole.ButtonText, "text"),
        (QPalette.ColorRole.AlternateBase, "panel"),
        (QPalette.ColorRole.ToolTipBase, "panel"),
        (QPalette.ColorRole.ToolTipText, "text"),
        (QPalette.ColorRole.PlaceholderText, "muted"),
    ):
        palette.setColor(role, QColor(colors[token]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(colors["hover"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(colors["text"]))
    palette.setColor(QPalette.ColorRole.Link, QColor(colors["gold"]))
    palette.setColor(QPalette.ColorRole.LinkVisited, QColor(colors["muted"]))
    widget.setPalette(palette)
    widget.setFont(QFont("Segoe UI", 11))
    widget.setStyleSheet(
        Template("""
        QWidget { color: $text; background-color: $bg; }
        QMainWindow, QDialog, QScrollArea, QTabWidget::pane { background: $bg; }
        QLabel { background: transparent; }
        QTabWidget::pane { border: none; }
        QGroupBox, QFrame[card="true"] { background: $panel; border: 1px solid $border;
            border-radius: 10px; padding: 14px; margin-top: 10px; }
        QGroupBox::title { color: $gold; subcontrol-origin: margin; left: 16px; padding: 0 6px; }
        QPushButton { background: $panel; border: 1px solid $border; border-radius: 6px;
            padding: 8px 14px; color: $text; }
        QPushButton:hover { background: $hover; border-color: $gold; }
        QPushButton:pressed { background: $field; }
        QPushButton:focus, QLineEdit:focus, QComboBox:focus, QListWidget:focus {
            border: 2px solid $gold; }
        QPushButton:disabled { color: $muted; border-color: $border; }
        QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextBrowser, QListWidget,
        QTableWidget, QTreeWidget { background: $field; border: 1px solid $border;
            border-radius: 6px; padding: 6px; selection-background-color: $hover; }
        QComboBox { padding-right: 26px; }
        QComboBox QAbstractItemView { background: $panel; color: $text; }
        QHeaderView::section { background: $panel; color: $gold; border: none; padding: 8px; }
        QScrollBar:vertical { background: $bg; width: 12px; margin: 0; }
        QScrollBar::handle:vertical { background: $border; border-radius: 5px;
            min-height: 24px; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        QToolTip { color: $text; background: $panel; border: 1px solid $gold;
            padding: 8px; }
        QMenuBar, QMenu { background: $bg; color: $text; }
        QMenu::item:selected { background: $hover; }
        QStatusBar { color: $muted; background: $bg; }
        QCheckBox { spacing: 9px; padding: 4px; }
        QSplitter::handle { background: $bg; width: 8px; height: 8px; }
        QLabel[eyebrow="true"] { color: $gold; font-size: 11px; letter-spacing: 2px; }
        QLabel[heading="true"] { color: $gold; font-family: Georgia; font-size: 26px; }
    """).substitute(colors)
    )


def sync_chrome(window, index):
    if window._legacy_controls:
        return
    menu = window.tabs.tabText(index) == "Главное меню"
    adventure = window.tabs.tabText(index) == "Приключение"
    compact = window.width() < 900
    for widget in (
        window.scene_title,
        window.mode_label,
        window.resource_label,
        window.navigation_bar,
    ):
        widget.setVisible(
            not menu and (widget is window.navigation_bar or not compact or adventure)
        )
    window.mode_label.setVisible(not menu and not compact)
    if not getattr(window, "_roll_dialog_open", False):
        window.resolution_panel.setVisible(not menu and adventure and not compact)
    window.compact_rolls.setVisible(not menu and adventure and compact)
    window.chronicles_shortcut.setVisible(not menu and not compact)
    window.menuBar().setVisible(not menu)
    window.statusBar().setVisible(not menu)
    window._content_layout.setContentsMargins(*((0, 0, 0, 0) if menu else (20, 16, 12, 16)))
    window.centralWidget().layout().setContentsMargins(0, 0, 0 if menu else 12, 0)
