"""Player knowledge projection. Never export a catalog snapshot or infer facts from prose."""

import hashlib
import json
from dataclasses import asdict, dataclass

from rpg_vkr.domain.combat import ACTORS
from rpg_vkr.domain.director import known_facts
from rpg_vkr.domain.social import grievance
from rpg_vkr.domain.world import LOCATIONS
from rpg_vkr.narrative.context import visible_changes
from rpg_vkr.storage.catalog import live_records

CATEGORIES = {
    "people": "Персонажи",
    "creatures": "Существа",
    "items": "Предметы",
    "places": "Места",
    "factions": "Фракции",
    "events": "События",
}
LABELS = {
    "public_name": "Известное имя",
    "role": "Род занятий",
    "appearance": "Внешность",
    "ancestry": "Происхождение",
    "background": "Прошлое",
    "material": "Материал",
    "properties": "Изученные свойства",
    "effects": "Изученные эффекты",
    "price": "Известная цена",
    "faction": "Известная принадлежность",
    "description": "Описание",
}


@dataclass(frozen=True)
class KnowledgeEntry:
    key: str  # Internal lookup only. Export uses a campaign-scoped opaque reference.
    category: str
    title: str
    description: str
    fields: tuple[tuple[str, str], ...]
    notes: tuple[tuple[str, str], ...] = ()
    last_seen: int = 0
    here: bool = False
    partial: bool = True

    @property
    def search_text(self):
        return " ".join(
            (
                self.title,
                self.description,
                *(v for _, v in self.fields),
                *(v for _, v in self.notes),
            )
        ).casefold()

    @property
    def rumour(self):
        return any(k == "Слух" for k, _ in self.notes)

    def public_dict(self, campaign_id):
        value = asdict(self)
        value["reference"] = hashlib.sha256((campaign_id + self.key).encode()).hexdigest()[:20]
        value.pop("key")
        value["category"] = CATEGORIES[self.category]
        return value


def public_notes(session):
    result = []
    for note in session.chronicle.memories if session.chronicle else ():
        if note.private or note.subject == "plot":
            continue
        if note.text.lstrip().startswith("{") and not revealed_fields([note]):
            continue
        result.append(note)
    return result


def revealed_fields(notes):
    """Explicit public knowledge fields use the existing MemoryNote envelope, not NLP."""
    result = {}
    for note in notes:
        if note.kind != "knowledge":
            continue
        try:
            value = json.loads(note.text)
        except (ValueError, TypeError):
            continue
        if (
            isinstance(value, dict)
            and set(value) == {"field", "value"}
            and value["field"] in LABELS
            and isinstance(value["value"], str)
        ):
            result[value["field"]] = value["value"]
    return result


def observation_history(session, definitions):
    observed, places = {}, {}
    states = {}
    if session.chronicle and session.chronicle.seed:
        states = {e.id: e.state or {} for e in session.chronicle.seed.catalog.entities}

    def observe(scene, turn):
        visible_now = set()
        places[scene.current] = (scene.place(), turn)
        for actor in scene.actor_refs:
            if actor.place == scene.current:
                observed[actor.id] = (scene.current, turn, dict(states.get(actor.id, {})))
                visible_now.add(actor.id)
        things = {t.id: t for t in scene.things}
        for thing in scene.things:
            holder, seen = thing.holder, {thing.id}
            visible = True
            while holder in things:
                if holder in seen:
                    visible = False
                    break
                seen.add(holder)
                parent = things[holder]
                properties = definitions.get(holder, {}) | states.get(holder, {})
                if not properties.get("open", True) or properties.get("locked", False):
                    visible = False
                holder = parent.holder
            # Contents of someone else's pockets are not visible merely by co-location.
            if visible and holder in {scene.current, "hero"}:
                observed[thing.id] = (scene.current, turn, dict(states.get(thing.id, {})))
                visible_now.add(thing.id)
        return visible_now

    if session.generated_world:
        observe(session.chronicle.seed.scene, 0)
    for i, turn in enumerate(session.turns, 1):
        record = turn.catalog
        for entity in getattr(record, "entities", ()):
            states[entity.id] = entity.state or {}
        if hasattr(record, "entity_after"):
            states[record.entity_after.id] = record.entity_after.state or {}
        for record in (turn.interaction, turn.trade, turn.catalog):
            before = getattr(record, "before", None)
            if hasattr(before, "actor_refs"):
                observe(before, i)
            after = getattr(record, "after", None)
            if hasattr(after, "actor_refs"):
                observe(after, i)
        # Catalog registration adds entities to its pre-registration scene.
        if getattr(turn.catalog, "entities", None):
            place = turn.catalog.before.current
            for entity in turn.catalog.entities:
                if entity.parent_id in {place, "hero"}:
                    observed[entity.id] = (place, i, dict(entity.state or {}))
    # Only current observations may use current state. Old entries retain last seen positions.
    current = session.interaction_state()
    for key, raw in live_records(session)[1].items():
        states[key] = raw.get("state", {})
    current_seen = observe(current, len(session.turns))
    for key, raw in live_records(session)[1].items():
        if raw["parent_id"] == "hero" and raw["quantity"] > 0:
            observed[key] = (current.current, len(session.turns), dict(raw.get("state", {})))
            current_seen.add(key)
    if not session.generated_world:
        visited = {
            session.memory.baseline
            and dict(session.memory.baseline).get("world.location", "gate")
            or "gate"
        }
        visited.update(e.location for e in session.memory.events)
        visited.add(session.world.location)
        for place in visited:
            if place in LOCATIONS:
                from rpg_vkr.domain.interactions import Place

                places[place] = (
                    Place(
                        place, LOCATIONS[place], "", place, "Известное место старого приключения."
                    ),
                    0,
                )
                for key, spec in ACTORS.items():
                    if spec[1] == place and key not in observed:
                        observed[key] = (place, 0, {})
    return observed, places, current_seen


