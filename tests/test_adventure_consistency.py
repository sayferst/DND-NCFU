"""Unscripted transfer, witness, defence and old-dialogue regressions."""

from copy import deepcopy

import pytest
from test_adventure import hero, started, world_value

from rpg_vkr.application import Session
from rpg_vkr.domain.adventure import build_world
from rpg_vkr.domain.interactions import Step, WorldPlan
from rpg_vkr.narrative.context import build_frame
from rpg_vkr.narrative.records import Narration
from rpg_vkr.storage.campaigns import CampaignRepository


def entity(session, id):
    return next(e for e in session.catalog.entities if e.id == id)


def seed_session(value, seed=5):
    session = hero()
    session.dice = type(session.dice)(seed)
    session.start_world(build_world(value, session, "synthetic-model"))
    return session


def test_witnesses_have_individual_memory_and_do_not_all_become_hostile():
    value = world_value()
    value["definitions"].append(
        {
            "id": "sentinel_type",
            "name": "Дозорный",
            "kind": "actor",
            "categories": ["npcs"],
            "properties": {"hp_max": 12, "courage": 8, "protects_others": True},
        }
    )
    value["entities"] += [
        {
            "id": "sentinel",
            "definition_id": "sentinel_type",
            "parent_id": "pier",
            "state": {"hp": 12},
        },
        {
            "id": "sleeper",
            "definition_id": "sentinel_type",
            "parent_id": "pier",
            "state": {"hp": 12, "asleep": True},
        },
    ]
    session = seed_session(value)
    turn = session.submit_interaction("забираю бинт", WorldPlan((Step("take", "stock", 1),)))
    assert turn.interaction.check.succeeded
    assert entity(session, "seller").state["relations"]["hero"]["grievance"] == 3
    assert entity(session, "seller").state.get("disposition") != "hostile"
    assert entity(session, "sentinel").state["disposition"] == "hostile"
    assert "last_observed_event" not in entity(session, "sleeper").state
    assert "last_observed_event" not in entity(session, "watcher").state
    assert Session.from_dict(session.to_dict()).to_dict() == session.to_dict()


def test_failed_theft_keeps_completed_travel_and_stops_before_gift():
    session = seed_session(world_value(), seed=1)
    session.submit_interaction("иду по тропе", WorldPlan((Step("move", "path"),)))
    turn = session.submit_interaction(
        "иду к причалу, беру бинт и отдаю верёвку Рену",
        WorldPlan(
            (Step("move", "pier"), Step("take", "stock", 1), Step("give", "rope", 1, "seller"))
        ),
    )
    assert not turn.interaction.check.succeeded
    assert session.current_place_id == "pier"
    assert next(t for t in session.interaction_state().things if t.id == "rope").holder == "hero"
    assert next(t for t in session.interaction_state().things if t.id == "stock").quantity == 3
    status = entity(session, "seller").state
    assert status["last_observed_event"]["kind"] == "theft_attempt"
    assert status["relations"]["hero"].get("trust", 0) == 0
    assert Session.from_dict(session.to_dict()).to_dict() == session.to_dict()


def test_gifted_coins_can_fund_merchant_purchase_without_duplicate_money():
    value = world_value()
    value["entities"][0]["state"]["gold_cp"] = 0
    session = seed_session(value)
    before = session.world.gold
    session.submit_interaction(
        "дарю Рену три монеты", WorldPlan((Step("give", "legacy_gold", 3, "seller"),))
    )
    assert session.world.gold == before - 3
    assert entity(session, "seller").state["relations"]["hero"]["trust"] == 1
    session.submit_trade("продаю верёвку", "seller", "rope", "sell", 1)
    assert session.world.gold == before - 1
    scene = session.interaction_state()
    npc_coins = sum(
        t.quantity
        for t in scene.things
        if t.resource == "gold" and scene.root_holder(t) == "seller"
    )
    assert npc_coins == 1
    assert entity(session, "seller").state["gold_cp"] == 0
    assert Session.from_dict(session.to_dict()).to_dict() == session.to_dict()


def test_attack_uses_counter_rng_and_replay_rejects_tampering():
    session = started()
    turn = session.submit_actor_attempt(
        "атакую Рена", "seller", "attack", False, "Атака", "synthetic-model"
    )
    assert turn.catalog.counter and turn.catalog.counter.roll.index == turn.roll.index + 1
    assert Session.from_dict(session.to_dict()).to_dict() == session.to_dict()
    bad = deepcopy(session.to_dict())
    bad["turns"][0]["catalog"]["counter"]["damage"] += 1
    with pytest.raises(ValueError):
        Session.from_dict(bad)


def test_dead_enemy_does_not_attack_back_or_revive_after_loading():
    value = world_value()
    value["entities"][0]["state"]["hp"] = 1
    session = seed_session(value)
    turn = session.submit_actor_attempt(
        "убиваю Рена", "seller", "attack", True, "Атака", "synthetic-model"
    )
    assert turn.catalog.entity_after.state["life"] == "dead"
    assert turn.catalog.counter is None
    assert session.dice.checkpoint()[1] == 1
    restored = Session.from_dict(session.to_dict())
    assert entity(restored, "seller").state["life"] == "dead"
    with pytest.raises(ValueError, match="мертва"):
        restored.submit_actor_attempt(
            "атакую Рена", "seller", "attack", False, "Атака", "synthetic-model"
        )


def test_old_conversation_is_searchable_without_leaking_rewound_future(tmp_path):
    session = started()
    session.add_narration(
        Narration(
            0,
            "synthetic-model",
            "Рен: «Полынь растёт у северной переправы».",
            build_frame(session).fingerprint,
        )
    )
    db = CampaignRepository(tmp_path / "campaigns.sqlite3")
    session.submit("состояние")
    checkpoint = deepcopy(session.to_dict())
    for _ in range(20):
        session.submit("состояние")
    session.add_narration(
        Narration(
            21,
            "synthetic-model",
            "Морок: «Ключ в янтарном сундуке».",
            build_frame(session).fingerprint,
        )
    )
    assert "Полынь" in str(db.recall(session, "полынь")["past_conversations"])
    assert "янтарном" in str(db.recall(session, "янтарном")["past_conversations"])
    assert not db.recall(Session.from_dict(checkpoint), "янтарном")["past_conversations"]


def test_offline_randomness_is_reproducible_and_genre_selection_is_bounded():
    from rpg_vkr.domain.adventure import offline_world
    from rpg_vkr.narrative.genres import relevant_cards

    session = hero()
    assert offline_world(session).to_dict() == offline_world(session).to_dict()
    assert len(relevant_cards("магия интриги гильдий тайны драма")) <= 2
    assert "dark_fantasy" not in {
        c["id"] for c in relevant_cards("без мрачного фэнтези, путешествие")
    }


def test_generated_story_frame_never_mentions_the_old_delivery_or_fake_inventory():
    session = started()
    session.submit_trade("покупаю бинт", "seller", "stock", "buy", 1)
    frame = build_frame(session)
    assert "Корзина" not in frame.quest and "жительница" not in frame.quest
    assert "учителя" in frame.quest
    assert "Верёвка" in frame.inventory
    assert "Ворота деревни" not in str(frame.to_dict())
    assert "Стражник" not in str(frame.to_dict())
    assert Session.from_dict(session.to_dict()).to_dict() == session.to_dict()
