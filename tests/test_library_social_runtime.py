"""Mood follows verified events, with visibility and old-campaign isolation."""

from copy import deepcopy
from dataclasses import replace

import pytest
from test_library_utility_runtime import library  # noqa: F401
from test_owner_rules_runtime import campaign

from rpg_vkr.application import Session
from rpg_vkr.domain.catalog_engine import Engine
from rpg_vkr.unified_session import context
from rpg_vkr.world_library.bridge import commit, preview
from rpg_vkr.world_library.social_rules import compile_social, update, validate


def npc(library, *, inventory=True):  # noqa: F811
    s = campaign(hp=12)
    commit(s, preview(library, s, "wl_npc_0_0", "smith", with_inventory=inventory))
    return s


def test_all_400_declared_personalities_are_closed_programs(library):  # noqa: F811
    rows = [r for r in library.all() if r["profile"] == "npc"]
    assert len(rows) == 400
    for row in rows:
        validate(compile_social(row))
    bad = compile_social(rows[0])
    bad["transitions"][0]["event"] = "story_says_so"
    with pytest.raises(ValueError):
        validate(bad)


def test_confirmed_contract_updates_mood_once_without_resources_or_rng(library):  # noqa: F811
    s = npc(library)
    e = Engine(s.gameplay, context(s), s.dice, {})
    before, rng = deepcopy(e.state), s.dice.checkpoint()
    e.events.append({"kind": "contract_completed", "npc": "smith", "id": "verified"})
    update(e)
    update(e)
    assert e.actors["smith"].state["mood"] == "calm"
    assert e.actors["smith"].state["relations"]["hero"]["trust"] == 1
    assert len([v for v in e.events if v["kind"] == "library_social_transition"]) == 1
    assert e.state == before and s.dice.checkpoint() == rng


@pytest.mark.parametrize("visible", [True, False])
def test_property_taking_needs_the_actual_owner_as_witness(library, visible):  # noqa: F811
    s = npc(library)
    e = Engine(s.gameplay, context(s), s.dice, {})
    actor = e.actors["smith"]
    e.actors["smith"] = replace(
        actor, state=dict(actor.state) | {"mood": "calm", "can_see": visible}
    )
    e.events.append(
        {
            "kind": "owner_physical_take",
            "legal_owner_after": "smith",
            "holder_after": "hero",
            "item": "owned_weapon",
        }
    )
    update(e)
    assert e.actors["smith"].state["mood"] == ("angry" if visible else "calm")
    assert bool(e.actors["smith"].state["relations"]) == visible


def test_old_npc_and_unverified_prose_have_no_social_effect(library):  # noqa: F811
    s = npc(library)
    e = Engine(s.gameplay, context(s), s.dice, {})
    actor = e.actors["smith"]
    e.events.append({"kind": "story", "npc": "smith", "text": "Обещание выполнено"})
    update(e)
    assert e.actors["smith"] == actor
    state = dict(actor.state)
    state.pop("library_social_version")
    e.actors["smith"] = old = replace(actor, state=state)
    e.events.append({"kind": "contract_completed", "npc": "smith"})
    update(e)
    assert e.actors["smith"] == old


def test_social_state_initialization_and_saved_wait_replay(library):  # noqa: F811
    s = npc(library, inventory=False)
    actual = next(v for v in s.catalog.entities if v.id == "smith")
    assert actual.state["mood"] == "wary" and actual.state["library_social_version"] == 1
    s.perform_gameplay("wait", {"minutes": 1}, "wait-social")
    assert Session.from_dict(s.to_dict(), version=31).to_dict() == s.to_dict()


def test_real_contract_completion_and_property_taking_change_npc_mood(library):  # noqa: F811
    from test_library_magic_runtime import take

    from rpg_vkr.domain.contracts import offers

    s = npc(library)
    offer = next(q for q in offers(s) if q["npc"] == "smith")
    s.perform_gameplay("contract", {"offer": offer["id"], "operation": "accept"}, "promise")
    for n in range(20):
        s.perform_gameplay("gather", {"material": offer["resource"], "quantity": 2}, f"work-{n}")
        if s.gameplay["activity"]["gathered"].get(offer["resource"], 0) >= offer["baseline"] + 2:
            break
    s.perform_gameplay("contract", {"offer": offer["id"], "operation": "complete"}, "kept")
    actor = next(e for e in s.catalog.entities if e.id == "smith")
    assert actor.state["mood"] == "calm"
    weapon = actor.state["library_weapon"]
    take(s, weapon)
    actor = next(e for e in s.catalog.entities if e.id == "smith")
    assert actor.state["mood"] == "angry"
    assert actor.state["relations"]["hero"] == {"trust": 1, "grievance": 3}
    from rpg_vkr.storage.catalog import CatalogIndex

    index = CatalogIndex(s)
    try:
        voice = index.narrator_record("smith")["npc_voice"]
        assert voice["mood"] == "angry"
        assert voice["library_personality"]["profession"]
        assert voice["library_personality"]["biography"]
        assert "gold_cp" not in voice["library_personality"]
    finally:
        index.close()
    assert Session.from_dict(s.to_dict(), version=31).to_dict() == s.to_dict()
