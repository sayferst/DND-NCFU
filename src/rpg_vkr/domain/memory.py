"""Versioned state differences for new turns; old histories start at a known baseline."""

import hashlib
import json
from dataclasses import asdict, dataclass

from rpg_vkr.domain.character import ABILITY_NAMES, Character
from rpg_vkr.domain.combat import ACTORS, CombatState
from rpg_vkr.domain.progression import ARCHETYPES, HeroProgress
from rpg_vkr.domain.world import LOCATIONS, WorldState

MEMORY_VERSION = "world-memory-1"


def snapshot(world, character, combat, progress):
    fields = {"world." + key: value for key, value in asdict(world).items()}
    fields.update({"hero." + key: value for key, value in asdict(character).items()})
    fields.update(
        {"combat." + key: getattr(combat, key) for key in ("active", "surprise", "rounds")}
    )
    for actor in combat.actors:
        fields[f"actor.{actor.id}.hp"] = actor.hp
        fields[f"actor.{actor.id}.disposition"] = actor.disposition
    fields.update(
        {
            "progress.class_id": progress.class_id,
            "progress.xp": progress.xp,
            "progress.level": progress.level,
        }
    )
    fields.update({"training." + key: progress.training(key) for key in ABILITY_NAMES})
    return tuple(sorted(fields.items()))


def digest(state):
    return hashlib.sha256(
        json.dumps(dict(state), sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def validate_snapshot(state):
    fields = dict(state)
    expected = dict(snapshot(WorldState(), Character(), CombatState(), HeroProgress()))
    if len(state) != len(fields) or fields.keys() != expected.keys():
        raise ValueError("Invalid memory fields")
    world = WorldState.from_dict({key: fields["world." + key] for key in asdict(WorldState())})
    Character.from_dict({key: fields["hero." + key] for key in asdict(Character())})
    combat = CombatState.from_dict(
        {
            "actors": [
                {
                    "id": key,
                    "hp": fields[f"actor.{key}.hp"],
                    "disposition": fields[f"actor.{key}.disposition"],
                }
                for key in ACTORS
            ],
            **{key: fields["combat." + key] for key in ("active", "surprise", "rounds")},
        }
    )
    if combat.active and (world.hp == 0 or ACTORS[combat.active][1] != world.location):
        raise ValueError("Invalid memory encounter")
    class_id = fields["progress.class_id"]
    if not isinstance(class_id, str) or class_id not in {"legacy", *ARCHETYPES}:
        raise ValueError("Invalid memory class")
    if any(
        type(fields[key]) is not int or not 0 <= fields[key] <= 8
        for key in ("progress.xp", *("training." + key for key in ABILITY_NAMES))
    ):
        raise ValueError("Invalid memory progression")
    level = fields["progress.level"]
    if type(level) is not int or level != (2 if fields["progress.xp"] >= 4 else 1):
        raise ValueError("Invalid memory level")
    if class_id == "legacy" and any(
        fields[key] for key in fields if key.startswith("training.") or key == "progress.xp"
    ):
        raise ValueError("Legacy memory cannot grant growth")
    return fields


@dataclass(frozen=True)
class Change:
    field: str
    before: str | int | bool | None
    after: str | int | bool | None


@dataclass(frozen=True)
class WorldEvent:
    turn_index: int
    location: str
    changes: tuple[Change, ...]
    roll_indices: tuple[int, ...]
    before_hash: str
    after_hash: str


def event_dict(event):
    return asdict(event) | {
        "changes": [asdict(c) for c in event.changes],
        "roll_indices": list(event.roll_indices),
    }


def roll_indices(turn):
    rolls = turn.combat.outcome.rolls if turn.combat else ((turn.roll,) if turn.roll else ())
    return tuple(roll.index for roll in rolls)


@dataclass(frozen=True)
class WorldMemory:
    base_turn: int
    baseline: tuple
    events: tuple[WorldEvent, ...] = ()

    def append(self, turn, before, after):
        expected = self.events[-1].after_hash if self.events else digest(self.baseline)
        if digest(before) != expected:
            raise ValueError("World changed outside recorded actions")
        old = dict(before)
        changes = tuple(
            Change(key, old[key], value)
            for key, value in after
            if type(old[key]) is not type(value) or old[key] != value
        )
        event = WorldEvent(
            self.base_turn + len(self.events) + 1,
            dict(after)["world.location"],
            changes,
            roll_indices(turn),
            expected,
            digest(after),
        )
        return WorldMemory(self.base_turn, self.baseline, (*self.events, event))

    def to_dict(self):
        return {
            "version": MEMORY_VERSION,
            "base_turn": self.base_turn,
            "baseline": dict(self.baseline),
            "events": [event_dict(event) for event in self.events],
        }

    @classmethod
    def from_dict(cls, data, turns, final):
        if (
            not isinstance(data, dict)
            or set(data) != {"version", "base_turn", "baseline", "events"}
            or data["version"] != MEMORY_VERSION
            or type(data["base_turn"]) is not int
            or not 0 <= data["base_turn"] <= len(turns)
            or not isinstance(data["baseline"], dict)
            or not isinstance(data["events"], list)
            or len(data["events"]) != len(turns) - data["base_turn"]
        ):
            raise ValueError("Invalid world memory")
        baseline = tuple(sorted(data["baseline"].items()))
        fields = validate_snapshot(baseline)
        result = cls(data["base_turn"], baseline)
        for offset, raw in enumerate(data["events"], data["base_turn"]):
            if not isinstance(raw, dict) or set(raw) != set(WorldEvent.__dataclass_fields__):
                raise ValueError("Invalid world event")
            if (
                type(raw["turn_index"]) is not int
                or raw["turn_index"] != offset + 1
                or raw["location"] not in LOCATIONS
                or not isinstance(raw["changes"], list)
                or not isinstance(raw["roll_indices"], list)
                or any(type(i) is not int for i in raw["roll_indices"])
                or raw["roll_indices"] != list(roll_indices(turns[offset]))
                or raw["before_hash"] != digest(tuple(fields.items()))
            ):
                raise ValueError("World event context mismatch")
            before = tuple(sorted(fields.items()))
            seen = set()
            for change in raw["changes"]:
                if not isinstance(change, dict) or set(change) != {"field", "before", "after"}:
                    raise ValueError("Invalid state change")
                key = change["field"]
                if (
                    not isinstance(key, str)
                    or key not in fields
                    or key in seen
                    or type(change["before"]) is not type(fields[key])
                    or change["before"] != fields[key]
                    or (
                        type(change["after"]) is type(fields[key])
                        and change["after"] == fields[key]
                    )
                ):
                    raise ValueError("State change mismatch")
                seen.add(key)
                fields[key] = change["after"]
            after = tuple(sorted(fields.items()))
            validate_snapshot(after)
            result = result.append(turns[offset], before, after)
            # JSON canonicalisation distinguishes bool from int and enforces ordering.
            if json.dumps(event_dict(result.events[-1]), sort_keys=True) != json.dumps(
                raw, sort_keys=True
            ):
                raise ValueError("Event record mismatch")
        if tuple(sorted(fields.items())) != final:
            raise ValueError("Final world does not match event memory")
        return result
