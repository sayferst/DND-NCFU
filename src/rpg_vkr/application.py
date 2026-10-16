"""Session state and command routing; narration never performs dice calculations."""

from dataclasses import asdict, dataclass

from rpg_vkr.commands import normalise_action
from rpg_vkr.domain.character import AbilityCheck, Character, describe_check, resolve_ability_check
from rpg_vkr.domain.dice import D20Roll, DiceRoller
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
    def __init__(self, seed: int | None = None, character: Character | None = None) -> None:
        self.dice = DiceRoller(seed)
        self.character = Character() if character is None else character
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
        if command in ROLL_COMMANDS:
            roll = self.dice.roll_d20()
            turn = Turn(action, "Кубик", f"d20 → {roll.value}", roll)
        elif command in CHECK_COMMANDS:
            ability = CHECK_COMMANDS[command]
            roll = self.dice.roll_d20()
            check = resolve_ability_check(ability, self.character.score(ability), roll.value, 10)
            turn = Turn(action, "Правила", describe_check(check, roll.value), roll, check)
        else:
            turn = Turn(action, "Рассказчик", respond(action))
        self._turns.append(turn)
        return turn

    def to_dict(self) -> dict:
        return {
            "seed": self.dice.seed,
            "character": asdict(self.character),
            "introduction": self.introduction,
            "turns": [asdict(turn) for turn in self._turns],
        }

    @classmethod
    def from_dict(cls, data: object, version: int = 2) -> "Session":
        if version not in (1, 2):
            raise ValueError("Unsupported session version")
        keys = {"seed", "introduction", "turns"}
        if version == 2:
            keys.add("character")
        if not isinstance(data, dict) or set(data) != keys:
            raise ValueError("Invalid session structure")
        # A missing seed must never silently create a new random sequence.
        if type(data["seed"]) is not int:
            raise ValueError("Missing session seed")
        character = Character() if version == 1 else Character.from_dict(data["character"])
        session = cls(seed=data["seed"], character=character)
        session.introduction = _text(data["introduction"], 4000)
        turns = data["turns"]
        if not isinstance(turns, list) or len(turns) > MAX_TURNS:
            raise ValueError("Invalid turn history")
        for item in turns:
            turn_keys = {"action", "speaker", "text", "roll"}
            if version == 2:
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
                    if CHECK_COMMANDS.get(normalise_action(action)) != stored_check["ability"]:
                        raise ValueError("Check does not match action")
                    check = resolve_ability_check(
                        stored_check["ability"],
                        stored_check["score"],
                        roll.value,
                        stored_check["difficulty"],
                    )
                    if (
                        stored_check != asdict(check)
                        or text != describe_check(check, roll.value)
                        or item["speaker"] != "Правила"
                    ):
                        raise ValueError("Check does not match calculation")
                elif (
                    normalise_action(action) not in ROLL_COMMANDS
                    or text != f"d20 → {roll.value}"
                    or item["speaker"] != "Кубик"
                ):
                    raise ValueError("Invalid dice turn")
            elif stored_check is not None or item["speaker"] != "Рассказчик":
                raise ValueError("Invalid narration turn")
            session._turns.append(Turn(action, item["speaker"], text, roll, check))
        return session
