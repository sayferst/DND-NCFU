"""Engine-only adapter. Preview is inert; commit uses the existing replayed transaction."""

from rpg_vkr.domain.catalog import Definition, Entity, seed_catalog
from rpg_vkr.world_library.model import digest, normalized

CATEGORY = {
    "source_creature": "creatures",
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
DESCRIPTIVE_ONLY = {
    "skill",
    "race",
    "source_reference",
}
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
    revisions = {}

    def convert(id, revision=None):
        revision = revision or library.revision(id)
        if id in resolved:
            if revisions[id] != revision:
                raise ValueError("Conflicting pinned component revisions")
            return resolved[id]
        revisions[id] = revision
        row = library.get(id, revision)
        if row["profile"] in {
            "source_creature",
            "source_equipment",
            "spell",
            "rune",
            "scroll",
            "combination",
        } and (
            not getattr(session, "is_unified", False)
            or session.gameplay.get("catalog_revision") != 3
        ):
            raise ValueError("Creature handler requires canonical catalog3 campaign")
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
            if profile in {"npc", "creature", "boss", "source_creature"}
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
        if profile == "source_creature":
            from rpg_vkr.world_library.creature_rules import compile_creature

            properties.update(compile_creature(row))
        if profile == "source_equipment":
            from rpg_vkr.world_library.equipment_rules import compile_equipment

            rules = compile_equipment(row)
            properties.update(
                mass_g=rules["mass_g"],
                durability=rules["durability"],
                library_item_rules=rules,
                portable=rules["mass_g"] <= 30000,
            )
        from rpg_vkr.world_library.physical_rules import PROFILES, compile_physical

        if profile in PROFILES:
            rules = compile_physical(row)
            properties.update(library_item_rules=rules, portable=rules["mass_g"] <= 30000)
        if profile == "recipe":
            from rpg_vkr.world_library.recipe_rules import compile_recipe

            recipe_links = []
            for relation, target, target_revision, quantity in library.execute(
                "SELECT relation,target_id,target_revision,quantity FROM wl_links "
                "WHERE id=? AND revision=? AND relation IN ('input','output') ORDER BY ordinal",
                (id, revision),
            ).fetchall():
                recipe_links.append(
                    {
                        "relation": relation,
                        "definition": convert(target, target_revision),
                        "quantity": quantity,
                    }
                )
            properties.update(
                library_recipe_rules=compile_recipe(
                    row, recipe_links, existing | {d.id: d for d in definitions}
                ),
                portable=True,
                mass_g=1,
                durability=1,
            )
        if profile in {"spell", "rune", "scroll", "combination"}:
            from rpg_vkr.world_library.magic_rules import compile_magic

            dependencies = []
            for target, target_revision in library.execute(
                "SELECT target_id,target_revision FROM wl_links WHERE id=? AND revision=? "
                "AND relation IN ('spell','combines') ORDER BY ordinal",
                (id, revision),
            ).fetchall():
                dependency = convert(target, target_revision)
                definition = existing.get(dependency) or next(
                    value for value in definitions if value.id == dependency
                )
                dependencies.append(definition.properties["library_magic_rules"])
            properties.update(
                library_magic_rules=compile_magic(row, dependencies),
                portable=True,
                mass_g=a.get("mass_g", 1),
                durability=a.get("durability", 1),
            )
        properties |= {
            "library_id": id,
            "library_revision": revision,
            "library_digest": digest(row),
            "description": row["description"],
            "library_attributes": a
            if profile != "source_creature"
            else {"appearance_homebrew": a["appearance_homebrew"], "source_url": a["source_url"]},
            "mechanics": "canonical-basic-combat-1; unsupported features listed explicitly"
            if profile == "source_creature"
            else "descriptive-until-engine-handler",
        }
        definition = Definition(
            id,
            row["name"],
            kind,
            (CATEGORY.get(profile, "miscellaneous"),),
            properties,
            price_cp=properties.get("library_item_rules", {}).get("price_cp", row["price_cp"]),
            materials=materials,
            origin="generated",
        )
        definitions.append(definition)
        resolved[id] = id
        return id

    target = convert(template_id)
    world = session.interaction_state()
    target_definition = existing.get(target) or next(d for d in definitions if d.id == target)
    instance_state = None
    if template_id in LEGACY_MATERIALS and target == LEGACY_MATERIALS[template_id][0]:
        from rpg_vkr.world_library.physical_rules import compile_physical

        instance_rules = compile_physical(library.get(template_id, revisions[template_id]))
        instance_state = {
            "condition": instance_rules["durability"],
            "library_instance_rules": instance_rules,
        }
    entity = Entity(
        instance_id,
        target,
        world.current,
        state=instance_state
        or (
            {"condition": target_definition.properties["durability"]}
            if any(
                target_definition.properties.get(key)
                for key in ("library_magic_rules", "library_recipe_rules")
            )
            or target_definition.properties.get("library_item_rules", {}).get("rules_version")
            == "library-equipment-2"
            else None
        ),
    )
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
