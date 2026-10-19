"""World genesis, notebook, selective durable recall and generic commerce."""

import hashlib
import json
import sqlite3
from contextlib import closing
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest

from rpg_vkr.application import Session
from rpg_vkr.domain.adventure import build_world, offline_world
from rpg_vkr.domain.character import Character
from rpg_vkr.domain.interactions import Step, WorldPlan
from rpg_vkr.storage.campaigns import CampaignRepository
from rpg_vkr.storage.catalog import CatalogIndex
from rpg_vkr.storage.slots import SaveSlots


def world_value():
    return {
        "title": "Карта переправы",
        "opening": (
            "Ветер шевелит ленты на мачте. Рен раскладывает дорожные припасы "
            "у причала. «Нужен свет в дорогу?»"
        ),
        "private_plot": (
            "Гильдия скрывает переправу, связанную с пропавшим учителем "
            "героя. Секретный знак: янтарная птица."
        ),
        "hooks": ["Выяснить происхождение карты", "Найти пропавшего учителя"],
        "start": "pier",
        "places": [
            {
                "id": "pier",
                "name": "Пристань туманов",
                "parent": "",
                "description": "Серый парус хлопает над лодкой.",
            },
            {
                "id": "path",
                "name": "Тропа у воды",
                "parent": "pier",
                "description": "Следы ведут к старому мосту.",
            },
        ],
        "definitions": [
            {
                "id": "seller_type",
                "name": "Рен",
                "kind": "actor",
                "categories": ["npcs"],
                "properties": {
                    "class": "merchant",
                    "hp_max": 8,
                    "goals": ["Сохранить караван"],
                    "appearance": "Серая косынка и кожаный передник",
                },
            },
            {
                "id": "rope_type",
                "name": "Верёвка",
                "kind": "item",
                "categories": ["miscellaneous"],
                "properties": {"mass_g": 300, "volume_ml": 600},
                "price_cp": 400,
            },
            {
                "id": "watcher_type",
                "name": "Морок",
                "kind": "actor",
                "categories": ["creatures", "bosses"],
                "properties": {"class": "beast", "hp_max": 14, "defence": 12},
            },
        ],
        "entities": [
            {
                "id": "seller",
                "definition_id": "seller_type",
                "parent_id": "pier",
                "state": {"hp": 8, "gold_cp": 1000, "secret": "Код переправы"},
            },
            {
                "id": "stock",
                "definition_id": "type_bandage",
                "parent_id": "seller",
                "owner_id": "seller",
                "quantity": 3,
            },
            {
                "id": "rope",
                "definition_id": "rope_type",
                "parent_id": "hero",
                "owner_id": "hero",
                "quantity": 2,
            },
            {
                "id": "watcher",
                "definition_id": "watcher_type",
                "parent_id": "path",
                "state": {"hp": 14},
            },
        ],
    }


def hero():
    return Session.create_hero(
        Character(name="Рада"),
        "scout",
        seed=5,
        description="Картограф ищет пропавшего учителя",
        world_brief="Речное фэнтези, интриги гильдий",
    )


def started():
    session = hero()
    session.start_world(build_world(world_value(), session, "synthetic-model"))
    return session


def note(text="Мята растёт у старого моста", **values):
    return {
        "subject": "world",
        "kind": "clue",
        "text": text,
        "importance": 5,
        "private": False,
    } | values


def test_generated_start_has_own_places_actors_plot_and_unchanged_rng():
    session = hero()
    rng = session.dice.checkpoint()
    session.start_world(build_world(world_value(), session, "synthetic-model"))
    assert session.current_place_id == "pier" and session.current_place_name == "Пристань туманов"
    assert not session.actor_is_here("guard") and session.actor_is_here("seller")
    assert session.dice.checkpoint() == rng and not session.turns
    assert "янтарная птица" in session.chronicle.seed.private_plot
    assert "янтарная птица" not in session.introduction
    assert Session.from_dict(session.to_dict()).to_dict() == session.to_dict()
    index = CatalogIndex(session)
    try:
        assert index.lookup("guard") is None
        assert index.lookup("watcher") is None
        assert index.lookup("seller")["entity"]["state"] == {}
    finally:
        index.close()


