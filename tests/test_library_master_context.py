"""Real local retrieval and shared review/master cards never grant world state."""

import hashlib
import json
from copy import deepcopy

import pytest
from test_owner_rules_runtime import campaign

from rpg_vkr.narrative.context import build_frame
from rpg_vkr.narrative.master import campaign_context
from rpg_vkr.narrative.story import story_context, story_payload
from rpg_vkr.world_library.model import ROOT, read_jsonl
from rpg_vkr.world_library.narrator import retrieve
from rpg_vkr.world_library.presentation import card, render
from rpg_vkr.world_library.store import Library


@pytest.fixture
def catalog_file(tmp_path):
    path = tmp_path / "library.sqlite3"
    lib = Library.sqlite(path)
    lib.migrate()
    rows = read_jsonl(ROOT / "data/world_library/seed-v1.jsonl")
    lib.import_records(rows)
    lib.close()
    return path


def test_actual_retrieval_is_read_only_and_uses_stable_id(catalog_file):
    before = hashlib.sha256(catalog_file.read_bytes()).hexdigest()
    result = retrieve("wl_weapon_0_0", path=catalog_file)
    assert result["status"] == "matched"
    assert result["cards"][0]["id"] == "wl_weapon_0_0"
    assert result["cards"][0]["template_only"]
    assert len(json.dumps(result["cards"], ensure_ascii=False)) <= 3200
    assert hashlib.sha256(catalog_file.read_bytes()).hexdigest() == before


def test_catalog_is_opt_in_and_invalid_path_does_not_create_database(tmp_path, monkeypatch):
    monkeypatch.delenv("RPG_VKR_WORLD_LIBRARY", raising=False)
    assert retrieve("меч") is None
    path = tmp_path / "missing.sqlite3"
    assert retrieve("меч", path=path)["status"] == "unavailable"
    assert not path.exists()


def test_prompt_receives_cards_without_committing_items_or_rng(catalog_file, monkeypatch):
    monkeypatch.setenv("RPG_VKR_WORLD_LIBRARY", str(catalog_file))
    session = campaign(hp=12)
    before, rng = session.to_dict(), session.dice.checkpoint()
    frame = build_frame(session)
    context = story_context(
        frame, "local-test", "Мастер покажи wl_weapon_0_0", campaign=campaign_context(session)
    )
    payload = story_payload(frame, "local-test", "Мастер покажи wl_weapon_0_0", context=context)
    assert "wl_weapon_0_0" in payload["messages"][1]["content"]
    assert "а не факты текущей сцены" in payload["messages"][1]["content"]
    assert session.to_dict() == before and session.dice.checkpoint() == rng


def test_model_text_is_bound_search_input(catalog_file):
    result = retrieve("'; DROP TABLE wl_templates; --", path=catalog_file)
    assert result["status"] == "no_match"
    lib = Library.sqlite(catalog_file)
    assert len(lib.all()) == 2864
    lib.close()
    with pytest.raises(ValueError):
        retrieve("меч", path=catalog_file, limit=500)


def test_shared_view_keeps_source_facts_separate_from_homebrew():
    rows = read_jsonl(ROOT / "data/world_library/rpgd100-creature-facts.jsonl")
    value = card(rows[0])
    assert value["name"] == rows[0]["attributes"]["source_name"]
    assert value["provenance"]["review"] == "unreviewed"
    assert "Справочная запись" not in render(value)
    assert value["mechanics"]["version"] == "library-creature-3"


def test_component_name_is_pinned_to_parent_revision(catalog_file):
    lib = Library.sqlite(catalog_file)
    parent = lib.get("wl_weapon_0_0")
    component_id = next(
        link["target"] for link in parent["links"] if link["relation"] == "component"
    )
    old = lib.get(component_id)
    edited = deepcopy(old)
    edited["name"] = "Материал после новой редакции"
    lib.import_records([edited], expected={component_id: 1})
    lib.close()
    result = retrieve(parent["id"], path=catalog_file)
    assert old["name"] in result["cards"][0]["appearance"]
    assert edited["name"] not in result["cards"][0]["appearance"]
