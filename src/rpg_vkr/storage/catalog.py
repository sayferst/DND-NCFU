"""One bounded, parameterized SQLite view of catalog types and live campaign instances."""

import json
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from rpg_vkr.domain.catalog import CATEGORIES, Definition, effective_properties, seed_catalog
from rpg_vkr.domain.combat import ACTORS


def live_records(session):
    """Legacy bindings are read from their sole current state, never a second wallet."""
    catalog = session.catalog or seed_catalog()
    resource_world = session.interactive_world and session.interactive_world.version in {
        "interactive-world-3",
        "interactive-world-4",
    }
    types = {d.id: d.to_dict() for d in catalog.definitions}
    records = {}

    def put(id, type_id, parent, owner, quantity, state=None, binding=""):
        records[id] = {
            "id": id,
            "definition_id": type_id,
            "parent_id": parent,
            "owner_id": owner,
            "quantity": quantity,
            "state": state or {},
            "binding": binding,
        }

    put(
        "legacy_bandages",
        "type_bandage",
        "hero",
        "hero",
        session.world.bandages,
        binding="world.bandages",
    )
    types["type_currency"] = Definition(
        "type_currency",
        "Золото",
        "item",
        ("miscellaneous",),
        {"currency": "gold", "copper_units_per_coin": 100, "mass_g": 5, "volume_ml": 1},
        origin="legacy-adapter",
    ).to_dict()
    put("legacy_gold", "type_currency", "hero", "hero", session.world.gold, binding="world.gold")
    put(
        "legacy_quest_cargo",
        "type_quest_cargo",
        "hero",
        "hero",
        session.world.basket,
        {"quest": session.world.quest},
        binding="world.basket",
    )
    if session.progress.enabled and not session.gameplay:
        type_id = {
            "fighter": "type_training_sword",
            "scout": "type_knife",
            "scholar": "type_staff",
        }[session.progress.class_id]
        put("legacy_equipment", type_id, "hero", "hero", 1, binding="progress.equipment")
        put("legacy_book", "type_book", "hero", "hero", 1, binding="progress.book")
    if session.gameplay:
        from rpg_vkr.domain.d20_combat import ARMOUR, WEAPONS
        from rpg_vkr.domain.gameplay import ITEM_NAMES, PRICES

        state = session.gameplay
        types["type_copper"] = Definition(
            "type_copper",
            "Медные монеты",
            "item",
            ("miscellaneous",),
            {"currency": "copper", "copper_units_per_coin": 1},
            origin="project-homebrew",
        ).to_dict()
        put(
            "gameplay_copper",
            "type_copper",
            "hero",
            "hero",
            state["copper"],
            binding="gameplay.copper",
        )
        if session.schema_version >= 28:
            from rpg_vkr.domain.content_v5 import ITEMS as ITEM_NAMES
            from rpg_vkr.domain.content_v5 import PRICES
        for value in state["items"]:
            kind = value["kind"]
            type_id = "v3_type_" + kind
            if "source" in value:
                type_id = "v3_source_" + value["id"]
            category = (
                "weapons"
                if kind in WEAPONS
                else "armour"
                if kind in ARMOUR or kind == "shield"
                else "materials"
                if kind in {"iron", "cloth", "herb"}
                else "miscellaneous"
            )
            props = {"durability": 20, "rules": state["version"]}
            if kind in WEAPONS:
                props.update(damage_dice=WEAPONS[kind][0], hands=WEAPONS[kind][1])
            types[type_id] = Definition(
                type_id,
                value.get("name") or ITEM_NAMES[kind],
                "item",
                (category,),
                props,
                price_cp=value.get("price_cp", PRICES[kind]),
                origin="project-homebrew",
            ).to_dict()
            put(
                value["id"],
                type_id,
                value["owner"],
                value["owner"],
                1,
                {
                    "durability": value["durability"],
                    "quality": value["quality"],
                    "equipped": next(
                        (
                            slot
                            for slot in ("weapon", "armour", "shield")
                            if state[slot] == value["id"]
                        ),
                        "",
                    ),
                },
                "gameplay.items",
            )
    for key, spec in ACTORS.items():
        if session.generated_world and not any(
            a.id == key for a in session.interaction_state().actor_refs
        ):
            continue
        category = "creatures" if key in {"wolf", "boar"} else "npcs"
        types["type_actor_" + key] = Definition(
            "type_actor_" + key,
            spec[0],
            "actor",
            (category,),
            {
                "hp_max": spec[2],
                "class": "legacy",
                "rules": (session.gameplay or {}).get("version", "homebrew-combat-1"),
            },
            origin="legacy-adapter",
        ).to_dict()
        state = {
            "hp": session.combat.actor(key).hp,
            "disposition": session.combat.actor(key).disposition,
            "gold_cp": (
                session.world.shop_gold * 100 + (session.gameplay or {}).get("shop_copper", 0)
            )
            if key == "merchant"
            else None,
        }
        if session.legacy_catalog_actor(key).state.get("life") == "dead":
            state["life"] = "dead"
        profile = session.campaign.profile(key)
        if profile:
            state["public_description"] = profile.appearance
        put(key, "type_actor_" + key, spec[1], "", 1, state, "combat." + key)
    mapping = {"apples": "type_apple", "produce_basket": "type_basket"}
    mapping.update({e.id: e.definition_id for e in catalog.entities})
    if session.schema_version >= 25:
        from rpg_vkr.domain.resources import type_mapping

        mapping.update(type_mapping(catalog, session.catalog_aliases))
    for i, turn in enumerate(session.turns, 1):
        if turn.trade and turn.trade.item_id in mapping:
            mapping[f"split_{i}_0"] = mapping[turn.trade.item_id]
        if turn.interaction:
            for j, step in enumerate(turn.interaction.plan.steps):
                if step.target in mapping:
                    mapping[f"split_{i}_{j}"] = mapping[step.target]
    for e in catalog.entities:
        if (
            resource_world
            and types[e.definition_id]["kind"] != "actor"
            and not any(t.id == e.id for t in session.interactive_world.things)
        ):
            continue
        put(e.id, e.definition_id, e.parent_id, e.owner_id, e.quantity, e.state)
    if session.interactive_world:
        if resource_world:
            records.pop("legacy_gold", None)
            records.pop("legacy_bandages", None)
        for a in session.interactive_world.actor_refs:
            if a.id in records:
                records[a.id]["parent_id"] = a.place
        for t in session.interactive_world.things:
            from rpg_vkr.domain.resources import RESOURCE_TYPES

            type_id = (
                RESOURCE_TYPES[t.resource]
                if t.resource
                else mapping.get(t.id, "imported_type_" + t.id)
            )
            if type_id not in types:
                types[type_id] = Definition(
                    type_id,
                    t.name,
                    "item",
                    ("miscellaneous",),
                    {"container": t.container},
                    origin="legacy-adapter",
                ).to_dict()
            old = records.get(t.id, {})
            put(t.id, type_id, t.holder, t.owner, t.quantity, old.get("state"))
    for value in records.values():
        if types[value["definition_id"]]["kind"] != "actor":
            continue
        coins = sum(
            t.quantity
            for t in session.interaction_state().things
            if t.resource == "gold" and session.interaction_state().root_holder(t) == value["id"]
        )
        if coins:
            value["state"] = dict(value["state"])
            value["state"]["wealth_cp"] = (value["state"].get("gold_cp") or 0) + coins * 100
    return types, records


