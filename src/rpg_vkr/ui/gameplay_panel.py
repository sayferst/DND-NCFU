"""Playable v3 controls call Session transactions; widgets never calculate outcomes."""

import uuid

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QWidget,
)

from rpg_vkr.domain.character import ABILITY_NAMES
from rpg_vkr.domain.d20_combat import armour_class
from rpg_vkr.domain.gameplay import (
    ITEM_NAMES,
    PROFILES,
    RECIPES,
    SPECIES,
    SPELLS,
    available,
    hero_combatant,
)
from rpg_vkr.domain.gameplay_v2 import TALENTS


def install(window, layout):
    group = QGroupBox("Правила приключения · v3")
    form = QFormLayout(group)
    window.gameplay_group = group
    window.gameplay_status = QLabel()
    window.gameplay_status.setWordWrap(True)
    form.addRow(window.gameplay_status)
    tabs = QTabWidget()
    window.gameplay_tabs = tabs
    form.addRow(tabs)
    window.gameplay_info = QPlainTextEdit()
    window.gameplay_info.setReadOnly(True)
    window.gameplay_info.setMaximumHeight(180)
    window.gameplay_info.setAccessibleName("Состояние новых игровых правил")
    form.addRow(window.gameplay_info)

    def page(title):
        widget = QWidget()
        tab = QFormLayout(widget)
        tabs.addTab(widget, title)
        return tab

    def choice(tab, title, values=None):
        box = QComboBox()
        for key, name in (values or {}).items():
            box.addItem(name, key)
        tab.addRow(title, box)
        return box

    def button(tab, title, command, arguments):
        value = QPushButton(title)
        value.clicked.connect(lambda: run(window, command, arguments()))
        tab.addRow(value)
        return value

    tab = page("Экипировка")
    window.gear_choice = choice(tab, "Ваши предметы")
    window.world_gear_choice = choice(tab, "Предмет из инвентаря мира")
    window.adopt_world_button = button(
        tab,
        "Подключить физический предмет к снаряжению",
        "adopt",
        lambda: {"item": window.world_gear_choice.currentData()},
    )
    button(
        tab, "Экипировать выбранное", "equip", lambda: {"item": window.gear_choice.currentData()}
    )
    window.slot_choice = choice(tab, "Снять", {"shield": "Щит", "armour": "Доспех"})
    button(tab, "Снять выбранное", "unequip", lambda: {"slot": window.slot_choice.currentData()})
    tab = page("Бой")
    window.encounter_controls = QWidget()
    team_form = QFormLayout(window.encounter_controls)
    window.group_enemies, window.group_allies = QListWidget(), QListWidget()
    for box in (window.group_enemies, window.group_allies):
        box.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        box.setMaximumHeight(90)
    team_form.addRow("Противники рядом", window.group_enemies)
    team_form.addRow("Согласившиеся союзники", window.group_allies)
    window.encounter_start = button(
        team_form,
        "Начать бой выбранных участников",
        "encounter",
        lambda: {
            "enemies": [
                i.data(Qt.ItemDataRole.UserRole) for i in window.group_enemies.selectedItems()
            ],
            "allies": [
                i.data(Qt.ItemDataRole.UserRole) for i in window.group_allies.selectedItems()
            ],
        },
    )
    window.battle_info = QLabel()
    window.battle_info.setWordWrap(True)
    team_form.addRow(window.battle_info)
    window.recover_st = button(team_form, "Перевести дух: до 3 ST, один ход", "recover", dict)
    tab.addRow(window.encounter_controls)
    window.gameplay_target = choice(tab, "Цель рядом")
    button(
        tab,
        "Атаковать · нелетально",
        "attack",
        lambda: {"target": window.gameplay_target.currentData(), "lethal": 0},
    )
    button(tab, "Уклониться", "dodge", dict)
    button(tab, "Безопасно отступить", "retreat", dict)
    button(tab, "Использовать бинт", "bandage", dict)
    window.distance_choice = QSpinBox()
    window.distance_choice.setRange(1, 30)
    window.distance_choice.setSuffix(" м")
    tab.addRow("Новая дистанция (до 6 м за ход)", window.distance_choice)
    button(tab, "Переместиться", "move", lambda: {"distance": window.distance_choice.value()})
    tab = page("Магия и развитие")
    window.spell_choice = choice(
        tab, "Заклинание", {k: f"{v[0]} · круг {v[1]} · {v[2]} MP" for k, v in SPELLS.items()}
    )
    button(
        tab,
        "Изучить (теория магии ≥ круга)",
        "learn",
        lambda: {"spell": window.spell_choice.currentData()},
    )
    window.spell_target = choice(tab, "Цель заклинания", {"hero": "Сам герой"})
    button(
        tab,
        "Применить заклинание",
        "cast",
        lambda: {
            "spell": window.spell_choice.currentData(),
            "target": window.spell_target.currentData(),
        },
    )
    window.talent_choice = choice(tab, "Талант", TALENTS)
    button(
        tab,
        "Получить за награду уровня",
        "talent",
        lambda: {"talent": window.talent_choice.currentData()},
    )
    window.attribute_choice = choice(tab, "Характеристика", ABILITY_NAMES)
    button(
        tab,
        "Повысить за награду уровня",
        "attribute",
        lambda: {"ability": window.attribute_choice.currentData()},
    )
    tab = page("Мастерская и рынок")
    window.material_choice = choice(tab, "Материал из инвентаря мира")
    button(
        tab,
        "Подготовить материал для мастерской",
        "prepare",
        lambda: {"item": window.material_choice.currentData()},
    )
    window.recipe_choice = choice(tab, "Рецепт", {k: ITEM_NAMES[k] for k in RECIPES})
    button(
        tab,
        "Изготовить на полевом верстаке",
        "craft",
        lambda: {"recipe": window.recipe_choice.currentData()},
    )
    window.repair_choice = choice(tab, "Предмет")
    button(
        tab,
        "Починить (железо, 15 минут)",
        "repair",
        lambda: {"item": window.repair_choice.currentData()},
    )
    window.merchant_choice = choice(tab, "Торговец рядом")
    window.market_choice = choice(tab, "Товар")
    button(
        tab,
        "Купить",
        "buy",
        lambda: {
            "merchant": window.merchant_choice.currentData(),
            "item": window.market_choice.currentData(),
        },
    )
    button(
        tab,
        "Продать свой выбранный предмет",
        "sell",
        lambda: {
            "merchant": window.merchant_choice.currentData(),
            "item": window.repair_choice.currentData(),
        },
    )
    window.merchant_choice.currentIndexChanged.connect(lambda: refresh_market(window))
    tab = page("Время и отношения")
    window.wait_minutes = QSpinBox()
    window.wait_minutes.setRange(1, 10080)
    window.wait_minutes.setValue(60)
    tab.addRow("Минуты", window.wait_minutes)
    button(tab, "Подождать", "wait", lambda: {"minutes": window.wait_minutes.value()})
    button(tab, "Отдых 8 часов", "rest", dict)
    window.news_choice = choice(tab, "Подтверждённая победа")
    button(
        tab,
        "Рассказать выбранному собеседнику из списка боя",
        "tell",
        lambda: {
            "target": window.gameplay_target.currentData(),
            "event": window.news_choice.currentData(),
        },
    )
    tab = page("Фракции")
    window.faction_tab = tabs.widget(tabs.count() - 1)
    window.faction_choice = choice(tab, "Известное объединение")
    window.faction_amount = QSpinBox()
    window.faction_amount.setRange(1, 1_000_000)
    window.faction_amount.setValue(100)
    tab.addRow("Взнос, медных", window.faction_amount)
    button(
        tab,
        "Передать взнос представителю рядом",
        "donate",
        lambda: {
            "faction": window.faction_choice.currentData(),
            "amount_cp": window.faction_amount.value(),
        },
    )
    window.faction_info = QPlainTextEdit()
    window.faction_info.setReadOnly(True)
    window.faction_info.setMaximumHeight(180)
    tab.addRow(window.faction_info)
    from rpg_vkr.ui.campaign_v5_panel import install as install_expanded

    install_expanded(window, page)
    layout.addWidget(group)


