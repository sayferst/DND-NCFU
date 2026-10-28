"""New data constraints, public execution, old replay and bounded intent retrieval."""

import json
from pathlib import Path

import pytest
from test_adventure import world_value
from test_catalog_campaign import act, started

from rpg_vkr.application import Session
from rpg_vkr.domain import game_catalog as content
from rpg_vkr.domain.adventure import build_world
from rpg_vkr.domain.catalog_revision2 import build
from rpg_vkr.domain.catalog_search import ranked
from rpg_vkr.domain.character import ABILITY_NAMES, Character
from rpg_vkr.domain.unified import CLASSES
from rpg_vkr.unified_session import UnifiedSession


def new_session(class_id="mage", seed=17):
    character = Character(**dict(zip(ABILITY_NAMES, CLASSES[class_id][3], strict=True)))
    s = UnifiedSession.create(
        character, class_id, CLASSES[class_id][4], seed=seed, content_revision=2, catalog_revision=2
    )
    value = world_value()
    s.start_world(build_world(value, s, "revision-two-integration"))
    return s


def test_both_published_catalogs_and_actual_previous_writer():
    old = Path("data/gameplay/catalog-v1.json")
    fresh = json.loads(Path("data/gameplay/catalog-v2.json").read_text(encoding="utf-8"))
    assert fresh == build(json.loads(old.read_text(encoding="utf-8")))
    assert content.validate(fresh)["total"] == 3360
    with content.using(2):
        assert set(content.load()) == {
            r["id"] for r in json.loads(old.read_text(encoding="utf-8"))["records"]
        }
        for row in content.load().values():
            if row["kind"] in ("weapon", "armour"):
                assert content.row(row["material"])["base"] not in (2, 7, 8)
    fixture = json.loads(
        Path("docs/validation/completion-audit-2026-10-28/schema31-before.json").read_text(
            encoding="utf-8"
        )
    )
    old_session = Session.from_dict(fixture["session"], version=31)
    assert json.loads(json.dumps(old_session.to_dict())) == fixture["session"]
    assert "catalog_revision" not in old_session._origin


def test_revision_two_public_magic_json_sqlite_and_no_scope_leak(tmp_path):
    from rpg_vkr.storage.campaigns import CampaignRepository

    s = new_session()
    before = s.gameplay["mp"]
    act(s, "cast", spell="light", target="hero")
    assert s.gameplay["mp"] == before - 1
    value = s.to_dict()
    assert value["snapshot"]["turns"]["encoding"] == "replayed-sha256-1"
    restored = Session.from_dict(json.loads(json.dumps(value)), version=31)
    assert restored.to_dict() == value and restored.dice.checkpoint() == s.dice.checkpoint()
    repository = CampaignRepository(tmp_path / "campaigns.sqlite3")
    repository.sync(s)
    assert repository.load(repository.identity(s)).to_dict() == value
    assert content.ACTIVE_REVISION.get() == 1
    with pytest.raises(ValueError):
        act(s, "cast", spell="not-a-spell", target="hero")
    assert s.to_dict() == value and content.ACTIVE_REVISION.get() == 1


@pytest.mark.parametrize("index", range(120))
def test_addresses_entries_outside_first_sixteen_without_ids(index):
    with content.using(2):
        spells = content.available("spell")
        row = spells[17 + index * 3 % 383]
        query = "Хочу изучить " + row["name"].lower().replace("ё", "е")
        result = ranked(spells, query, limit=16)
        assert result[0]["id"] == row["id"]
        assert row["id"] not in query


@pytest.mark.parametrize(
    "query,operation",
    [
        ("осветить темноту", "light"),
        ("найти дорогу", "reveal_routes"),
        ("починить снаряжение", "repair"),
        ("замедлить противника", "slow"),
    ],
)
def test_intent_synonyms(query, operation):
    with content.using(2):
        results = ranked(content.available("spell"), query, limit=16)
    assert any(any(e["op"] == operation for e in r["effects"]) for r in results)


def test_changed_history_digest_is_rejected():
    s = new_session()
    act(s, "wait", minutes=1)
    value = s.to_dict()
    value["snapshot"]["turns"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="повтор"):
        Session.from_dict(value, version=31)
    assert started().history_limit == 2000 and s.history_limit == 10000


def test_semantic_validation_rejects_herbal_swords_and_free_outputs():
    data = json.loads(Path("data/gameplay/catalog-v2.json").read_text(encoding="utf-8"))
    sword = next(r for r in data["records"] if r["id"] == "gear_sword_0_0")
    sword["material"] = "mat_2_0"
    with pytest.raises(ValueError, match="основа"):
        content.validate(data)
    sword["material"] = "mat_0_0"
    recipe = next(r for r in data["records"] if r["id"] == "recipe_smithing_0_0")
    recipe["materials_by_output"]["gear_sword_0_0"] = {}
    with pytest.raises(ValueError, match="бесплатный"):
        content.validate(data)
