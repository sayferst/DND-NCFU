from copy import deepcopy

import pytest

from rpg_vkr.application import Session
from rpg_vkr.domain.character import ABILITY_NAMES, Character
from rpg_vkr.domain.unified import CLASSES, VERSION, bonus, level, proficiency
from rpg_vkr.storage.campaigns import CampaignRepository
from rpg_vkr.storage.slots import SaveSlots
from rpg_vkr.unified_session import UnifiedSession


def hero(class_id="mage", seed=13):
    return UnifiedSession.create(
        Character(**dict(zip(ABILITY_NAMES, CLASSES[class_id][3], strict=True))),
        class_id,
        CLASSES[class_id][4],
        seed=seed,
        content_revision=1,  # Published schema30 compatibility suite.
    )


@pytest.mark.parametrize("key", CLASSES)
def test_one_ruleset_all_classes_real_inventory_no_skill_currency_and_save(key, tmp_path):
    s = hero(key)
    assert s.schema_version == 30 and s.gameplay["version"] == VERSION
    assert s.d20_progress is None and s.gameplay["items"]
    assert sum(getattr(s.character, a) - 8 for a in ABILITY_NAMES) == 24
    s.perform_gameplay("wait", {"minutes": 10}, "wait_once")
    s.perform_gameplay("wait", {"minutes": 10}, "wait_once")
    assert s.gameplay["minute"] == 490
    r = Session.from_dict(s.to_dict(), version=30)
    assert r.to_dict() == s.to_dict() and r.dice.checkpoint() == s.dice.checkpoint()
    slots = SaveSlots(tmp_path / "saves")
    slots.save(1, s)
    assert slots.load(1).to_dict() == s.to_dict()
    repo = CampaignRepository(tmp_path / "campaigns.sqlite3")
    repo.sync(s)
    assert repo.load(repo.identity(s)).to_dict() == s.to_dict()
    damaged = deepcopy(s.to_dict())
    damaged["snapshot"]["gameplay"]["state"]["copper"] += 1
    with pytest.raises(ValueError):
        Session.from_dict(damaged, version=30)


@pytest.mark.parametrize("lv", [1, 2, 5, 10, 20])
def test_progression_and_automatic_preparation(lv):
    xp = 50 * (lv - 1) * lv
    assert level(xp) == lv and proficiency(xp) == 2 + (lv - 1) // 4
    s = hero("artisan")
    assert bonus(s.gameplay, s.character, "repair")[1] == 6


def test_scroll_and_mana_consumed_only_on_success_and_duplicate_request_has_no_effect():
    s = hero()
    scroll = next(i["id"] for i in s.gameplay["items"] if i["kind"] == "scroll_light")
    s.perform_gameplay("consume", {"item": scroll}, "scroll")
    assert not any(i["id"] == scroll for i in s.gameplay["items"])
    before = s.to_dict()
    s.perform_gameplay("consume", {"item": scroll}, "scroll")
    assert s.to_dict()["snapshot"] == before["snapshot"]
    s.perform_gameplay("cast", {"spell": "light", "target": "hero"}, "cast")
    mana = next(i["id"] for i in s.gameplay["items"] if i["kind"] == "mana")
    s.perform_gameplay("consume", {"item": mana}, "mana")
    assert s.gameplay["mp"] == s.gameplay["mp_cap"]
    before = s.to_dict(), s.dice.checkpoint()
    with pytest.raises(ValueError):
        s.perform_gameplay("manufacture", {"recipe": "sword"}, "bad")
    assert (s.to_dict(), s.dice.checkpoint()) == before


def test_real_world_team_attack_and_magic_have_one_shared_turn_and_replay():
    from test_adventure import world_value

    from rpg_vkr.domain.adventure import build_world

    for class_id in ("warrior", "mage"):
        s = hero(class_id)
        s.start_world(build_world(world_value(), s, "own-test"))
        target = next(a.id for a in s.interaction_state().actor_refs if s.actor_is_here(a.id))
        s.perform_gameplay("encounter", {"enemies": [target], "allies": []}, "start")
        command = "attack" if class_id == "warrior" else "cast"
        args = {"target": target} if command == "attack" else {"spell": "bolt", "target": target}
        turn = s.perform_gameplay(command, args, "one-round")
        assert turn.gameplay["result"]["rolls"]
        assert (
            any(a["actor_id"] == target for a in turn.gameplay["result"]["attacks"])
            or not s.in_combat
        )
        before = s.to_dict()["snapshot"], s.dice.checkpoint()
        s.perform_gameplay(command, args, "one-round")
        assert (s.to_dict()["snapshot"], s.dice.checkpoint()) == before
        assert Session.from_dict(s.to_dict()).to_dict() == s.to_dict()


def test_real_trade_spends_only_confirmed_copper_and_transfers_existing_instance():
    from test_adventure import world_value

    from rpg_vkr.domain.adventure import build_world

    s = hero("artisan")
    value = world_value()
    value["definitions"][1]["price_cp"] = 40
    for entity in value["entities"]:
        if entity["definition_id"] == "rope_type":
            entity.update(parent_id="seller", owner_id="seller")
    s.start_world(build_world(value, s, "own-trade-test"))
    rope = next(e for e in s.catalog.entities if e.definition_id == "rope_type")
    s.perform_gameplay(
        "trade_world",
        {"merchant": "seller", "item": rope.id, "operation": "buy", "quantity": 1},
        "trade",
    )
    assert s.gameplay["copper"] == 160
    assert sum(i["name"] == "Верёвка" for i in s.gameplay["items"]) == 1
    assert next(e for e in s.catalog.entities if e.id == rope.id).quantity == 1
    assert any(e.owner_id == "hero" and e.definition_id == "rope_type" for e in s.catalog.entities)
    assert Session.from_dict(s.to_dict()).to_dict() == s.to_dict()


