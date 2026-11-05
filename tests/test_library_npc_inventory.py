"""Inventory creation, item identity, NPC wear, and opt-in revision coexistence."""

from copy import deepcopy

import pytest
from test_library_utility_runtime import library  # noqa: F401
from test_owner_rules_runtime import campaign

from rpg_vkr.application import Session
from rpg_vkr.domain.catalog_engine import Engine
from rpg_vkr.unified_session import context
from rpg_vkr.world_library.bridge import commit, preview
from rpg_vkr.world_library.npc_equipment import weapon


def test_npc_starts_with_real_owned_items_and_replays(library):  # noqa: F811
    s = campaign(hp=12)
    before_items = list(s.gameplay["items"])
    request = preview(library, s, "wl_npc_0_0", "smith", with_inventory=True)
    assert any(e.owner_id == "smith" for e in request.entities)
    commit(s, request)
    held = [e for e in s.catalog.entities if e.owner_id == "smith"]
    assert len(held) == 1 and held[0].parent_id == "smith"
    assert s.gameplay["items"] == before_items
    assert Session.from_dict(s.to_dict(), version=31).to_dict() == s.to_dict()


def test_npc_uses_intact_item_and_does_not_recreate_missing_weapon(library):  # noqa: F811
    s = campaign(hp=12)
    commit(s, preview(library, s, "wl_npc_0_0", "smith", with_inventory=True))
    e = Engine(s.gameplay, context(s), s.dice, {})
    id = e.actors["smith"].state["library_weapon"]
    condition = e.actors[id].state["condition"]
    rules = weapon(e, "smith")
    assert rules["kind"] == "weapon"
    assert e.actors[id].state["condition"] == condition - 1
    e.actors.pop(id)
    assert weapon(e, "smith")["category"] == "unarmed"
    assert id not in e.actors


def test_new_revision_does_not_overwrite_old_definition_or_instance(library):  # noqa: F811
    s = campaign(hp=12)
    original = library.get("wl_food_0_0")
    commit(s, preview(library, s, original["id"], "old_ration"))
    previous = next(d for d in s.catalog.definitions if d.id == original["id"])
    changed = deepcopy(original)
    changed["description"] += " Новая редакция."
    library.import_records([changed], expected={original["id"]: 1})
    with pytest.raises(ValueError, match="pins"):
        preview(library, s, original["id"], "blocked_ration")
    commit(s, preview(library, s, original["id"], "new_ration", new_revision=True))
    old = next(e for e in s.catalog.entities if e.id == "old_ration")
    new = next(e for e in s.catalog.entities if e.id == "new_ration")
    assert old.definition_id != new.definition_id
    assert next(d for d in s.catalog.definitions if d.id == previous.id) == previous
    assert Session.from_dict(s.to_dict(), version=31).to_dict() == s.to_dict()