def populate_catalog(db, session):
    db.executescript("""
        CREATE TABLE catalog_types(id TEXT PRIMARY KEY, name TEXT NOT NULL,
            kind TEXT NOT NULL, rarity TEXT NOT NULL, price_cp INTEGER, payload TEXT NOT NULL);
        CREATE TABLE catalog_categories(type_id TEXT NOT NULL REFERENCES catalog_types(id),
            category TEXT NOT NULL, PRIMARY KEY(type_id,category));
        CREATE TABLE catalog_instances(id TEXT PRIMARY KEY,
            type_id TEXT NOT NULL REFERENCES catalog_types(id), parent_id TEXT NOT NULL,
            owner_id TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity>=0),
            payload TEXT NOT NULL);
        CREATE TABLE catalog_composition(type_id TEXT NOT NULL REFERENCES catalog_types(id),
            material_id TEXT NOT NULL REFERENCES catalog_types(id), parts INTEGER NOT NULL);
        CREATE TABLE catalog_effects(type_id TEXT NOT NULL REFERENCES catalog_types(id),
            effect_index INTEGER NOT NULL, payload TEXT NOT NULL,
            PRIMARY KEY(type_id,effect_index));
        CREATE TABLE catalog_loot(type_id TEXT NOT NULL REFERENCES catalog_types(id),
            item_type_id TEXT NOT NULL REFERENCES catalog_types(id), payload TEXT NOT NULL);
        CREATE TABLE catalog_events(turn_index INTEGER PRIMARY KEY, model TEXT NOT NULL,
            reason TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE INDEX catalog_parent ON catalog_instances(parent_id);
        CREATE INDEX catalog_type_instances ON catalog_instances(type_id);
        CREATE INDEX catalog_sections ON catalog_categories(category,type_id);
    """)
    types, records = live_records(session)

    def dump(value):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    db.executemany(
        "INSERT INTO catalog_types VALUES (?,?,?,?,?,?)",
        [
            (d["id"], d["name"], d["kind"], d["rarity"], d["price_cp"], dump(d))
            for d in types.values()
        ],
    )
    db.executemany(
        "INSERT INTO catalog_categories VALUES (?,?)",
        [(d["id"], c) for d in types.values() for c in d["categories"]],
    )
    db.executemany(
        "INSERT INTO catalog_instances VALUES (?,?,?,?,?,?)",
        [
            (e["id"], e["definition_id"], e["parent_id"], e["owner_id"], e["quantity"], dump(e))
            for e in records.values()
        ],
    )
    db.executemany(
        "INSERT INTO catalog_composition VALUES (?,?,?)",
        [(d["id"], r["definition_id"], r["parts"]) for d in types.values() for r in d["materials"]],
    )
    db.executemany(
        "INSERT INTO catalog_effects VALUES (?,?,?)",
        [(d["id"], i, dump(r)) for d in types.values() for i, r in enumerate(d["effects"])],
    )
    db.executemany(
        "INSERT INTO catalog_loot VALUES (?,?,?)",
        [(d["id"], r["definition_id"], dump(r)) for d in types.values() for r in d["loot"]],
    )
    db.executemany(
        "INSERT INTO catalog_events VALUES (?,?,?,?)",
        [
            (i, t.catalog.model, t.catalog.reason, dump(t.catalog.to_dict()))
            for i, t in enumerate(session.turns, 1)
            if t.catalog
        ],
    )


