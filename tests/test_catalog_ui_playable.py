"""Real widgets and mocked RouterAI transport execute the new Session rules."""

import json

import pytest
from test_catalog_campaign import started
from test_catalog_ui import enable, send
from test_routerai import router_server

from rpg_vkr.domain import game_catalog as catalog
from rpg_vkr.ui import unified_panel
from rpg_vkr.ui.copper_shop import CopperTradeDialog
from rpg_vkr.ui.creation_dialog import CreationDialog


def test_creation_launches_expanded_game_without_technical_options(qt_app):
    dialog = CreationDialog()
    session = dialog.create_session()
    assert session.schema_version == 31 and session.gameplay["catalog_revision"] == 3
    assert dialog.creation_steps.count() == 4
    dialog.close()


def test_revision_two_recipe_cost_tracks_the_selected_product(window):
    window._session = started("artisan", catalog_revision=2)
    unified_panel.refresh(window)
    window.unified_recipe.setCurrentIndex(window.unified_recipe.findData("recipe_production_0_0"))
    costs = []
    with catalog.using(2):
        recipe = catalog.row("recipe_production_0_0")
        for result in ("house_0_0", "gear_light_0_0"):
            window.unified_result.setCurrentIndex(window.unified_result.findData(result))
            text = window.unified_recipe_cost.text()
            for material, quantity in recipe["materials_by_output"][result].items():
                assert catalog.row(material)["name"] + f" ×{quantity}" in text
            costs.append(text)
    assert costs[0] != costs[1]
    assert catalog.ACTIVE_REVISION.get() == 1


def test_revision_two_repair_button_honours_selected_recipe_atomically(window):
    from PySide6.QtWidgets import QPushButton
    from test_catalog_campaign import act

    window._session = s = started("artisan", supplies=True, catalog_revision=2)
    act(s, "manufacture", recipe="recipe_production_0_0", result="house_0_0")
    unified_panel.refresh(window)
    window.unified_items.setCurrentIndex(window.unified_items.findData("start_1"))
    index = window.unified_recipe.findData("recipe_repair_1_0")
    assert index >= 0
    window.unified_recipe.setCurrentIndex(index)
    repair = next(b for b in window.findChildren(QPushButton) if b.text() == "Отремонтировать")
    before = s.to_dict(), s.dice.checkpoint()
    repair.click()
    assert "Несовместимая" in window.unified_log.toPlainText()
    assert (s.to_dict(), s.dice.checkpoint()) == before
    window.unified_recipe.setCurrentIndex(window.unified_recipe.findData("recipe_repair_0_0"))
    repair.click()
    assert len(s.turns) == 2


def test_catalog_controls_execute_and_filter_at_actual_level(window):
    window._session = started("mage")
    unified_panel.refresh(window)
    assert window.unified_spell.count() == 2 and window.unified_learn.count() > 3
    assert window.unified_destination.count() == 1
    assert all(
        catalog.row(window.unified_learn.itemData(i))["level"] <= 1
        for i in range(window.unified_learn.count())
    )
    unified_panel.run(window, "cast", {"spell": "light", "target": "hero"})
    assert "Применено" in window.unified_log.toPlainText()
    assert window._session.gameplay["mp"] == window._session.gameplay["mp_cap"] - 1
    shop = CopperTradeDialog(window, "seller")
    ids = [r[0] for r in shop.rows]
    assert len(ids) == len(set(ids))
    stock = next(i for i in window._session.gameplay["items"] if i["owner"] == "seller")
    shop.table.selectRow(ids.index(stock["id"]))
    assert shop.execute.isEnabled()
    shop.submit()
    assert len(window._session.turns) == 2
    shop.close()


def test_routerai_gameplay_proposal_commits_once_then_narrates(window, qt_app, monkeypatch):
    from rpg_vkr.application import Session

    window._session = started("mage")
    monkeypatch.setattr(window, "_confirm", lambda text: True)

    def reject_history_replay(*args, **kwargs):
        raise AssertionError("An AI action preview must not reload and replay committed history")

    monkeypatch.setattr(Session, "from_dict", reject_history_replay)
    text = "Зажигаю путеводный свет"
    proposal = {
        "steps": [],
        "places": [],
        "check": "none",
        "gameplay": {"command": "cast", "args": {"spell": "light", "target": "hero"}},
    }
    with router_server(
        world_plans={text: proposal}, writer_text="У ладони загорается мягкий свет."
    ) as (url, records):
        enable(window, monkeypatch, url)
        send(window, qt_app, text)
        assert len(window._session.turns) == 1
        assert window._session.gameplay["mp"] == window._session.gameplay["mp_cap"] - 1
        bodies = [r["body"] for r in records if r["method"] == "POST"]
        assert len(bodies) == 2
        assert "catalog_actions" in json.dumps(bodies[0])


@pytest.mark.parametrize(
    "bad",
    [
        {"command": "cast", "args": {"spell": "light", "xp": 99999}},
        {"command": "give_gold", "args": {}},
    ],
)
def test_ai_cannot_propose_direct_state_mutation(bad):
    from rpg_vkr.narrative.catalog_protocol import validate_proposal

    with pytest.raises(ValueError):
        validate_proposal(
            bad, {"steps": [], "places": [], "check": "none"}, {"catalog_actions": True}
        )
