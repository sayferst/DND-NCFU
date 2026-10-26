"""Original small worlds; all data and caches live in pytest temporary directories."""

from dataclasses import replace

import pytest
from test_pipeline import small_package  # noqa: F401

from rpg_vkr.application import Session
from rpg_vkr.domain.adventure import build_world
from rpg_vkr.domain.character import ABILITY_NAMES, Character
from rpg_vkr.domain.progression import ARCHETYPES


def new_session(*, world_id=None, scene="Площадь у кузницы"):
    character = Character(
        name="Путник", **dict(zip(ABILITY_NAMES, ARCHETYPES["fighter"].scores, strict=True))
    )
    session = Session.create_hero(character, "fighter", seed=37)
    if world_id:
        session.campaign = replace(session.campaign, world_id=world_id)
    session.enable_gameplay(
        {
            "species": "human",
            "profile": "mage",
            "age": 25,
            "background": "Путешественник",
            "appearance": "Дорожный плащ",
            "skills": {"arcana": 1},
            "talent": "",
        },
        revision=5,
    )
    value = {
        "title": "Малый район",
        "opening": "У ворот кузницы слышен звон молотка.",
        "private_plot": "СКРЫТАЯ_МЕТКА: тайный план не известен встречным.",
        "hooks": ["Узнать о ремесле"],
        "start": "square",
        "places": [
            {"id": "square", "name": scene, "parent": "", "description": scene},
            {
                "id": "tower",
                "name": "Дальняя башня",
                "parent": "square",
                "description": "За поворотом стоит башня.",
            },
        ],
        "definitions": [
            {
                "id": "resident_type",
                "name": "Ильма",
                "kind": "actor",
                "categories": ["npcs"],
                "properties": {"hp_max": 12, "class": "resident"},
            },
            {
                "id": "watcher_type",
                "name": "Орн",
                "kind": "actor",
                "categories": ["npcs"],
                "properties": {"hp_max": 12, "class": "resident"},
            },
            {
                "id": "blade_type",
                "name": "Выставочный меч",
                "kind": "item",
                "categories": ["weapons"],
                "price_cp": 100,
                "properties": {"appearance": "Прямой клинок с простой рукоятью"},
            },
        ],
        "entities": [
            {
                "id": "witness",
                "definition_id": "resident_type",
                "parent_id": "square",
                "state": {"hp": 12},
            },
            {
                "id": "distant",
                "definition_id": "watcher_type",
                "parent_id": "tower",
                "state": {"hp": 12},
            },
            {
                "id": "display_blade",
                "definition_id": "blade_type",
                "parent_id": "witness",
                "owner_id": "witness",
            },
        ],
    }
    session.start_world(build_world(value, session, "own-offline-fixture"))
    return session


@pytest.fixture
def learning_session():
    return new_session()


@pytest.fixture
def new_session_factory():
    return new_session