def test_offline_worlds_vary_without_consuming_game_rng():
    places = set()
    for i in range(18):
        session = hero()
        session.campaign = replace(session.campaign, world_id=str(UUID(int=i + 1)))
        rng = session.dice.checkpoint()
        seed = offline_world(session)
        places.add(seed.scene.place().name)
        assert session.dice.checkpoint() == rng
        assert session.campaign.raw_player_description in seed.private_plot
    assert len(places) >= 3


@pytest.mark.parametrize(
    "damage", ["cycle", "old_actor", "missing_type", "wrong_start", "unknown_field"]
)
def test_bad_world_is_rejected_without_changing_hero(damage):
    session = hero()
    before = session.to_dict(), session.dice.checkpoint()
    value = world_value()
    if damage == "cycle":
        value["places"][0]["parent"] = "path"
    elif damage == "old_actor":
        value["entities"][0]["id"] = "guard"
    elif damage == "missing_type":
        value["entities"][0]["definition_id"] = "does_not_exist"
    elif damage == "wrong_start":
        value["start"] = "nowhere"
    else:
        value["execute_sql"] = "not permitted"
    with pytest.raises((ValueError, KeyError)):
        build_world(value, session, "synthetic-model")
    assert (session.to_dict(), session.dice.checkpoint()) == before


def test_world_cannot_replace_a_progressed_session_or_another_hero():
    session, other = hero(), hero()
    seed = build_world(world_value(), other, "synthetic-model")
    with pytest.raises(ValueError):
        session.start_world(seed)
    session.submit("бросить кубик")
    with pytest.raises(ValueError):
        session.start_world(build_world(world_value(), session, "synthetic-model"))


def test_diary_edit_pin_delete_retains_revisions_without_changing_world_or_rng():
    session = started()
    before = session.world, session.dice.checkpoint(), session.turns
    session.write_diary("Травы", "Мята у моста", pinned=True)
    id = session.chronicle.entries[0].id
    session.write_diary("Травы у моста", "Со слов Рена: мята у моста", id=id, pinned=True)
    assert len(session.chronicle.entries) == 1 and len(session.chronicle.diary) == 2
    session.write_diary("Травы у моста", "Со слов Рена: мята у моста", id=id, delete=True)
    assert not session.chronicle.entries and len(session.chronicle.diary) == 3
    assert (session.world, session.dice.checkpoint(), session.turns) == before
    assert Session.from_dict(session.to_dict()).to_dict() == session.to_dict()


def test_memory_distinguishes_rumour_private_plan_and_stable_appearance(tmp_path):
    session = started()
    session.remember(
        [note("Мост охраняется", kind="rumour"), note("Код переправы", private=True)],
        "synthetic-model",
    )
    session.remember(
        [note("Серая косынка и кожаный передник", subject="seller", kind="appearance")],
        "synthetic-model",
    )
    with pytest.raises(ValueError):
        session.remember(
            [note("Красная косынка", subject="seller", kind="appearance")], "synthetic-model"
        )
    db = CampaignRepository(tmp_path / "memory.sqlite3")
    public = db.recall(session, "мост")
    assert any(n["kind"] == "rumour" for n in public["facts"])
    assert "Код переправы" not in json.dumps(public, ensure_ascii=False)
    assert "янтарная птица" not in json.dumps(public, ensure_ascii=False)
    private = db.recall(session, "мост", private=True)
    assert "янтарная птица" in private["private_plot"]


def test_important_early_memory_and_pinned_diary_survive_long_unrelated_history(tmp_path):
    session = started()
    session.remember([note()], "synthetic-model")
    session.write_diary("Травы", "Мята у моста, сведения от Рена", pinned=True)
    for _ in range(100):
        session.submit("состояние")
    db = CampaignRepository(tmp_path / "memory.sqlite3")
    result = db.recall(session, "что важно", budget=5000)
    assert any("Мята" in n["text"] for n in result["facts"])
    assert result["hero_notes"][0]["title"] == "Травы"
    assert len(json.dumps(result, ensure_ascii=False)) <= 5000
    assert db.load(db.identity(session)).to_dict() == session.to_dict()


