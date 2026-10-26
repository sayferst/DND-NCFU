"""Versioned proposed HP/ST/MP formulas for the second playable revision only."""

from copy import deepcopy
from dataclasses import replace

from rpg_vkr.domain.character import ability_modifier
from rpg_vkr.domain.gameplay import effective_character

RESOURCE_VERSION = "hero-resources-1"
COSTS = {
    "attack": 2,
    "cast": 1,
    "dodge": 1,
    "move": 1,
    "bandage": 1,
    "craft": 3,
    "repair": 2,
    "prepare": 1,
}


def limits(state, character, level):
    if type(level) is not int or not 1 <= level <= 20:
        raise ValueError("Нужен уровень 1–20.")
    character = effective_character(state, character)
    strength = ability_modifier(character.strength)
    constitution = ability_modifier(character.constitution)
    intelligence = ability_modifier(character.intelligence)
    magic = state["identity"]["profile"] in {"mage", "healer"} or bool(state["spells"])
    return {
        "hp": 16
        + 2 * constitution
        + max(1, 6 + constitution) * (level - 1)
        + (2 if "resilient" in state["talents"] else 0),
        "st": max(10, 20 + 2 * (strength + constitution))
        + 3 * (level - 1)
        + (4 if "enduring" in state["talents"] else 0),
        "mp": max(4, 12 + 4 * intelligence + 4 * (level - 1))
        + (4 if "focus" in state["talents"] else 0)
        if magic
        else 0,
    }


def refresh(state, world, character, level, *, initial=False, rest=False):
    state = deepcopy(state)
    caps = limits(state, character, level)
    delta = caps["hp"] - world.max_hp
    hp = 0 if world.hp == 0 else min(caps["hp"], world.hp + max(0, delta))
    world = replace(world, max_hp=caps["hp"], hp=caps["hp"] if rest else hp)
    stamina = state.get("st", caps["st"])
    stamina += max(0, caps["st"] - state.get("st_cap", caps["st"]))
    state.update(
        resource_version=RESOURCE_VERSION,
        st=min(stamina, caps["st"]),
        st_cap=caps["st"],
        mp_cap=caps["mp"],
    )
    state["mp"] = min(state["mp"], caps["mp"])
    if initial or rest:
        state["st"] = caps["st"]
        state["mp"] = caps["mp"]
    return state, world
