"""Session state and command routing; narration never performs dice calculations."""

from dataclasses import asdict, dataclass

from rpg_vkr.commands import normalise_action
from rpg_vkr.domain.character import (
    ABILITY_NAMES,
    AbilityCheck,
    Character,
    describe_check,
    resolve_ability_check,
)
from rpg_vkr.domain.dice import D20Roll, DiceRoller
from rpg_vkr.domain.world import WORLD_COMMANDS, WorldState, perform_action
from rpg_vkr.narrative.offline import INTRODUCTION, respond

ROLL_COMMANDS = {"бросить d20", "бросить д20"}
CHECK_COMMANDS = {
    "проверить силу": "strength",
    "проверить ловкость": "dexterity",
    "проверить телосложение": "constitution",
    "проверить интеллект": "intelligence",
    "проверить мудрость": "wisdom",
    "проверить харизму": "charisma",
}
MAX_TURNS = 2000


@dataclass(frozen=True)
class Turn:
    action: str
    speaker: str
    text: str
    roll: D20Roll | None = None
    check: AbilityCheck | None = None


def _text(value: object, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError("Invalid session text")
    return value


class Session:
    def __init__(
        self,
        seed: int | None = None,
        character: Character | None = None,
        world: WorldState | None = None,
    ) -> None:
        self.dice = DiceRoller(seed)
        self.character = Character() if character is None else character
        self.world = WorldState() if world is None else world
        self.introduction = INTRODUCTION
        self._turns: list[Turn] = []

    @property
    def turns(self) -> tuple[Turn, ...]:
        return tuple(self._turns)

    def submit(self, action: str) -> Turn:
        action = _text(action, 500).strip()
        if len(self._turns) >= MAX_TURNS:
            raise ValueError("Достигнут предел в 2000 действий. Сохраните сессию.")
        command = normalise_action(action)
        checkpoint = self.dice.checkpoint()
        try:
            turn, world = self._resolve_turn(action, command)
        except Exception:
            self.dice.restore(checkpoint)
            raise
        self.world = world
        self._turns.append(turn)
        return turn

    def _resolve_turn(self, action: str, command: str) -> tuple[Turn, WorldState]:
        if command in WORLD_COMMANDS:
            outcome = perform_action(self.world, command, self.character, self.dice)
            turn = Turn(action, "Мир", outcome.text, outcome.roll, outcome.check)
            return turn, outcome.state
        elif command in ROLL_COMMANDS:
            roll = self.dice.roll_d20()
            turn = Turn(action, "Кубик", f"d20 → {roll.value}", roll)
        elif command in CHECK_COMMANDS:
            ability = CHECK_COMMANDS[command]
            roll = self.dice.roll_d20()
            check = resolve_ability_check(ability, self.character.score(ability), roll.value, 10)
            turn = Turn(action, "Правила", describe_check(check, roll.value), roll, check)
        else:
            turn = Turn(action, "Рассказчик", respond(action))
        return turn, self.world

    def edit_character(self, character: Character) -> bool:
        if not isinstance(character, Character):
            raise ValueError("Invalid character")
        if character == self.character:
            return False
        if len(self._turns) >= MAX_TURNS:
            raise ValueError("Достигнут предел действий. Сохраните сессию и начните новую.")
        summary = "; ".join(
            f"{label}: {character.score(key)}" for key, label in ABILITY_NAMES.items()
        )
        turn = Turn(
            "Изменить персонажа", "Система", f"Профиль изменён: {character.name}. {summary}."
        )
        self.character = character
        self._turns.append(turn)
        return True

    def to_dict(self) -> dict:
        return {
            "seed": self.dice.seed,
            "character": asdict(self.character),
            "world": asdict(self.world),
            "introduction": self.introduction,
            "turns": [asdict(turn) for turn in self._turns],
        }

    @classmethod
    def from_dict(cls, data: object, version: int = 4) -> "Session":
        if type(version) is not int or version not in (1, 2, 3, 4):
            raise ValueError("Unsupported session version")
        keys = {"seed", "introduction", "turns"}
        if version >= 2:
            keys.add("character")
        if version >= 3:
            keys.add("world")
        if not isinstance(data, dict) or set(data) != keys:
            raise ValueError("Invalid session structure")
        # A missing seed must never silently create a new random sequence.
        if type(data["seed"]) is not int:
            raise ValueError("Missing session seed")
        character = Character() if version == 1 else Character.from_dict(data["character"])
        if version < 3:
            world = WorldState()
        elif version == 3:
            old_world = data["world"]
            legacy_keys = set(asdict(WorldState())) - {"market_known", "trading"}
            if not isinstance(old_world, dict) or set(old_world) != legacy_keys:
                raise ValueError("Invalid legacy world")
            # Old worlds had public navigation; preserve access without replaying history.
            world = WorldState.from_dict(old_world | {"market_known": True, "trading": False})
        else:
            world = WorldState.from_dict(data["world"])
        session = cls(seed=data["seed"], character=character, world=world)
        session.introduction = _text(data["introduction"], 4000)
        turns = data["turns"]
        if not isinstance(turns, list) or len(turns) > MAX_TURNS:
            raise ValueError("Invalid turn history")
        for item in turns:
            turn_keys = {"action", "speaker", "text", "roll"}
            if version >= 2:
                turn_keys.add("check")
            if not isinstance(item, dict) or set(item) != turn_keys:
                raise ValueError("Invalid turn")
            action = _text(item["action"], 500)
            text = _text(item["text"], 4000)
            roll = None
            check = None
            stored_check = item.get("check")
            if item["roll"] is not None:
                stored_roll = item["roll"]
                if not isinstance(stored_roll, dict) or set(stored_roll) != {"index", "value"}:
                    raise ValueError("Invalid roll")
                if any(type(value) is not int for value in stored_roll.values()):
                    raise ValueError("Invalid roll numbers")
                roll = session.dice.roll_d20()
                if stored_roll != asdict(roll):
                    raise ValueError("Dice history does not match the seed")
                if stored_check is not None:
                    check_keys = {
                        "ability",
                        "score",
                        "difficulty",
                        "modifier",
                        "total",
                        "succeeded",
                    }
                    if not isinstance(stored_check, dict) or set(stored_check) != check_keys:
                        raise ValueError("Invalid ability check")
                    if (
                        any(
                            type(stored_check[key]) is not int
                            for key in ("score", "difficulty", "modifier", "total")
                        )
                        or type(stored_check["succeeded"]) is not bool
                    ):
                        raise ValueError("Invalid check numbers")
                    world_check = (
                        version >= 3
                        and normalise_action(action) == "исследовать дорогу"
                        and item["speaker"] == "Мир"
                        and stored_check["ability"] == "dexterity"
                        and stored_check["difficulty"] == 10
                    )
                    if (
                        CHECK_COMMANDS.get(normalise_action(action)) != stored_check["ability"]
                        and not world_check
                    ):
                        raise ValueError("Check does not match action")
                    check = resolve_ability_check(
                        stored_check["ability"],
                        stored_check["score"],
                        roll.value,
                        stored_check["difficulty"],
                    )
                    expected = describe_check(check, roll.value)
                    valid_text = (
                        text.startswith(expected + "\n") if world_check else text == expected
                    )
                    valid_speaker = world_check or item["speaker"] == "Правила"
                    if stored_check != asdict(check) or not valid_text or not valid_speaker:
                        raise ValueError("Check does not match calculation")
                elif (
                    normalise_action(action) not in ROLL_COMMANDS
                    or text != f"d20 → {roll.value}"
                    or item["speaker"] != "Кубик"
                ):
                    raise ValueError("Invalid dice turn")
            else:
                valid_speaker = (
                    item["speaker"] == "Рассказчик"
                    or (
                        version >= 3
                        and item["speaker"] == "Мир"
                        and normalise_action(action) in WORLD_COMMANDS
                    )
                    or (
                        version >= 3
                        and item["speaker"] == "Система"
                        and action == "Изменить персонажа"
                    )
                )
                if stored_check is not None or not valid_speaker:
                    raise ValueError("Invalid narration turn")
            session._turns.append(Turn(action, item["speaker"], text, roll, check))
        return session
