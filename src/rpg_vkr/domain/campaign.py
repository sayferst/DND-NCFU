"""Persistent authored facts, separate from mechanics and the dice stream."""

import hashlib
import json
import random
import re
import uuid
from dataclasses import asdict, dataclass, replace

NPC_IDS = {"guard", "villager", "merchant"}
PROFILE_FIELDS = ("appearance", "ancestry", "work_detail", "public_background")
DESCRIPTION_LIMIT = 6000


def plain(value, limit, *, empty=False):
    if (
        not isinstance(value, str)
        or len(value) > limit
        or (not empty and not value.strip())
        or any(ord(c) < 32 and c not in "\n\t" for c in value)
    ):
        raise ValueError("Invalid campaign text")
    return value


@dataclass(frozen=True)
class NPCProfile:
    actor_id: str
    appearance: str
    ancestry: str
    work_detail: str
    public_background: str
    source: str
    created_at_turn: int
    version: str = "npc-public-1"

    def __post_init__(self):
        if self.actor_id not in NPC_IDS or self.version != "npc-public-1":
            raise ValueError("Invalid NPC profile identity")
        for field in PROFILE_FIELDS:
            value = plain(getattr(self, field), 300)
            if not re.search(r"[А-Яа-яЁё]", value) or re.search(
                r"\d|золот\w*|урон\w*|получа\w*|инвентар\w*|характеристик\w*|"
                r"заклинан\w*|<|>|https?://",
                value,
                re.IGNORECASE,
            ):
                raise ValueError("NPC detail attempted an unsupported effect or markup")
        plain(self.source, 160)
        if type(self.created_at_turn) is not int or not 1 <= self.created_at_turn <= 2000:
            raise ValueError("Invalid NPC creation anchor")

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            raise ValueError("Invalid NPC profile")
        return cls(**value)


@dataclass(frozen=True)
class Campaign:
    world_id: str
    hero_id: str
    raw_player_description: str = ""
    npc_profiles: tuple[NPCProfile, ...] = ()
    version: str = "campaign-1"

    def __post_init__(self):
        if self.version != "campaign-1":
            raise ValueError("Unsupported campaign version")
        for value in (self.world_id, self.hero_id):
            if not isinstance(value, str) or str(uuid.UUID(value)) != value:
                raise ValueError("Invalid campaign identity")
        plain(self.raw_player_description, DESCRIPTION_LIMIT, empty=True)
        if not isinstance(self.npc_profiles, tuple) or len(self.npc_profiles) > 3:
            raise ValueError("Invalid public canon")
        ids = [p.actor_id for p in self.npc_profiles if isinstance(p, NPCProfile)]
        if len(ids) != len(self.npc_profiles) or len(ids) != len(set(ids)):
            raise ValueError("Duplicate or invalid NPC profile")

    @classmethod
    def create(cls, description=""):
        return cls(str(uuid.uuid4()), str(uuid.uuid4()), description)

    @classmethod
    def migrate(cls, old_data):
        digest = hashlib.sha256(json.dumps(old_data, sort_keys=True).encode()).hexdigest()
        return cls(
            str(uuid.uuid5(uuid.NAMESPACE_URL, "dnd-legacy-world:" + digest)),
            str(uuid.uuid5(uuid.NAMESPACE_URL, "dnd-legacy-hero:" + digest)),
        )

    def profile(self, actor_id):
        return next((p for p in self.npc_profiles if p.actor_id == actor_id), None)

    def add(self, profile):
        if not isinstance(profile, NPCProfile) or self.profile(profile.actor_id):
            raise ValueError("Existing canon cannot be overwritten")
        return replace(self, npc_profiles=self.npc_profiles + (profile,))

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or set(data) != set(cls.__dataclass_fields__):
            raise ValueError("Invalid campaign")
        if not isinstance(data["npc_profiles"], (list, tuple)):
            raise ValueError("Invalid NPC list")
        return cls(
            **(
                data
                | {"npc_profiles": tuple(NPCProfile.from_dict(p) for p in data["npc_profiles"])}
            )
        )


def procedural_profile(campaign, actor_id, turn):
    """Honest offline authoring; its independent RNG never rolls a game die."""
    rng = random.Random(campaign.world_id + actor_id + "npc-public-1")
    hair = rng.choice(("русые", "тёмные", "каштановые", "светлые"))
    clothes = rng.choice(("серого", "синего", "зелёного", "коричневого"))
    appearance, work, background = {
        "villager": (
            f"Женщина с {hair[:-2]}ыми волосами, убранными под платок {clothes} "
            f"цвета. На рукавах следы яблочного сока.",
            "Выращивает яблоки для продажи на рынке; привыкла сама заботиться о товаре.",
            "Живёт в деревне, с детства помогает ухаживать за садом.",
        ),
        "guard": (
            f"Стражник с короткими волосами; поверх дорожной одежды плащ {clothes} "
            f"цвета. Ладони обветрены.",
            "Несёт караул у ворот и следит за дорогой.",
            "Знаком с местной дорогой и обычаями деревни.",
        ),
        "merchant": (
            f"Торговец в жилете {clothes} цвета, с аккуратно подвёрнутыми рукавами и "
            f"внимательным взглядом.",
            "Занимается обменом и следит за своим прилавком.",
            "Привык встречать на рынке и местных жителей, и путников.",
        ),
    }[actor_id]
    return NPCProfile(
        actor_id,
        appearance,
        "Человек, местная жительница." if actor_id == "villager" else "Человек, местный житель.",
        work,
        background,
        "offline-procedural-1",
        turn,
    )