def test_durable_store_isolates_campaigns_and_rewind_hides_future_but_keeps_archive(tmp_path):
    session = started()
    db = CampaignRepository(tmp_path / "memory.sqlite3")
    old = deepcopy(session.to_dict())
    session.submit("бросить кубик")
    session.remember([note("Будущее событие")], "synthetic-model")
    db.sync(session)
    other = started()
    assert "Будущее событие" not in json.dumps(db.recall(other, "событие"), ensure_ascii=False)
    rewound = Session.from_dict(old)
    assert "Будущее событие" not in json.dumps(db.recall(rewound, "событие"), ensure_ascii=False)
    with closing(sqlite3.connect(db.path)) as sql:
        assert (
            sql.execute(
                "SELECT count(*) FROM events WHERE campaign=?", (db.identity(session),)
            ).fetchone()[0]
            == 1
        )
        assert (
            sql.execute(
                "SELECT count(*) FROM current_events WHERE campaign=?", (db.identity(session),)
            ).fetchone()[0]
            == 0
        )


def test_foreign_database_is_not_replaced(tmp_path):
    path = tmp_path / "other.sqlite3"
    with closing(sqlite3.connect(path)) as sql, sql:
        sql.execute("CREATE TABLE important(value)")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="другая база"):
        CampaignRepository(path)
    assert path.read_bytes() == before


def test_generic_trade_conserves_money_goods_and_replays_without_rng():
    session = started()
    rng = session.dice.checkpoint()
    gold = session.world.gold
    session.submit_trade("покупаю бинты", "seller", "stock", "buy", 2)
    assert session.world.gold == gold - 6
    seller = next(e for e in session.catalog.entities if e.id == "seller")
    assert seller.state["gold_cp"] == 1600
    assert (
        sum(t.quantity for t in session.interactive_world.carried() if t.resource == "bandages")
        == session.world.bandages
    )
    session.submit_trade("продаю верёвку", "seller", "rope", "sell", 1)
    assert session.world.gold == gold - 4
    assert session.dice.checkpoint() == rng
    assert Session.from_dict(session.to_dict()).to_dict() == session.to_dict()


@pytest.mark.parametrize("damage", ["quantity", "price", "remote", "no_money"])
def test_invalid_trade_does_not_change_anything(damage):
    session = started()
    if damage == "remote":
        session.submit_interaction("иду по тропе", WorldPlan((Step("move", "path"),)))
    if damage == "no_money":
        session.submit_interaction(
            "выбрасываю монеты", WorldPlan((Step("drop", "legacy_gold", 0),))
        )
    before = session.to_dict(), session.dice.checkpoint()
    quantity = 10 if damage == "quantity" else 1
    item = "rope" if damage == "price" else "stock"
    with pytest.raises(ValueError):
        session.submit_trade("покупаю", "seller", item, "buy", quantity)
    assert (session.to_dict(), session.dice.checkpoint()) == before


def test_existing_v20_fixture_migrates_without_rewriting_and_new_world_saves_roundtrip(tmp_path):
    fixtures = Path(__file__).parent / "fixtures"
    raw = (fixtures / "save-v20.json").read_bytes()
    source = json.loads((fixtures / "save-v20.source.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(raw).hexdigest() == source["sha256"]
    slots = SaveSlots(tmp_path)
    (tmp_path / "slot-1.json").write_bytes(raw)
    old = slots.load(1)
    assert not old.generated_world
    slots.save(2, old)
    assert slots.load(2).to_dict() == old.to_dict()
    session = started()
    session.write_diary("Карта", "Ищу переправу", pinned=True)
    slots.save(3, session)
    assert slots.load(3).to_dict() == session.to_dict()
    assert (tmp_path / "slot-1.json").read_bytes() == raw
