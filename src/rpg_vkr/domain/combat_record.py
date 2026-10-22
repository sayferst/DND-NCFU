"""Replay each combat action against its recorded inputs and shared dice sequence."""

import json
from dataclasses import asdict, dataclass

from rpg_vkr.domain.character import Character
from rpg_vkr.domain.combat import RULES_VERSION, CombatOutcome, CombatState, perform_combat
from rpg_vkr.domain.world import WorldState


@dataclass(frozen=True)
class CombatRecord:
    before: CombatState
    world_before: WorldState
    character: Character
    class_id: str
    command: str
    outcome: CombatOutcome
    rules_version: str = RULES_VERSION

    def to_dict(self) -> dict:
        result = asdict(self)
        result["before"] = self.before.to_dict()
        result["outcome"]["state"] = self.outcome.state.to_dict()
        result["outcome"]["rolls"] = [asdict(roll) for roll in self.outcome.rolls]
        return result


def canonical(value):
    # JSON also distinguishes True from 1 and 1.0 from 1 during validation.
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def restore_record(data, action: str, previous: CombatState, dice) -> CombatRecord:
    if not isinstance(data, dict) or set(data) != set(CombatRecord.__dataclass_fields__):
        raise ValueError("Invalid combat record")
    if data["rules_version"] != RULES_VERSION or data["command"] != action:
        raise ValueError("Combat rules or action mismatch")
    before = CombatState.from_dict(data["before"])
    if before != previous:
        raise ValueError("Combat history chain mismatch")
    world = WorldState.from_dict(data["world_before"])
    character = Character.from_dict(data["character"])
    if not isinstance(data["class_id"], str):
        raise ValueError("Invalid combat profile")
    outcome = perform_combat(before, world, character, data["class_id"], action, dice)
    result = CombatRecord(before, world, character, data["class_id"], action, outcome)
    if canonical(result.to_dict()) != canonical(data):
        raise ValueError("Combat record does not match replay")
    return result
