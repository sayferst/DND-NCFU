"""Policy-four projection of real NPC-owned items; no item or money creation."""

from rpg_vkr.domain import game_catalog as content


def import_items(e):
    existing = {i["id"] for i in e.state["items"]}
    for actor in e.catalog.entities:
        if actor.id in existing or actor.owner_id not in e.refs or actor.quantity <= 0:
            continue
        definition = e.definitions[actor.definition_id]
        template = definition.properties.get("game_template_id")
        if definition.kind not in ("item", "material") or not template:
            continue
        row = content.row(template)
        if row["kind"] not in ("material", "weapon", "armour", "household", "consumable"):
            raise ValueError("Свойство предмета ссылается на неподходящий шаблон.")
        state = actor.state or {}
        quality = state.get("quality", 1)
        if type(quality) is not int or not 1 <= quality <= 5:
            raise ValueError("Неверное качество предмета NPC.")
        cap = row.get("durability", 20) + 3 * (quality - 1)
        condition = state.get("condition", definition.properties.get("durability", cap))
        if type(condition) is not int or condition < 0:
            raise ValueError("Неверная прочность предмета NPC.")
        item = {
            "id": actor.id,
            "source": actor.id,
            "owner": actor.owner_id,
            "name": definition.name,
            "template": template,
            "kind": row["kind"],
            "quantity": actor.quantity,
            "durability": min(cap, condition),
            "durability_cap": cap,
            "quality": quality,
            "price_cp": definition.price_cp if definition.price_cp is not None else row["price_cp"],
        }
        for key in ("open", "deployed", "made_by", "spell_override"):
            if key in state:
                item[key] = state[key]
        if row.get("category") == "ammunition":
            item["ammunition"] = True
        e.state["items"].append(item)
        existing.add(actor.id)


def accessible(e, item, owner):
    if owner not in e.refs or item["quantity"] <= 0:
        return False
    thing = e.things.get(item["id"])
    if thing is None:
        return not item.get("source")
    if e.scene.root_holder(thing) not in (owner, e.refs[owner].place):
        return False
    cursor = thing
    while cursor.holder in e.things:
        cursor = e.things[cursor.holder]
        physical = (e.actors[cursor.id].state or {}) if cursor.id in e.actors else {}
        cached = next((i for i in e.state["items"] if i["id"] == cursor.id), {})
        if cached.get("open", physical.get("open", True)) is False:
            return False
    return True
