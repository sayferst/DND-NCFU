"""A uniform d20 roll with an independent, reproducible random sequence."""

from dataclasses import dataclass
from random import Random
from secrets import randbits


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

    def restore(self, checkpoint: tuple) -> None:
        state, count = checkpoint
        self._random.setstate(state)
        self._count = count
