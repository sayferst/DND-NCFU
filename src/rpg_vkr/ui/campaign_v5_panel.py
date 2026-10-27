"""Connected controls for the completed catalog, world and opt-in retrieval."""

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
)

from rpg_vkr.domain.content_v5 import ABILITIES, ITEMS, RECIPES


def install(window, page):
    from rpg_vkr.ui.gameplay_panel import run

    form = page("Производство и мир")
    window.expanded_page = window.gameplay_tabs.widget(window.gameplay_tabs.count() - 1)

    def choice(label, values):
        box = QComboBox()
        for key, name in values.items():
            box.addItem(name, key)
        form.addRow(label, box)
        return box

    def action(title, command, args):
        button = QPushButton(title)
        button.clicked.connect(lambda: run(window, command, args()))
        form.addRow(button)
        return button

    window.profile_ability = action("Способность профиля (один раз в день)", "ability", dict)
    window.production_recipe = choice("Производство", {k: v["name"] for k, v in RECIPES.items()})
    window.production_quality = QSpinBox()
    window.production_quality.setRange(1, 3)
    form.addRow("Качество (требует ранга)", window.production_quality)
    action(
        "Изготовить по рецепту",
        "manufacture",
        lambda: {
            "recipe": window.production_recipe.currentData(),
            "quality": window.production_quality.value(),
        },
    )
    window.gather_kind = choice(
        "Материал местности", {k: ITEMS[k] for k in ("wood", "iron", "herb")}
    )
    window.gather_amount = QSpinBox()
    window.gather_amount.setRange(1, 10)
    form.addRow("Количество", window.gather_amount)
    action(
        "Добыть конечный запас",
        "gather",
        lambda: {
            "material": window.gather_kind.currentData(),
            "quantity": window.gather_amount.value(),
        },
    )
    window.consume_item = choice("Расходуемый предмет", {})
    action("Использовать предмет", "consume", lambda: {"item": window.consume_item.currentData()})
    window.supply_kind = choice(
        "Поставка фракции", {k: ITEMS[k] for k in ("wood", "iron", "herb", "meal")}
    )
    action(
        "Поставить материал выбранной фракции",
        "supply",
        lambda: {
            "faction": window.faction_choice.currentData(),
            "material": window.supply_kind.currentData(),
            "quantity": window.gather_amount.value(),
        },
    )
    window.other_faction = choice("Вторая сторона переговоров", {})
    action(
        "Провести переговоры (нужны оба представителя)",
        "diplomacy",
        lambda: {
            "faction": window.faction_choice.currentData(),
            "other": window.other_faction.currentData(),
        },
    )
    window.living_world_info = QPlainTextEdit()
    window.living_world_info.setReadOnly(True)
    window.living_world_info.setMaximumHeight(140)
    form.addRow(window.living_world_info)


def refresh(window):
    if not hasattr(window, "expanded_page"):
        return
    session, state = window._session, window._session.gameplay
    from rpg_vkr.learning.settings import load

    window._session._learning_flags = load()
    window._session._rag_mode = load()["mode"]
    enabled = state is not None and session.schema_version >= 28
    window.gameplay_tabs.setTabVisible(window.gameplay_tabs.indexOf(window.expanded_page), enabled)
    if not enabled:
        return
    from rpg_vkr.ui.gameplay_panel import refill

    refill(
        window.consume_item,
        [
            (i["id"], i["name"])
            for i in state["items"]
            if i["owner"] == "hero" and i["kind"] in {"potion", "meal", "crystal", "rune"}
        ],
    )
    refill(window.other_faction, [(k, v["name"]) for k, v in state["known_factions"].items()])
    window.profile_ability.setText(
        ABILITIES[state["identity"]["profile"]][0] + " (один раз в день)"
    )
    world = state.get("living_world")
    if world:
        calendar = world.get("calendar", {})
        current = world["nodes"].get(session.current_place_id, {})
        known = {id: r for id, r in world["observed"].items() if session.actor_is_here(id)}
        seasons = ("весна", "лето", "осень", "зима")
        timestamp = (
            f"Год {calendar.get('year', 1)}, месяц {calendar.get('month', 1)}, "
            f"день {calendar.get('day', 1)} · "
            f"{calendar.get('hour', 0):02}:{calendar.get('minute', 0):02} · "
            + seasons[calendar.get("season", 0)]
        )
        stocks = ", ".join(f"{ITEMS[k]}: {v}" for k, v in current.items())
        residents = "\n".join(
            value["name"]
            + ": "
            + ("ищет еду" if value["goal"] == "seek_food" else "занимается своими делами")
            + f"; местных наблюдений: {len(value['reports'])}"
            for value in known.values()
        )
        window.living_world_info.setPlainText(
            timestamp
            + "\nЗапасы места: "
            + stocks
            + "\nЖители рядом:\n"
            + (residents or "Сейчас никого не видно.")
        )
    else:
        window.living_world_info.setPlainText("Сведения о мире обновятся после первого действия.")


def migrate(window):
    from rpg_vkr.storage.migration import create, write_copy

    try:
        candidate = create(window._session)
        detail = (
            "Будет создана отдельная копия. "
            f"HP: {window._session.world.hp} → {candidate.world.hp}; "
            f"монеты: {window._session.world.gold} → {candidate.world.gold}. "
            "История, навыки, вещи и порядок будущих бросков сохраняются; "
            "исходник и резервная копия остаются. Перейти в новую копию?"
        )
        if not window._confirm(detail):
            return
        path, _ = QFileDialog.getSaveFileName(
            window,
            "Новый файл копии",
            str(window._saves.directory / "campaign-copy.json"),
            "JSON (*.json)",
        )
        if not path:
            return
        copied, report = write_copy(window._session, Path(path))
        window._session = copied
        window._current_slot = None
        window._dirty = False
        window._refresh_character()
        window._render_journal()
        window._rebuild_history()
        QMessageBox.information(
            window,
            "Копия создана",
            f"{path}\nРядом находятся original.json и migration.json. "
            "Сохраните продолжение в свободную ячейку.",
        )
    except (OSError, ValueError, TypeError) as error:
        QMessageBox.information(window, "Копия не создана", str(error))