def test_virtual_tutorial_never_changes_new_hero_progression():
    s = hero()
    before = s.to_dict(), s.dice.checkpoint()
    with pytest.raises(ValueError):
        s.submit("изучить учебник")
    assert (s.to_dict(), s.dice.checkpoint()) == before


def test_sale_and_consumption_update_the_single_physical_source_and_replay():
    from test_adventure import world_value

    from rpg_vkr.domain.adventure import build_world

    for consume in (False, True):
        s = hero("mage")
        value = world_value()
        value["definitions"][1]["price_cp"] = 40
        value["definitions"][1]["properties"]["unified_kind"] = "scroll_light"
        for entry in value["entities"]:
            if entry["definition_id"] == "rope_type":
                entry.update(parent_id="seller", owner_id="seller", quantity=1)
        s.start_world(build_world(value, s, "own-physical-test"))
        source = next(e.id for e in s.catalog.entities if e.definition_id == "rope_type")
        s.perform_gameplay("buy", {"merchant": "seller", "item": source}, "buy")
        if consume:
            s.perform_gameplay("consume", {"item": source}, "consume")
            assert not any(e.id == source for e in s.catalog.entities)
            assert not any(t.id == source for t in s.interaction_state().things)
            before = s.to_dict(), s.dice.checkpoint()
            with pytest.raises(ValueError):
                s.perform_gameplay("consume", {"item": source}, "consume-again")
            assert (s.to_dict(), s.dice.checkpoint()) == before
        else:
            s.perform_gameplay("sell", {"merchant": "seller", "item": source}, "sell")
            assert s.gameplay["copper"] == 180
            assert next(e for e in s.catalog.entities if e.id == source).owner_id == "seller"
            assert (
                next(t for t in s.interaction_state().things if t.id == source).holder == "seller"
            )
            before = s.to_dict(), s.dice.checkpoint()
            with pytest.raises(ValueError):
                s.perform_gameplay("sell", {"merchant": "seller", "item": source}, "sell-again")
            assert (s.to_dict(), s.dice.checkpoint()) == before
            s.perform_gameplay("buy", {"merchant": "seller", "item": source}, "rebuy")
            assert s.gameplay["copper"] == 140
            assert sum(i["id"] == source for i in s.gameplay["items"]) == 1
        assert Session.from_dict(s.to_dict()).to_dict() == s.to_dict()


def test_freeform_checks_use_canonical_preparation_and_dc_without_legacy_ranks():
    s = hero("artisan")
    check = {"ability": "intelligence", "dc": 30, "purpose": "починить замок", "skill": "repair"}
    turn = s.submit_challenge("Пробую починить замок", assessment=check)
    assert "подготовка(+2)" in turn.text and "DC 30" in turn.text
    pure = {"ability": "intelligence", "dc": 10, "purpose": "сообразить"}
    turn = s.submit_challenge("Пробую сообразить", assessment=pure)
    assert "подготовка(+0)" in turn.text
    turn = s.submit_challenge("Пытаюсь выдержать нагрузку", suggested_kind="endure")
    assert "Телосложение" in turn.text
    before = s.to_dict(), s.dice.checkpoint()
    with pytest.raises(ValueError):
        s.submit_challenge("Пытаюсь решить", assessment=check | {"skill": "faith"})
    assert (s.to_dict(), s.dice.checkpoint()) == before
    assert Session.from_dict(s.to_dict()).to_dict() == s.to_dict()


def test_actual_check_ui_and_ai_plan_use_the_same_canonical_tasks(qt_app, tmp_path, monkeypatch):
    from rpg_vkr.narrative.context import build_frame
    from rpg_vkr.narrative.ollama import OllamaClient
    from rpg_vkr.ui.main_window import MainWindow
    from rpg_vkr.ui.narrator_panel import catalog_context, request_challenge

    s = hero("artisan")
    window = MainWindow(session=s, saves=SaveSlots(tmp_path / "saves"))
    monkeypatch.setattr(window, "_confirm", lambda _: True)
    text = "Пробую починить сложный замок"
    try:
        state = catalog_context(window, text)
        assert "skill_rules" not in state
        assert state["class_tasks"]["repair"] == {"ability": "intelligence", "prepared": True}
        client = OllamaClient()
        client.models = ["fixture"]
        calls = []
        monkeypatch.setattr(client, "_start", lambda path, kind, body: calls.append(body))
        client.plan_world(build_frame(s), "fixture", text, state)
        prompt = calls[0]["messages"][0]["content"]
        assert "dc=5/10/15/20/25/30" in prompt and "class_tasks" in prompt
        assert request_challenge(
            window,
            text,
            assessment={
                "ability": "intelligence",
                "dc": 30,
                "purpose": "ремонт",
                "skill": "repair",
            },
        )
        assert "DC 30" in s.turns[-1].text and "подготовка(+2)" in s.turns[-1].text
        assert Session.from_dict(s.to_dict()).to_dict() == s.to_dict()
    finally:
        window._dirty = False
        window.close()