class CatalogIndex:
    def __init__(self, session):
        self.db = sqlite3.connect(":memory:")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA application_id=1145980227")
        self.session = session
        try:
            populate_catalog(self.db, session)
            self.db.execute("CREATE TABLE snapshot(version INTEGER,payload TEXT)")
            self.db.execute(
                "INSERT INTO snapshot VALUES (?,?)",
                (21, json.dumps(session.to_dict(), ensure_ascii=False)),
            )
            self.db.commit()
        except Exception:
            self.db.close()
            raise

    def close(self):
        self.db.close()

    def _visible(self, row):
        current = self.session.current_place_id
        parents = {
            r[0]: r[1] for r in self.db.execute("SELECT id,parent_id FROM catalog_instances")
        }
        cursor, seen = row["id"], set()
        while cursor in parents:
            if cursor in seen:
                return False
            seen.add(cursor)
            cursor = parents[cursor]
        if cursor in {current, "hero"}:
            return True
        visited = self.session.visited_places
        return cursor in visited

    def lookup(self, id, *, public=True):
        if not isinstance(id, str) or len(id) > 80:
            raise ValueError("Неверный ID запроса.")
        row = self.db.execute("SELECT payload FROM catalog_instances WHERE id=?", (id,)).fetchone()
        if row:
            entity = json.loads(row[0])
            if public and not self._visible(entity):
                return None
            definition = json.loads(
                self.db.execute(
                    "SELECT payload FROM catalog_types WHERE id=?", (entity["definition_id"],)
                ).fetchone()[0]
            )
        else:
            entity = None
            value = self.db.execute(
                "SELECT payload FROM catalog_types WHERE id=?", (id,)
            ).fetchone()
            if not value:
                return None
            definition = json.loads(value[0])
            if public and definition["kind"] == "actor":
                visible_instances = self.db.execute(
                    "SELECT payload FROM catalog_instances WHERE type_id=?", (id,)
                ).fetchall()
                if not any(self._visible(json.loads(r[0])) for r in visible_instances):
                    return None
        if public and definition["kind"] == "actor":
            definition["properties"] = {
                k: v
                for k, v in definition["properties"].items()
                if k in {"public_description", "ancestry", "appearance"}
            }
            definition["loot"] = []
            if entity:
                entity["state"] = {
                    k: v
                    for k, v in entity["state"].items()
                    if k in {"public_description", "disposition", "life"}
                }
        value = {"definition": definition, "entity": entity}
        if definition["kind"] != "actor":
            # Lookup material records, not the complete DB, for a reproducible calculation.
            materials = tuple(
                Definition.from_dict(
                    json.loads(
                        self.db.execute(
                            "SELECT payload FROM catalog_types WHERE id=?", (r["definition_id"],)
                        ).fetchone()[0]
                    )
                )
                for r in definition["materials"]
            )
            current = Definition.from_dict(definition)
            computed, trace = effective_properties((*materials, current), current)
            value["derived_properties"] = computed
            value["material_calculation"] = trace
        return value

    def search(self, text="", category="", *, limit=20, public=True):
        if category and category not in CATEGORIES:
            raise ValueError("Неизвестный раздел поиска.")
        if (
            not isinstance(text, str)
            or len(text) > 500
            or type(limit) is not int
            or not 1 <= limit <= 50
        ):
            raise ValueError("Некорректный запрос каталога.")
        # Python casefold supplies Unicode matching; SQLite's default LOWER is ASCII-only.
        needle = text.casefold()
        ids = self.db.execute(
            """
            SELECT t.id,t.name FROM catalog_types t
            WHERE (?='' OR EXISTS(SELECT 1 FROM catalog_categories c
                WHERE c.type_id=t.id AND c.category=?)) ORDER BY t.name
        """,
            (category, category),
        ).fetchall()
        result = []
        for id, name in ids:
            if needle and needle not in name.casefold() and needle not in id.casefold():
                continue
            value = self.lookup(id, public=public)
            if value:
                result.append(value)
            if len(result) == limit:
                break
        return result

    def relevant(self, text, *, limit=6):
        import re

        result = []
        for token in re.findall(r"[a-z][a-z0-9_]{2,63}|[а-яё]{4,}", text.casefold())[:20]:
            direct = self.lookup(token)
            values = [direct] if direct else self.search(token[:7], limit=2)
            for value in values:
                if value not in result:
                    result.append(value)
            if len(result) >= limit:
                break
        result = result[:limit]
        while result and len(json.dumps(result, ensure_ascii=False)) > 24000:
            result.pop()
        return result

    def narrator_record(self, id):
        value = self.lookup(id)
        raw = self.lookup(id, public=False)
        if value and raw and value["definition"]["kind"] == "actor":
            value["npc_voice"] = {
                "goals": raw["definition"]["properties"].get("goals", []),
                "traits": raw["definition"]["properties"].get("traits", []),
                "relations_to_hero": raw["entity"]["state"].get("relations", {}).get("hero", {}),
                "observed_event": raw["entity"]["state"].get("last_observed_event"),
            }
        return value

    def export(self, path):
        path = Path(path)
        with path.open("xb"):
            pass
        try:
            with closing(sqlite3.connect(path)) as target:
                self.db.backup(target)
        except Exception:
            path.unlink(missing_ok=True)
            raise

    def publish(self, path):
        """Replace only our working projection, never a foreign database or a save slot."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as old:
                if old.execute("PRAGMA application_id").fetchone()[0] != 1145980227:
                    raise ValueError("По этому пути находится другая база; она не перезаписана.")
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=path.parent, suffix=".sqlite3.tmp", delete=False
            ) as f:
                temporary = Path(f.name)
            # A Connection context commits/rolls back, but does not close the file.
            # Windows requires both the old and temporary handles closed for replace.
            with closing(sqlite3.connect(temporary)) as target:
                self.db.backup(target)
            os.replace(temporary, path)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
