"""Engine-only adapter. Preview is inert; commit uses the existing replayed transaction."""

from rpg_vkr.domain.catalog import Definition, Entity, seed_catalog
from rpg_vkr.world_library.model import digest, normalized

CATEGORY = {
    "weapon": "weapons",
    "ammunition": "weapons",
    "armour": "armour",
    "material": "materials",
    "ore": "materials",
    "ingredient": "materials",
    "plant": "plants",
    "medicine": "medicine",
    "poison": "medicine",
    "npc": "npcs",
    "creature": "creatures",
    "boss": "bosses",
    "quest": "quest",
}
DESCRIPTIVE_ONLY = {"spell", "rune", "scroll", "combination", "skill", "race", "recipe"}
LEGACY_MATERIALS = {
    "wl_material_0": ("mat_ash", "Ясень"),
    "wl_material_2": ("mat_oak", "Дуб"),
    "wl_material_8": ("mat_iron", "Железо"),
    "wl_material_11": ("mat_copper", "Медь"),
}


def preview(library, session, template_id, instance_id):
    """Pin dependency closure and scene. Never grant HP, money, resources or rolls."""
    from rpg_vkr.domain.catalog import Registration, register

    catalog = session.catalog or seed_catalog()
    library.get(template_id)  # Top-level retired templates cannot spawn new instances.
    existing = {r.id: r for r in catalog.definitions}
    by_name = {normalized(r.name): r.id for r in catalog.definitions}
    definitions = []
    resolved = {}

    def convert(id, revision=None):
        if id in resolved:
            return resolved[id]
        revision = revision or library.revision(id)
        row = library.get(id, revision)
        if id in LEGACY_MATERIALS and revision == 1:
            legacy_id, name = LEGACY_MATERIALS[id]
            if (
                legacy_id in existing
                and normalized(row["name"]) == normalized(name)
                and normalized(existing[legacy_id].name) == normalized(name)
            ):
                resolved[id] = legacy_id
                return legacy_id
        if row["profile"] in DESCRIPTIVE_ONLY:
            raise ValueError("No executable handler for this content profile")
        if id in existing:
            if existing[id].properties.get("library_digest") != digest(row):
                raise ValueError("World pins a different template revision")
            resolved[id] = id
            return id
        if normalized(row["name"]) in by_name:
            # Explicit reconciliation is needed; never silently equate same-name content.
            raise ValueError("Name already exists in world; reconcile aliases explicitly")
        pinned = library.execute(
            "SELECT target_id,target_revision,quantity FROM wl_links "
            "WHERE id=? AND revision=? AND relation='component' ORDER BY ordinal",
            (id, revision),
        ).fetchall()
        materials = tuple(
            {"definition_id": convert(target, target_revision), "parts": quantity}
            for target, target_revision, quantity in pinned
        )
        profile = row["profile"]
        kind = (
            "actor"
            if profile in {"npc", "creature", "boss"}
            else "material"
            if profile in {"material", "ore", "ingredient", "plant"}
            else "item"
        )
        a = row["attributes"]
        properties = {
            k: v
            for k, v in a.items()
            if k in {"mass_g", "durability", "quality", "hp_max", "penetration", "defence", "hands"}
        }
        if profile == "weapon":
            properties["damage_dice"] = f"{a['damage_count']}d{a['damage_die']}"
        properties |= {
            "library_id": id,
            "library_revision": revision,
            "library_digest": digest(row),
            "description": row["description"],
            "library_attributes": a,
            "mechanics": "descriptive-until-engine-handler",
        }
        definition = Definition(
            id,
            row["name"],
            kind,
            (CATEGORY.get(profile, "miscellaneous"),),
            properties,
            price_cp=row["price_cp"],
            materials=materials,
            origin="generated",
        )
        definitions.append(definition)
        resolved[id] = id
        return id

    target = convert(template_id)
    world = session.interaction_state()
    entity = Entity(instance_id, target, world.current)
    # The same validator used by commit rejects duplicate IDs, hero grants and stale scenes.
    record = Registration(
        tuple(definitions),
        (entity,),
        "Создание из библиотеки " + template_id,
        "world-library-1",
        len(session.turns),
        world,
    )
    register(catalog, world, record)
    return record


def commit(session, record):
    """Trusted engine entry only. Engine journal is the atomic audit and replay source."""
    if record.before != session.interaction_state() or record.base_turn != len(session.turns):
        raise ValueError("Stale scene/turn; preview again")
    return session.register_catalog(
        "Осмотреть созданную сцену",
        record.definitions,
        record.entities,
        record.reason,
        record.model,
    )
