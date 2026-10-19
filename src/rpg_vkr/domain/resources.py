"""Physical stacks are authoritative; legacy hero counters are checked read models."""

from dataclasses import replace

from rpg_vkr.domain.interactions import Thing

RESOURCE_TYPES = {"gold": "type_currency", "bandages": "type_bandage"}
POOL_IDS = {"gold": "legacy_gold", "bandages": "legacy_bandages"}
NAMES = {"gold": "Золотые монеты", "bandages": "Бинт"}
VERSION = "interactive-world-3"


def physical(scene):
    return scene.version == VERSION


def type_mapping(catalog, aliases=None):
    values = {e.id: e.definition_id for e in catalog.entities} if catalog else {}
    pending = dict(aliases or {})
    for _ in range(len(pending)):
        found = {key: values[source] for key, source in pending.items() if source in values}
        if not found:
            break
        values.update(found)
        for key in found:
            pending.pop(key)
    return values


def activate(scene, world, catalog=None, aliases=None):
    """Explicit lazy migration: old prose and previous frames remain unchanged."""
    if physical(scene):
        validate_balances(scene, world)
        return scene
    mapping = type_mapping(catalog, aliases)
    kinds = {type_id: field for field, type_id in RESOURCE_TYPES.items()}
    things = [replace(t, resource=kinds.get(mapping.get(t.id), "")) for t in scene.things]
    for field, id in POOL_IDS.items():
        amount = getattr(world, field)
        if amount:
            if any(t.id == id for t in things):
                raise ValueError("Конфликт ID при переносе старого ресурса.")
            things.append(Thing(id, NAMES[field], "hero", "hero", amount, resource=field))
    return replace(scene, things=tuple(things), actors=scene.actor_refs, version=VERSION)


def needed(scene, plan, catalog=None, aliases=None):
    if physical(scene):
        return True
    if any(s.target in POOL_IDS.values() for s in plan.steps):
        return True
    return any(
        value in RESOURCE_TYPES.values() for value in type_mapping(catalog, aliases).values()
    )


def balances(scene):
    return {
        field: sum(t.quantity for t in scene.carried() if t.resource == field)
        for field in RESOURCE_TYPES
    }


def project(scene, world):
    return replace(world, **balances(scene)) if physical(scene) else world


def validate_balances(scene, world):
    if physical(scene) and any(getattr(world, k) != v for k, v in balances(scene).items()):
        raise ValueError("Остатки ресурсов расходятся с физическими предметами.")


def properties(scene, id, catalog):
    from rpg_vkr.domain.catalog import seed_catalog

    types = {d.id: d for d in (catalog or seed_catalog()).definitions}
    entity = next((e for e in catalog.entities if e.id == id), None) if catalog else None
    thing = next((t for t in scene.things if t.id == id), None)
    type_id = entity.definition_id if entity else None
    if thing and thing.resource:
        type_id = RESOURCE_TYPES[thing.resource]
    if type_id == "type_currency":
        # Authored coin dimensions; not an SRD weight table or a metal simulation.
        return {"mass_g": 5, "volume_ml": 1}
    values = dict(types[type_id].properties) if type_id in types else {}
    if entity:
        values.update({k: v for k, v in (entity.state or {}).items() if k in {"locked", "open"}})
    return values


def accessible(scene, thing, catalog):
    if scene.root_holder(thing) != "hero":
        return False
    by_id = {t.id: t for t in scene.things}
    while thing.holder in by_id:
        thing = by_id[thing.holder]
        if properties(scene, thing.id, catalog).get("locked"):
            return False
    return True


def reconcile(scene, before, after, turn_index, catalog=None):
    """Apply a validated old rule's resource delta to actual stacks, without minting copies."""
    if not physical(scene):
        return scene
    validate_balances(scene, before)
    state = scene
    for field in RESOURCE_TYPES:
        delta = getattr(after, field) - getattr(before, field)
        if not delta:
            continue
        things = list(state.things)
        if delta > 0:
            loose = next(
                (t for t in things if t.resource == field and t.holder == t.owner == "hero"), None
            )
            if loose:
                things[things.index(loose)] = replace(loose, quantity=loose.quantity + delta)
            else:
                id = f"resource_{field}_{turn_index}"
                if any(t.id == id for t in things):
                    raise ValueError("Повторный ID поступления ресурса.")
                things.append(Thing(id, NAMES[field], "hero", "hero", delta, resource=field))
        else:
            remaining = -delta
            candidates = sorted(
                (t for t in things if t.resource == field and accessible(state, t, catalog)),
                key=lambda t: (t.holder != "hero", t.id),
            )
            if sum(t.quantity for t in candidates) < remaining:
                raise ValueError("Для действия не хватает доступного ресурса: " + NAMES[field])
            for item in candidates:
                amount = min(remaining, item.quantity)
                things.remove(item)
                if item.quantity > amount:
                    things.append(replace(item, quantity=item.quantity - amount))
                remaining -= amount
                if not remaining:
                    break
        state = replace(state, things=tuple(things))
    validate_balances(state, after)
    return state
