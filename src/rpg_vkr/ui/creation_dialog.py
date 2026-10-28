"""Four-page creation flow for the single canonical new campaign."""

from collections import Counter

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from rpg_vkr.domain.campaign import DESCRIPTION_LIMIT, WORLD_BRIEF_LIMIT, plain
from rpg_vkr.domain.character import ABILITY_NAMES, Character, ability_modifier
from rpg_vkr.domain.unified import CLASSES, ITEMS, KITS, TALENTS, caps, initial, talents
from rpg_vkr.unified_session import UnifiedSession

HELP = {
    "strength": "Сила — физические усилия, тяжёлое оружие и перенос груза.",
    "dexterity": "Ловкость — меткость, скрытность, реакция.",
    "constitution": "Телосложение — здоровье и стойкость.",
    "intelligence": "Интеллект — знания, исследование, ремесло.",
    "wisdom": "Мудрость — внимательность и интуиция.",
    "charisma": "Харизма — общение, убеждение и влияние.",
}


class CreationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        if parent is not None:
            self.setFont(parent.font())
        self.setWindowTitle("Создать героя")
        self.resize(680, 680)
        self.setMinimumSize(480, 360)
        outer = QVBoxLayout(self)
        self.heading = QLabel()
        outer.addWidget(self.heading)
        self.creation_steps = QStackedWidget()
        outer.addWidget(self.creation_steps, 1)

        def page(title):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            content = QWidget()
            layout = QFormLayout(content)
            layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
            scroll.setWidget(content)
            scroll.setProperty("title", title)
            self.creation_steps.addWidget(scroll)
            return layout

        def label(text):
            v = QLabel(text)
            v.setWordWrap(True)
            v.setTextFormat(Qt.TextFormat.PlainText)
            return v

        form = page("Герой")
        self.name_input = QLineEdit("Путник")
        self.name_input.setMaxLength(40)
        self.name_input.setToolTip(
            "Имя героя. Остальные особенности можно описать на шаге «История и мир»."
        )
        form.addRow("Имя", self.name_input)
        self.class_choice = QComboBox()
        for key, data in CLASSES.items():
            self.class_choice.addItem(data[0], key)
        self.class_choice.setToolTip(
            "Класс даёт подготовку к своим действиям. Другие действия тоже доступны."
        )
        form.addRow("Класс", self.class_choice)
        self.class_info = label("")
        form.addRow(self.class_info)
        self.kit_label = label("")
        form.addRow("Стартовый комплект", self.kit_label)
        form = page("Характеристики и талант")
        self.scores = {}
        self.modifiers = {}
        for key, title in ABILITY_NAMES.items():
            line = QWidget()
            row = QHBoxLayout(line)
            row.setContentsMargins(0, 0, 0, 0)
            spin = QSpinBox()
            spin.setRange(8, 16)
            spin.setMaximumWidth(95)
            spin.setToolTip(HELP[key])
            spin.setAccessibleName(HELP[key])
            value = label("")
            row.addWidget(spin)
            row.addWidget(value)
            row.addStretch()
            self.scores[key] = spin
            self.modifiers[key] = value
            form.addRow(title, line)
            spin.valueChanged.connect(self._update_budget)
        self.budget_label = label("")
        form.addRow(self.budget_label)
        recommend = QPushButton("Рекомендованные характеристики")
        recommend.clicked.connect(self.apply_recommended)
        form.addRow(recommend)
        self.initial_talent = QComboBox()
        form.addRow("Талант", self.initial_talent)
        self.talent_info = label("")
        form.addRow(self.talent_info)
        self.resource_preview = label("")
        form.addRow(self.resource_preview)
        form = page("История и мир")
        self.description_input = QPlainTextEdit()
        self.description_input.setMinimumHeight(140)
        self.description_input.setPlaceholderText(
            "Внешность, возраст, раса, семья, прошлое и желания. Можно оставить пустым."
        )
        self.description_input.setToolTip(
            "Свободное описание сохраняется дословно; не выдаёт бонусы и предметы."
        )
        form.addRow("Описание персонажа", self.description_input)
        self.description_limit = label("")
        form.addRow(self.description_limit)
        self.world_brief_input = QPlainTextEdit()
        self.world_brief_input.setMinimumHeight(120)
        self.world_brief_input.setPlaceholderText(
            "Жанр, атмосфера, магия, пожелания и ограничения мира."
        )
        self.world_brief_input.setToolTip("Мастер создаст новый мир на основании этих пожеланий.")
        form.addRow("Пожелания к миру", self.world_brief_input)
        self.world_brief_limit = label("")
        form.addRow(self.world_brief_limit)
        form = page("Подтверждение")
        self.creation_summary = label("")
        form.addRow(self.creation_summary)
        self.error = label("")
        outer.addWidget(self.error)
        row = QHBoxLayout()
        outer.addLayout(row)
        self.back = QPushButton("Назад")
        self.next = QPushButton("Далее")
        row.addWidget(self.back)
        row.addStretch()
        row.addWidget(self.next)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Создать героя")
        row.addWidget(self.buttons)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.back.clicked.connect(lambda: self.step(-1))
        self.next.clicked.connect(lambda: self.step(1))
        self.name_input.textChanged.connect(self._update_budget)
        self.description_input.textChanged.connect(self._update_budget)
        self.world_brief_input.textChanged.connect(self._update_budget)
        self.initial_talent.currentIndexChanged.connect(self._update_budget)
        self.class_choice.currentIndexChanged.connect(self._update_kit)
        self._update_kit()
        self.step(0)

    def step(self, delta):
        n = max(0, min(3, self.creation_steps.currentIndex() + delta))
        self.creation_steps.setCurrentIndex(n)
        self.heading.setText(
            f"{n + 1}/4 · " + self.creation_steps.currentWidget().property("title")
        )
        self.back.setEnabled(n > 0)
        self.next.setVisible(n < 3)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setVisible(n == 3)
        self._update_budget()
        height = (360, 650, 600, 600 if self.description_input.toPlainText() else 460)[n]
        self.resize(self.width(), height)

    def apply_recommended(self):
        for key, value in zip(
            ABILITY_NAMES, CLASSES[self.class_choice.currentData()][3], strict=True
        ):
            self.scores[key].setValue(value)
        self._update_budget()

    def _update_kit(self):
        key = self.class_choice.currentData()
        data = CLASSES[key]
        self.class_info.setText(
            data[1] + ". Подготовка +2 на первом уровне; растёт автоматически по уровню."
        )
        self.kit_label.setText(", ".join(f"{ITEMS[k]} ×{n}" for k, n in Counter(KITS[key]).items()))
        self.initial_talent.blockSignals(True)
        self.initial_talent.clear()
        for id in talents(key):
            self.initial_talent.addItem(TALENTS[id][0], id)
        self.initial_talent.setCurrentIndex(self.initial_talent.findData(CLASSES[key][4]))
        self.initial_talent.blockSignals(False)
        if not getattr(self, "_initialized", False):
            self.apply_recommended()
            self._initialized = True
        else:
            self._update_budget()

    def character(self):
        value = Character(
            name=self.name_input.text().strip(), **{k: s.value() for k, s in self.scores.items()}
        )
        initial(
            {
                "class_id": self.class_choice.currentData(),
                "talent": self.initial_talent.currentData(),
            },
            value,
        )
        return value

    def _update_budget(self, *args):
        if not hasattr(self, "buttons"):
            return
        left = 24 - sum(s.value() - 8 for s in self.scores.values())
        self.budget_label.setText(f"Осталось очков: {left}. Нужно распределить ровно24.")
        for key, spin in self.scores.items():
            self.modifiers[key].setText(f"{spin.value()} → {ability_modifier(spin.value()):+}")
        talent = self.initial_talent.currentData()
        self.talent_info.setText(TALENTS[talent][1] if talent else "Выберите талант.")
        self.initial_talent.setToolTip(self.talent_info.text())
        self.description_limit.setText(
            f"{len(self.description_input.toPlainText())}/{DESCRIPTION_LIMIT} символов"
        )
        self.world_brief_limit.setText(
            f"{len(self.world_brief_input.toPlainText())}/{WORLD_BRIEF_LIMIT} символов"
        )
        try:
            character = self.character()
            plain(self.description_input.toPlainText(), DESCRIPTION_LIMIT, empty=True)
            plain(self.world_brief_input.toPlainText(), WORLD_BRIEF_LIMIT, empty=True)
            state = initial(
                {"class_id": self.class_choice.currentData(), "talent": talent}, character
            )
            limits = caps(state, character)
            self.resource_preview.setText(
                f"HP {limits['hp']} · MP {limits['mp']} · ST {limits['st']}"
            )
            error = ""
        except ValueError as e:
            error = str(e)
        self.error.setText(error)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(not error)
        self.next.setEnabled(not error)
        self.creation_summary.setText(
            self.name_input.text()
            + " · "
            + self.class_choice.currentText()
            + "\n"
            + self.kit_label.text()
            + "\n"
            + "\n".join(
                f"{ABILITY_NAMES[k]} {s.value()} ({ability_modifier(s.value()):+})"
                for k, s in self.scores.items()
            )
            + "\nТалант: "
            + self.initial_talent.currentText()
            + " — "
            + self.talent_info.text()
            + "\n"
            + self.resource_preview.text()
            + "\n\n"
            + self.description_input.toPlainText()
            + "\n\n"
            + self.world_brief_input.toPlainText()
        )

    def create_session(self):
        return UnifiedSession.create(
            self.character(),
            self.class_choice.currentData(),
            self.initial_talent.currentData(),
            description=self.description_input.toPlainText(),
            world_brief=self.world_brief_input.toPlainText(),
            content_revision=2,
            catalog_revision=2,
        )

    def accept(self):
        self._update_budget()
        if (
            self.creation_steps.currentIndex() == 3
            and self.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
        ):
            super().accept()
