"""Undead Fortitude is one derived save per hit and respects its exceptions."""

from dataclasses import replace

import pytest
from test_source_rules_runtime import engine_with_rules

from rpg_vkr.world_library.damage_packets import apply as packet
from rpg_vkr.world_library.resilience_rules import VERSION, extract


def engine():
    e, rules = engine_with_rules()
    rules["legendary_resistance"] = 0
    old = e.definitions["wounded_type"]
    e.definitions[old.id] = replace(
        old,
        properties=old.properties
        | {
            "library_resilience_rules": {
                "version": VERSION,
                "undead_fortitude": True,
                "supported_names": ["Стойкость нежити"],
            },
        },
    )
    return e


@pytest.mark.parametrize("natural,survives", [(18, True), (2, False), (20, True)])
def test_one_save_before_the_canonical_hp_transition(monkeypatch, natural, survives):
    e = engine()
    rolled = []
    monkeypatch.setattr(e, "roll", lambda *a: rolled.append(a) or natural)
    e.damage("wounded", 12, "physical")
    assert len(rolled) == 1
    assert e.hp("wounded") == (1 if survives else 0)
    assert len([x for x in e.events if x["kind"] == "source_undead_fortitude"]) == 1
    assert len([x for x in e.events if x["kind"] == "owner_life"]) == 1


@pytest.mark.parametrize("kind", ["radiant", "critical", "nonlethal", "already_zero", "legacy"])
def test_exceptions_never_spend_a_fortitude_roll(monkeypatch, kind):
    e = engine()
    if kind in {"critical", "nonlethal"}:
        e.owner_hit_flags = {kind: True}
    if kind == "already_zero":
        e.change_hp("wounded", -12)
    if kind == "legacy":
        old = e.definitions["wounded_type"]
        props = dict(old.properties)
        props.pop("library_resilience_rules")
        e.definitions[old.id] = replace(old, properties=props)

    def ordinary_roll(expression, reason):
        if kind == "nonlethal" and expression == "1d4":
            return 2  # R01 schedules the real recovery time for a stable knockout.
        pytest.fail("No fortitude roll is eligible")

    monkeypatch.setattr(e, "roll", ordinary_roll)
    e.damage("wounded", 12, "radiant" if kind == "radiant" else "physical")
    assert e.hp("wounded") == 0


def test_a_mixed_hit_has_one_save_and_preserves_large_derived_dc(monkeypatch):
    e = engine()
    rolled = []
    monkeypatch.setattr(e, "roll", lambda *a: rolled.append(a) or 20)
    packet(e, "wounded", [(1000000, "physical"), (1000000, "fire")], "hero")
    assert len(rolled) == 1 and e.hp("wounded") == 1
    event = next(x for x in e.events if x["kind"] == "source_undead_fortitude")
    assert event["dc"] == 2000005  # R01 natural20 remains the best possible result.


def test_radiant_component_bypasses_only_when_it_actually_causes_damage(monkeypatch):
    e = engine()
    old = e.definitions["wounded_type"]
    e.definitions[old.id] = replace(
        old, properties=old.properties | {"source_immunities": ["radiant"]}
    )
    monkeypatch.setattr(e, "roll", lambda *a: 20)
    packet(e, "wounded", [(12, "physical"), (4, "radiant")], "hero")
    assert e.hp("wounded") == 1
    e = engine()
    monkeypatch.setattr(e, "roll", lambda *a: pytest.fail("Radiant damage excludes the save"))
    packet(e, "wounded", [(12, "physical"), (4, "radiant")], "hero")
    assert e.hp("wounded") == 0


def test_extractor_never_claims_combined_or_limited_traits():
    standard = (
        "Если урон опускает хиты существа до 0, оно совершает спасбросок Телосложения "
        "Сл 5 + полученный урон, кроме урона излучением или критического попадания. "
        "При успехе хиты существа остаются на 1."
    )
    row = {"название": "Стойкость нежити", "описание": standard}
    assert extract({"черты": [row]})["undead_fortitude"]
    row["описание"] += " Дополнительная особенность: существо получает временные хиты."
    assert not extract({"черты": [row]})["undead_fortitude"]
    row.update(название="Стойкость нежити (1/день)", описание=standard)
    assert not extract({"черты": [row]})["undead_fortitude"]
