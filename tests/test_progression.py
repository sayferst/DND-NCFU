"""Independent expected creation budgets, learning rewards and audit replay."""

from copy import deepcopy
from dataclasses import replace

import pytest

from rpg_vkr.application import Session
from rpg_vkr.domain.character import ABILITY_NAMES, Character
from rpg_vkr.domain.progression import ARCHETYPES, HeroProgress


def created(class_id="fighter", seed=5):
    scores = dict(zip(ABILITY_NAMES, ARCHETYPES[class_id].scores, strict=True))
    return Session.create_hero(Character(name="Мира", **scores), class_id, seed=seed)


@pytest.mark.parametrize(
    "class_id,gold,bandages,equipment",
    [
        ("fighter", 8, 2, "Учебный меч"),
        ("scout", 10, 1, "Дорожный нож"),
        ("scholar", 9, 1, "Дорожный посох"),
    ],
)
def test_creation_profile_and_owned_kit(class_id, gold, bandages, equipment):
    session = created(class_id)
    assert sum(session.character.score(key) - 8 for key in ABILITY_NAMES) == 24
    assert session.progress.level == 1
    assert session.progress.xp == 0
    assert session.world.gold == gold
    assert session.world.bandages == bandages
    assert (session.world.hp, session.world.max_hp) == (12, 12)
    assert equipment in session.submit("инвентарь").text
    assert "Дорожный учебник" in session.submit("инвентарь").text


@pytest.mark.parametrize(
    "changes", [{"strength": 15}, {"charisma": 11}, {"strength": 17}, {"strength": 7}]
)
def test_creation_rejects_wrong_budget_or_bounds(changes):
    character = replace(created().character, **changes)
    with pytest.raises(ValueError):
        Session.create_hero(character, "fighter")


def test_unknown_profile_cannot_create_a_hero():
    with pytest.raises(ValueError):
        Session.create_hero(Character(), "wizard-that-does-not-exist")


def test_successful_work_and_book_grow_separate_abilities_and_level_without_healing():
    session = created(seed=5)
    session = Session(
        seed=5,
        character=session.character,
        world=replace(session.world, hp=7),
        progress=session.progress,
    )
    turn = session.submit("помочь разгрузить телегу")
    assert turn.roll.value == 20
    assert turn.check.total == 23
    assert session.character.strength == 17
    assert session.character.intelligence == 8
    assert session.progress.xp == 2
    assert session.progress.level == 1
    assert session.progress.events[0].before_score == 16
    assert session.progress.events[0].after_score == 17
    session.submit("изучить учебник")
    assert session.character.intelligence == 9
    assert session.progress.xp == 4
    assert session.progress.level == 2
    assert (session.world.hp, session.world.max_hp) == (7, 14)
    assert "Уровень 2" in session.turns[-1].text
    assert session.progress.events[1].max_hp_delta == 2
    session.submit("использовать бинт")
    assert session.world.hp == 11
    assert session.progress.xp == 4


def test_failed_practice_grants_one_learning_point_and_does_not_increase_score():
    session = created(seed=42)
    turn = session.submit("помочь разгрузить телегу")
    assert turn.roll.value == 4
    assert not turn.check.succeeded
    assert session.progress.xp == 1
    assert session.progress.training("strength") == 1
    assert session.character.strength == 16


def test_repeat_and_remote_practice_do_not_draw_dice_or_grant_rewards():
    session = created(seed=5)
    session.submit("идти на дорогу")
    assert session.submit("помочь разгрузить телегу").roll is None
    assert session.progress.xp == 0
    session.submit("идти к воротам")
    session.submit("помочь разгрузить телегу")
    previous = session.progress
    for _ in range(3):
        assert session.submit("помочь разгрузить телегу").roll is None
        assert session.progress == previous
    assert session.submit("бросить d20").roll.index == 2
    session.submit("изучить учебник")
    previous = session.progress
    session.submit("изучить учебник")
    assert session.progress == previous


def test_legacy_history_does_not_retroactively_grant_experience():
    session = Session(seed=42)
    session.submit("идти на дорогу")
    session.submit("исследовать дорогу")
    for command in ("изучить учебник", "помочь разгрузить телегу"):
        assert session.submit(command).roll is None
    assert session.progress == HeroProgress()
    assert session.character == Character()
    assert Session.from_dict(session.to_dict()).progress == HeroProgress()


