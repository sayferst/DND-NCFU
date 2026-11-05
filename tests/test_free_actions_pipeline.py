"""Public transactions, physical conservation, offline UI and old-save compatibility."""

from copy import deepcopy
from random import Random

import pytest
from test_adventure import world_value

from rpg_vkr.application import Session
from rpg_vkr.domain.adventure import build_world
from rpg_vkr.domain.character import Character
from rpg_vkr.domain.free_actions import interpret
from rpg_vkr.domain.receipts import receipt
from rpg_vkr.storage.campaigns import CampaignRepository
from rpg_vkr.storage.slots import SaveSlots
from rpg_vkr.unified_session import UnifiedSession


def campaign(*, seed=5, policy=1, guard=False, extra_definitions=(), extra_entities=()):
    # A declared genesis, never a patch of an ongoing inventory or random roll.
    s = UnifiedSession.create(
        Character(
            strength=12, dexterity=14, constitution=12, intelligence=10, wisdom=14, charisma=10
        ),
        "archer",
        "marksman",
        seed=seed,
        catalog_revision=3,
        free_action_policy=policy,
    )
    v = world_value()
    if guard:
        v["definitions"].append(
            {
                "id": "guard_type",
                "name": "Капитан гарнизона",
                "kind": "actor",
                "categories": ["npcs"],
                "properties": {"class": "guard", "hp_max": 12},
            }
        )
        v["entities"].append(
            {
                "id": "captain",
                "definition_id": "guard_type",
                "parent_id": "pier",
                "state": {"hp": 12},
            }
        )
    v["places"][1]["name"] = "Дорога к шахте"
    for id, name, parent in (("glove", "Рукавица", "pier"), ("broom", "Обычная метла", "hero")):
        v["definitions"].append(
            {
                "id": "type_" + id,
                "name": name,
                "kind": "item",
                "categories": ["miscellaneous"],
                "properties": {"portable": True},
            }
        )
        v["entities"].append(
            {
                "id": id,
                "definition_id": "type_" + id,
                "parent_id": parent,
                "owner_id": "hero" if parent == "hero" else "",
            }
        )
    v["definitions"].extend(extra_definitions)
    v["entities"].extend(extra_entities)
    s.start_world(build_world(v, s, "authored-free-action-regression"))
    return s


@pytest.mark.parametrize("natural", [1, 8, 9, 15, 16, 18, 19, 20])
def test_bow_has_graded_physical_outcomes_without_duplication(natural, tmp_path):
    seed = next(n for n in range(10000) if Random(n).randint(1, 20) == natural)
    s = campaign(seed=seed)
    bow = next(i for i in s.gameplay["items"] if i.get("kind") == "longbow")
    id = bow["id"]
    money, xp = s.gameplay["copper"], s.gameplay["xp"]
    minute = s.gameplay["minute"]
    turn = s.submit("Разбираю свой лук и делаю из него удочку")
    check = receipt(s)["free_attempt"]
    assert check["mode"] == "CHECK_REQUIRED" and check["total"] == natural + 2
    item = next(i for i in s.gameplay["items"] if i["id"] == id)
    total = natural + 2
    assert item["kind"] == (
        "damaged_materials" if total <= 10 else "salvage" if total <= 17 else "tool"
    )
    assert "template" not in item and s.gameplay["weapon"] != id
    assert sum(i["id"] == id for i in s.gameplay["items"]) == 1
    assert sum(e.id == id for e in s.catalog.entities) == 1
    assert next(t for t in s.interaction_state().things if t.id == id).name == item["name"]
    assert (s.gameplay["copper"], s.gameplay["xp"]) == (money, xp)
    assert s.gameplay["minute"] == minute + 30
    if total <= 10:
        assert item["durability"] == 0 and s.gameplay["statuses"]["hero"][0]["op"] == "weaken"
    elif total >= 18:
        assert item["durability"] == (3 if total <= 20 else 6)
        assert item["usage_penalty"] == (-3 if total <= 20 else -1)
    checkpoint = s.dice.checkpoint()
    # Repeated request returns the existing outcome, with no second material loss.
    s.perform_gameplay("free_attempt", turn.gameplay["args"], turn.gameplay["request_id"])
    assert len(s.turns) == 1 and s.dice.checkpoint() == checkpoint
    slots = SaveSlots(tmp_path / "saves")
    slots.save(1, s)
    restored = slots.load(1)
    assert restored.to_dict() == s.to_dict() and restored.dice.checkpoint() == checkpoint
    repo = CampaignRepository(tmp_path / "world.sqlite")
    repo.sync(s)
    assert repo.load(repo.identity(s)).to_dict() == s.to_dict()