def refill(box, values):
    selected = box.currentData()
    box.blockSignals(True)
    box.clear()
    for key, title in values:
        box.addItem(title, key)
    box.setCurrentIndex(max(0, box.findData(selected)))
    box.blockSignals(False)


def refresh(window):
    if not hasattr(window, "gameplay_group"):
        return
    session = window._session
    state = session.gameplay
    window.gameplay_group.setVisible(state is not None)
    if state is None:
        return
    window.gameplay_group.setEnabled(
        session.world.hp > 0 and not getattr(getattr(window, "ollama", None), "busy", False)
    )
    window.gameplay_tabs.setTabVisible(
        window.gameplay_tabs.indexOf(window.faction_tab), session.schema_version >= 26
    )
    if session.schema_version >= 26:
        known = state["known_factions"]
        refill(window.faction_choice, [(k, f["name"]) for k, f in known.items()])
        window.faction_info.setPlainText(
            "\n\n".join(
                f"{f['name']} · репутация {f['reputation']}\n{f['news']}\n"
                f"Последние сведения: день {f['last_seen_minute'] // 1440 + 1}."
                for f in known.values()
            )
            or "Объединения пока не известны. Сведения появляются при встрече с представителем."
        )
    from rpg_vkr.ui.campaign_v5_panel import refresh as refresh_expanded

    refresh_expanded(window)
    spells = SPELLS
    if session.schema_version >= 28:
        from rpg_vkr.domain.content_v5 import spell_rows

        spells = spell_rows()
    refill(
        window.spell_choice, [(k, f"{v[0]} · круг {v[1]} · {v[2]} MP") for k, v in spells.items()]
    )
    progress = session.d20_progress
    from rpg_vkr.domain.gameplay import TALENTS as LEGACY_TALENTS

    refill(
        window.talent_choice,
        list((TALENTS if session.schema_version >= 25 else LEGACY_TALENTS).items()),
    )
    hero = hero_combatant(state, session.world, session.character, progress)
    ac = armour_class(hero.dexterity, hero.armour, hero.shield)
    day, minute = divmod(state["minute"], 1440)
    window.gameplay_status.setText(
        f"{SPECIES[state['identity']['species']]} · {PROFILES[state['identity']['profile']]} · "
        f"HP {session.world.hp}/{session.world.max_hp} · AC {ac} · "
        f"MP {state['mp']}/{state['mp_cap']}\n"
        f"День {day + 1}, {minute // 60:02d}:{minute % 60:02d} · "
        f"{session.world.gold * 100 + state['copper']} медных · "
        f"Бой: {state['active'] or 'нет'} · раунд {state['round']} · {state['distance']} м"
    )
    if session.schema_version >= 25:
        window.gameplay_status.setText(
            window.gameplay_status.text() + f"\nST {state['st']}/{state['st_cap']}"
        )
    from rpg_vkr.domain.gameplay_v2 import name

    own = [
        (i["id"], f"{name(i)} · износ {i['durability']}/20 · {i['id']}")
        for i in state["items"]
        if i["owner"] == "hero"
    ]
    refill(window.gear_choice, own)
    window.adopt_world_button.setEnabled(session.schema_version >= 25)
    refill(
        window.world_gear_choice,
        [(t.id, t.name) for t in session.interaction_state().carried() if not t.resource],
    )
    refill(
        window.material_choice,
        [(t.id, t.name) for t in session.interaction_state().carried() if not t.resource],
    )
    refill(window.repair_choice, own)
    window.encounter_controls.setVisible(session.schema_version >= 27)
    if session.schema_version >= 27:
        battle = state["battle"]
        window.encounter_start.setEnabled(battle is None)
        window.recover_st.setEnabled(battle is not None)
        names = {r.id: r.name for r in session.interaction_state().actor_refs}
        names["hero"] = session.character.name
        window.battle_info.setText(
            "Раунд "
            + str(battle["round"])
            + ". Очередь: "
            + " → ".join(names.get(id, id) for id in battle["order"])
            + ". Сейчас ход героя."
            if battle
            else "Выберите несколько противников и доступных союзников."
        )
        for box, allies_only in [(window.group_enemies, False), (window.group_allies, True)]:
            selected = {i.data(Qt.ItemDataRole.UserRole) for i in box.selectedItems()}
            if battle:
                selected = {
                    id
                    for id, side in battle["sides"].items()
                    if (side == "party") == allies_only and id != "hero"
                }
            box.setEnabled(battle is None)
            box.clear()
            if session.catalog:
                for ref in session.interaction_state().actor_refs:
                    if not session.actor_is_here(ref.id):
                        continue
                    entity = next(e for e in session.catalog.entities if e.id == ref.id)
                    definition = next(
                        d for d in session.catalog.definitions if d.id == entity.definition_id
                    )
                    if (entity.state or {}).get("hp", definition.properties["hp_max"]) <= 0:
                        continue
                    ally = (
                        definition.properties.get("party_ally") is True
                        and (entity.state or {}).get("disposition") == "friendly"
                    )
                    if ally != allies_only:
                        continue
                    row = QListWidgetItem(ref.name)
                    row.setData(Qt.ItemDataRole.UserRole, ref.id)
                    box.addItem(row)
                    row.setSelected(ref.id in selected)
    targets, merchants, spell_targets = [], [], []
    for ref in session.interaction_state().actor_refs:
        if not session.actor_is_here(ref.id):
            continue
        battle = state.get("battle")
        entity = (
            next((e for e in session.catalog.entities if e.id == ref.id), None)
            if session.catalog
            else None
        )
        definition = (
            next(
                (d for d in session.catalog.definitions if entity and d.id == entity.definition_id),
                None,
            )
            if session.catalog
            else None
        )
        living = not entity or (entity.state or {}).get("hp", 1) > 0
        if living:
            spell_targets.append((ref.id, ref.name))
        if (
            session.schema_version < 27
            or living
            and (not battle or battle["sides"].get(ref.id) == "enemy")
        ):
            targets.append((ref.id, ref.name))
        if available(state, ref.id, definition) and (
            ref.id == "merchant"
            or definition
            and (
                definition.properties.get("can_trade")
                or definition.properties.get("class")
                in {"merchant", "trader", "shopkeeper", "торговец", "купец"}
            )
        ):
            merchants.append((ref.id, ref.name))
    refill(window.gameplay_target, targets)
    refill(
        window.spell_target,
        [("hero", "Сам герой"), *(spell_targets if session.schema_version >= 28 else targets)],
    )
    refill(window.merchant_choice, merchants)
    refill(window.news_choice, [(id, id) for id in state["victories"]])
    refresh_market(window)
    window.gameplay_info.setPlainText(
        "Изучено: "
        + (", ".join(spells[k][0] for k in state["spells"]) or "нет")
        + "\nЭффекты: "
        + str(state["effects"])
        + "\nТаланты: "
        + (", ".join(TALENTS[k] for k in state["talents"]) or "нет")
        + f"\nНаграды: таланты {len(state['talents'])}/{progress.talent_rewards}, "
        f"характеристики {len(state['attributes'])}/{progress.attribute_rewards}."
        + (
            "\nРепутация местных свидетелей: " + str(state["factions"].get("local_witnesses", 0))
            if session.schema_version < 26
            else ""
        )
        + "\n"
        + (
            next(
                (t.text for t in reversed(session.turns) if t.gameplay),
                "Выберите действие. Отказ не расходует ресурс.",
            )
        )
    )


