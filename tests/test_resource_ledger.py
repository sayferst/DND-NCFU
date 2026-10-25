"""Conservation across generic transfers, legacy rules, containers and replay."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from test_catalog import workshop

from rpg_vkr.application import Session
from rpg_vkr.domain.catalog import Definition, Entity
from rpg_vkr.domain.interactions import Step, WorldPlan
from rpg_vkr.domain.resources import balances, physical
from rpg_vkr.domain.world import WorldState
from rpg_vkr.storage.catalog import CatalogIndex
from rpg_vkr.storage.knowledge import restore_session
from rpg_vkr.storage.slots import SaveSlots


def act(session, op, target, quantity=0, destination=""):
    words = {"drop": "выбрасываю", "take": "беру", "put": "кладу", "give": "отдаю"}
    return session.submit_interaction(
        words[op] + " предмет", WorldPlan((Step(op, target, quantity, destination),))
    )


def check(session):
    assert physical(session.interactive_world)
    assert balances(session.interactive_world) == {
        "gold": session.world.gold,
        "bandages": session.world.bandages,
    }
    restored = Session.from_dict(session.to_dict())
    assert restored.to_dict() == session.to_dict()
    assert restored.dice.checkpoint() == session.dice.checkpoint()


@pytest.mark.parametrize("field", ["gold", "bandages"])
def test_partial_drop_and_take_conserve_resources_and_identity(field):
    session = Session(seed=5, world=WorldState(gold=10, bandages=4))
    start = getattr(session.world, field)
    act(session, "drop", "legacy_" + field, 2)
    assert getattr(session.world, field) == start - 2
    dropped = next(t for t in session.interactive_world.things if t.id == "split_1_0")
    assert dropped.resource == field and dropped.quantity == 2 and dropped.holder == "gate"
    check(session)
    act(session, "take", dropped.id)
    assert getattr(session.world, field) == start
    assert sum(t.quantity for t in session.interactive_world.things if t.resource == field) == start
    assert any(t.id == dropped.id for t in session.interactive_world.carried())
    check(session)


def test_bandages_follow_container_and_only_carried_supplies_can_heal():
    session = Session(seed=5, world=WorldState(hp=4, bandages=3))
    workshop(session)
    act(session, "take", "case_one")
    act(session, "put", "legacy_bandages", destination="case_one")
    act(session, "drop", "case_one")
    assert session.world.bandages == 0
    check(session)
    session.submit("использовать бинт")
    assert session.world.hp == 4 and session.world.bandages == 0
    act(session, "take", "case_one")
    assert session.world.bandages == 3
    session.submit("использовать бинт")
    assert session.world.hp == 8 and session.world.bandages == 2
    assert (
        next(t for t in session.interactive_world.things if t.resource == "bandages").holder
        == "case_one"
    )
    check(session)


def test_buy_and_sell_change_the_same_real_stacks_and_leave_dropped_coins():
    world = WorldState(location="market", market_known=True, trading=True, bandages=0)
    session = Session(seed=5, world=world)
    act(session, "drop", "legacy_gold", 2)
    session.submit("купить бинт")
    assert (session.world.gold, session.world.bandages) == (5, 1)
    assert (session.world.shop_stock, session.world.shop_gold) == (2, 23)
    assert any(t.resource == "bandages" for t in session.interactive_world.carried())
    check(session)
    session.submit("продать бинт")
    assert (session.world.gold, session.world.bandages) == (6, 0)
    assert not any(t.resource == "bandages" for t in session.interactive_world.carried())
    assert next(t for t in session.interactive_world.things if t.id == "split_1_0").quantity == 2
    assert session.world.gold + session.world.shop_gold + 2 == 30
    check(session)


def test_reward_creates_a_new_stack_when_original_purse_was_left_elsewhere():
    session = Session(seed=5)
    act(session, "drop", "legacy_gold")
    session.submit("идти на дорогу")
    result = session.submit("исследовать дорогу")
    assert result.check.succeeded and session.world.gold == 2
    assert (
        next(t for t in session.interactive_world.things if t.id == "legacy_gold").holder == "gate"
    )
    carried = [t for t in session.interactive_world.carried() if t.resource == "gold"]
    assert len(carried) == 1 and carried[0].id == "resource_gold_3" and carried[0].quantity == 2
    check(session)


@pytest.mark.parametrize("field", ["gold", "bandages"])
def test_gifts_are_real_items_with_new_owner_and_no_extra_hero_balance(field):
    session = Session(seed=5, world=WorldState(bandages=4))
    act(session, "give", "legacy_" + field, 2, "villager")
    gift = next(t for t in session.interactive_world.things if t.id == "split_1_0")
    assert gift.holder == gift.owner == "villager" and gift.quantity == 2
    assert getattr(session.world, field) == (8 if field == "gold" else 2)
    assert session.combat.actor("villager").disposition == "neutral"
    check(session)


def test_generated_standard_bandage_can_be_consumed_without_a_catalog_ghost():
    session = Session(seed=5, world=WorldState(hp=4, bandages=0))
    item = Entity("clean_bandage", "type_bandage", "gate")
    session.register_catalog("осмотрюсь", (), (item,), "Видна перевязочная ткань", "test-model")
    act(session, "take", item.id)
    assert session.world.bandages == 1
    session.submit("использовать бинт")
    assert session.world.bandages == 0 and session.world.hp == 8
    index = CatalogIndex(session)
    try:
        assert index.lookup(item.id) is None
        assert not any(t.id == item.id for t in session.interactive_world.things)
    finally:
        index.close()
    check(session)


def test_same_name_does_not_turn_an_arbitrary_object_into_a_healing_resource():
    session = Session(seed=5, world=WorldState(hp=4, bandages=0))
    definition = Definition("painted_bandage", "Бинт", "item", ("miscellaneous",), {})
    session.register_catalog(
        "осмотрюсь",
        (definition,),
        (Entity("prop", definition.id, "gate"),),
        "Театральный реквизит",
        "test-model",
    )
    act(session, "take", "prop")
    session.submit("использовать бинт")
    assert session.world.bandages == 0 and session.world.hp == 4


def test_locked_container_blocks_consumption_and_rolls_back_all_changes():
    session = Session(seed=5, world=WorldState(hp=4, bandages=0))
    workshop(session, locked=True)
    session.register_catalog(
        "осмотрюсь",
        (),
        (Entity("sealed_bandage", "type_bandage", "gate"),),
        "Виден запечатанный набор",
        "test-model",
    )
    # Registering into an existing container is deliberately unavailable. Place the
    # resource in a new locked container through the supported registration protocol.
    definition = Definition(
        "locked_box",
        "Опечатанная сумка",
        "item",
        ("miscellaneous",),
        {"container": True, "locked": True},
    )
    session.register_catalog(
        "осмотрюсь",
        (definition,),
        (
            Entity("sealed_box", definition.id, "gate"),
            Entity("inside_bandage", "type_bandage", "sealed_box"),
        ),
        "Видна опечатанная сумка",
        "test-model",
    )
    act(session, "take", "sealed_box")
    assert session.world.bandages == 1
    before, rng = session.to_dict(), session.dice.checkpoint()
    with pytest.raises(ValueError, match="доступного ресурса"):
        session.submit("использовать бинт")
    assert session.to_dict() == before and session.dice.checkpoint() == rng
    check(session)


def test_npc_bandaging_consumes_the_same_physical_supply():
    session = Session(seed=5, world=WorldState(bandages=3))
    workshop(session)
    act(session, "drop", "legacy_gold", 1)
    session.submit_actor_attempt("атакую Миру", "mira", "attack", False, "Удар", "test-model")
    session.submit_actor_attempt(
        "перевязываю Миру", "mira", "heal", False, "Перевязка", "test-model"
    )
    assert session.world.bandages == 2
    assert (
        sum(t.quantity for t in session.interactive_world.carried() if t.resource == "bandages")
        == 2
    )
    check(session)


@pytest.mark.parametrize("quantity", [0, 1, 3])
def test_resource_container_capacity_uses_real_mass_and_volume(quantity):
    session = Session(seed=5, world=WorldState(bandages=3))
    workshop(session)
    # Clear the nearby ingots from this comparison: they remain where generated.
    act(session, "take", "case_one")
    act(session, "put", "legacy_bandages", quantity, "case_one")
    assert session.world.bandages == 3
    check(session)


def test_oversized_resource_put_is_rejected_without_migrating_or_changing_rng():
    session = Session(seed=5, world=WorldState(bandages=11))
    workshop(session)
    before, rng = session.to_dict(), session.dice.checkpoint()
    with pytest.raises(ValueError, match="Вместимость"):
        act(session, "put", "legacy_bandages", destination="case_one")
    assert session.to_dict() == before and session.dice.checkpoint() == rng


def test_invalid_chain_does_not_partly_activate_or_spend_resources():
    session = Session(seed=5)
    before = session.to_dict(), session.dice.checkpoint()
    with pytest.raises(ValueError):
        session.submit_interaction(
            "выбрасываю монеты и иду вдаль",
            WorldPlan((Step("drop", "legacy_gold", 2), Step("move", "nowhere"))),
        )
    assert (session.to_dict(), session.dice.checkpoint()) == before


@pytest.mark.parametrize(
    "text", ["купить бинт?", "не использовать бинт", "говорю: «продать бинт»", "если купить бинт"]
)
def test_questions_negations_and_reported_commands_are_not_local_resource_actions(text):
    from rpg_vkr.narrative.actions import action_plan

    session = Session(seed=5)
    assert action_plan(session, text, allow_interactions=True) is None


def test_loose_resource_is_spent_before_locked_supply_and_failure_preserves_rng():
    session = Session(seed=5, world=WorldState(hp=1, bandages=1))
    definition = Definition(
        "sealed",
        "Опечатанный футляр",
        "item",
        ("miscellaneous",),
        {"container": True, "locked": True},
    )
    session.register_catalog(
        "осмотрюсь",
        (definition,),
        (
            Entity("sealed_case", definition.id, "gate"),
            Entity("sealed_supply", "type_bandage", "sealed_case", quantity=2),
        ),
        "Виден закрытый футляр",
        "test-model",
    )
    act(session, "take", "sealed_case")
    assert session.world.bandages == 3
    session.submit("использовать бинт")
    assert session.world.hp == 5 and session.world.bandages == 2
    before = session.to_dict(), session.dice.checkpoint()
    with pytest.raises(ValueError, match="доступного ресурса"):
        session.submit("использовать бинт")
    assert (session.to_dict(), session.dice.checkpoint()) == before
    check(session)


@pytest.mark.parametrize("damage", ["world", "quantity", "resource", "downgrade"])
def test_tampered_physical_resource_state_is_rejected(damage):
    session = Session(seed=5)
    act(session, "drop", "legacy_gold", 2)
    data = deepcopy(session.to_dict())
    if damage == "world":
        data["world"]["gold"] += 1
    elif damage == "quantity":
        data["interactive_world"]["things"][-1]["quantity"] += 1
    elif damage == "resource":
        data["interactive_world"]["things"][-1]["resource"] = "bandages"
    if damage == "downgrade":
        data.pop("chronicle")
        for turn in data["turns"]:
            turn.pop("trade")
    with pytest.raises(ValueError):
        Session.from_dict(data, version=19 if damage == "downgrade" else 21)


def test_real_v19_migration_and_three_slots_sqlite_roundtrip(tmp_path):
    root = Path(__file__).parent / "fixtures"
    raw = (root / "save-v19.json").read_bytes()
    source = json.loads((root / "save-v19.source.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(raw).hexdigest() == source["sha256"]
    path = tmp_path / "slot-1.json"
    path.write_bytes(raw)
    slots = SaveSlots(tmp_path)
    session = slots.load(1)
    old_turns, old_rng = session.turns, session.dice.checkpoint()
    act(session, "drop", "legacy_gold", 2)
    assert session.turns[:-1] == old_turns and session.dice.checkpoint() == old_rng
    for slot in (2, 3):
        slots.save(slot, session)
        assert slots.load(slot).to_dict() == session.to_dict()
    index = CatalogIndex(session)
    try:
        export = tmp_path / "world.sqlite3"
        index.export(export)
        assert restore_session(export).to_dict() == session.to_dict()
    finally:
        index.close()
    assert path.read_bytes() == raw
    check(session)
