"""Trusted public speaker metadata; model prefixes never select a role."""

import re
from dataclasses import asdict, dataclass

from rpg_vkr.domain.campaign import plain
from rpg_vkr.narrative.limits import MAX_PROSE


@dataclass(frozen=True)
class Segment:
    speaker_id: str
    display_name: str
    text: str

    def __post_init__(self):
        if (
            not isinstance(self.speaker_id, str)
            or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", self.speaker_id)
            or self.speaker_id == "hero"
        ):
            raise ValueError("Invalid visible speaker")
        expected = {
            "master": "Мастер",
            "guard": "Стражник",
            "villager": "Жительница",
            "merchant": "Торговец",
        }
        if self.speaker_id in expected and self.display_name != expected[self.speaker_id]:
            raise ValueError("Untrusted speaker name")
        plain(self.display_name, 100)
        plain(self.text, MAX_PROSE)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            raise ValueError("Invalid segment")
        return cls(**value)


def split_story(text, actor_id=None, display_name=None):
    from rpg_vkr.domain.combat import ACTORS

    if not actor_id:
        return (Segment("master", "Мастер", text),)
    result, offset = [], 0
    for match in re.finditer(r"«[^»]+»|(?:^|\n)\s*—\s*[^\n]+", text):
        before = text[offset : match.start()].strip()
        if before:
            result.append(Segment("master", "Мастер", before))
        result.append(
            Segment(
                actor_id,
                display_name or ACTORS.get(actor_id, (actor_id,))[0],
                match[0].strip().removeprefix("— "),
            )
        )
        offset = match.end()
    tail = text[offset:].strip()
    if tail and result and all(c in ".,!?…" for c in tail):
        previous = result[-1]
        result[-1] = Segment(previous.speaker_id, previous.display_name, previous.text + tail)
    elif tail:
        result.append(Segment("master", "Мастер", tail))
    return tuple(result)
