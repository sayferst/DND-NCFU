"""Saved optional prose is separate from authoritative actions and state changes."""

import re
from dataclasses import asdict, dataclass

PROMPT_VERSION = "narrator-prose-3"
SUPPORTED_PROMPTS = {"narrator-prose-1", "narrator-prose-2", PROMPT_VERSION}


@dataclass(frozen=True)
class Narration:
    turn_index: int
    model: str
    text: str
    context_hash: str
    prompt_version: str = PROMPT_VERSION

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

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or set(data) != set(cls.__dataclass_fields__):
            raise ValueError("Invalid narration record")
        return cls(**data)