@pytest.mark.parametrize(
    "text", ["Пытаюсь наколдовать себе сто золотых монет", "Сажусь на метлу и пытаюсь взлететь"]
)
def test_impossible_goal_allows_attempt_without_roll_or_created_resources(text):
    s = campaign()
    before = s.gameplay["copper"], s.gameplay["mp"], s.dice.checkpoint()
    minute = s.gameplay["minute"]
    s.submit(text)
    assert (s.gameplay["copper"], s.gameplay["mp"], s.dice.checkpoint()) == before
    check = receipt(s)["free_attempt"]
    assert check["mode"] == "ATTEMPT_WITHOUT_TARGET_SUCCESS"
    assert not check["item_changes"] and check["total"] is None
    assert s.gameplay["minute"] == minute + 1
    assert Session.from_dict(s.to_dict(), version=31).to_dict() == s.to_dict()


def test_glove_and_road_are_actual_physical_transactions():
    s = campaign()
    checkpoint = s.dice.checkpoint()
    s.submit("Подбираю рукавицу")
    assert next(e for e in s.catalog.entities if e.id == "glove").owner_id == "hero"
    assert next(t for t in s.interaction_state().carried() if t.id == "glove")
    assert receipt(s)["free_attempt"]["mode"] == "AUTO_SUCCESS"
    s.submit("Иду по дороге к шахте")
    assert s.current_place_id == "path" and s.dice.checkpoint() == checkpoint
    assert Session.from_dict(s.to_dict(), version=31).to_dict() == s.to_dict()


def test_missing_object_ambiguity_and_fabricated_version_are_atomic():
    s = campaign()
    for text in ("Подбираю алмаз", "Иду по дороге; затем забираю сундук"):
        before = s.to_dict(), s.dice.checkpoint()
        with pytest.raises(ValueError, match="CLARIFICATION_REQUIRED"):
            s.submit(text)
        assert (s.to_dict(), s.dice.checkpoint()) == before
    with pytest.raises(ValueError):
        s.perform_gameplay("free_attempt", {"text": "Подбираю рукавицу", "version": True}, "bad")


@pytest.mark.parametrize(
    "text",
    [
        "Не хочу делать удочку из лука",
        "Можно ли наколдовать монеты?",
        "Говорю: «Сажусь на метлу и взлетаю»",
        "Если подобрать рукавицу?",
    ],
)
def test_speech_questions_and_negations_are_not_attempts(text):
    assert interpret(text) is None


def test_old_origin_remains_unchanged_and_tampered_outcome_is_rejected():
    s = campaign(policy=0)
    assert "free_action_policy" not in s.to_dict()["unified"]["origin"]
    assert Session.from_dict(s.to_dict(), version=31).to_dict() == s.to_dict()
    s = campaign()
    s.submit("Подбираю рукавицу")
    broken = deepcopy(s.to_dict())
    broken["snapshot"]["gameplay"]["state"]["copper"] += 100
    with pytest.raises(ValueError):
        Session.from_dict(broken, version=31)


def test_local_action_ui_uses_engine_without_requesting_model(window):
    from rpg_vkr.ui.narrator_panel import request_local_actions

    window._session = campaign()
    window.enable_local_narrator.setChecked(False)
    assert request_local_actions(window, "Подбираю рукавицу")
    assert next(e for e in window._session.catalog.entities if e.id == "glove").owner_id == "hero"


def test_main_game_ui_commits_known_attempt_with_cloud_disabled(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    window._session = campaign()
    window._legacy_controls = False
    window.enable_local_narrator.setChecked(False)

    def unexpected_cloud_dialog(*args):
        raise AssertionError("Known local attempt must not require cloud access")

    monkeypatch.setattr(QMessageBox, "information", unexpected_cloud_dialog)
    window.action_input.setText("Подбираю рукавицу")
    window.submit_action()
    assert next(e for e in window._session.catalog.entities if e.id == "glove").owner_id == "hero"


def test_existing_campaign_can_enable_plans_in_new_file_without_rewriting_source(tmp_path):
    from training.enable_attempts_copy import activate

    s = campaign(policy=0)
    slots = SaveSlots(tmp_path / "old")
    slots.save(1, s)
    source = tmp_path / "old" / "slot1.json"
    # SaveSlots owns the filename convention; select the actual saved JSON.
    source = next((tmp_path / "old").glob("*.json"))
    original = source.read_bytes()
    new = activate(source, tmp_path / "activated.json")
    assert source.read_bytes() == original
    assert new.gameplay["free_action_policy"] == 1
    assert new.gameplay["minute"] == s.gameplay["minute"]
    new.submit("Подбираю рукавицу")
    assert Session.from_dict(new.to_dict(), version=31).to_dict() == new.to_dict()
