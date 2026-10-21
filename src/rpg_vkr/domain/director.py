"""Append-only, local scene proposals; no new mechanics or direct resource mutations."""

import re
from dataclasses import asdict, dataclass

from rpg_vkr.commands import CHAT_TARGETS, NPC_CONTACTS, allowed_intents
from rpg_vkr.domain.campaign import plain
from rpg_vkr.domain.combat import ACTORS
from rpg_vkr.domain.world import LOCATIONS
from rpg_vkr.narrative.limits import MAX_PROSE

FACT_KEYS = {"sensory_detail", "motive", "concern", "rumour", "occupation_detail", "public_name"}
SUBJECTS = {*LOCATIONS, "guard", "villager", "merchant"}


def mechanical_commands():
    return (
        allowed_intents()
        - set(CHAT_TARGETS)
        - set(NPC_CONTACTS)
        - {
            "осмотреться",
            "оглядеться",
            "поговорить",
            "инвентарь",
            "состояние",
            "задание",
            "помощь",
            "спросить мастера",
            "уточнить намерение",
            "что я вижу",
            "где я нахожусь",
        }
    )


@dataclass(frozen=True)
class StoryFact:
    subject: str
    key: str
    value: str

    def __post_init__(self):
        if self.subject not in SUBJECTS or self.key not in FACT_KEYS:
            raise ValueError("Unsupported narrative fact")
        if self.key == "public_name" and (
            self.subject not in {"guard", "villager", "merchant"}
            or not re.fullmatch(r"[А-ЯЁ][а-яё]{1,29}(?:-[А-ЯЁ][а-яё]{1,29})?", self.value)
        ):
            raise ValueError("Invalid public NPC name")
        plain(self.value, 240)
        if not re.search(r"[А-Яа-яЁё]", self.value) or re.search(
            r"\d|https?://|<|>|\b(?:урон|золота|золотых|опыта|здоровья)\b", self.value, re.I
        ):
            raise ValueError("Narrative fact attempted a mechanical value or markup")

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != {"subject", "key", "value"}:
            raise ValueError("Invalid fact fields")
        return cls(**value)


@dataclass(frozen=True)
class Proposal:
    mechanical_command: str
    focus_id: str
    narration: str
    facts: tuple[StoryFact, ...]

    def __post_init__(self):
        if self.mechanical_command:
            if self.mechanical_command not in mechanical_commands():
                raise ValueError("Unknown mechanical request")
            if self.focus_id or self.narration or self.facts:
                raise ValueError("Cannot mix mechanics and speculative outcomes")
            return
        if not isinstance(self.focus_id, str) or (
            self.focus_id and not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", self.focus_id)
        ):
            raise ValueError("Unknown scene speaker")
        plain(self.narration, MAX_PROSE)
        if len(self.facts) > 3 or not all(isinstance(f, StoryFact) for f in self.facts):
            raise ValueError("Too many scene facts")
        ids = [(f.subject, f.key) for f in self.facts]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate proposed fact")

    @classmethod
    def from_dict(cls, value):
        if (
            not isinstance(value, dict)
            or set(value) != {"mechanical_command", "focus_id", "narration", "facts"}
            or not isinstance(value["facts"], list)
        ):
            raise ValueError("Invalid master proposal")
        if not all(
            isinstance(value[k], str) for k in ("mechanical_command", "focus_id", "narration")
        ):
            raise ValueError("Invalid master proposal types")
        return cls(**(value | {"facts": tuple(StoryFact.from_dict(f) for f in value["facts"])}))


