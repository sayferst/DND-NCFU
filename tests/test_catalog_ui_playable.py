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
    assert dialog.create_session().schema_version == 31
    assert dialog.creation_steps.count() == 4
    dialog.close()


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
