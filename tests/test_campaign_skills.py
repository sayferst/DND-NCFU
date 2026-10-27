"""Actual skill checks, authenticated XP origins, UI and both save paths."""

import json
from copy import deepcopy

import pytest

from rpg_vkr.application import Session
from rpg_vkr.domain.character import ABILITY_NAMES, Character
from rpg_vkr.domain.progression import ARCHETYPES
from rpg_vkr.storage.campaigns import CampaignRepository
from rpg_vkr.storage.knowledge import export_session, restore_session
from rpg_vkr.storage.slots import SaveSlots


def hero():
    return Session.create_hero(
        Character(**dict(zip(ABILITY_NAMES, ARCHETYPES["fighter"].scores, strict=True))),
        "fighter",
        seed=13,
    )


def trained():
    session = hero()
    session.enable_d20_progress()
    session.train_skill("athletics")
    session.train_skill("athletics")
    return session


def test_skill_changes_actual_outcome_and_survives_replay():
    old, new = hero(), trained()
    attempt = "пытаюсь взобраться на стену"
    plain, skilled = old.submit_challenge(attempt), new.submit_challenge(attempt)
    assert plain.roll == skilled.roll
    assert not plain.check.succeeded and skilled.check.succeeded
    assert skilled.check.modifier == plain.check.modifier + 4
    assert new.d20_progress.xp == 10
    new.submit_challenge(attempt)
    assert new.d20_progress.xp == 10
    assert Session.from_dict(new.to_dict()).to_dict() == new.to_dict()


def test_general_assessment_uses_registered_profession_and_replays():
    session = trained()
    session.train_skill("repair")
    turn = session.submit_challenge(
        "пытаюсь оценить возможность ремонта механизма",
        assessment={
            "ability": "intelligence",
            "dc": 15,
            "purpose": "оценить повреждения механизма",
            "skill": "repair",
        },
    )
    assert turn.check.modifier == 1  # INT 8 -> -1, rank 1 -> +2.
    assert turn.challenge.assessment["skill"] == "repair"
    assert Session.from_dict(session.to_dict()).to_dict() == session.to_dict()


def test_skill_assessment_on_legacy_campaign_does_not_consume_roll():
    session = hero()
    before = session.to_dict(), session.dice.checkpoint()
    with pytest.raises(ValueError):
        session.submit_challenge(
            "пытаюсь оценить механизм",
            assessment={
                "ability": "intelligence",
                "dc": 15,
                "purpose": "осмотр механизма",
                "skill": "repair",
            },
        )
    assert (session.to_dict(), session.dice.checkpoint()) == before


def test_skill_campaign_json_sqlite_and_archive_roundtrip(tmp_path):
    session = trained()
    session.submit_challenge("пытаюсь взобраться на стену")
    slots = SaveSlots(tmp_path / "saves")
    slots.save(1, session)
    assert (
        json.loads((tmp_path / "saves/slot-1.json").read_text(encoding="utf-8"))["schema_version"]
        == 23
    )
    assert slots.load(1).to_dict() == session.to_dict()
    export_session(session, tmp_path / "world.sqlite3")
    assert restore_session(tmp_path / "world.sqlite3").to_dict() == session.to_dict()
    repository = CampaignRepository(tmp_path / "campaigns.sqlite3")
    repository.sync(session)
    session.train_skill("knowledge")
    repository.sync(session)
    assert repository.load(repository.identity(session)).to_dict() == session.to_dict()


def test_forged_xp_rejected_even_if_progress_ledger_is_internally_valid():
    session = trained()
    data = session.to_dict()
    data["d20_progress"] = session.d20_progress.grant_xp("fake", 1000, "Проза ИИ").to_dict()
    with pytest.raises(ValueError, match="не подтверждена"):
        Session.from_dict(data)


def test_past_check_cannot_use_future_training():
    session = trained()
    session.submit_challenge("пытаюсь взобраться на стену")
    data = session.to_dict()
    data["d20_progress"]["events"] = data["d20_progress"]["events"][2:]
    with pytest.raises(ValueError, match="Бонус навыка"):
        Session.from_dict(data)


def test_legacy_schema_unchanged_and_no_implicit_migration(tmp_path):
    session = hero()
    before = deepcopy(session.to_dict())
    assert "d20_progress" not in before and session.schema_version == 22
    slots = SaveSlots(tmp_path)
    slots.save(1, session)
    restored = slots.load(1)
    assert restored.d20_progress is None and restored.to_dict() == before
    session.submit("осмотреться")
    with pytest.raises(ValueError):
        session.enable_d20_progress()
    with pytest.raises(ValueError):
        Session.from_dict(trained().to_dict(), version=22)


def test_creation_and_skill_ui_spend_real_points(window, qt_app):
    session = hero()
    session.enable_d20_progress()
    window._session = session
    window._refresh_character()
    window.skill_choice.setCurrentIndex(window.skill_choice.findData("athletics"))
    window.train_skill_button.click()
    assert session.d20_progress.rank("athletics") == 0
    window.skill_apply_button.click()
    assert session.d20_progress.rank("athletics") == 1
    assert session.d20_progress.skill_points == 12 and window._dirty
    window.train_skill_button.click()
    window.skill_apply_button.click()
    assert session.d20_progress.rank("athletics") == 2
    assert not window.train_skill_button.isEnabled()
