"""Explicit homebrew creation with a fixed budget, separate from the legacy editor."""

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from rpg_vkr.application import Session
from rpg_vkr.domain.campaign import DESCRIPTION_LIMIT, WORLD_BRIEF_LIMIT, plain
from rpg_vkr.domain.character import ABILITY_NAMES, Character
from rpg_vkr.domain.progression import ARCHETYPES, POINT_BUDGET, validate_creation


class CreationDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        if parent is not None and not getattr(parent, "_legacy_controls", False):
            self.setFont(parent.font())
        self.setWindowTitle("Создать героя · авторские правила")
        self.setMinimumSize(480, 550)
        self.resize(580, 740)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        container = QVBoxLayout(content)
        self.creation_steps = QTabWidget()
        container.addWidget(self.creation_steps)

        def step(title):
            page = QWidget()
            self.creation_steps.addTab(page, title)
            return QFormLayout(page)

        layout = step("Личность")
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        note = QLabel(
            "База 8, распределите 24 очка. Повышение на 1 стоит 1 очко; максимум 16. "
            "Это homebrew-профили, не полные классы SRD."
        )
        note.setWordWrap(True)
        layout.addRow(note)
        self.name_input = QLineEdit("Путник")
        self.name_input.setMaxLength(40)
        layout.addRow("Имя", self.name_input)
        self.class_choice = QComboBox()
        for key, archetype in ARCHETYPES.items():
            self.class_choice.addItem(archetype.name, key)
        layout.addRow("Класс / авторский профиль", self.class_choice)
        self.use_d20_skills = QCheckBox("Навыки D20: 13 очков, бонус +2 за ранг")
        self.use_d20_skills.setToolTip(
            "Отдельное развитие навыков; включается только для нового героя."
        )
        layout.addRow(self.use_d20_skills)
        from rpg_vkr.domain.gameplay import PROFILES, SPECIES

        self.use_gameplay = QCheckBox("Приключение v3: экипировка, бой, магия, мастерская, время")
        layout.addRow(self.use_gameplay)
        self.species_choice = QComboBox()
        for key, name in SPECIES.items():
            self.species_choice.addItem(name, key)
        layout.addRow("Вид (v3)", self.species_choice)
        self.profile_choice = QComboBox()
        for key, name in PROFILES.items():
            self.profile_choice.addItem(name, key)
        layout.addRow("Специализация (v3)", self.profile_choice)
        self.age_input = QSpinBox()
        self.age_input.setRange(18, 1000)
        self.age_input.setValue(20)
        layout.addRow("Возраст (v3)", self.age_input)
        self.background_input = QLineEdit("Путешественник")
        self.background_input.setMaxLength(400)
        layout.addRow("Происхождение (v3)", self.background_input)
        self.appearance_input = QLineEdit("Дорожная одежда")
        self.appearance_input.setMaxLength(400)
        layout.addRow("Внешность (v3)", self.appearance_input)
        note_v3 = QLabel(
            "v3 включается только для новой кампании. Виды описательные; "
            "старые профили выше задают характеристики. Магия требует обучения "
            "Теории магии. Все действия нового набора доступны на странице героя."
        )
        note_v3.setWordWrap(True)
        layout.addRow(note_v3)
        from rpg_vkr.domain.d20_progression import SKILLS

        layout = step("Навыки и талант")
        from rpg_vkr.domain.gameplay_v2 import TALENTS

        self.initial_talent = QComboBox()
        self.initial_talent.addItem("Выбрать позже", "")
        for key, name in TALENTS.items():
            self.initial_talent.addItem(name, key)
        layout.addRow("Начальный талант (v3)", self.initial_talent)
        self.initial_skills = {}
        self.initial_skill_budget = QLabel("Начальные навыки: 0 / 13 очков")
        layout.addRow(self.initial_skill_budget)
        for key, (name, _) in SKILLS.items():
            spin = QSpinBox()
            spin.setRange(0, 2)
            spin.valueChanged.connect(self._update_creation_skills)
            self.initial_skills[key] = spin
            layout.addRow(name + " (v3)", spin)
        layout = step("История и мир")
        self.description_input = QPlainTextEdit()
        self.description_input.setAccessibleName("Свободное описание героя")
        self.description_input.setPlaceholderText(
            "Внешность, происхождение, семья, прошлое и желания героя. Можно оставить пустым."
        )
        self.description_input.setMaximumHeight(150)
        layout.addRow("Расскажите о герое", self.description_input)
        self.description_limit = QLabel(
            f"До {DESCRIPTION_LIMIT} символов. Исходный текст сохраняется без переписывания."
        )
        self.description_limit.setWordWrap(True)
        layout.addRow(self.description_limit)
        self.description_input.textChanged.connect(self._update_budget)
        self.world_brief_input = QPlainTextEdit()
        self.world_brief_input.setAccessibleName("Пожелания к миру и жанру")
        self.world_brief_input.setPlaceholderText(
            "Например: приключенческое фэнтези, редкая магия, торговля, интриги гильдий. "
            "Это пожелания к повествованию, а не выдача предметов или готовый мир."
        )
        self.world_brief_input.setMaximumHeight(100)
        layout.addRow("Мир, жанры и настроение", self.world_brief_input)
        self.world_brief_limit = QLabel(f"До {WORLD_BRIEF_LIMIT} символов. Поле необязательное.")
        self.world_brief_limit.setWordWrap(True)
        layout.addRow(self.world_brief_limit)
        self.world_brief_input.textChanged.connect(self._update_budget)
        self.generate_world = QCheckBox("Создать новый мир и сюжет мастером")
        self.generate_world.setChecked(not getattr(parent, "_legacy_controls", False))
        layout.addRow(self.generate_world)
        self.generate_world.setVisible(getattr(parent, "_legacy_controls", False))
        generation_note = QLabel(
            "Место и сюжет выбирает мастер по описаниям выше. Включите ИИ до "
            "создания героя; для нового мира требуется облачное подключение."
        )
        generation_note.setWordWrap(True)
        layout.addRow(generation_note)
        layout = step("Характеристики")
        self.kit_label = QLabel()
        self.kit_label.setWordWrap(True)
        layout.addRow(self.kit_label)
        self.scores = {}
        for ability, name in ABILITY_NAMES.items():
            spin = QSpinBox()
            spin.setRange(8, 16)
            self.scores[ability] = spin
            layout.addRow(name, spin)
            spin.valueChanged.connect(self._update_budget)
        recommended = QPushButton("Применить рекомендованные характеристики")
        recommended.clicked.connect(self.apply_recommended)
        layout.addRow(recommended)
        self.budget_label = QLabel()
        self.budget_label.setWordWrap(True)
        layout.addRow(self.budget_label)
        layout = step("Подтверждение")
        self.creation_summary = QLabel()
        self.creation_summary.setWordWrap(True)
        layout.addRow(self.creation_summary)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Создать героя")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        outer.addWidget(self.buttons)
        self.class_choice.currentIndexChanged.connect(self._update_kit)
        self.name_input.textChanged.connect(self._update_budget)
        self.apply_recommended()
        self._update_kit()
        self.use_gameplay.toggled.connect(self._update_budget)
        self.initial_talent.currentIndexChanged.connect(self._update_budget)
        self.profile_choice.currentIndexChanged.connect(self._update_budget)
        self.species_choice.currentIndexChanged.connect(self._update_budget)
        self.background_input.textChanged.connect(self._update_budget)
        self.appearance_input.textChanged.connect(self._update_budget)

    def apply_recommended(self) -> None:
        for ability, score in zip(
            ABILITY_NAMES, ARCHETYPES[self.class_choice.currentData()].scores, strict=True
        ):
            self.scores[ability].setValue(score)
        self._update_budget()

    def _update_kit(self) -> None:
        if self.use_gameplay.isChecked():
            from collections import Counter

            from rpg_vkr.domain.gameplay import ITEM_NAMES
            from rpg_vkr.domain.gameplay_v2 import initial
            from rpg_vkr.domain.hero_resources import limits

            try:
                character = Character(
                    name=self.name_input.text().strip() or "Путник",
                    **{k: v.value() for k, v in self.scores.items()},
                )
                state = initial(self.gameplay_identity(), character)
                caps = limits(state, character, 1)
                inventory = ", ".join(
                    f"{ITEM_NAMES[k]} ×{n}"
                    for k, n in Counter(i["kind"] for i in state["items"]).items()
                )
                self.kit_label.setText(
                    f"Предпросмотр: HP {caps['hp']}, ST {caps['st']}, MP {caps['mp']}. "
                    f"Стартовый набор: {inventory}."
                )
            except ValueError as error:
                self.kit_label.setText(str(error))
            return
        kit = ARCHETYPES[self.class_choice.currentData()]
        self.kit_label.setText(
            f"{kit.description}\nСтарт: {kit.gold} золотых, бинты ×{kit.bandages}, "
            f"{kit.equipment}, дорожный учебник. Здоровье 12/12."
        )

    def _update_budget(self) -> None:
        if not hasattr(self, "buttons"):
            return
        remaining = POINT_BUDGET - sum(spin.value() - 8 for spin in self.scores.values())
        self.budget_label.setText(f"Осталось очков: {remaining}. Для создания должно остаться 0.")
        used = len(self.description_input.toPlainText())
        world_used = len(self.world_brief_input.toPlainText())
        self.world_brief_limit.setText(
            f"Пожелания к миру: {world_used}/{WORLD_BRIEF_LIMIT} символов. "
            + ("Сократите текст." if world_used > WORLD_BRIEF_LIMIT else "Поле необязательное.")
        )
        self.description_limit.setText(
            f"Описание: {used}/{DESCRIPTION_LIMIT} символов. "
            + (
                "Лимит превышен; сократите текст. Он остаётся в поле ввода."
                if used > DESCRIPTION_LIMIT
                else "Исходный текст сохраняется без переписывания."
            )
        )
        valid_identity = True
        if self.use_gameplay.isChecked():
            from rpg_vkr.domain.gameplay_v2 import initial

            try:
                initial(self.gameplay_identity(), Character())
            except ValueError:
                valid_identity = False
        self._update_kit()
        self.creation_summary.setText(
            f"{self.name_input.text().strip()} · {self.class_choice.currentText()}\n"
            f"Характеристики: {', '.join(str(v.value()) for v in self.scores.values())}.\n"
            + (
                f"Приключение v3: {self.species_choice.currentText()}, "
                f"{self.profile_choice.currentText()}; {self.initial_skill_budget.text()}; "
                f"талант: {self.initial_talent.currentText()}.\n"
                + self.kit_label.text()
                + "\n"
                + "Проверьте выбор. До создания героя можно вернуться в любой раздел."
                if self.use_gameplay.isChecked()
                else "Прежний совместимый набор правил."
            )
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            valid_identity
            and remaining == 0
            and bool(self.name_input.text().strip())
            and len(self.description_input.toPlainText()) <= DESCRIPTION_LIMIT
            and world_used <= WORLD_BRIEF_LIMIT
        )

    def character(self) -> Character:
        character = Character(
            name=self.name_input.text().strip(),
            **{key: spin.value() for key, spin in self.scores.items()},
        )
        validate_creation(character, self.class_choice.currentData())
        return character

    def _update_creation_skills(self):
        cost = sum(spin.value() * (spin.value() + 1) // 2 for spin in self.initial_skills.values())
        self.initial_skill_budget.setText(
            f"Начальные навыки: {cost} / 13 очков; остаток {13 - cost}"
        )
        if hasattr(self, "buttons"):
            self._update_budget()

    def gameplay_identity(self):
        return {
            "species": self.species_choice.currentData(),
            "profile": self.profile_choice.currentData(),
            "age": self.age_input.value(),
            "background": self.background_input.text().strip(),
            "appearance": self.appearance_input.text().strip(),
            "talent": self.initial_talent.currentData(),
            "skills": {k: v.value() for k, v in self.initial_skills.items() if v.value()},
        }

    def create_session(self) -> Session:
        description = plain(self.description_input.toPlainText(), DESCRIPTION_LIMIT, empty=True)
        session = Session.create_hero(
            self.character(),
            self.class_choice.currentData(),
            description=description,
            world_brief=plain(self.world_brief_input.toPlainText(), WORLD_BRIEF_LIMIT, empty=True),
        )
        if self.use_d20_skills.isChecked():
            session.enable_d20_progress()
        if self.use_gameplay.isChecked():
            session.enable_gameplay(self.gameplay_identity(), revision=4)
        return session

    def accept(self) -> None:
        try:
            character = self.character()
            if self.use_gameplay.isChecked():
                from rpg_vkr.domain.gameplay_v2 import initial

                initial(self.gameplay_identity(), character)
            plain(self.description_input.toPlainText(), DESCRIPTION_LIMIT, empty=True)
            plain(self.world_brief_input.toPlainText(), WORLD_BRIEF_LIMIT, empty=True)
        except ValueError as error:
            QMessageBox.warning(self, "Проверьте героя", str(error))
            return
        super().accept()
