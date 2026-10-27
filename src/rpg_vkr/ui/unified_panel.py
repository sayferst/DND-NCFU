"""Player controls for the single ruleset; all effects go through Session."""

import uuid

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QPlainTextEdit,
    QPushButton,
)

from rpg_vkr.domain.unified import CLASSES, RECIPES


def install(window, layout):
    window.unified_group = QGroupBox("Герой и действия")
    layout.addWidget(window.unified_group)
    form = QFormLayout(window.unified_group)
    window.unified_info = QLabel()
    window.unified_info.setWordWrap(True)
    form.addRow(window.unified_info)
    window.unified_items = QComboBox()
    form.addRow("Предмет", window.unified_items)
    window.unified_target = QComboBox()
    form.addRow("Цель", window.unified_target)

    def button(label, command, arguments):
        value = QPushButton(label)
        form.addRow(value)
        value.clicked.connect(lambda: run(window, command, arguments()))

    button("Экипировать", "equip", lambda: {"item": window.unified_items.currentData()})
    button(
        "Использовать",
        "consume",
        lambda: {
            "item": window.unified_items.currentData(),
            "target": window.unified_target.currentData(),
        },
    )
    button(
        "Начать бой",
        "encounter",
        lambda: {"enemies": [window.unified_target.currentData()], "allies": []},
    )
    button("Атаковать", "attack", lambda: {"target": window.unified_target.currentData()})
    button("Перевести дух", "recover", dict)
    window.unified_spell = QComboBox()
    form.addRow("Заклинание", window.unified_spell)
    button(
        "Применить заклинание",
        "cast",
        lambda: {
            "spell": window.unified_spell.currentData(),
            "target": window.unified_target.currentData(),
        },
    )
    window.unified_recipe = QComboBox()
    for key in RECIPES:
        window.unified_recipe.addItem(key, key)
    form.addRow("Рецепт", window.unified_recipe)
    button("Изготовить", "manufacture", lambda: {"recipe": window.unified_recipe.currentData()})
    button("Отремонтировать", "repair", lambda: {"item": window.unified_items.currentData()})
    button("Отдохнуть", "rest", dict)
    from rpg_vkr.domain.character import ABILITY_NAMES

    window.unified_growth = QGroupBox("Развитие героя")
    growth = QFormLayout(window.unified_growth)
    window.unified_growth_status = QLabel()
    growth.addRow(window.unified_growth_status)
    window.unified_raise = QComboBox()
    for key, name in ABILITY_NAMES.items():
        window.unified_raise.addItem(name, key)
    growth.addRow("Характеристика", window.unified_raise)
    raise_button = QPushButton("Повысить характеристику")
    growth.addRow(raise_button)
    raise_button.clicked.connect(
        lambda: run(window, "raise", {"ability": window.unified_raise.currentData()})
    )
    window.unified_raise_button = raise_button
    window.unified_talent = QComboBox()
    growth.addRow("Новый талант", window.unified_talent)
    talent_button = QPushButton("Получить талант")
    growth.addRow(talent_button)
    talent_button.clicked.connect(
        lambda: run(window, "talent", {"talent": window.unified_talent.currentData()})
    )
    window.unified_talent_button = talent_button
    form.addRow(window.unified_growth)
    window.unified_log = QPlainTextEdit()
    window.unified_log.setReadOnly(True)
    window.unified_log.setMaximumHeight(140)
    form.addRow(window.unified_log)
    window.unified_group.hide()


def refresh(window):
    enabled = getattr(window._session, "is_unified", False)
    window.unified_group.setVisible(enabled)
    if not enabled:
        return
    from rpg_vkr.domain.unified import level, proficiency

    state = window._session.gameplay
    s = window._session
    window.unified_info.setText(
        f"{CLASSES[state['identity']['class_id']][0]} · "
        f"уровень{level(state['xp'])} · XP{state['xp']}\n"
        f"HP{s.world.hp}/{s.world.max_hp} · MP{state['mp']}/{state['mp_cap']} · "
        f"ST{state['st']}/{state['st_cap']}\n"
        f"Подготовка+{proficiency(state['xp'])} · {state['copper']} медных"
    )

    from rpg_vkr.domain.unified import TALENTS, talents

    lv = level(state["xp"])
    points = 2 * sum(lv >= n for n in (4, 8, 12, 16, 20)) - sum(state["ability_increases"].values())
    choices = 1 + sum(lv >= n for n in (5, 10, 15, 20)) - len(state["talents"])
    window.unified_growth.setVisible(points > 0 or choices > 0)
    window.unified_growth_status.setText(
        f"Повышения характеристик: {points}; доступных талантов: {choices}."
    )
    window.unified_raise_button.setEnabled(points > 0)
    window.unified_talent_button.setEnabled(choices > 0)
    window.unified_talent.clear()
    for key in talents(state["identity"]["class_id"]):
        if key not in state["talents"]:
            window.unified_talent.addItem(TALENTS[key][0] + " — " + TALENTS[key][1], key)

    def refill(box, rows):
        selected = box.currentData()
        box.clear()
        for key, name in rows:
            box.addItem(name, key)
        if box.findData(selected) >= 0:
            box.setCurrentIndex(box.findData(selected))

    refill(
        window.unified_items,
        [(i["id"], i["name"]) for i in state["items"] if i["owner"] == "hero"]
        + [
            (t.id, t.name)
            for t in s.interaction_state().carried()
            if not any(i["id"] == t.id for i in state["items"])
        ],
    )
    refill(
        window.unified_target,
        [("hero", "Герой")]
        + [(a.id, a.name) for a in s.interaction_state().actor_refs if s.actor_is_here(a.id)],
    )
    refill(
        window.unified_spell,
        [
            (
                k,
                {
                    "light": "Путеводный свет ·1MP",
                    "heal": "Исцеление ·3MP",
                    "bolt": "Магический разряд ·3MP",
                }.get(k, k),
            )
            for k in state["spells"]
        ],
    )


def run(window, command, args):
    if not getattr(window._session, "is_unified", False):
        return
    try:
        turn = window._session.perform_gameplay(command, args, "ui_" + uuid.uuid4().hex)
        window.unified_log.setPlainText(turn.text)
        window._dirty = True
        window._render_journal()
        window._refresh_character()
    except ValueError as e:
        window.unified_log.setPlainText(str(e))
