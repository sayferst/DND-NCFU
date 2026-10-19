"""Generic object/container/location transactions; no paid API or model prose as state."""

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from rpg_vkr.application import Session
from rpg_vkr.domain.interactions import InteractiveWorld, Place, Step, Thing, WorldPlan, apply_plan
from rpg_vkr.narrative.context import build_frame
from rpg_vkr.narrative.dialogue import last_interlocutor
from rpg_vkr.narrative.story import validate_story_text
from rpg_vkr.narrative.story_quality import check_story_quality
from rpg_vkr.storage.knowledge import CampaignIndex, export_session, restore_session
from rpg_vkr.storage.slots import SaveSlots


def escape_plan():
    return WorldPlan(
        (Step("take", "produce_basket"), Step("move", "road"), Step("move", "forest")),
        (Place("forest", "Лесная тропа", "road", "road", "Деревья обступают узкую тропу."),),
    )


def test_take_escape_unpack_drop_updates_inventory_place_and_relationships(tmp_path):
    s = Session(seed=5)
    s.submit("подойти к жительнице")
    first = s.submit_interaction("молча беру корзину с яблоками и убегаю в лес", escape_plan())
    assert first.check.succeeded
    assert s.current_place_id == "forest" and s.current_place_name == "Лесная тропа"
    assert not s.actor_is_here("villager") and not s.actor_is_here("guard")
    assert last_interlocutor(s) is None
    assert s.combat.actor("villager").disposition == "hostile"
    assert s.combat.actor("guard").disposition == "hostile"
    assert {t.id for t in s.interactive_world.carried()} == {"produce_basket", "apples"}
    count = s.dice.checkpoint()
    s.submit_interaction(
        "забираю все яблоки и выкидываю корзину у тропы",
        WorldPlan(
            (
                Step("take", "apples", 12),
                Step("drop", "produce_basket"),
            )
        ),
    )
    assert s.dice.checkpoint() == count
    assert [(t.id, t.quantity) for t in s.interactive_world.carried()] == [("apples", 12)]
    basket = next(t for t in s.interactive_world.things if t.id == "produce_basket")
    assert basket.holder == "forest"
    assert "Яблоки ×12" in build_frame(s).inventory
    assert build_frame(s).visible_actors == ()
    s.submit("осмотреть свой инвентарь", intent="инвентарь")
    assert "Яблоки ×12" in s.turns[-1].text
    slots = SaveSlots(tmp_path / "saves")
    slots.save(1, s)
    restored = slots.load(1)
    assert restored.to_dict() == s.to_dict()
    assert restored.dice.checkpoint() == s.dice.checkpoint()
    path = tmp_path / "world.sqlite3"
    export_session(s, path)
    assert restore_session(path).to_dict() == s.to_dict()
    index = CampaignIndex(s)
    try:
        assert index.db.execute(
            "SELECT holder,quantity FROM objects WHERE id='apples'"
        ).fetchone() == ("hero", 12)
    finally:
        index.close()


def test_failed_theft_changes_witness_attitude_without_transferring_or_travelling():
    s = Session(seed=2)
    turn = s.submit_interaction("беру корзину и убегаю в лес", escape_plan())
    assert not turn.check.succeeded
    assert s.current_place_id == "gate" and not s.interactive_world.carried()
    assert s.combat.actor("villager").disposition == "hostile"
    assert "не удалось" in turn.text
    assert Session.from_dict(s.to_dict()).to_dict() == s.to_dict()


def test_engine_is_generic_for_other_items_and_preserves_quantities():
    before = replace(
        InteractiveWorld.initial("gate"),
        things=(
            Thing("satchel", "Сумка", "hero", "hero", 1, True),
            Thing("letters", "Письма", "satchel", "hero", 7),
        ),
    )
    after, risky, _, _ = apply_plan(
        before,
        WorldPlan(
            (
                Step("take", "letters", 3),
                Step("drop", "satchel"),
            )
        ),
        turn_index=4,
    )
    assert not risky
    assert sum(t.quantity for t in after.things if t.name == "Письма") == 7
    assert [(t.name, t.quantity) for t in after.carried()] == [("Письма", 3)]
    assert next(t for t in after.things if t.id == "letters").holder == "satchel"
    assert next(t for t in after.things if t.id == "satchel").holder == "gate"


