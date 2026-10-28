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
    QSpinBox,
)

from rpg_vkr.domain.game_catalog import for_session
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
        return value

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
    window.unified_spell_label = QLabel("Заклинание")
    form.addRow(window.unified_spell_label, window.unified_spell)
    window.unified_cast_button = button(
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
    window.unified_recipe_cost = QLabel()
    window.unified_recipe_cost.setWordWrap(True)
    form.addRow(window.unified_recipe_cost)
    window.unified_result.currentIndexChanged.connect(lambda: refresh_cost(window))
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
    button("Отремонтировать", "repair", lambda: repair_args(window))
    button("Отдохнуть", "rest", dict)
    window.unified_flee = button(
        "Отступить", "flee", lambda: {"destination": window.unified_destination.currentData()}
    )
    window.unified_first_aid = button(
        "Оказать первую помощь",
        "first_aid",
        lambda: {
            "target": window.unified_target.currentData(),
            "item": window.unified_items.currentData(),
        },
    )
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
    window.unified_gather_quantity = QSpinBox()
    window.unified_gather_quantity.setRange(1, 20)
    extra.addRow("Количество", window.unified_gather_quantity)
    gather = QPushButton("Добыть ресурс")
    gather.clicked.connect(
        lambda: run(
            window,
            "gather",
            {
                "material": window.unified_material.currentData(),
                "quantity": window.unified_gather_quantity.value(),
            },
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
    from rpg_vkr.ui.contracts_panel import build as build_contracts

    build_contracts(window, extra)
    explore = QPushButton("Исследовать окрестности")
    explore.clicked.connect(lambda: run(window, "explore", {}))
    extra.addRow(explore)
    form.addRow(window.catalog_actions)
    window.unified_search.textChanged.connect(lambda: refresh_learning(window))
    window.unified_learn_kind.currentIndexChanged.connect(lambda: refresh_learning(window))
    window.unified_recipe.currentIndexChanged.connect(lambda: refresh_outputs(window))
    window.unified_group.hide()


@for_session
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
    window.unified_recipe_cost.setVisible(expanded)
    window.unified_flee.setVisible(state.get("catalog_revision") == 3)
    window.unified_flee.setEnabled(bool(state.get("battle")))
    window.unified_first_aid.setVisible(state.get("catalog_revision") == 3)
    from rpg_vkr.ui.contracts_panel import refresh as refresh_contracts

    refresh_contracts(window)
    has_magic = bool(state["spells"])
    for widget in (window.unified_spell, window.unified_spell_label, window.unified_cast_button):
        widget.setVisible(has_magic)
    if expanded and not state["mp_cap"]:
        window.unified_learn_kind.setCurrentIndex(window.unified_learn_kind.findData("recipe"))
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
        if state.get("catalog_revision") == 3:
            from rpg_vkr.ui.world_news import labels

            public_news = "\n".join(
                ([public_news] if public_news else [])
                + labels(world, s.interaction_state().current)
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
                if state.get("catalog_revision") in (2, 3) or catalog.row(k)["category"] != "repair"
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


@for_session
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
    from rpg_vkr.domain.catalog_search import ranked

    for r in ranked(rows, query, matching_only=True):
        if r["id"] not in known:
            window.unified_learn.addItem(r["name"], r["id"])


@for_session
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
    refresh_cost(window)


@for_session
def refresh_cost(window):
    from rpg_vkr.domain import game_catalog as catalog

    if not window._session.gameplay or window._session.gameplay.get("content_revision") != 2:
        return
    key, result = window.unified_recipe.currentData(), window.unified_result.currentData()
    if not key:
        window.unified_recipe_cost.clear()
        return
    recipe = catalog.row(key, "recipe")
    materials = recipe.get("materials_by_output", {}).get(result, recipe["ingredients"])
    text = "; ".join(catalog.row(id)["name"] + f" ×{n}" for id, n in materials.items())
    stations = {
        "forge": "горн",
        "alchemy": "алхимический стол",
        "workbench": "верстак",
        "tools": "инструменты",
    }
    window.unified_recipe_cost.setText(
        f"Расход: {text}. Рабочее место: {stations[recipe['station']]}; "
        f"время: {recipe['minutes']} мин. Неудача тоже расходует сырьё."
    )


@for_session
def repair_args(window):
    from rpg_vkr.domain import game_catalog as catalog

    args = {"item": window.unified_items.currentData()}
    key = window.unified_recipe.currentData()
    if window._session.gameplay.get("content_revision") == 2 and key:
        if catalog.row(key, "recipe")["category"] == "repair":
            args["recipe"] = key
    return args