def knowledge_entries(session):
    current_types, current_entities = live_records(session)
    types, entities = {}, {}
    catalogs = [session.chronicle.seed.catalog] if session.generated_world else []
    for catalog in catalogs:
        types.update({d.id: d.to_dict() for d in catalog.definitions})
        entities.update({e.id: e.to_dict() for e in catalog.entities})
    for turn in session.turns:
        types.update({d.id: d.to_dict() for d in getattr(turn.catalog, "definitions", ())})
        entities.update({e.id: e.to_dict() for e in getattr(turn.catalog, "entities", ())})
    types.update(current_types)
    if session.generated_world:
        from rpg_vkr.domain.resources import RESOURCE_TYPES

        for thing in session.chronicle.seed.scene.things:
            if thing.resource:
                entities.setdefault(
                    thing.id,
                    {
                        "id": thing.id,
                        "definition_id": RESOURCE_TYPES[thing.resource],
                        "parent_id": thing.holder,
                        "owner_id": thing.owner,
                        "quantity": thing.quantity,
                        "state": {},
                    },
                )
    entities.update(current_entities)
    props = {key: types[e["definition_id"]]["properties"] for key, e in entities.items()}
    observed, places, current_seen = observation_history(session, props)
    notes = public_notes(session)
    facts = known_facts(session.turns)
    result = []
    place_names = {key: p.name for key, (p, _) in places.items()}
    note_map = {}
    for note in notes:
        note_map.setdefault(note.subject, []).append(note)

    def known_name(key):
        if key == "hero":
            return session.character.name
        if key in place_names:
            return place_names[key]
        if key not in observed and key not in note_map:
            return "Неизвестно"
        revealed = revealed_fields(note_map.get(key, []))
        explicit = facts.get((key, "public_name"))
        # Definition.name is a canonical identity, not necessarily the name learned by hero.
        public = revealed.get("public_name") or explicit
        if key in entities and key in observed:
            public = public or observed[key][2].get("public_name")
        return public or (ACTORS[key][0] if key in ACTORS else "Неизвестный персонаж")

    for key, entity in entities.items():
        if entity["quantity"] <= 0 and key not in observed:
            continue
        if key not in observed and key not in note_map:
            continue
        definition = types[entity["definition_id"]]
        place, turn, seen_state = observed.get(key, ("", 0, {}))
        local = key in current_seen
        # Do not publish a distant NPC's updated state/position just because it exists in DB.
        state = entity["state"] if local else seen_state
        own_notes = note_map.get(key, [])
        revealed = revealed_fields(own_notes)
        properties = definition["properties"]
        actor = definition["kind"] == "actor"
        category = (
            "creatures"
            if actor and set(definition["categories"]) & {"creatures", "bosses"}
            else "people"
            if actor
            else "items"
        )
        title = known_name(key) if actor else (state.get("public_name") or definition["name"])
        if not actor and properties.get("unidentified"):
            title = state.get("public_name", "Неизвестный предмет")
        seen_properties = properties if key in observed else {}
        description = (
            revealed.get("description")
            or state.get("public_description")
            or seen_properties.get("public_description")
            or seen_properties.get("appearance")
            or "Дальнейшие сведения пока неизвестны."
        )
        details = [("Последнее известное место", place_names.get(place, "Неизвестно"))]
        for field, label in LABELS.items():
            value = revealed.get(field)
            if not value and field in {"appearance", "description"}:
                value = state.get("public_" + field) or seen_properties.get("public_" + field)
            if value:
                details.append((label, value))
        if actor:
            disposition = state.get("disposition")
            details.append(
                (
                    "Наблюдаемое отношение",
                    {"hostile": "Враждебен", "neutral": "Нейтральное"}.get(
                        disposition, "Неизвестно"
                    ),
                )
            )
            if grievance(session.turns, key):
                details.append(("Память общения", "Помнит грубость героя"))
            details.extend(
                (
                    ("Занятие", revealed.get("role", "Неизвестно")),
                    ("Прошлое", revealed.get("background", "Неизвестно")),
                )
            )
        else:
            root = session.interaction_state()
            thing = next((t for t in root.things if t.id == key), None)
            if thing and root.root_holder(thing) == "hero":
                details.append(("При вас", str(thing.quantity)))
            elif local and entity["parent_id"] == "hero":
                details.append(("При вас", str(entity["quantity"])))
            # Owner identifiers and private NPC inventories never enter the public view.
            if local and entity.get("owner_id"):
                details.append(("Известный владелец", known_name(entity["owner_id"])))
        displayed_notes = []
        for note in own_notes:
            if note.text.lstrip().startswith("{"):
                continue
            displayed_notes.append(
                ("Слух" if note.kind == "rumour" else "Известные сведения", note.text)
            )
        result.append(
            KnowledgeEntry(
                key,
                category,
                title,
                str(description),
                tuple(details),
                tuple(displayed_notes),
                turn,
                local,
            )
        )

    for key, (place, turn) in places.items():
        result.append(
            KnowledgeEntry(
                key,
                "places",
                place.name,
                place.description,
                (
                    ("Регион", "Неизвестно"),
                    (
                        "Посещение",
                        "Здесь сейчас" if key == session.current_place_id else "Посещено ранее",
                    ),
                ),
                tuple(
                    ("Слух" if n.kind == "rumour" else "Известные сведения", n.text)
                    for n in note_map.get(key, [])
                ),
                turn,
                key == session.current_place_id,
                False,
            )
        )
    for i, event in enumerate(session.memory.events):
        changes = visible_changes(event)
        if changes:
            result.append(
                KnowledgeEntry(
                    "event:" + str(i),
                    "events",
                    f"Событие · ход {event.turn_index}",
                    "\n".join(changes),
                    (("Источник", "Проверенное событие движка"),),
                    last_seen=event.turn_index,
                    partial=False,
                )
            )
    for i, note in enumerate(notes):
        if note.kind == "event" or (
            note.kind in {"clue", "thread", "rumour"} and note.subject in {"world", "hero"}
        ):
            result.append(
                KnowledgeEntry(
                    "note:"
                    + hashlib.sha256(
                        json.dumps(
                            [note.subject, note.kind, note.text, note.turn, note.source],
                            ensure_ascii=False,
                        ).encode()
                    ).hexdigest()[:32],
                    "events",
                    f"{'Слух' if note.kind == 'rumour' else 'Хроника'} · ход {note.turn}",
                    note.text,
                    (("Источник", "Память кампании"),),
                    (("Слух", note.text),) if note.kind == "rumour" else (),
                    note.turn,
                )
            )
        revealed = revealed_fields([note])
        if "faction" in revealed:
            name = revealed["faction"]
            key = "faction:" + hashlib.sha256(name.casefold().encode()).hexdigest()[:16]
            if not any(e.key == key for e in result):
                result.append(
                    KnowledgeEntry(
                        key,
                        "factions",
                        name,
                        "Организация, упомянутая в доступных герою сведениях.",
                        (("Источник", "Память кампании"),),
                        last_seen=note.turn,
                    )
                )
    return tuple(result)
