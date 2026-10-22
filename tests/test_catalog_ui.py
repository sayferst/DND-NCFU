"""Real Qt/HTTP path for bounded catalog reads, generation and actor attempts."""

import json
import sqlite3
from contextlib import closing

from test_catalog import workshop
from test_local_narrator import wait_for
from test_routerai import configure, router_server

from rpg_vkr.application import Session
from rpg_vkr.domain.interactions import Step, WorldPlan
from rpg_vkr.domain.world import WorldState
from rpg_vkr.storage.catalog import CatalogIndex

LOOK = "осмотрюсь в открытой мастерской"
PROSE = "В мастерской пахнет древесной стружкой. Мира откладывает инструменты и смотрит на вас."


def creation():
    sample = Session(seed=5)
    definitions, entities = workshop(sample)
    return {
        "steps": [],
        "places": [],
        "check": "none",
        "queries": [],
        "catalog": {
            "definitions": [d.to_dict() for d in definitions],
            "entities": [e.to_dict() for e in entities],
            "reason": "Герой видит открытую мастерскую и её хозяйку.",
        },
    }


def enable(window, monkeypatch, url):
    configure(window, monkeypatch, url)
    window.world_agent.setChecked(True)
    window.director_mode.setChecked(True)


def send(window, qt_app, text):
    window.action_input.setText(text)
    window.send_button.click()
    wait_for(qt_app, lambda: not window.ollama.busy)


def test_master_creation_is_real_and_is_visible_in_catalog_and_working_sqlite(
    window, qt_app, monkeypatch
):
    window._session = Session(seed=5)
    with router_server(world_plans={LOOK: creation()}, writer_text=PROSE) as (url, records):
        enable(window, monkeypatch, url)
        send(window, qt_app, LOOK)
        assert window._session.catalog
        assert len(window._session.turns) == 1 and len(window._session.narrations) == 1
        window.open_section("Каталог мира")
        ids = [
            window.catalog_table.item(r, 0).text() for r in range(window.catalog_table.rowCount())
        ]
        assert "mira" in ids and "case_one" in ids
        path = window._saves.directory.parent / "world-catalog.sqlite3"
        with closing(sqlite3.connect(path)) as db:
            assert (
                db.execute("SELECT quantity FROM catalog_instances WHERE id='ingots'").fetchone()[0]
                == 2
            )
            assert db.execute("SELECT count(*) FROM catalog_events").fetchone()[0] == 1
        index = CatalogIndex(window._session)
        try:
            assert "gold_cp" not in index.lookup("mira")["entity"]["state"]
        finally:
            index.close()
        window.save_slot(1)
        expected = window._session.to_dict()
        window.load_slot(1)
        assert window._session.to_dict() == expected
        assert len([r for r in records if r["method"] == "POST"]) == 2


def test_catalog_query_is_batched_and_only_selected_records_are_sent(window, qt_app, monkeypatch):
    query = {"steps": [], "places": [], "check": "none", "queries": ["mat_copper", "type_basket"]}
    with router_server(world_plans={LOOK: [query, creation()]}, writer_text=PROSE) as (
        url,
        records,
    ):
        enable(window, monkeypatch, url)
        send(window, qt_app, LOOK)
        posts = [r for r in records if r["method"] == "POST"]
        assert len(posts) == 3 and window._session.catalog
        second = json.loads(posts[1]["body"]["messages"][1]["content"])
        results = second["state"]["catalog_query_results"]
        assert {r["definition"]["id"] for r in results} == {"mat_copper", "type_basket"}
        assert "mat_granite" not in json.dumps(results)


def test_repeated_catalog_queries_stop_without_mutation(window, qt_app, monkeypatch):
    query = {"steps": [], "places": [], "check": "none", "queries": ["mat_copper"]}
    before = window._session.to_dict(), window._session.dice.checkpoint()
    with router_server(world_plans={LOOK: query}) as (url, records):
        enable(window, monkeypatch, url)
        send(window, qt_app, LOOK)
        assert "исчерпал" in window.narrator_status.text()
        assert window.action_input.text() == LOOK
        assert (window._session.to_dict(), window._session.dice.checkpoint()) == before
        assert len([r for r in records if r["method"] == "POST"]) == 2


def test_create_then_take_keeps_one_player_message_and_correct_save_history(
    window, qt_app, monkeypatch
):
    text = "осмотрюсь в мастерской и возьму кофр"
    proposal = creation()
    proposal["steps"] = [{"op": "take", "target": "case_one", "quantity": 1, "destination": ""}]
    with router_server(world_plans={text: proposal}, writer_text=PROSE) as (url, _):
        enable(window, monkeypatch, url)
        send(window, qt_app, text)
        assert len(window._session.turns) == 2
        assert window._session.turns[1].origin == "system"
        assert window.journal.toPlainText().count(text) == 1
        assert any(t.id == "case_one" for t in window._session.interactive_world.carried())
        assert Session.from_dict(window._session.to_dict()).to_dict() == window._session.to_dict()


