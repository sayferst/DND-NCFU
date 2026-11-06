"""On-hit grapple links enforce escape, capacity, drag and release conditions."""

from copy import deepcopy
from dataclasses import replace

import pytest
from test_source_rules_runtime import engine_with_rules

from rpg_vkr.domain.catalog_actions_v2 import hit
from rpg_vkr.world_library import grapple_rules as grapple
from rpg_vkr.world_library import source_runtime as runtime
from rpg_vkr.world_library.creature_actions import extract as actions
from rpg_vkr.world_library.source_extract import extract as features
from rpg_vkr.world_library.source_geometry import move, positions


def raw():
    return {
        "действия": [
            {
                "название": "Клешня",
                "описание": "Рукопашная атака оружием: +3 к попаданию, "
                "досягаемость 5 футов, одна цель. "
                "Попадание: 0 рубящего урона, и цель схвачена (Сл высвобождения 11). "
                "У краба две клешни, каждой из них он может схватить одну цель",
            }
        ]
    }


def engine():
    stat = raw()
    a = actions(stat)
    program = grapple.extract(stat, a["actions"])
    assert program
    f = features(stat, a)
    e, _ = engine_with_rules(stat)
    old = e.definitions["wounded_type"]
    e.definitions[old.id] = replace(
        old,
        properties=old.properties
        | {
            "source_actions_v2": a,
            "source_features_v3": f,
            "source_attack_math_version": 2,
            "library_grapple_rules": program,
            "library_creature_size": "Средний",
        },
    )
    return e


@pytest.mark.parametrize("natural", [1, 20])
def test_real_hit_applies_grapple_only_on_hit_even_at_zero_damage(monkeypatch, natural):
    e = engine()
    monkeypatch.setattr(e, "roll", lambda formula, label: natural)
    hit(e, "wounded", "hero", source_attack=0)
    assert e.attacks[-1]["damage"] == 0
    assert runtime.has(e, "hero", "grappled") == (natural == 20)
    assert runtime.speed(e, "hero", 30) == (0 if natural == 20 else 30)


@pytest.mark.parametrize("natural,success", [(1, False), (20, True)])
def test_escape_is_an_actual_skill_check_and_releases_only_on_success(
    monkeypatch, natural, success
):
    e = engine()
    grapple.apply(e, "wounded", "hero", 0)
    monkeypatch.setattr(e, "roll", lambda formula, label: natural)
    assert grapple.escape(e, {"source": "wounded", "ability": "dexterity"}) == success
    assert runtime.has(e, "hero", "grappled") is not success


def test_capacity_blocks_third_target_and_duplicate_hits_do_not_duplicate_links():
    e = engine()
    grapple.apply(e, "wounded", "hero", 0)
    grapple.apply(e, "wounded", "hero", 0)
    assert len(grapple.links(e)) == 1
    grapple.apply(e, "wounded", "seller", 0)
    assert len(grapple.links(e)) == 2
    assert not grapple.allowed(e, "wounded", "watcher", 0)


@pytest.mark.parametrize("reason", ["incapacitated", "distance"])
def test_source_incapacitation_or_forced_separation_ends_grapple(reason):
    e = engine()
    grapple.apply(e, "wounded", "hero", 0)
    if reason == "incapacitated":
        runtime.apply_condition(e, "wounded", "stunned", "hero", 2)
    else:
        positions(e)["hero"]["point"] = [100, 0, 0]
    assert not runtime.has(e, "hero", "grappled")
    assert not grapple.links(e)


def test_drag_moves_held_target_at_reduced_speed_without_breaking_the_hold():
    e = engine()
    grapple.apply(e, "wounded", "hero", 0)
    assert runtime.speed(e, "wounded", 30) == 15
    move(e, "wounded", [10, 0, 0], 15)
    assert positions(e)["hero"]["point"] == [5, 0, 0]
    assert runtime.has(e, "hero", "grappled")


def test_condition_immunity_prevents_grapple_and_unknown_tail_is_not_compiled():
    e = engine()
    actor, definition = e.actor("seller", False)
    source = e.definitions["wounded_type"]
    spec = deepcopy(source.properties["source_features_v3"])
    spec["condition_immunities"] = ["grappled"]
    e.definitions[definition.id] = replace(
        definition,
        properties=definition.properties
        | {"library_rules_version": runtime.VERSION, "source_features_v3": spec},
    )
    grapple.apply(e, "wounded", "seller", 0)
    assert not grapple.links(e)
    stat = raw()
    stat["действия"][0]["описание"] += ". В начале хода цель получает урон холодом."
    assert grapple.extract(stat, actions(stat)["actions"]) is None


def test_real_session_grapple_is_saved_and_exposed_as_an_escape_proposal(tmp_path):
    import sqlite3

    from test_owner_rules_runtime import campaign

    from rpg_vkr.application import Session
    from rpg_vkr.narrative.catalog_protocol import planning_context
    from rpg_vkr.world_library.bridge import commit, preview
    from rpg_vkr.world_library.model import ROOT, read_jsonl
    from rpg_vkr.world_library.store import Library

    row = deepcopy(
        next(
            r
            for r in read_jsonl(ROOT / "data/world_library/rpgd100-creature-facts.jsonl")
            if r["attributes"]["source_name"] == "Алдани (Лобстеролюд)"
        )
    )
    row.update(id="test_grapple_template", name="Тестовый захват без повреждений")
    attack = row["attributes"]["actions_v2"]["actions"][0]
    attack.update(dice="0d4+0", components=[{"dice": "0d4+0", "element": "physical"}])
    library = Library(sqlite3.connect(":memory:"))
    try:
        library.migrate()
        library.import_records([row])
        s = campaign(hp=12)
        commit(s, preview(library, s, row["id"], "grappler"))
    finally:
        library.close()
    s.perform_gameplay("encounter", {"enemies": ["grappler"]}, "grapple-session-battle")
    for turn in range(10):
        if s.gameplay["source_rules_v3"].get("grapples_v1"):
            break
        s.perform_gameplay(
            "source_move", {"position": [0, 0, 0]}, "grapple-session-wait-" + str(turn)
        )
    assert s.gameplay["source_rules_v3"]["grapples_v1"]
    before_view = s.to_dict()
    view = planning_context(s)
    assert s.to_dict() == before_view
    assert view["source_geometry"]["units"] == "feet"
    assert any(r["id"] == "grappler" for r in view["source_geometry"]["positions"])
    assert view["source_grapples"][0]["command"] == "source_escape"
    assert view["source_grapples"][0]["source"] == "grappler"
    saved = s.to_dict()
    assert Session.from_dict(saved, version=31).to_dict() == saved
    assert Session.from_dict(saved, version=31).dice.checkpoint() == s.dice.checkpoint()
    before = s.to_dict()
    with pytest.raises(ValueError):
        s.perform_gameplay("source_move", {"position": [1, 0, 0]}, "illegal-grapple-move")
    assert s.to_dict() == before
    s.perform_gameplay(
        "source_escape", {"source": "grappler", "ability": "dexterity"}, "session-escape"
    )
    assert Session.from_dict(s.to_dict(), version=31).to_dict() == s.to_dict()
    from rpg_vkr.storage.knowledge import export_session, restore_session

    destination = tmp_path / "grapple-world.sqlite3"
    export_session(s, destination)
    restored = restore_session(destination)
    assert restored.to_dict() == s.to_dict()
    assert restored.dice.checkpoint() == s.dice.checkpoint()
