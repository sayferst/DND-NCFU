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


def preview(
    library, session, template_id, instance_id, *, with_inventory=False, new_revision=False
):
    """Pin dependency closure and scene. Never grant HP, money, resources or rolls."""
    from rpg_vkr.domain.catalog import Registration, register

    catalog = session.catalog or seed_catalog()
    if type(with_inventory) is not bool or type(new_revision) is not bool:
        raise ValueError("Creation options must be Boolean")
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
        definition_id = id
        if id in existing:
            if existing[id].properties.get("library_digest") == digest(row):
                resolved[id] = id
                return id
            if not new_revision or existing[id].properties.get("library_id") != id:
                raise ValueError("World pins a different template revision")
            definition_id = id[:50] + "_v" + digest(row)[:10]
            if definition_id in existing:
                if existing[definition_id].properties.get("library_digest") != digest(row):
                    raise ValueError("Revision identity collision")
                resolved[id] = definition_id
                return definition_id
        if normalized(row["name"]) in by_name and definition_id == id:
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
        if profile in {"npc", "creature", "boss"} and "abilities" in a:
            properties.update(a["abilities"])
            properties.update(
                armour_class=a["armour_class"],
                damage_dice=a["damage_dice"],
                weapon="unarmed",
                level=a["level"],
            )
        if profile == "weapon":
            properties["damage_dice"] = f"{a['damage_count']}d{a['damage_die']}"
        if profile == "npc" and (
            row["provenance"]["generator"] == "world-library-4"
            or a.get("social_version") == "library-social-1"
        ):
            from rpg_vkr.world_library.social_rules import compile_social

            properties["library_social_rules"] = compile_social(row)
            properties["can_trade"] = a.get(
                "can_trade",
                a["profession"]
                in {
                    "торговец",
                    "кузнец",
                    "повар",
                    "лекарь",
                    "гончар",
                    "ткач",
                    "сапожник",
                },
            )
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
            if "pack_v1" in a:
                properties["library_pack_rules"] = a["pack_v1"]
        from rpg_vkr.world_library.physical_rules import PROFILES, compile_physical

        if profile in PROFILES:
            rules = compile_physical(row)
            properties.update(library_item_rules=rules, portable=rules["mass_g"] <= 30000)
        from rpg_vkr.world_library.utility_rules import PROFILES as UTILITY_PROFILES
        from rpg_vkr.world_library.utility_rules import compile_utility

        if profile in UTILITY_PROFILES and (
            row["provenance"]["generator"] == "world-library-3"
            or a.get("utility_version") == "library-utility-1"
        ):
            properties["library_utility_rules"] = compile_utility(row)
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
            definition_id,
            a["pack_v1"]["unit_name"] + " · " + id[-8:] if "pack_v1" in a else row["name"],
            kind,
            (CATEGORY.get(profile, "miscellaneous"),),
            properties,
            price_cp=properties.get("library_item_rules", {}).get("price_cp", row["price_cp"]),
            materials=materials,
            origin="generated",
        )
        definitions.append(definition)
        resolved[id] = definition_id
        return definition_id

    target = convert(template_id)
    world = session.interaction_state()
    target_definition = existing.get(target) or next(d for d in definitions if d.id == target)
    instance_state = None
    if target_definition.properties.get("library_social_rules"):
        instance_state = {
            "library_social_version": 1,
            "mood": target_definition.properties["library_social_rules"]["initial"],
            "relations": {},
        }
    if target_definition.properties.get("library_utility_rules", {}).get("profile") == "food":
        instance_state = {
            "library_created_minute": session.gameplay["minute"],
            "condition": target_definition.properties["library_item_rules"]["durability"],
        }
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
        quantity=target_definition.properties.get("library_pack_rules", {}).get("quantity", 1),
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
    entities = [entity]
    if with_inventory and target_definition.kind == "actor":
        from dataclasses import replace

        inventory = library.execute(
            "SELECT target_id,target_revision,quantity FROM wl_links "
            "WHERE id=? AND revision=? AND relation='starting_inventory' ORDER BY ordinal",
            (template_id, revisions[template_id]),
        ).fetchall()
        actor_state = dict(entity.state or {})
        actor_state["library_inventory_version"] = 1
        actor_state["mood"] = target_definition.properties["library_attributes"].get(
            "initial_mood", "wary"
        )
        for number, (item_id, revision, quantity) in enumerate(inventory):
            item_definition_id = convert(item_id, revision)
            item_definition = existing.get(item_definition_id) or next(
                d for d in definitions if d.id == item_definition_id
            )
            import hashlib

            child_id = (
                instance_id[:40]
                + "_inv"
                + hashlib.sha256(instance_id.encode()).hexdigest()[:8]
                + "_"
                + str(number)
            )
            state = {"condition": item_definition.properties.get("durability", 20)}
            if item_definition.properties.get("library_utility_rules", {}).get("profile") == "food":
                state["library_created_minute"] = session.gameplay["minute"]
            entities.append(
                Entity(child_id, item_definition_id, instance_id, instance_id, quantity, state)
            )
            if item_definition.properties.get("library_item_rules", {}).get("kind") == "weapon":
                actor_state.setdefault("library_weapon", child_id)
            item_rules = item_definition.properties.get("library_item_rules", {})
            if item_rules.get("kind") == "armour":
                slot = "library_shield" if item_rules["category"] == "shield" else "library_armour"
                actor_state.setdefault(slot, child_id)
        entities[0] = replace(entity, state=actor_state)
    # The same validator used by commit rejects duplicate IDs, hero grants and stale scenes.
    record = Registration(
        tuple(definitions),
        tuple(entities),
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
