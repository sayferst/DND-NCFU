"""Lightweight shared fantasy design tokens; no game state or remote assets."""

from string import Template

from PySide6.QtGui import QColor, QFont, QPalette

DARK = {
    "bg": "#171a21",
    "panel": "#20252f",
    "field": "#171a21",
    "text": "#e8dfc9",
    "muted": "#b8b1a5",
    "border": "#3d5056",
    "gold": "#e8be77",
    "hover": "#30464c",
}
LIGHT = {
    "bg": "#ede7da",
    "panel": "#f7f2e7",
    "field": "#fffaf0",
    "text": "#252c2e",
    "muted": "#566366",
    "border": "#b7ab94",
    "gold": "#705221",
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
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
        QPalette.ColorRole.PlaceholderText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(colors["muted"]))
    widget.setPalette(palette)
    widget.setFont(QFont("Segoe UI", 11))
    widget.setStyleSheet(
        Template("""
        QWidget { color: $text; background-color: $bg; }
        QMainWindow, QDialog, QScrollArea, QTabWidget::pane { background: $bg; }
        QLabel { background: transparent; }
        QTabWidget::pane { border: none; }
        QTabBar::tab { background: $panel; color: $text; border:1px solid $border;
            padding: 7px 10px; }
        QTabBar::tab:selected { background:$hover; color:$gold; }
        QTabBar#sectionTabs::tab { background: $panel; color: $text; border: 1px solid $border;
            border-radius: 5px; padding: 9px 12px; margin: 0 3px 0 0; }
        QTabBar#sectionTabs::tab:selected { background: $hover; border-color: $gold; color: $gold; }
        QTabBar#sectionTabs::tab:hover { border-color: $gold; }
        QTabBar#sectionTabs::tab:disabled { color: $muted; }
        QGroupBox, QFrame[card="true"] { background: $panel; border: 1px solid $border;
            border-radius: 10px; padding: 14px; margin-top: 10px; }
        QGroupBox::title { color: $gold; subcontrol-origin: margin; left: 16px; padding: 0 6px; }
        QPushButton, QToolButton { background: $panel; border: 1px solid $border;
            border-radius: 6px;
            padding: 8px 14px; color: $text; }
        QPushButton:hover, QToolButton:hover { background: $hover; border-color: $gold; }
        QPushButton:pressed { background: $field; }
        QPushButton:focus, QLineEdit:focus, QComboBox:focus, QListWidget:focus {
            border: 2px solid $gold; }
        QPushButton:disabled { color: $muted; border-color: $border; }
        QLineEdit, QAbstractSpinBox, QComboBox, QTextEdit, QPlainTextEdit, QTextBrowser,
        QAbstractItemView { background: $field; color:$text; border: 1px solid $border;
            border-radius: 6px; padding: 6px; selection-background-color: $hover;
            selection-color: $text; }
        QLineEdit, QTextEdit, QPlainTextEdit { placeholder-text-color: $muted; }
        QLabel:disabled, QLineEdit:disabled, QAbstractSpinBox:disabled, QComboBox:disabled,
        QToolButton:disabled {color:$muted;}
        QProgressBar { background:$field; color:$text; border:1px solid $border;
            border-radius:5px; text-align:center; }
        QProgressBar::chunk { background:$hover; }
        QListWidget::item:selected, QTableWidget::item:selected {
            background: $hover; color: $text; }
        QListWidget#knowledgeCards::item, QListWidget#albumCards::item {
            background: $panel; border: 1px solid $border; border-radius: 8px; padding: 5px; }
        QListWidget#knowledgeCards::item:hover, QListWidget#albumCards::item:hover {
            border-color: $gold; background: $hover; }
        QListWidget#knowledgeCards::item:selected, QListWidget#albumCards::item:selected {
            border: 2px solid $gold; background: $hover; }
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
        QCheckBox::indicator:unchecked { border: 1px solid $muted; border-radius: 3px;
            background: $field; width: 14px; height: 14px; }
        QSplitter::handle { background: $bg; width: 8px; height: 8px; }
        QLabel[eyebrow="true"] { color: $gold; font-size: 11px; letter-spacing: 2px; }
        QLabel[heading="true"] { color: $gold; font-family: Georgia; font-size: 26px; }
    """).substitute(colors)
    )


def sync_chrome(window, index):
    if window._legacy_controls:
        return
    if (
        hasattr(window, "world_creation_screen")
        and window.screen_stack.currentWidget() is window.world_creation_screen
    ):
        window.menuBar().hide()
        window.statusBar().hide()
        return
    menu = window.tabs.tabText(index) == "Главное меню"
    from rpg_vkr.ui.navigation_policy import GAME

    playing = window.tabs.tabText(index) in GAME and bool(window._session.generated_world)
    if hasattr(window, "api_settings_button"):
        console = getattr(window, "developer_console", None)
        account_profile = getattr(getattr(window, "release_profile", None), "account_login", False)
        window.api_settings_button.setVisible(
            getattr(window, "_account_name", "") == "admin"
            or bool(console and console.access.authorized and not account_profile)
        )
        if hasattr(window, "notifications"):
            window.notifications.menu.developer_button.setVisible(
                not account_profile or getattr(window, "_account_name", "") == "admin"
            )
    adventure = window.tabs.tabText(index) == "Приключение"
    compact = window.width() < 900
    for widget in (
        window.scene_title,
        window.mode_label,
        window.resource_label,
        window.navigation_bar,
    ):
        widget.setVisible(
            not menu and (widget is window.navigation_bar or playing and (not compact or adventure))
        )
    window.mode_label.setVisible(playing and not compact)
    if not getattr(window, "_roll_dialog_open", False):
        window.resolution_panel.setVisible(playing and adventure and not compact)
    window.compact_rolls.setVisible(playing and adventure and compact)
    window.chronicles_shortcut.setVisible(
        not hasattr(window, "section_tabs") and not menu and not compact
    )
    window.menuBar().setVisible(playing)
    window.statusBar().setVisible(not menu)
    window._content_layout.setContentsMargins(*((0, 0, 0, 0) if menu else (20, 16, 12, 16)))
    window._columns_layout.setContentsMargins(0, 0, 0 if menu else 12, 0)