@pytest.mark.parametrize("class_id", list(ARCHETYPES))
def test_complete_finite_learning_cycle_and_restore(class_id):
    session = created(class_id, seed=42)
    for command in (
        "помочь разгрузить телегу",
        "изучить учебник",
        "идти на дорогу",
        "исследовать дорогу",
    ):
        session.submit(command)
    assert 4 <= session.progress.xp <= 6
    assert session.progress.level == 2
    assert session.world.max_hp == 14
    assert len(session.progress.events) == 3
    restored = Session.from_dict(session.to_dict())
    assert restored.to_dict() == session.to_dict()
    previous = restored.progress
    for command in (
        "исследовать дорогу",
        "изучить учебник",
        "идти к воротам",
        "помочь разгрузить телегу",
    ):
        restored.submit(command)
    assert restored.progress == previous
    assert restored.submit("бросить d20").roll.value == session.submit("бросить d20").roll.value


def test_free_checks_and_information_do_not_farm_progression():
    session = created()
    for command in ("проверить силу", "бросить d20", "развитие", "осмотреться", "состояние"):
        session.submit(command)
    assert session.progress.xp == 0
    assert session.character.strength == 16


def test_created_hero_cannot_use_free_editor_to_replace_recorded_growth():
    session = created()
    previous = session.to_dict()
    with pytest.raises(ValueError):
        session.edit_character(replace(session.character, strength=20))
    assert session.to_dict() == previous


def test_failure_after_roll_restores_character_world_progress_and_rng(monkeypatch):
    session = created()
    before = session.to_dict()

    def fail(*args):
        raise ValueError("simulated reward calculation failure")

    monkeypatch.setattr(HeroProgress, "award", fail)
    with pytest.raises(ValueError):
        session.submit("помочь разгрузить телегу")
    assert session.to_dict() == before
    assert session.submit("бросить d20").roll.value == 20
    assert session.turns[-1].roll.index == 1


@pytest.mark.parametrize(
    "key,value",
    [
        ("points", 99),
        ("points", True),
        ("turn_index", 0),
        ("turn_index", True),
        ("before_score", 1),
        ("after_score", 30),
        ("after_level", 2),
        ("max_hp_delta", 2),
        ("ability", "wisdom"),
        ("activity", "book"),
        ("reason", "invented reward"),
        ("roll_index", True),
        ("rules_version", "future"),
    ],
)
def test_modified_development_event_is_rejected(key, value):
    session = created()
    session.submit("помочь разгрузить телегу")
    data = deepcopy(session.to_dict())
    data["progress"]["events"][0][key] = value
    with pytest.raises(ValueError):
        Session.from_dict(data)


def test_missing_event_cannot_silently_drop_completed_study():
    session = created()
    session.submit("изучить учебник")
    data = session.to_dict()
    data["progress"]["events"] = []
    data["character"]["intelligence"] = 8
    with pytest.raises(ValueError, match="events"):
        Session.from_dict(data)


def test_duplicate_activity_is_rejected_by_award():
    session = created()
    session.submit("изучить учебник")
    with pytest.raises(ValueError):
        session.progress.award("book", 2, None, None)


@pytest.mark.parametrize(
    "key,value",
    [
        ("rules_version", "unknown"),
        ("class_id", []),
        ("initial", None),
        ("events", "not-a-list"),
    ],
)
def test_malformed_progress_container_is_rejected(key, value):
    session = created()
    data = session.to_dict()
    data["progress"][key] = value
    with pytest.raises(ValueError):
        Session.from_dict(data)


def test_duplicate_recorded_event_and_wrong_level_health_are_rejected():
    session = created()
    session.submit("изучить учебник")
    data = session.to_dict()
    data["progress"]["events"].append(deepcopy(data["progress"]["events"][0]))
    with pytest.raises(ValueError):
        Session.from_dict(data)
    data = session.to_dict()
    data["world"]["max_hp"] = 13
    with pytest.raises(ValueError):
        Session.from_dict(data)
