"""Versioned semantic evidence; a question is never an executable transaction."""

from dataclasses import asdict, dataclass

ACTS = {"question", "greeting", "contact", "refusal", "insult", "threat", "apology", "farewell"}
TOPICS = {
    "occupation",
    "help",
    "local_help",
    "wares",
    "directions",
    "greeting",
    "appearance",
    "background",
    "other",
}


@dataclass(frozen=True)
class Meaning:
    kind: str
    target: str
    speech_act: str
    topic: str
    version: str = "meaning-1"

    def __post_init__(self):
        valid_target = self.target in {
            "",
            "guard",
            "villager",
            "merchant",
        }
        if self.version == "meaning-2":
            import re

            valid_target = isinstance(self.target, str) and (
                not self.target or bool(re.fullmatch(r"[a-z][a-z0-9_]{0,63}", self.target))
            )
        if self.kind not in {"master", "dialogue"} or not valid_target:
            raise ValueError("Invalid semantic addressee")
        if self.kind == "master" and self.speech_act != "question":
            raise ValueError("A master question cannot perform a social action")
        if self.kind == "dialogue" and not self.target:
            raise ValueError("Missing interlocutor")
        if (
            self.speech_act not in ACTS
            or self.topic not in TOPICS
            or self.version not in {"meaning-1", "meaning-2"}
        ):
            raise ValueError("Invalid semantic interpretation")

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or set(data) != set(cls.__dataclass_fields__):
            raise ValueError("Invalid saved meaning")
        return cls(**data)
