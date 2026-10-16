"""Session state and command routing; narration never performs dice calculations."""

from dataclasses import asdict, dataclass

from rpg_vkr.commands import normalise_action
from rpg_vkr.domain.dice import D20Roll, DiceRoller
from rpg_vkr.narrative.offline import INTRODUCTION, respond

ROLL_COMMANDS = {"бросить d20", "бросить д20"}
MAX_TURNS = 2000


@dataclass(frozen=True)
class Turn:
    action: str
    speaker: str
    text: str
    roll: D20Roll | None = None


def _text(value: object, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError("Invalid session text")
    return value


class Session:
    def __init__(self, seed: int | None = None) -> None:
        self.dice = DiceRoller(seed)
        self.introduction = INTRODUCTION
        self._turns: list[Turn] = []

    @property
    def turns(self) -> tuple[Turn, ...]:
        return tuple(self._turns)

    def submit(self, action: str) -> Turn:
        action = _text(action, 500).strip()
        if len(self._turns) >= MAX_TURNS:
            raise ValueError("Достигнут предел в 2000 действий. Сохраните сессию.")
        if normalise_action(action) in ROLL_COMMANDS:
            roll = self.dice.roll_d20()
            turn = Turn(action, "Кубик", f"d20 → {roll.value}", roll)
        else:
            turn = Turn(action, "Рассказчик", respond(action))
        self._turns.append(turn)
        return turn

    def to_dict(self) -> dict:
        return {
            "seed": self.dice.seed,
            "introduction": self.introduction,
            "turns": [asdict(turn) for turn in self._turns],
        }

    @classmethod
    def from_dict(cls, data: object) -> "Session":
        if not isinstance(data, dict) or set(data) != {"seed", "introduction", "turns"}:
            raise ValueError("Invalid session structure")
        # A missing seed must never silently create a new random sequence.
        if type(data["seed"]) is not int:
            raise ValueError("Missing session seed")
        session = cls(seed=data["seed"])
        session.introduction = _text(data["introduction"], 4000)
        turns = data["turns"]
        if not isinstance(turns, list) or len(turns) > MAX_TURNS:
            raise ValueError("Invalid turn history")
        for item in turns:
            if not isinstance(item, dict) or set(item) != {"action", "speaker", "text", "roll"}:
                raise ValueError("Invalid turn")
            action = _text(item["action"], 500)
            text = _text(item["text"], 4000)
            roll = None
            if normalise_action(action) in ROLL_COMMANDS:
                stored_roll = item["roll"]
                if not isinstance(stored_roll, dict) or set(stored_roll) != {"index", "value"}:
                    raise ValueError("Invalid roll")
                if any(type(value) is not int for value in stored_roll.values()):
                    raise ValueError("Invalid roll numbers")
                roll = session.dice.roll_d20()
                if stored_roll != asdict(roll) or text != f"d20 → {roll.value}":
                    raise ValueError("Dice history does not match the seed")
                if item["speaker"] != "Кубик":
                    raise ValueError("Invalid dice speaker")
            elif item["roll"] is not None or item["speaker"] != "Рассказчик":
                raise ValueError("Invalid narration turn")
            session._turns.append(Turn(action, item["speaker"], text, roll))
        return session