@pytest.mark.parametrize(
    "steps",
    [
        (Step("take", "unknown"),),
        (Step("take", "apples", 99),),
        (Step("take", "produce_basket"), Step("move", "unknown")),
        (Step("drop", "produce_basket"),),
        (Step("move", "road"), Step("take", "produce_basket")),
    ],
)
def test_invalid_sequence_is_rejected_before_rng_and_without_partial_changes(steps):
    s = Session(seed=5)
    before = s.to_dict(), s.dice.checkpoint()
    with pytest.raises(ValueError):
        s.submit_interaction("беру предмет и убегаю, выкидываю корзину", WorldPlan(steps))
    assert (s.to_dict(), s.dice.checkpoint()) == before


def test_drop_filled_container_keeps_contents_on_ground_and_can_be_recovered():
    s = Session(seed=5)
    s.submit_interaction("беру корзину и убегаю в лес", escape_plan())
    s.submit_interaction("выкидываю корзину", WorldPlan((Step("drop", "produce_basket"),)))
    assert s.interactive_world.carried() == ()
    assert (
        next(t for t in s.interactive_world.things if t.id == "apples").holder == "produce_basket"
    )
    s.submit_interaction("беру корзину", WorldPlan((Step("take", "produce_basket"),)))
    assert sum(t.quantity for t in s.interactive_world.carried() if t.id == "apples") == 12


@pytest.mark.parametrize("damage", ["items", "place", "before", "check", "relation"])
def test_tampered_interaction_save_is_rejected(damage):
    s = Session(seed=5)
    s.submit_interaction("беру корзину и убегаю в лес", escape_plan())
    data = deepcopy(s.to_dict())
    if damage == "items":
        data["interactive_world"]["things"][1]["quantity"] = 99
    elif damage == "place":
        data["interactive_world"]["current"] = "gate"
    elif damage == "before":
        data["turns"][0]["interaction"]["before"]["things"][1]["quantity"] = 99
    elif damage == "check":
        data["turns"][0]["interaction"]["check"]["succeeded"] = False
    else:
        data["combat"]["actors"][0]["disposition"] = "neutral"
    with pytest.raises(ValueError):
        Session.from_dict(data)


def test_generic_giving_partial_stack_and_inspection_conserve_items_and_ownership():
    before = replace(
        InteractiveWorld.initial("gate"),
        things=(
            Thing("satchel", "Сумка", "hero", "hero", 1, True),
            Thing("letters", "Письма", "satchel", "hero", 7),
        ),
    )
    after, risky, _, messages = apply_plan(
        before,
        WorldPlan(
            (
                Step("look", "satchel"),
                Step("give", "letters", 3, "villager"),
            )
        ),
        turn_index=3,
    )
    assert not risky and "Письма ×7" in messages[0]
    gift = next(t for t in after.things if t.id == "split_3_1")
    assert (gift.holder, gift.owner, gift.quantity) == ("villager", "villager", 3)
    assert sum(t.quantity for t in after.things if t.name == "Письма") == 7
    with pytest.raises(ValueError, match="отсутствующий"):
        apply_plan(before, WorldPlan((Step("look", "missing"),)))
    with pytest.raises(ValueError, match="чужой инвентарь"):
        apply_plan(before, WorldPlan((Step("inventory", "villager"),)))