@dataclass(frozen=True)
class SceneRecord:
    base_turn: int
    location: str
    model: str
    proposal: Proposal
    version: str = "scene-director-6"

    def __post_init__(self):
        if type(self.base_turn) is not int or not 0 <= self.base_turn < 2000:
            raise ValueError("Invalid scene revision")
        if self.location not in LOCATIONS or self.version not in {
            "scene-director-1",
            "scene-director-2",
            "scene-director-3",
            "scene-director-4",
            "scene-director-5",
            "scene-director-6",
        }:
            raise ValueError("Invalid scene context")
        if not re.fullmatch(r"~?[A-Za-z0-9_.:/-]{1,128}", self.model):
            raise ValueError("Invalid source model")
        if not isinstance(self.proposal, Proposal) or self.proposal.mechanical_command:
            raise ValueError("Scene cannot execute a mechanical request")

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            raise ValueError("Invalid saved scene")
        if value["version"] != "scene-director-6" and (
            len(value["proposal"]["narration"]) > 1500
            or value["proposal"]["focus_id"] not in {"", "guard", "villager", "merchant"}
        ):
            raise ValueError("Legacy scene limits exceeded")
        p = dict(value["proposal"])
        p["facts"] = list(p["facts"])
        return cls(**(value | {"proposal": Proposal.from_dict(p)}))


def known_facts(turns):
    result = {}
    for turn in turns:
        if turn.scene:
            for fact in turn.scene.proposal.facts:
                key = (fact.subject, fact.key)
                if key in result and result[key] != fact.value:
                    raise ValueError("Established narrative fact was overwritten")
                result[key] = fact.value
    return result


def validate_scene(record, turns, location, combat, hp, *, scene=None, catalog=None):
    if record.base_turn != len(turns) or record.location != location:
        raise ValueError("Сцена устарела. Мир не изменён.")
    if record.version == "scene-director-6":
        if hp <= 0:
            raise ValueError("Герой выбыл; загрузите сохранение или начните новую игру.")
        target = record.proposal.focus_id
        if target:
            if scene is None or not any(
                a.id == target and a.place == scene.current for a in scene.actor_refs
            ):
                raise ValueError("Собеседника нет в текущем месте.")
            if target in ACTORS:
                alive = combat.actor(target).hp > 0
            else:
                entity = (
                    next((e for e in catalog.entities if e.id == target), None) if catalog else None
                )
                alive = bool(
                    entity
                    and (entity.state or {}).get("hp", 1) > 0
                    and (entity.state or {}).get("life") != "dead"
                )
            if not alive:
                raise ValueError("Погибший или поверженный собеседник не отвечает.")
        from rpg_vkr.narrative.story import validate_story_text

        validate_story_text(record.proposal.narration, confirmed=True)
        current = known_facts(turns)
        for fact in record.proposal.facts:
            if fact.subject not in {location, target}:
                raise ValueError("Предложение изменяет сведения вне текущей сцены.")
            if (fact.subject, fact.key) in current and current[
                fact.subject, fact.key
            ] != fact.value:
                raise ValueError("Мастер попытался заменить уже установленный факт.")
        return
    if combat.active or hp <= 0:
        raise ValueError("Для этой ситуации сначала нужны игровые правила, не свободная сцена.")
    target = record.proposal.focus_id
    if target and (
        ACTORS[target][1] != location
        or combat.actor(target).hp <= 0
        or combat.actor(target).disposition == "hostile"
    ):
        raise ValueError("Собеседник недоступен для мирного разговора.")
    current = known_facts(turns)
    for fact in record.proposal.facts:
        if fact.subject != location and fact.subject != target:
            raise ValueError("Предложение изменяет сведения вне текущей сцены.")
        if (fact.subject, fact.key) in current and current[fact.subject, fact.key] != fact.value:
            raise ValueError("Мастер попытался заменить уже установленный факт.")
    text = record.proposal.narration
    if record.version in {
        "scene-director-2",
        "scene-director-3",
        "scene-director-4",
        "scene-director-5",
    }:
        from rpg_vkr.narrative.story import validate_story_text

        validate_story_text(text, legacy=True)
        if target and not re.search(r"«[^»]+»|(?:^|\n)\s*—\s*\S", text):
            raise ValueError("В сцене отсутствует прямая речь выбранного NPC.")
        return
    if any(c.isalpha() and not re.fullmatch(r"[А-Яа-яЁё]", c) for c in text):
        raise ValueError("Мастер ответил не по-русски.")
    if not re.search(r"[А-Яа-яЁё]", text) or "<" in text or ">" in text:
        raise ValueError("Неверный текст сцены.")
    if target and not re.search(r"«[^»]+»|(?:^|\n)\s*—\s*\S", text):
        raise ValueError("В сцене отсутствует прямая речь выбранного NPC.")