def test_registered_actor_attack_is_resolved_before_writer(window, qt_app, monkeypatch):
    window._session = Session(seed=5)
    workshop(window._session)
    monkeypatch.setattr(window, "_confirm", lambda _: True)
    text = "атакую Миру"
    proposal = {
        "steps": [],
        "places": [],
        "check": "none",
        "attempt": {
            "operation": "attack",
            "target_id": "mira",
            "lethal": False,
            "reason": "Нападение на Миру",
        },
    }
    with router_server(
        world_plans={text: proposal},
        writer_text="Мира отшатывается после удара. В мастерской становится тихо.",
    ) as (url, records):
        enable(window, monkeypatch, url)
        send(window, qt_app, text)
        target = next(e for e in window._session.catalog.entities if e.id == "mira")
        assert target.state["hp"] == 2
        assert window._session.dice.checkpoint()[1] == 1
        assert len(window._session.narrations) == 1
        assert len([r for r in records if r["method"] == "POST"]) == 2


def test_cancelled_actor_attempt_consumes_neither_die_nor_bandage(window, qt_app, monkeypatch):
    window._session = Session(seed=5)
    workshop(window._session)
    monkeypatch.setattr(window, "_confirm", lambda _: False)
    text = "хочу убить Миру"
    proposal = {
        "steps": [],
        "places": [],
        "check": "none",
        "attempt": {
            "operation": "attack",
            "target_id": "mira",
            "lethal": True,
            "reason": "Смертельное нападение",
        },
    }
    before = window._session.to_dict(), window._session.dice.checkpoint()
    with router_server(world_plans={text: proposal}) as (url, records):
        enable(window, monkeypatch, url)
        send(window, qt_app, text)
        assert (window._session.to_dict(), window._session.dice.checkpoint()) == before
        assert window.action_input.text() == text
        assert len([r for r in records if r["method"] == "POST"]) == 1


def test_resource_gift_uses_real_balance_and_working_sqlite(window, qt_app, monkeypatch):
    text = "отдаю жительнице один бинт"
    plan = {
        "steps": [
            {"op": "give", "target": "legacy_bandages", "quantity": 1, "destination": "villager"}
        ],
        "places": [],
        "check": "none",
    }
    window._session = Session(seed=5)
    with router_server(world_plans={text: plan}, writer_text="Жительница принимает бинт.") as (
        url,
        records,
    ):
        enable(window, monkeypatch, url)
        send(window, qt_app, text)
        assert window._session.world.bandages == 0
        item = next(t for t in window._session.interactive_world.things if t.resource == "bandages")
        assert item.holder == item.owner == "villager"
        path = window._saves.directory.parent / "world-catalog.sqlite3"
        with closing(sqlite3.connect(path)) as db:
            row = db.execute(
                "SELECT parent_id,quantity FROM catalog_instances WHERE id=?", (item.id,)
            ).fetchone()
            assert row == ("villager", 1)
        assert len([r for r in records if r["method"] == "POST"]) == 2
        assert window.journal.toPlainText().count(text) == 1
        window.save_slot(1)
        expected = window._session.to_dict()
        window.load_slot(1)
        assert window._session.to_dict() == expected


def test_cancelled_resource_plan_does_not_activate_or_spend(window, qt_app, monkeypatch):
    text = "пожертвую монеты жительнице"
    plan = {
        "steps": [
            {"op": "give", "target": "legacy_gold", "quantity": 2, "destination": "villager"}
        ],
        "places": [],
        "check": "none",
    }
    before = window._session.to_dict(), window._session.dice.checkpoint()
    monkeypatch.setattr(window, "_confirm", lambda _: False)
    with router_server(world_plans={text: plan}) as (url, records):
        enable(window, monkeypatch, url)
        send(window, qt_app, text)
        assert (window._session.to_dict(), window._session.dice.checkpoint()) == before
        assert window.action_input.text() == text
        assert len([r for r in records if r["method"] == "POST"]) == 1


def test_chat_purchase_consumes_same_coins_and_creates_real_bandage(window, qt_app, monkeypatch):
    text = "купить бинт"
    window._session = Session(
        seed=5, world=WorldState(location="market", market_known=True, trading=True, bandages=0)
    )
    window._session.submit_interaction(
        "выбрасываю монеты", WorldPlan((Step("drop", "legacy_gold", 2),))
    )
    with router_server(writer_text="Торговец передаёт вам бинт и принимает плату.") as (url, _):
        enable(window, monkeypatch, url)
        send(window, qt_app, text)
        assert window._session.world.gold == 5 and window._session.world.bandages == 1
        assert (
            sum(
                t.quantity
                for t in window._session.interactive_world.carried()
                if t.resource == "gold"
            )
            == 5
        )
        assert Session.from_dict(window._session.to_dict()).to_dict() == window._session.to_dict()
