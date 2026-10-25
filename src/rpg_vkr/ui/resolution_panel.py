"""A persistent companion to the story: previous rolls and current action guidance."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QInputDialog,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from rpg_vkr.commands import normalise_action
from rpg_vkr.domain.challenge import CHALLENGES, proposed_challenge
from rpg_vkr.domain.character import ABILITY_NAMES
from rpg_vkr.domain.combat import ATTACK_COMMANDS, STEALTH_COMMANDS
from rpg_vkr.domain.inspection import requested_abilities
from rpg_vkr.narrative.presentation import present_turn


def label(text=""):
    widget = QLabel(text)
    widget.setWordWrap(True)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    return widget


def install_resolution_panel(window, layout):
    window.resolution_panel = QGroupBox("Кубик и результат")
    window.resolution_panel.setMinimumWidth(210)
    window.resolution_panel.setMaximumWidth(330)
    panel = QVBoxLayout(window.resolution_panel)
    window.action_guidance = label()
    panel.addWidget(window.action_guidance)
    panel.addWidget(label("Последнее действие"))
    window.action_result = label("Пока нет действий.")
    window.action_result.setFont(window.journal.font())
    panel.addWidget(window.action_result)
    panel.addWidget(label("Разбор · 100 действий с бросками"))
    window.breakdown_selector = QComboBox()
    window.breakdown_selector.setMinimumContentsLength(8)
    window.breakdown_selector.setSizeAdjustPolicy(
        QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
    )
    window.breakdown_selector.setAccessibleName("Выбрать действие для разбора бросков")
    panel.addWidget(window.breakdown_selector)
    window.roll_breakdown = QPlainTextEdit()
    window.roll_breakdown.setReadOnly(True)
    window.roll_breakdown.setFont(window.journal.font())
    window.roll_breakdown.setAccessibleName("Понятный расчёт бросков выбранного действия")
    panel.addWidget(window.roll_breakdown, 1)
    window.export_rolls_button = QPushButton("Экспорт всех расчётов…")
    window.export_rolls_button.clicked.connect(window.export_calculations)
    panel.addWidget(window.export_rolls_button)
    window.preview_dice_button = QPushButton("Пробный бросок NdM±K…")
    window.preview_dice_button.clicked.connect(lambda: preview_dice(window))
    panel.addWidget(window.preview_dice_button)
    window.preview_dice_result = label()
    panel.addWidget(window.preview_dice_result)
    layout.addWidget(window.resolution_panel)
    window.breakdown_selector.currentIndexChanged.connect(lambda index: show_breakdown(window))
    window.action_input.textChanged.connect(lambda text: refresh_guidance(window))
    refresh_resolution_panel(window)


def preview_dice(window):
    from rpg_vkr.domain.dice import DiceRoller

    expression, accepted = QInputDialog.getText(
        window, "Пробные кубики", "Например, 2d6+3. Не меняет исходы действий в игре."
    )
    if not accepted:
        return
    if not hasattr(window, "_preview_dice"):
        window._preview_dice = DiceRoller()
    try:
        result = window._preview_dice.roll(expression)
    except ValueError as error:
        window.preview_dice_result.setText(str(error))
        return
    window.preview_dice_result.setText(
        f"{result.expression}: {', '.join(map(str, result.individual_rolls))}; "
        f"поправка {result.modifier:+d}; итог {result.total}. Пробный бросок."
    )


def refresh_guidance(window):
    session = window._session
    command = normalise_action(window.action_input.text())
    inspection = requested_abilities(window.action_input.text())
    challenge = proposed_challenge(window.action_input.text())
    actor_id = ATTACK_COMMANDS.get(command) or STEALTH_COMMANDS.get(command)
    actor_id = actor_id or (session.combat.active if command == "атаковать" else None)
    if session.world.hp == 0:
        text = "Герой выбыл. Загрузите сессию или создайте нового героя."
    elif actor_id and not session.actor_is_here(actor_id):
        text = "Цели здесь нет. Сначала доберитесь до её места."
    elif actor_id and session.combat.actor(actor_id).hp == 0:
        text = "Цель уже повержена. Повторной награды нет."
    elif session.combat.active and command in STEALTH_COMMANDS:
        text = "В открытой схватке скрытно подойти заново нельзя."
    elif actor_id and session.combat.active not in (None, actor_id):
        text = "Сначала завершите текущую схватку или отступите."
    elif command in STEALTH_COMMANDS:
        text = (
            "Скрытность: Ловкость, нужно 15 для незамеченного подхода. Он удвоит урон атаки "
            "при попадании. Если заметят — противник ответит."
        )
    elif actor_id:
        text = "Атака: сначала попадание, затем усиление удара. Выживший противник отвечает."
        if session.combat.actor(actor_id).disposition == "neutral":
            text += " Нападение сделает цель враждебной."
        if session.combat.surprise:
            text += " Незамеченный подход: урон ×2 при попадании; промах потратит преимущество."
    elif inspection:
        text = (
            "Исследование недоступно во время схватки."
            if session.combat.active
            else "Исследование: "
            + ", ".join(ABILITY_NAMES[a] for a in inspection)
            + ". Отдельный кубик для каждой проверки, сложность 10. "
            "Телосложение поддерживает долгий поиск; обычный осмотр — без броска."
        )
    elif command == "использовать бинт" and session.combat.active:
        text = "Бинт лечит до 4 здоровья вместо атаки. После лечения противник отвечает."
    elif command in {"уклониться", "отступить"} and session.combat.active:
        text = "Проверка Ловкости: нужно набрать 10. Неудача позволяет противнику ответить."
    elif challenge:
        ability, difficulty, purpose = CHALLENGES[challenge]
        text = (
            "Эта проверка недоступна во время схватки."
            if session.combat.active
            else f"Попытка: {purpose}. {ABILITY_NAMES[ability]}, сложность {difficulty}. "
            "После отправки можно подтвердить или отменить бросок."
        )
    else:
        text = (
            "Введите действие. Если нужен кубик, бросок произойдёт автоматически. "
            "Здесь можно просмотреть его расчёт."
        )
    window.action_guidance.setText(text)


def refresh_resolution_panel(window):
    if not hasattr(window, "resolution_panel"):
        return
    turns = window._session.turns
    if turns:
        last = turns[-1]
        view = present_turn(last)
        action = last.action[:60] + ("…" if len(last.action) > 60 else "")
        window.action_result.setText(view.title + "\n" + action)
        window.action_result.setToolTip(last.action)
        palette = QPalette(window.palette())
        if last.actor_id:
            palette.setColor(
                QPalette.ColorRole.WindowText, window.journal.actor_colour(last.actor_id)
            )
        window.action_result.setPalette(palette)
        colors = window.journal.highlighter.colors
        if colors:
            role = "system"
            check = last.check or (last.challenge.check if last.challenge else None)
            if check:
                role = "success" if check.succeeded else "hostile"
            if last.combat:
                outcome = last.combat.outcome
                if outcome.world.hp < last.combat.world_before.hp:
                    role = "hostile"
                elif outcome.victory:
                    role = "important"
            window.action_result.setStyleSheet("color: " + colors[role] + ";")
    else:
        window.action_result.setText("Пока нет действий.")
        window.action_result.setToolTip("")
        window.action_result.setPalette(window.palette())
        window.action_result.setStyleSheet("")
    key = (window._session, len(turns))
    if getattr(window, "_breakdown_key", None) != key:
        previous = window.breakdown_selector.currentData()
        same_session = getattr(window, "_breakdown_key", (None,))[0] is window._session
        window._breakdown_key = key
        entries = [
            (i, turn)
            for i, turn in enumerate(turns)
            if turn.inspection
            or turn.roll
            or (turn.combat and turn.combat.outcome.rolls)
            or (turn.gameplay and turn.gameplay["result"]["rolls"])
        ][-100:]
        window.breakdown_selector.blockSignals(True)
        window.breakdown_selector.clear()
        for i, turn in entries:
            window.breakdown_selector.addItem(f"Ход {i + 1}: {turn.action[:35]}", i)
        index = window.breakdown_selector.findData(previous) if same_session else -1
        if turns and (
            (turns[-1].gameplay and turns[-1].gameplay["result"]["rolls"])
            or turns[-1].inspection
            or turns[-1].roll
            or (turns[-1].combat and turns[-1].combat.outcome.rolls)
        ):
            index = len(entries) - 1
        window.breakdown_selector.setCurrentIndex(index if index >= 0 else len(entries) - 1)
        window.breakdown_selector.setEnabled(bool(entries))
        window.breakdown_selector.blockSignals(False)
    show_breakdown(window)
    refresh_guidance(window)


def show_breakdown(window):
    index = window.breakdown_selector.currentData()
    if index is None:
        text = "Бросков пока нет. Мирные действия могут выполняться без кубика."
    else:
        turn = window._session.turns[index]
        view = present_turn(turn)
        text = f"Действие №{index + 1}: {turn.action}\n{view.title}\n\n{view.details}"
    if text != window.roll_breakdown.toPlainText():
        window.roll_breakdown.setPlainText(text)
