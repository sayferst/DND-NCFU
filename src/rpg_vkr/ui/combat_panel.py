"""Combat controls show only actors in the player's current location."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QPalette
from PySide6.QtWidgets import QComboBox, QPlainTextEdit

from rpg_vkr.domain.combat import (
    ACTORS,
    ANGER_COMMANDS,
    ATTACK_COMMANDS,
    STEALTH_COMMANDS,
    disposition_label,
    health_description,
)
from rpg_vkr.narrative.presentation import present_turn


def install_combat_panel(window):
    from rpg_vkr.ui.episode_panels import plain_label

    layout = window._episode_page("Схватка")
    layout.addWidget(
        plain_label(
            "Авторская учебная схватка: попадание и урон считаются отдельно. "
            "Красный и подпись обозначают враждебность. После удара возможен ответ."
        )
    )
    window.encounter_status = plain_label()
    layout.addWidget(window.encounter_status)
    window.combat_targets = QComboBox()
    window.combat_targets.setAccessibleName("Цель схватки")
    layout.addWidget(window.combat_targets)
    window.target_description = plain_label()
    layout.addWidget(window.target_description)
    window.combat_attack = window._panel_button(
        layout, "Атаковать", lambda: attack_selected(window)
    )
    window.combat_stealth = window._panel_button(
        layout, "Подкрасться", lambda: send_selected(window, STEALTH_COMMANDS)
    )
    window.combat_provoke = window._panel_button(
        layout, "Спровоцировать / поссориться", lambda: provoke_selected(window)
    )
    window.combat_dodge = window._panel_button(
        layout, "Уклониться", lambda: window._run_command("уклониться")
    )
    window.combat_retreat = window._panel_button(
        layout, "Отступить", lambda: window._run_command("отступить")
    )
    window.combat_bandage = window._panel_button(
        layout, "Использовать бинт вместо атаки", lambda: window._run_command("использовать бинт")
    )
    window.combat_result = QPlainTextEdit()
    window.combat_result.setReadOnly(True)
    window.combat_result.setFont(window.journal.font())
    window.combat_result.setAccessibleName("Последняя схватка с выбранной целью")
    layout.addWidget(window.combat_result)
    window.combat_targets.currentIndexChanged.connect(lambda index: refresh_target(window))


def send_selected(window, commands):
    actor_id = window.combat_targets.currentData()
    command = next((key for key, value in commands.items() if value == actor_id), None)
    if command:
        window._run_command(command)


def attack_selected(window):
    actor_id = window.combat_targets.currentData()
    if actor_id and window._session.combat.actor(actor_id).disposition == "neutral":
        if not window._confirm(
            "Напасть на нейтрального персонажа? Он станет враждебным; "
            "мирное общение будет недоступно."
        ):
            return
    send_selected(window, ATTACK_COMMANDS)


def provoke_selected(window):
    if window._confirm(
        "Спровоцировать цель? Она станет враждебной, мирное общение будет недоступно."
    ):
        send_selected(window, ANGER_COMMANDS)


def refresh_combat_panel(window):
    previous = window._session.combat.active or window.combat_targets.currentData()
    window.combat_targets.blockSignals(True)
    window.combat_targets.clear()
    for actor in window._session.combat.actors:
        if ACTORS[actor.id][1] == window._session.world.location:
            mark = disposition_label(actor)
            window.combat_targets.addItem(f"{ACTORS[actor.id][0]} [{mark}]", actor.id)
            index = window.combat_targets.count() - 1
            window.combat_targets.setItemData(
                index, QBrush(window.journal.actor_colour(actor.id)), Qt.ItemDataRole.ForegroundRole
            )
    index = window.combat_targets.findData(previous)
    window.combat_targets.setCurrentIndex(max(0, index))
    window.combat_targets.blockSignals(False)
    active = window._session.combat.active
    world = window._session.world
    window.encounter_status.setText(
        f"Ваше здоровье {world.hp}/{world.max_hp}. "
        + (
            f"Схватка: {ACTORS[active][0]}."
            if active
            else "Активной схватки нет. Выбор цели сам по себе не атакует."
        )
    )
    refresh_target(window)


def refresh_target(window):
    actor_id = window.combat_targets.currentData()
    session = window._session
    actor = session.combat.actor(actor_id) if actor_id else None
    active = session.combat.active
    hostile = actor is not None and actor.disposition == "hostile"
    available = (
        actor is not None and actor.hp > 0 and session.world.hp > 0 and active in (None, actor_id)
    )
    window.target_description.setText(
        f"{ACTORS[actor_id][0]} — {health_description(actor)}; " + disposition_label(actor).lower()
        if actor
        else "Здесь нет целей."
    )
    palette = QPalette(window.palette())
    if actor_id:
        palette.setColor(QPalette.ColorRole.Text, window.journal.actor_colour(actor_id))
        palette.setColor(QPalette.ColorRole.ButtonText, window.journal.actor_colour(actor_id))
        palette.setColor(QPalette.ColorRole.WindowText, window.journal.actor_colour(actor_id))
    window.combat_targets.setPalette(palette)
    window.target_description.setPalette(palette)
    window.combat_attack.setEnabled(available)
    window.combat_stealth.setEnabled(
        available and active is None and actor_id in STEALTH_COMMANDS.values()
    )
    window.combat_provoke.setEnabled(
        available and not hostile and actor_id in ANGER_COMMANDS.values()
    )
    window.combat_dodge.setEnabled(active is not None and session.world.hp > 0)
    window.combat_retreat.setEnabled(active is not None and session.world.hp > 0)
    window.combat_bandage.setEnabled(
        active is not None
        and session.world.bandages > 0
        and session.world.hp < session.world.max_hp
    )
    latest = next(
        (
            present_turn(turn).story
            for turn in reversed(session.turns)
            if turn.combat and turn.actor_id == actor_id
        ),
        "С этой целью действий ещё не было.",
    )
    palette = QPalette(window.palette())
    if actor_id:
        palette.setColor(QPalette.ColorRole.Text, window.journal.actor_colour(actor_id))
    window.combat_result.setPalette(palette)
    window.combat_result.setPlainText(latest)
