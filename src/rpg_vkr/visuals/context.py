"""Public visual briefs and stable entity/type/event identity. No hidden canon exports."""

import hashlib
import json
from dataclasses import dataclass

from rpg_vkr.storage.campaigns import CampaignRepository
from rpg_vkr.storage.catalog import live_records
from rpg_vkr.ui.knowledge import knowledge_entries

STYLE = (
    "Original medieval fantasy pixel art; coherent limited jewel-tone palette, "
    "crisp pixel clusters, readable silhouettes, deliberate lighting and detailed environments. "
    "No text, letters, labels, UI, frames, captions, watermarks, statistics or character sheets. "
    "Render only supplied publicly observed features. Do not invent secret identities, "
    "hidden affiliations, unseen possessions, wounds or outcomes. Reference images preserve "
    "the same visual identity, not necessarily the same pose, framing or lighting."
)
VISUAL_FIELDS = {"Внешность", "Описание", "Материал", "Род занятий"}


@dataclass(frozen=True)
class VisualTarget:
    campaign: str
    entity: str
    subject: str
    title: str
    category: str
    common: bool
    type_id: str
    brief: str
    participants: tuple[str, ...] = ()


def public_brief(entry):
    parts = [entry.title, entry.description]
    parts.extend(name + ": " + value for name, value in entry.fields if name in VISUAL_FIELDS)
    return "\n".join(parts)[:6000]


def entity_target(session, entry, *, shared=None):
    # Only an entry from the public projection can reach the image pipeline.
    current = {e.key: e for e in knowledge_entries(session)}
    if entry.key not in current or current[entry.key] != entry:
        raise ValueError(
            "Сведения изменились или объект не известен герою. Откройте карточку заново."
        )
    types, entities = live_records(session)
    entity = entities.get(entry.key, {})
    type_id = entity.get("definition_id", "")
    definition = types.get(type_id, {})
    tags = definition.get("categories", definition.get("tags", []))
    properties = definition.get("properties", {})
    ordinary = (
        entry.category in {"items", "creatures"}
        and bool(type_id)
        and not properties.get("unidentified")
        and not properties.get("unique")
        and not set(tags).intersection({"quest_items", "bosses", "unique"})
        and not (entity.get("state") or {}).get("public_appearance")
    )
    common = ordinary if shared is None else ordinary and shared
    subject = ("type:" + type_id) if common else ("entity:" + entry.key)
    return VisualTarget(
        CampaignRepository.identity(session),
        entry.key,
        subject,
        entry.title,
        entry.category,
        common,
        type_id,
        public_brief(entry),
        (entry.key,),
    )


def scene_target(session, *, event=None):
    entries = knowledge_entries(session)
    by_id = {e.key: e for e in entries}
    place = by_id.get(session.current_place_id)
    if not session.generated_world or place is None:
        raise ValueError("Сначала создайте мир облачным мастером.")
    chosen = [
        e for e in entries if e.here and e.category in {"people", "creatures", "items", "places"}
    ]
    if event is not None:
        if event.key not in by_id or by_id[event.key] != event or event.category != "events":
            raise ValueError("Событие недоступно в публичных знаниях.")
        # Match a known historical turn to observations; never add current strangers to old events.
        chosen = [
            e
            for e in entries
            if e.last_seen <= event.last_seen
            and e.category in {"people", "creatures", "items", "places"}
        ]
        key = "event:" + event.key
        brief = public_brief(event)
    else:
        public = {
            "place": place.key,
            "turn": len(session.turns),
            "objects": sorted((e.key, public_brief(e)) for e in chosen),
        }
        key = (
            "scene:"
            + hashlib.sha256(
                json.dumps(public, ensure_ascii=False, sort_keys=True).encode()
            ).hexdigest()
        )
        brief = "Текущая сцена, без новых действий и результатов.\n" + public_brief(place)
    # Prioritize actors over portable items and background. At most12public components in brief.
    chosen.sort(
        key=lambda e: ({"people": 0, "creatures": 0, "places": 1, "items": 2}[e.category], e.key)
    )
    chosen = chosen[:12]
    brief += "\nПублично известные участники/объекты:\n" + "\n".join(
        public_brief(e) for e in chosen
    )
    return VisualTarget(
        CampaignRepository.identity(session),
        key,
        key,
        event.title if event else "Сцена · " + place.title,
        "events",
        False,
        "",
        brief[:12000],
        tuple(e.key for e in chosen),
    )


def reference_candidates(registry, target):
    """Stable IDs, never fuzzy prose/name matching or a scan of100turns of text."""
    found = []
    for entity in target.participants:
        asset = registry.latest_for(target.campaign, entity)
        if asset and asset["id"] not in {a["id"] for a in found}:
            found.append(asset)
    return found


def make_prompt(target, references):
    mapping = "\n".join(
        f"Reference {i + 1}: visual identity {a['subject']}" for i, a in enumerate(references)
    )
    return STYLE + "\n\nPUBLIC VISUAL BRIEF:\n" + target.brief + "\n" + mapping
