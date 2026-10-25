"""A uniform d20 roll with an independent, reproducible random sequence."""

import re
from dataclasses import dataclass
from random import Random
from secrets import randbits


@dataclass(frozen=True)
class DiceResult:
    expression: str
    individual_rolls: tuple[int, ...]
    modifier: int
    total: int
    rng_counter: int
    reason: str


def parse_expression(expression):
    if not isinstance(expression, str) or len(expression) > 32:
        raise ValueError("Выражение кубиков слишком длинное.")
    match = re.fullmatch(r"\s*(\d{0,3})[dDдД](4|6|8|10|12|20|100)([+-]\d{1,5})?\s*", expression)
    if not match:
        raise ValueError("Формат: 2d6+3; доступны d4, d6, d8, d10, d12, d20, d100.")
    count, sides, modifier = int(match[1] or 1), int(match[2]), int(match[3] or 0)
    if not 1 <= count <= 100 or abs(modifier) > 10000:
        raise ValueError("Допустимы 1–100 кубиков и модификатор до 10000 по модулю.")
    return count, sides, modifier


@dataclass(frozen=True)
class D20Roll:
    index: int
    value: int


class DiceRoller:
    def __init__(self, seed: int | None = None) -> None:
        self.seed = randbits(128) if seed is None else seed
        if type(self.seed) is not int or not 0 <= self.seed < 2**128:
            raise ValueError("Invalid dice seed")
        self._random = Random(self.seed)
        self._count = 0

    def roll_d20(self) -> D20Roll:
        self._count += 1
        return D20Roll(index=self._count, value=self._random.randint(1, 20))

    def checkpoint(self) -> tuple:
        return self._random.getstate(), self._count

    def roll(self, expression, *, reason="Пробный бросок"):
        count, sides, modifier = parse_expression(expression)
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 200:
            raise ValueError("Укажите краткую причину броска.")
        rolls = tuple(self._random.randint(1, sides) for _ in range(count))
        self._count += count
        return DiceResult(expression, rolls, modifier, sum(rolls) + modifier, self._count, reason)

    def restore(self, checkpoint: tuple) -> None:
        state, count = checkpoint
        self._random.setstate(state)
        self._count = count