def test_read_only_question_and_return_path_preserve_objects_and_rng():
    s = Session(seed=5)
    s.submit_interaction("беру корзину и убегаю в лес", escape_plan())
    s.submit_interaction("выкидываю корзину", WorldPlan((Step("drop", "produce_basket"),)))
    checkpoint = s.dice.checkpoint()
    s.submit_interaction("что лежит в корзине?", WorldPlan((Step("look", "produce_basket"),)))
    assert "Яблоки ×12" in s.turns[-1].text
    s.submit_interaction("иду к воротам", WorldPlan((Step("move", "road"), Step("move", "gate"))))
    assert not next(
        t for t in s.interaction_state().context()["objects"] if t["id"] == "produce_basket"
    )["available_here"]
    s.submit_interaction(
        "иду обратно в лес", WorldPlan((Step("move", "road"), Step("move", "forest")))
    )
    s.submit_interaction("беру всю корзину", WorldPlan((Step("take", "produce_basket", 0),)))
    assert s.dice.checkpoint() == checkpoint
    assert "Яблоки ×12" in s.interactive_world.inventory()
    assert Session.from_dict(s.to_dict()).to_dict() == s.to_dict()


def test_real_v17_fixture_migrates_without_changing_world_brief_challenge_or_rng(tmp_path):
    root = Path(__file__).parent / "fixtures"
    raw = (root / "save-v17.json").read_bytes()
    source = json.loads((root / "save-v17.source.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(raw).hexdigest() == source["sha256"]
    original = json.loads(raw)["session"]
    slots = SaveSlots(tmp_path)
    (tmp_path / "slot-1.json").write_bytes(raw)
    s = slots.load(1)
    assert s.interactive_world is None
    assert json.loads(json.dumps(s.campaign.to_dict())) == original["campaign"]
    migrated_turns = json.loads(json.dumps(s.to_dict()["turns"]))
    assert all(t.pop("interaction") is None for t in migrated_turns)
    assert migrated_turns == original["turns"]
    checkpoint = s.dice.checkpoint()
    slots.save(2, s)
    restored = slots.load(2)
    assert restored.to_dict() == s.to_dict()
    assert restored.dice.checkpoint() == checkpoint
    assert restored.dice.roll_d20() == s.dice.roll_d20()
    assert (tmp_path / "slot-1.json").read_bytes() == raw


@pytest.mark.parametrize(
    "prose",
    [
        "Вы берёте яблоки и кладёте их в свою дорожную сумку.",
        "Вы забираете корзину и молча смотрите на дорогу.",
        "Вы убегаете в лес; ветки качаются над тропой.",
    ],
)
def test_free_prose_cannot_execute_transfers_or_travel(prose):
    with pytest.raises(ValueError, match="неподтверждённый"):
        validate_story_text(prose)


def test_failed_transfer_and_absent_npc_cannot_be_undone_by_writer():
    s = Session(seed=2)
    s.submit_interaction("беру корзину и убегаю в лес", escape_plan())
    with pytest.raises(ValueError, match="не удалась"):
        check_story_quality(
            "Вы берёте корзину и убегаете в лес.",
            build_frame(s),
            s.turns[-1].action,
            campaign={"interaction_result": s.turns[-1].text},
        )
    away = Session(seed=5)
    away.submit_interaction("беру корзину и убегаю в лес", escape_plan())
    with pytest.raises(ValueError, match="нет рядом"):
        check_story_quality(
            "Жительница поднимает голову и смотрит на вас.", build_frame(away), "Осмотрюсь"
        )


def test_silent_attempt_is_not_mistaken_for_negation_and_real_negation_stays_inert():
    s = Session(seed=5)
    s.submit_interaction("ничего не говоря, беру корзину и убегаю в лес", escape_plan())
    assert s.current_place_id == "forest"
    no = Session(seed=5)
    before = no.to_dict(), no.dice.checkpoint()
    with pytest.raises(ValueError, match="отрицание"):
        no.submit_interaction(
            "не беру корзину и не убегаю в лес", escape_plan(), confirmed_plan=True
        )
    assert (no.to_dict(), no.dice.checkpoint()) == before
