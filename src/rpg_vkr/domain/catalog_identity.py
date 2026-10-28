"""Identity validation for synchronized physical items; legacy validation stays frozen."""


def ensure_names(state, catalog):
    if not catalog or state.get("catalog_revision") != 3:
        from rpg_vkr.domain.gameplay import ensure_names as legacy

        return legacy(state, catalog)
    items = {i["id"]: i for i in state["items"]}
    definitions = {d.id: d for d in catalog.definitions}
    if items.keys() & definitions.keys():
        raise ValueError("ID нового предмета совпал с определением мира.")
    for entity in catalog.entities:
        if entity.id not in items:
            continue
        item = items[entity.id]
        definition = definitions[entity.definition_id]
        matched = (
            item.get("template")
            and definition.properties.get("game_template_id") == item["template"]
        )
        if definition.kind == "actor" or not (matched or item.get("source") == entity.id):
            raise ValueError("ID нового предмета совпал с существующим объектом мира.")
