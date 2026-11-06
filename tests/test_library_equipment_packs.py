"""Source packages are finite units; fractional copper prices cannot mint money."""

from dataclasses import replace

import pytest
from test_library_utility_runtime import library  # noqa: F401
from test_owner_rules_runtime import campaign

from rpg_vkr.application import Session
from rpg_vkr.domain.catalog_engine import Engine
from rpg_vkr.unified_session import context
from rpg_vkr.world_library.bridge import commit, preview
from rpg_vkr.world_library.equipment_packs import quote
from rpg_vkr.world_library.model import equipment_records


def add_source_packages(library):  # noqa: F811
    rows = [
        r
        for r in equipment_records()
        if "pack_v1" in r["attributes"]
    ]
    library.import_records(rows)
    return next(r for r in rows if r["attributes"]["source_name"] == "Пули (10)")


def test_one_pack_is_ten_units_with_a_single_unit_name_and_unit_value(library):  # noqa: F811
    row = add_source_packages(library)
    s = campaign(hp=12)
    rng = s.dice.checkpoint()
    proposal = preview(library, s, row["id"], "new_bullets")
    commit(s, proposal)
    item = next(e for e in s.catalog.entities if e.id == "new_bullets")
    definition = next(d for d in s.catalog.definitions if d.id == item.definition_id)
    assert item.quantity == 10
    assert definition.name.startswith("Пуля ·")
    assert definition.price_cp * item.quantity == 300
    assert definition.properties["mass_g"] == 91
    assert "unit_mass_rounding" in definition.properties["library_item_rules"]["homebrew_fields"]
    assert s.dice.checkpoint() == rng
    assert Session.from_dict(s.to_dict(), version=31).to_dict() == s.to_dict()


def test_fractional_unit_prices_round_only_the_total_payment(library):  # noqa: F811
    row = add_source_packages(library)
    s = campaign(hp=12)
    proposal = preview(library, s, row["id"], "new_bullets")
    definition = next(d for d in proposal.definitions if d.id == row["id"])
    pack = dict(definition.properties["library_pack_rules"], quantity=50, pack_price_cp=10)
    definition = replace(
        definition, properties=definition.properties | {"library_pack_rules": pack}
    )
    e = Engine(s.gameplay, context(s), s.dice, {})
    assert quote(e, definition, 50, 100) == 10
    assert quote(e, definition, 1, 100) == 1
    assert quote(e, definition, 50, 100, selling=True) == 5
    with pytest.raises(ValueError, match="партия"):
        quote(e, definition, 1, 100, selling=True)


def test_real_buy_sell_keeps_ten_units_and_conserves_all_money(library):  # noqa: F811
    from test_catalog_invariants import coins

    row = add_source_packages(library)
    s = campaign(hp=12)
    commit(s, preview(library, s, "wl_npc_0_9", "trader"))
    proposal = preview(library, s, row["id"], "seller_bullets")
    proposal = replace(
        proposal,
        entities=tuple(
            replace(e, owner_id="trader", parent_id="trader") for e in proposal.entities
        ),
    )
    commit(s, proposal)
    total, cash, rng = coins(s), s.gameplay["copper"], s.dice.checkpoint()
    s.perform_gameplay(
        "buy", {"merchant": "trader", "item": "seller_bullets", "quantity": 1}, "buy-one-bullet"
    )
    assert s.gameplay["copper"] == cash - 30 and coins(s) == total
    purchased = next(
        e for e in s.catalog.entities if e.owner_id == "hero" and e.definition_id == row["id"]
    )
    s.perform_gameplay(
        "sell", {"merchant": "trader", "item": purchased.id, "quantity": 1}, "sell-one-bullet"
    )
    assert s.gameplay["copper"] == cash - 15 and coins(s) == total
    assert sum(e.quantity for e in s.catalog.entities if e.definition_id == row["id"]) == 10
    assert s.dice.checkpoint() == rng
    assert Session.from_dict(s.to_dict(), version=31).to_dict() == s.to_dict()
