"""Generated campaign canon, private plans and the hero's explicitly written notebook."""

import hashlib
import json
import random
import uuid
from dataclasses import asdict, dataclass, replace

from rpg_vkr.domain.campaign import plain
from rpg_vkr.domain.catalog import Catalog, Definition, Entity, seed_catalog
from rpg_vkr.domain.interactions import ActorRef, InteractiveWorld, Place, Thing, identifier
from rpg_vkr.domain.resources import NAMES, POOL_IDS


def input_signature(campaign, class_id):
    return hashlib.sha256(
        json.dumps(
            [campaign.world_id, campaign.raw_player_description, campaign.world_brief, class_id],
            ensure_ascii=False,
        ).encode()
    ).hexdigest()


@dataclass(frozen=True)
class WorldSeed:
    title: str
    opening: str
    private_plot: str
    hooks: tuple[str, ...]
    scene: InteractiveWorld
    catalog: Catalog
    source: str
    signature: str
    version: int = 1

    def __post_init__(self):
        plain(self.title, 100)
        if type(self.version) is not int or self.version not in (1, 2):
            raise ValueError("Неизвестный формат вступления.")
        plain(self.opening, 7500 if self.version == 2 else 3500)
        plain(self.private_plot, 6000)
        plain(self.source, 160)
        if len(self.signature) != 64 or self.scene.version != "interactive-world-4":
            raise ValueError("Неверное происхождение нового мира.")
        if not 1 <= len(self.hooks) <= 6:
            raise ValueError("Нужны от одной до шести сюжетных зацепок.")
        for hook in self.hooks:
            plain(hook, 500)
        types = {d.id: d for d in self.catalog.definitions}
        actors = {a.id: a for a in self.scene.actors}
        things = {t.id: t for t in self.scene.things}
        for entity in self.catalog.entities:
            kind = types[entity.definition_id].kind
            if kind == "actor":
                if entity.id not in actors or actors[entity.id].place != entity.parent_id:
                    raise ValueError("Существо не связано с местом нового мира.")
            elif entity.id not in things or things[entity.id].holder != entity.parent_id:
                raise ValueError("Предмет не связан с новым миром.")

    def to_dict(self):
        value = asdict(self) | {"scene": self.scene.to_dict(), "catalog": self.catalog.to_dict()}
        if self.version == 1:
            value.pop("version")
        return value

    @classmethod
    def from_dict(cls, data):
        required = set(cls.__dataclass_fields__) - {"version"}
        if not isinstance(data, dict) or set(data) not in (required, required | {"version"}):
            raise ValueError("Неверный снимок рождения мира.")
        return cls(
            **(
                data
                | {
                    "hooks": tuple(data["hooks"]),
                    "scene": InteractiveWorld.from_dict(data["scene"]),
                    "catalog": Catalog.from_dict(data["catalog"]),
                }
            )
        )


def build_world(value, session, source):
    """Interpret declarative generation only; no code, SQL or model numeric decisions."""
    if not isinstance(value, dict) or set(value) != {
        "title",
        "opening",
        "private_plot",
        "hooks",
        "start",
        "places",
        "definitions",
        "entities",
    }:
        raise ValueError("Неверные поля генерации мира.")
    if (
        not 1 <= len(value["places"]) <= 12
        or len(value["entities"]) > 60
        or len(value["definitions"]) > 30
    ):
        raise ValueError("Первый район слишком большой.")
    places = tuple(Place(**(p | {"anchor": "gate"})) for p in value["places"])
    definitions = tuple(
        Definition(**(d | {"categories": tuple(d["categories"])})) for d in value["definitions"]
    )
    if any(
        d.origin != "generated" or d.id.startswith(("legacy_", "resource_", "type_actor_"))
        for d in definitions
    ):
        raise ValueError("Генератор не заменяет служебные типы.")
    entities = tuple(Entity(**e) for e in value["entities"])
    if any(
        e.id.startswith(("legacy_", "resource_"))
        or e.id in {"guard", "villager", "merchant", "wolf", "boar"}
        for e in entities
    ):
        raise ValueError("Новому миру нужны собственные ID, не акторы старого эпизода.")
    catalog = Catalog(seed_catalog().definitions + definitions, entities)
    types = {d.id: d for d in catalog.definitions}
    actors = tuple(
        ActorRef(e.id, types[e.definition_id].name, e.parent_id)
        for e in entities
        if types[e.definition_id].kind == "actor"
    )
    if any(e.owner_id for e in entities if types[e.definition_id].kind == "actor"):
        raise ValueError("NPC не создаётся как чья-то вещь.")
    things = [
        Thing(
            e.id,
            types[e.definition_id].name,
            e.parent_id,
            e.owner_id,
            e.quantity,
            types[e.definition_id].properties.get("container", False),
            {"type_bandage": "bandages"}.get(e.definition_id, ""),
        )
        for e in entities
        if types[e.definition_id].kind != "actor"
    ]
    for field, id in POOL_IDS.items():
        if getattr(session.world, field):
            things.append(
                Thing(
                    id, NAMES[field], "hero", "hero", getattr(session.world, field), resource=field
                )
            )
    scene = InteractiveWorld(value["start"], places, tuple(things), "interactive-world-4", actors)
    return WorldSeed(
        value["title"],
        value["opening"],
        value["private_plot"],
        tuple(value["hooks"]),
        scene,
        catalog,
        source,
        input_signature(session.campaign, session.progress.class_id),
        version=2 if getattr(session, "is_unified", False) else 1,
    )


