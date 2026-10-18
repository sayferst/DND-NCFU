"""Small authored social reactions, replayed separately from combat/world deltas."""

from dataclasses import asdict, dataclass

NPC_IDS = {"guard", "villager", "merchant"}
ACTS = {"question", "greeting", "contact", "refusal", "insult", "threat", "apology", "farewell"}
TOPICS = {
    "occupation",
    "help",
    "wares",
    "directions",
    "greeting",
    "other",
    "local_help",
    "appearance",
    "background",
}


def grievance_after(before, act):
    return max(0, min(3, before + {"insult": 1, "threat": 2, "apology": -1}.get(act, 0)))


@dataclass(frozen=True)
class DialogueRecord:
    target: str
    act: str
    topic: str
    before: int
    after: int
    rules_version: str = "homebrew-social-1"

    def __post_init__(self):
        if self.rules_version != "homebrew-social-1":
            raise ValueError("Unsupported social rules")
        if (
            not all(isinstance(v, str) for v in (self.target, self.act, self.topic))
            or self.target not in NPC_IDS
            or self.act not in ACTS
            or self.topic not in TOPICS
        ):
            raise ValueError("Invalid social act")
        if any(type(v) is not int or not 0 <= v <= 3 for v in (self.before, self.after)):
            raise ValueError("Invalid social state")
        if self.after != grievance_after(self.before, self.act):
            raise ValueError("Social reaction does not match rule")

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or set(data) != set(cls.__dataclass_fields__):
            raise ValueError("Invalid social record")
        return cls(**data)


def grievance(turns, target):
    return next(
        (t.dialogue.after for t in reversed(turns) if t.dialogue and t.dialogue.target == target),
        0,
    )
