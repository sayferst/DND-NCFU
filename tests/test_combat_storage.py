"""Multi-roll replay, hostility migration and corrupted combat records."""

from copy import deepcopy
from pathlib import Path

import pytest
from test_combat import hero

from rpg_vkr.application import Session
from rpg_vkr.storage.slots import SaveSlots


def pending():
    session = hero()
    session.submit("идти на дорогу")
    session.submit("подкрасться к волку")
    return session


def test_save_mid_approach_restore_and_same_following_attack(tmp_path):
    session = pending()
    store = SaveSlots(tmp_path)
    store.save(1, session)
    restored = store.load(1)
    assert restored.combat.surprise
    assert restored.combat.active == "wolf"
    assert restored.submit("атаковать волка") == session.submit("атаковать волка")
    assert restored.to_dict() == session.to_dict()
    store.save(2, restored)
    assert store.load(2).submit("бросить d20").roll.value == 17


@pytest.mark.parametrize(
    "field",
    [
        "die",
        "damage",
        "profile",
        "command",
        "rules",
        "identity",
        "turn_roll",
        "check",
        "reward_text",
    ],
)
def test_tampered_combat_record_rejected(field):
    session = pending()
    session.submit("атаковать волка")
    data = session.to_dict()
    turn = data["turns"][-1]
    record = turn["combat"]
    if field == "die":
        record["outcome"]["rolls"][1]["value"] = 99
    elif field == "damage":
        record["outcome"]["state"]["actors"][3]["hp"] = 1
    elif field == "profile":
        record["character"]["strength"] = 30
    elif field == "command":
        record["command"] = "отступить"
    elif field == "rules":
        record["rules_version"] = "future"
    elif field == "identity":
        turn["actor_id"] = "merchant"
    elif field == "turn_roll":
        turn["roll"]["index"] = True
    elif field == "reward_text":
        turn["text"] += "\nРазвитие: выдуманная награда"
    else:
        turn["check"]["total"] = 999
    with pytest.raises(ValueError):
        Session.from_dict(data)


def test_actor_state_cannot_change_without_record_and_record_order_is_checked():
    session = pending()
    data = session.to_dict()
    data["combat"]["actors"][0]["disposition"] = "hostile"
    with pytest.raises(ValueError):
        Session.from_dict(data)
    data = session.to_dict()
    data["turns"][-1]["combat"]["before"]["rounds"] = 99
    with pytest.raises(ValueError):
        Session.from_dict(data)


def test_healing_cannot_be_inserted_between_active_rounds():
    session = pending()
    session.submit("уклониться")  # seed5 next9 + Dex1 succeeds
    data = session.to_dict()
    data["turns"][-1]["combat"]["world_before"]["hp"] = 11
    with pytest.raises(ValueError):
        Session.from_dict(data)


def test_v5_created_hero_keeps_growth_events_and_rng_without_new_combat_history(tmp_path):
    original = (Path(__file__).parent / "fixtures" / "save-v5.json").read_bytes()
    path = tmp_path / "slot-1.json"
    path.write_bytes(original)
    store = SaveSlots(tmp_path)
    restored = store.load(1)
    assert restored.progress.enabled
    assert restored.progress.level == 2
    assert len(restored.progress.events) == 3
    assert restored.combat.active is None
    assert restored.turns[-1].action == "атаковать волка"
    assert "пока не понимаю" in restored.turns[-1].text
    assert restored.combat.actor("wolf").hp == 10
    assert restored.combat.actor("guard").disposition == "neutral"
    assert all(
        event.rules_version == "homebrew-progression-1" for event in restored.progress.events
    )
    assert path.read_bytes() == original
    assert restored.submit("бросить d20").roll.value == 12
    store.save(1, restored)
    assert store.load(1).to_dict() == restored.to_dict()


def test_missing_npc_identity_is_rejected():
    session = Session()
    session.submit("поговорить с жительницей")
    data = deepcopy(session.to_dict())
    data["turns"][0]["actor_id"] = None
    with pytest.raises(ValueError):
        Session.from_dict(data)