def refresh_market(window):
    state = window._session.gameplay
    if not state:
        return
    id = window.merchant_choice.currentData()
    from rpg_vkr.domain.gameplay import PRICES, SHOP_STOCK, stock_id

    names = ITEM_NAMES
    if window._session.schema_version >= 28:
        from rpg_vkr.domain.content_v5 import ITEMS, PRICES

        names = ITEMS

    values = [
        (i["id"], f"{names[i['kind']]} · базовая цена {PRICES[i['kind']]} медных")
        for i in state["items"]
        if i["owner"] == id
    ]
    if id and id not in state["stocked"]:
        values = [
            (stock_id(id, k), f"{ITEM_NAMES[k]} · базовая цена {PRICES[k]} медных")
            for k in SHOP_STOCK
        ]
    refill(window.market_choice, values)


def run(window, command, args):
    if window.ollama.busy:
        return
    if any(v is None for v in args.values()):
        QMessageBox.information(
            window, "Действие недоступно", "Сначала выберите доступный предмет или цель."
        )
        return
    if command == "encounter" and not window._confirm(
        "Начать бой с выбранными противниками? Участники действуют по инициативе; "
        "союзники и противники получают самостоятельные ходы."
    ):
        return
    spells = SPELLS
    if window._session.schema_version >= 28:
        from rpg_vkr.domain.content_v5 import spell_rows

        spells = spell_rows()
    if command == "attack" or command == "cast" and spells[args["spell"]][3] == "attack":
        id = args["target"]
        from rpg_vkr.domain.combat import ACTORS

        if id in ACTORS:
            neutral = window._session.combat.actor(id).disposition == "neutral"
        else:
            entity = (
                next((e for e in window._session.catalog.entities if e.id == id), None)
                if window._session.catalog
                else None
            )
            neutral = bool(
                entity and (entity.state or {}).get("disposition", "neutral") != "hostile"
            )
        if neutral and not window._confirm(
            "Напасть на нейтрального персонажа? Он станет враждебным."
        ):
            return
    if command == "adopt":
        session, index = window._session, len(window._session.turns)
        try:
            candidate = session.preview_gameplay(command, args)["state"]["items"][-1]
        except ValueError as error:
            QMessageBox.information(window, "Предмет не подключён", str(error))
            return
        from rpg_vkr.domain.d20_combat import WEAPONS
        from rpg_vkr.domain.gameplay_v2 import name

        detail = (
            WEAPONS[candidate["kind"]][0] if candidate["kind"] in WEAPONS else candidate["kind"]
        )
        if not window._confirm(
            f"Подключить {name(candidate)} к снаряжению? "
            f"Карточка: {detail}, прочность {candidate['durability']}/20. "
            "Одна исходная единица исчезнет из обычного инвентаря; "
            "имя, цена и происхождение сохранятся."
        ):
            return
        if window._session is not session or len(session.turns) != index:
            QMessageBox.information(window, "Состояние изменилось", "Проверьте предмет заново.")
            return
    try:
        turn = window._session.perform_gameplay(command, args, "ui_" + uuid.uuid4().hex)
    except ValueError as error:
        QMessageBox.information(window, "Действие не выполнено", str(error))
        return
    window.journal.append_turn(turn)
    window._dirty = True
    window._refresh_character()
    from rpg_vkr.ui.narrator_panel import after_action

    after_action(window, turn)
