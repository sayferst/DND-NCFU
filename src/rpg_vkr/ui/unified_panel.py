"""Player controls for the single ruleset; all effects go through Session."""

import uuid

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
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
            **target_args(window),
        },
    )
    window.unified_recipe = QComboBox()
    for key in RECIPES:
        window.unified_recipe.addItem(key, key)
    form.addRow("Рецепт", window.unified_recipe)
    window.unified_result = QComboBox()
    form.addRow("Результат", window.unified_result)
    button(
        "Изготовить",
        "manufacture",
        lambda: {
            "recipe": window.unified_recipe.currentData(),
            **(
                {"result": window.unified_result.currentData()}
                if window.unified_result.currentData()
                else {}
            ),
        },
    )
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
    window.catalog_actions = QGroupBox("Исследование и обучение")
    extra = QFormLayout(window.catalog_actions)
    window.unified_world_info = QLabel()
    window.unified_world_info.setWordWrap(True)
    extra.addRow(window.unified_world_info)
    window.unified_search = QLineEdit()
    window.unified_search.setPlaceholderText("Название техники или рецепта")
    extra.addRow("Поиск", window.unified_search)
    window.unified_learn_kind = QComboBox()
    for key, label in (("spell", "Заклинания"), ("recipe", "Рецепты")):
        window.unified_learn_kind.addItem(label, key)
    extra.addRow("Изучение", window.unified_learn_kind)
    window.unified_learn = QComboBox()
    extra.addRow(window.unified_learn)
    learn = QPushButton("Изучить: сырьё трав и ткань ×1, 1 час, проверка")
    learn.clicked.connect(
        lambda: run(window, "research", {"entry": window.unified_learn.currentData()})
    )
    extra.addRow(learn)
    window.unified_ability = QComboBox()
    extra.addRow("Способность", window.unified_ability)
    ability = QPushButton("Применить способность")
    ability.clicked.connect(
        lambda: run(
            window,
            "ability",
            {"talent": window.unified_ability.currentData(), **target_args(window)},
        )
    )
    extra.addRow(ability)
    window.unified_material = QComboBox()
    extra.addRow("Сырьё", window.unified_material)
    gather = QPushButton("Добыть одну единицу")
    gather.clicked.connect(
        lambda: run(
            window, "gather", {"material": window.unified_material.currentData(), "quantity": 1}
        )
    )
    extra.addRow(gather)
    window.unified_destination = QComboBox()
    extra.addRow("Соседний путь", window.unified_destination)
    travel = QPushButton("Отправиться")
    travel.clicked.connect(
        lambda: run(window, "travel", {"destination": window.unified_destination.currentData()})
    )
    extra.addRow(travel)
    explore = QPushButton("Исследовать окрестности")
    explore.clicked.connect(lambda: run(window, "explore", {}))
    extra.addRow(explore)
    form.addRow(window.catalog_actions)
    window.unified_search.textChanged.connect(lambda: refresh_learning(window))
    window.unified_learn_kind.currentIndexChanged.connect(lambda: refresh_learning(window))
    window.unified_recipe.currentIndexChanged.connect(lambda: refresh_outputs(window))
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
    expanded = state.get("content_revision") == 2
    window.catalog_actions.setVisible(expanded)
    if expanded:
        from rpg_vkr.domain import game_catalog as catalog

        for row in catalog.available("talent", lv, state["identity"]["class_id"]):
            if row["id"] not in state["talents"]:
                window.unified_talent.addItem(row["name"], row["id"])
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
        [
            (
                i["id"],
                i["name"]
                + f" ×{i.get('quantity', 1)} · {i['durability']}/{i.get('durability_cap', 20)}",
            )
            for i in state["items"]
            if i["owner"] == "hero"
            and (not i.get("source") or i["id"] in {t.id for t in s.interaction_state().carried()})
        ]
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
    if expanded:
        minute = state["minute"]
        world = state.get("living_world") or {}
        weather = {
            "clear": "ясно",
            "rain": "дождь",
            "drought": "засуха",
            "fog": "туман",
            "storm": "буря",
            "frost": "заморозки",
            "flood": "паводок",
            "thaw": "оттепель",
            "growth": "рост",
        }.get(world.get("weather"), "")
        public_news = "; ".join(
            v["name"] + ": " + v["news"] for v in state["known_factions"].values()
        )
        window.unified_world_info.setText(
            f"День {minute // 1440 + 1} · {minute // 60 % 24:02}:{minute % 60:02} · {weather}\n"
            + public_news
        )
        refill(
            window.unified_recipe,
            [
                (k, catalog.row(k)["name"])
                for k in state["known_recipes"]
                if catalog.row(k)["category"] != "repair"
            ],
        )
        refill(
            window.unified_ability,
            [(k, catalog.row(k)["name"]) for k in state["talents"] if k.startswith("talent_")],
        )
        refill(
            window.unified_material,
            [(r["id"], r["name"]) for r in catalog.available("material", lv) if r["process"] == 0],
        )
        place = s.interaction_state().place()
        refill(
            window.unified_destination,
            [
                (p.id, p.name)
                for p in s.interaction_state().places
                if p.parent == place.id or place.parent == p.id
            ],
        )
        refresh_learning(window)
        refresh_outputs(window)
    refill(
        window.unified_spell,
        [
            (
                k,
                {
                    "light": "Путеводный свет ·1MP",
                    "heal": "Исцеление ·3MP",
                    "bolt": "Магический разряд ·3MP",
                }.get(k, k)
                if not expanded
                else catalog.row(k)["name"] + f" · {catalog.row(k)['mp']}MP",
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


def target_args(window):
    result = {"target": window.unified_target.currentData()}
    if window._session.gameplay.get("content_revision") == 2:
        result.update(
            item=window.unified_items.currentData(),
            destination=window.unified_destination.currentData(),
        )
    return result


def refresh_learning(window):
    from rpg_vkr.domain import game_catalog as catalog
    from rpg_vkr.domain.unified import level

    if (
        not getattr(window._session, "is_unified", False)
        or window._session.gameplay.get("content_revision") != 2
    ):
        return
    state = window._session.gameplay
    kind = window.unified_learn_kind.currentData()
    known = state["spells" if kind == "spell" else "known_recipes"]
    query = window.unified_search.text().casefold().strip()
    window.unified_learn.clear()
    rows = catalog.available(kind, level(state["xp"]))
    if kind == "spell" and not state["mp_cap"]:
        rows = []
    for r in rows:
        if r["id"] not in known and (not query or query in r["name"].casefold()):
            window.unified_learn.addItem(r["name"], r["id"])


def refresh_outputs(window):
    from rpg_vkr.domain import game_catalog as catalog
    from rpg_vkr.domain.unified import level

    if (
        not getattr(window._session, "is_unified", False)
        or window._session.gameplay.get("content_revision") != 2
    ):
        return
    state = window._session.gameplay
    key = window.unified_recipe.currentData()
    window.unified_result.clear()
    if not key:
        return
    for id in catalog.row(key, "recipe")["outputs"]:
        row = catalog.row(id)
        if row["level"] <= level(state["xp"]):
            window.unified_result.addItem(row["name"], id)
