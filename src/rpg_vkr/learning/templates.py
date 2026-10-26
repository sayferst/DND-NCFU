"""Local templates are proposals. Existing catalog validation owns every world edit."""

import hashlib
from dataclasses import dataclass

from rpg_vkr.domain.catalog import Definition, Entity
from rpg_vkr.learning.quality import CLAIM, safe_excerpt


def candidate(library, record_id):
    value = library.record(record_id)
    row = value["record"]
    review = library.db.execute("SELECT approved FROM reviews WHERE id=?", (record_id,)).fetchone()
    namespace = value["annotation"]["namespace"]
    result = {
        "record_id": record_id,
        "source_id": row["source_id"],
        "source_sha256": row["source_sha256"],
        "namespace": namespace,
        "status": "reviewed_template" if review and review[0] else "needs_review",
        "template_or_instance": "template",
        "effects_applied": False,
        "links": library.graph(record_id),
    }
    if namespace == "crafting":
        from rpg_vkr.domain.content_v5 import RECIPES

        result["supported_recipe_ids"] = sorted(RECIPES)
        result["constraint"] = "Выбрать существующий рецепт; затраты проверяет движок."
    elif namespace == "events":
        result["constraint"] = "Сюжетный повод; исход, жертвы и награды не назначаются."
    elif namespace == "behavior":
        result["constraint"] = "Мотив не передаёт NPC знания героя или мировые тайны."
    return result


@dataclass(frozen=True)
class CatalogProposal:
    world_id: str
    hero_id: str
    place: str
    definition: Definition
    entity: Entity
    source_id: str
    record_id: str


def propose_catalog(library, session, record_id, *, request_id, name, description, kind="actor"):
    """Names/descriptions are original operator input; raw source text never enters canon."""
    flags = getattr(session, "_learning_flags", {})
    if not flags.get("templates"):
        raise ValueError("Предложения шаблонов выключены.")
    info = candidate(library, record_id)
    if info["status"] != "reviewed_template" or info["namespace"] not in ("entities", "behavior"):
        raise ValueError("Требуется локально одобренный шаблон сущности или поведения.")
    for value, size in ((request_id, 100), (name, 100), (description, 400)):
        if (
            not isinstance(value, str)
            or not 1 <= len(value.strip()) <= size
            or not safe_excerpt(value)
        ):
            raise ValueError("Нужны короткие безопасные оригинальные поля предложения.")
    if CLAIM.search(description) or kind not in ("actor", "item"):
        raise ValueError("Шаблон не задаёт числовые эффекты и новые правила.")
    place = session.interaction_state().current
    token = hashlib.sha256((session.campaign.world_id + ":" + request_id).encode()).hexdigest()[:24]
    properties = {
        "appearance": description,
        "template_record": record_id,
        "template_source": info["source_id"],
        "template_sha256": info["source_sha256"],
    }
    if kind == "actor":
        properties["hp_max"] = 1  # Explicit neutral catalog bound, not imported combat statistics.
    definition = Definition(
        "learn_type_" + token,
        name,
        kind,
        ("npcs",) if kind == "actor" else ("miscellaneous",),
        properties,
    )
    entity = Entity(
        "learn_" + token, definition.id, place, state={"hp": 1} if kind == "actor" else None
    )
    return CatalogProposal(
        session.campaign.world_id,
        session.campaign.hero_id,
        place,
        definition,
        entity,
        info["source_id"],
        record_id,
    )


def apply_catalog(session, proposal, *, confirmed=False):
    if not confirmed or not getattr(session, "_learning_flags", {}).get("templates"):
        raise ValueError("Добавление требует включённого режима и явного подтверждения.")
    if (proposal.world_id, proposal.hero_id) != (
        session.campaign.world_id,
        session.campaign.hero_id,
    ):
        raise ValueError("Предложение относится к другому миру или герою.")
    existing = next(
        (d for d in session.catalog.definitions if d.id == proposal.definition.id), None
    )
    if existing:
        if existing != proposal.definition:
            raise ValueError("Повторный request_id содержит другие поля.")
        return {"entity_id": proposal.entity.id, "already_applied": True}
    if session.interaction_state().current != proposal.place:
        raise ValueError("Место изменилось; пересоздайте предложение.")
    session.register_catalog(
        "Замечаю: " + proposal.definition.name,
        [proposal.definition],
        [proposal.entity],
        "Подтверждённое оригинальное предложение по локальному шаблону " + proposal.record_id,
        "local-reviewed-template",
    )
    return {"entity_id": proposal.entity.id, "already_applied": False}