def offline_world(session):
    """Authored zero-cost fallback; uses a separate stream, never combat dice."""
    rng = random.Random(session.campaign.world_id)
    scene, detail = rng.choice(
        [
            (
                "Речная пристань",
                "Под настилом плещется вода, у причала покачивается грузовая лодка.",
            ),
            ("Горный перевал", "Ветер несёт запах снега. На камне у тропы вырезан знакомый знак."),
            ("Архив старой гильдии", "Пыльный свет ложится на связки карт и запечатанный ларец."),
            ("Лесная стоянка", "Между стволами тянется дымок костра, слышен плеск ручья."),
            (
                "Тихая обсерватория",
                "Медный прибор медленно поворачивается над картой ночного неба.",
            ),
            (
                "Постоялый двор на тракте",
                "Под навесом сушатся плащи, в зале спорят о закрытой переправе.",
            ),
        ]
    )
    name = rng.choice(["Ива", "Рен", "Лада", "Тарен", "Нэра", "Орин"])
    return build_world(
        {
            "title": "След за горизонтом",
            "start": "arrival",
            "opening": detail
            + f" {name} откладывает дорожную сумку. «Вы ищете дорогу или человека?» "
            "Рядом лежит обрывок карты; его край исписан мелкими знаками.",
            "private_plot": (
                "Не навязывать готовый путь. Связать происхождение героя с потерянной картой: "
            )
            + session.campaign.raw_player_description[:1200]
            + "\nМир: "
            + session.campaign.world_brief[:1200],
            "hooks": ["Выяснить происхождение карты", "Узнать о закрытом пути"],
            "places": [
                {"id": "arrival", "name": scene, "parent": "", "description": detail},
                {
                    "id": "nearby",
                    "name": "Тропа у " + scene.lower(),
                    "parent": "arrival",
                    "description": "Тропа ведёт к укрытию путников; свежие следы уходят дальше.",
                },
            ],
            "definitions": [
                {
                    "id": "traveller_type",
                    "name": name,
                    "kind": "actor",
                    "categories": ["npcs"],
                    "properties": {
                        "hp_max": 8,
                        "class": "traveller",
                        "goals": ["Найти безопасный путь"],
                        "appearance": "Дорожный плащ и сумка с картами",
                    },
                }
            ],
            "entities": [
                {
                    "id": "traveller",
                    "definition_id": "traveller_type",
                    "parent_id": "arrival",
                    "state": {"hp": 8, "gold_cp": 700},
                }
            ],
        },
        session,
        "offline-authored-1",
    )


@dataclass(frozen=True)
class DiaryRevision:
    id: str
    title: str
    text: str
    place: str
    turn: int
    pinned: bool = False
    deleted: bool = False

    def __post_init__(self):
        if (
            str(uuid.UUID(self.id)) != self.id
            or type(self.turn) is not int
            or not 0 <= self.turn <= 2000
        ):
            raise ValueError("Неверная запись дневника.")
        plain(self.title, 150)
        plain(self.text, 6000)
        plain(self.place, 100, empty=True)
        if type(self.pinned) is not bool or type(self.deleted) is not bool:
            raise ValueError("Неверные отметки дневника.")


@dataclass(frozen=True)
class MemoryNote:
    subject: str
    kind: str
    text: str
    importance: int
    private: bool
    turn: int
    source: str

    def __post_init__(self):
        identifier(self.subject)
        if self.kind not in {
            "appearance",
            "motive",
            "clue",
            "rumour",
            "thread",
            "event",
            "knowledge",
            "relationship",
        }:
            raise ValueError("Память не изменяет числовые характеристики мира.")
        plain(self.text, 1000)
        plain(self.source, 160)
        if (
            type(self.importance) is not int
            or not 0 <= self.importance <= 5
            or type(self.private) is not bool
        ):
            raise ValueError("Неверная важность воспоминания.")
        if type(self.turn) is not int or not 0 <= self.turn <= 2000:
            raise ValueError("Неверное время воспоминания.")


@dataclass(frozen=True)
class Chronicle:
    seed: WorldSeed | None = None
    diary: tuple[DiaryRevision, ...] = ()
    memories: tuple[MemoryNote, ...] = ()

    def __post_init__(self):
        if len(self.diary) > 2000 or len(self.memories) > 4000:
            raise ValueError("Достигнут предел записей кампании.")
        if any(a.turn > b.turn for a, b in zip(self.diary, self.diary[1:], strict=False)):
            raise ValueError("Нарушен порядок дневника.")

    @property
    def entries(self):
        latest = {entry.id: entry for entry in self.diary}
        return tuple(e for e in latest.values() if not e.deleted)

    def revise(self, title, text, place, turn, *, id=None, pinned=False, delete=False):
        if id and not any(e.id == id for e in self.entries):
            raise ValueError("Запись дневника отсутствует.")
        entry = DiaryRevision(id or str(uuid.uuid4()), title, text, place, turn, pinned, delete)
        return replace(self, diary=self.diary + (entry,))

    def remember(self, notes):
        result = list(self.memories)
        for note in notes:
            if any(
                n.subject == note.subject and n.kind == note.kind and n.text == note.text
                for n in result
            ):
                continue
            if note.kind == "appearance" and any(
                n.subject == note.subject and n.kind == note.kind for n in result
            ):
                raise ValueError("Установленная внешность не меняется от пересказа.")
            result.append(note)
        return replace(self, memories=tuple(result))

    def to_dict(self):
        return {
            "seed": self.seed.to_dict() if self.seed else None,
            "diary": [asdict(e) for e in self.diary],
            "memories": [asdict(n) for n in self.memories],
        }

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != {"seed", "diary", "memories"}:
            raise ValueError("Неверная хроника кампании.")
        return cls(
            WorldSeed.from_dict(value["seed"]) if value["seed"] else None,
            tuple(DiaryRevision(**e) for e in value["diary"]),
            tuple(MemoryNote(**e) for e in value["memories"]),
        )
