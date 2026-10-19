"""Saved optional prose is separate from authoritative actions and state changes."""

import re
from dataclasses import asdict, dataclass

from rpg_vkr.narrative.segments import Segment

PROMPT_VERSION = "narrator-prose-12"
SUPPORTED_PROMPTS = {
    "narrator-prose-1",
    "narrator-prose-2",
    "narrator-prose-3",
    "narrator-prose-4",
    "narrator-prose-5",
    "narrator-prose-6",
    "narrator-prose-7",
    "narrator-prose-8",
    "narrator-prose-9",
    "narrator-prose-10",
    "narrator-prose-11",
    PROMPT_VERSION,
}


@dataclass(frozen=True)
class Narration:
    turn_index: int
    model: str
    text: str
    context_hash: str
    prompt_version: str = PROMPT_VERSION
    segments: tuple[Segment, ...] = ()
    instruction_hash: str = ""

    def __post_init__(self):
        if type(self.turn_index) is not int or not 0 <= self.turn_index <= 2000:
            raise ValueError("Invalid narration anchor")
        if not isinstance(self.model, str) or not re.fullmatch(
            r"[A-Za-z0-9_.:/-]{1,128}", self.model
        ):
            raise ValueError("Invalid installed model name")
        if (
            not isinstance(self.text, str)
            or not self.text.strip()
            or len(self.text) > 1500
            or any(ord(c) < 32 and c not in "\n\t" for c in self.text)
        ):
            raise ValueError("Invalid narration text")
        if (
            not isinstance(self.context_hash, str)
            or not re.fullmatch(r"[0-9a-f]{64}", self.context_hash)
            or self.prompt_version not in SUPPORTED_PROMPTS
        ):
            raise ValueError("Invalid narration provenance")

        if (
            not isinstance(self.segments, tuple)
            or len(self.segments) > 24
            or not all(isinstance(item, Segment) for item in self.segments)
        ):
            raise ValueError("Invalid visible segments")
        if self.segments:

            def compact(value):
                return re.sub(r"[\s—«»]", "", value)

            if compact("".join(item.text for item in self.segments)) != compact(self.text):
                raise ValueError("Segments differ from narration")
        if not isinstance(self.instruction_hash, str) or (
            self.instruction_hash and not re.fullmatch(r"[0-9a-f]{64}", self.instruction_hash)
        ):
            raise ValueError("Invalid instruction hash")

    def to_dict(self):
        result = asdict(self)
        if self.prompt_version != PROMPT_VERSION and not self.instruction_hash:
            result.pop("instruction_hash")
        return result

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or set(data) not in (
            set(cls.__dataclass_fields__),
            set(cls.__dataclass_fields__) - {"segments"},
            set(cls.__dataclass_fields__) - {"instruction_hash"},
            set(cls.__dataclass_fields__) - {"segments", "instruction_hash"},
        ):
            raise ValueError("Invalid narration record")
        segments = data.get("segments", ())
        if not isinstance(segments, (list, tuple)):
            raise ValueError("Invalid saved segments")
        return cls(**(data | {"segments": tuple(Segment.from_dict(item) for item in segments)}))
