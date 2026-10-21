"""Visible keyboard-accessible fantasy tabs, using Qt's bounded scroll buttons."""

from PySide6.QtWidgets import QTabBar

from rpg_vkr.ui.motion import Motion

LABELS = {
    "Приключение": "Приключение",
    "Герой": "Герой",
    "Инвентарь": "Инвентарь",
    "Дневник": "Дневник",
    "Карта": "Карта",
    "Хроники мира": "Энциклопедия",
    "Энциклопедия мира": "Энциклопедия",
    "Фотоальбом": "Фотоальбом",
    "Сохранения": "Сохранения",
    "Настройки": "Настройки",
    "Главное меню": "Меню",
}


class SectionTabs(QTabBar):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.setObjectName("sectionTabs")
        self.setAccessibleName("Разделы приключения")
        self.setExpanding(False)
        self.setUsesScrollButtons(True)
        self.setDrawBase(False)
        self.setDocumentMode(True)
        self.rebuild()
        self.currentChanged.connect(self.activate)
        window.tabs.currentChanged.connect(self.sync)

    def rebuild(self):
        self.blockSignals(True)
        while self.count():
            self.removeTab(0)
        for name, label in LABELS.items():
            for index in range(self.window.tabs.count()):
                if self.window.tabs.tabText(index) == name:
                    tab = self.addTab(label)
                    self.setTabData(tab, self.window.tabs.widget(index))
                    self.setTabToolTip(tab, name)
        self.blockSignals(False)
        self.sync(self.window.tabs.currentIndex())

    def activate(self, index):
        if index < 0:
            return
        page = self.tabData(index)
        name = self.window.tabs.tabText(self.window.tabs.indexOf(page))
        self.window.open_section(name)

    def sync(self, index):
        self.blockSignals(True)
        for tab in range(self.count()):
            if self.tabData(tab) is self.window.tabs.widget(index):
                self.setCurrentIndex(tab)
                break
        self.blockSignals(False)


def install_section_tabs(window):
    from PySide6.QtWidgets import QPushButton

    from rpg_vkr.ui.motion import ButtonGlow, system_reduced_motion
    from rpg_vkr.ui.notifications import Notifications

    window.section_tabs = SectionTabs(window)
    row = window.navigation_bar.layout()
    # Compatibility picker is retained only for old programmatic navigation, never displayed.
    for i in range(row.count()):
        widget = row.itemAt(i).widget()
        if widget and widget is not window.compact_rolls:
            widget.hide()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(6)
    row.insertWidget(0, window.section_tabs, 1)
    window.motion = Motion(window)
    window.tabs.currentChanged.connect(lambda _: window.motion.reveal(window.tabs.currentWidget()))
    window._content_layout.setSpacing(6)
    window.button_glows = [
        ButtonGlow(button, window) for button in window.findChildren(QPushButton)
    ]
    window.notifications = Notifications(window)
    window.world_creation_screen.motion_enabled = (
        window.animation_mode.currentIndex() != 2 and not system_reduced_motion()
    )
