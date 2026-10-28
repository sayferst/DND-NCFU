"""Canonical content execution. Frozen campaigns continue their original replay path."""

from copy import deepcopy
from dataclasses import asdict, replace

from rpg_vkr.domain import game_catalog as content
from rpg_vkr.domain.catalog import Catalog, Definition, Entity, seed_catalog
from rpg_vkr.domain.character import Character, ability_modifier
from rpg_vkr.domain.interactions import InteractiveWorld, Thing
from rpg_vkr.domain.world import WorldState

RAW = ("iron", "wood", "herb", "cloth", "leather", "stone", "copper", "salt", "glass", "crystal")


def initial(base, character):
    state = deepcopy(base)
    state.update(
        content_revision=2,
        catalog_hash=content.digest(),
        statuses={},
        pending=[],
        cooldowns={},
        known_recipes=["recipe_production_0_0"],
        achievements=[],
        sequence=0,
        discoveries={},
        world_log=[],
    )
    if state["identity"]["class_id"] == "artisan":
        state["known_recipes"] = [
            f"recipe_{d}_{m}_0"
            for d in ("production", "repair", "smithing", "alchemy")
            for m in range(2)
        ]
    for item in state["items"]:
        kind = item["kind"]
        template = (
            f"mat_{RAW.index(kind)}_0"
            if kind in RAW and kind != "leather"
            else "house_0_0"
            if kind in ("tools", "locks")
            else f"gear_{'light' if kind == 'leather' else kind}_0_0"
            if kind in ("sword", "dagger", "longbow", "focus", "shield", "leather")
            else "use_dressings_0_0"
            if kind == "bandage"
            else "use_potions_3_0"
            if kind == "mana"
            else "house_4_4"
            if kind == "symbol"
            else "use_scrolls_0_0"
        )
        item.update(
            template=template,
            quantity=1,
            durability_cap=content.row(template).get("durability", 20),
        )
        item["durability"] = item["durability_cap"]
        item["price_cp"] = content.row(template).get("price_cp", 10)
        if kind.startswith("scroll_"):
            item["spell_override"] = "light" if kind == "scroll_light" else "heal"
        if kind == "arrow":
            item["template"] = "use_ammunition_0_0"
            item["ammunition"] = True
            item["price_cp"] = 2
    if not state["weapon"]:
        state["weapon"] = next(
            (i["id"] for i in state["items"] if content.row(i["template"])["kind"] == "weapon"), ""
        )
    return state


class Engine:
    def __init__(self, state, context, dice, args):
        self.state = deepcopy(state)
        self.char = Character.from_dict(context["character"])
        self.world = WorldState.from_dict(context["world"])
        if self.state.get("catalog_revision") == 3 and self.world.gold:
            self.state["copper"] += self.world.gold * 100
            self.world = replace(self.world, gold=0)
        self.scene = InteractiveWorld.from_dict(context["scene"])
        self.catalog = (
            Catalog.from_dict(context["catalog"]) if context["catalog"] else seed_catalog()
        )
        self.dice, self.args, self.turn = dice, args, context["turn"]
        self.rolls, self.attacks, self.events = [], [], []
        self.last_damage = 0
        self.action_minutes = 1
        self.context_combat = context["combat"]
        self.text = []
        self.actors = {e.id: e for e in self.catalog.entities}
        self.definitions = {d.id: d for d in self.catalog.definitions}
        self.things = {t.id: t for t in self.scene.things}
        self.refs = {a.id: a for a in self.scene.actor_refs}
        for item in self.state["items"]:
            if item.get("source") in self.actors:
                entity = self.actors[item["source"]]
                item.update(owner=entity.owner_id, quantity=entity.quantity)
                if "open" in (entity.state or {}):
                    item["open"] = entity.state["open"]
        imported = {i["id"] for i in self.state["items"]}
        for thing in self.scene.carried():
            entity = self.actors.get(thing.id)
            if (
                entity
                and thing.id not in imported
                and self.definitions[entity.definition_id].properties.get("game_template_id")
            ):
                self.owned(thing.id)
        from rpg_vkr.domain.catalog_world import initialize

        initialize(self)

    def mint(self, prefix="item"):
        self.state["sequence"] += 1
        return f"{prefix}_{self.turn}_{self.state['sequence']}"

    def roll(self, expression, reason):
        value = self.dice.roll(expression, reason=reason)
        self.rolls.append(asdict(value) | {"index": value.rng_counter})
        return value.total

    def hero_bonus(self, task):
        from rpg_vkr.domain.unified import bonus

        result = bonus(self.state, self.char, task)[1]
        if task in ("melee", "ranged", "arcana"):
            result += self.status_power("hero", "accuracy")
        if task in ("ranged", "stealth"):
            result += sum(r.get("trait") == "precision" for _, r in self.worn())
        if task in ("smithing", "alchemy", "repair"):
            result += self.status_power("hero", "craft")
            tools = [
                self.template(i).get("strength", 1)
                for i in self.state["items"]
                if i["owner"] == "hero"
                and i["durability"] > 0
                and not i.get("ammunition")
                and self.template(i).get("capability") == "tools"
            ]
            result += max(tools, default=1) - 1
        if task in ("perception", "knowledge"):
            result += self.status_power("hero", "perception")
        if task in ("arcana", "faith", "knowledge"):
            result += self.status_power("hero", "clarity")
        if task == "stealth":
            result += self.status_power("hero", "conceal")
        if task == "perception" and not 6 <= self.state["minute"] // 60 % 24 < 20:
            result -= max(0, 2 - self.status_power("hero", "light"))
        if self.state["living_world"].get("weather") == "fog" and task in ("ranged", "perception"):
            result -= 2
        if task in ("smithing", "alchemy", "repair", "survival"):
            resource = self.args.get("material")
            if resource in RAW:
                resource = f"mat_{RAW.index(resource)}_0"
            resources = (
                [resource]
                if resource
                else list(content.row(self.args["recipe"])["ingredients"])
                if self.args.get("recipe") in content.load()
                else []
            )
            for key in resources:
                modifier = self.state["living_world"].get("environment", {}).get(key)
                if modifier and modifier["until"] > self.state["minute"]:
                    result += (
                        modifier["amount"]
                        if modifier["kind"] in ("thaw", "growth")
                        else -modifier["amount"]
                    )
        return result - self.status_power("hero", "weaken")

    def check(self, task, dc):
        value = self.roll("1d20", task)
        bonus = self.hero_bonus(task)
        self.text.append(f"d20({value}) {bonus:+} = {value + bonus} против DC {dc}")
        return value + bonus >= dc

    def template(self, item):
        return (
            content.row(item["template"])
            if item.get("template")
            else {
                "id": "legacy_misc",
                "kind": "miscellaneous",
                "category": "miscellaneous",
                "name": item["name"],
                "price_cp": item["price_cp"],
                "level": 1,
            }
        )

    def worn(self):
        for slot in ("armour", "shield"):
            try:
                item = self.owned(self.state[slot])
            except ValueError:
                continue
            if item["durability"] > 0:
                yield item, self.template(item)

    def owned(self, id):
        cursor = self.things.get(id)
        while cursor and cursor.holder in self.things:
            parent = self.things[cursor.holder]
            holder = next((i for i in self.state["items"] if i["id"] == parent.id), {})
            if holder.get("open") is False:
                raise ValueError("Сначала откройте контейнер.")
            cursor = parent
        item = next(
            (i for i in self.state["items"] if i["id"] == id and i["owner"] == "hero"), None
        )
        entity = self.actors.get(id)
        if item and (
            not item.get("source")
            or id in self.things
            and self.scene.root_holder(self.things[id]) == "hero"
        ):
            return item
        if (
            entity
            and entity.owner_id == "hero"
            and id in self.things
            and self.scene.root_holder(self.things[id]) == "hero"
        ):
            definition = self.definitions[entity.definition_id]
            template = definition.properties.get("game_template_id")
            item = {
                "id": id,
                "source": id,
                "name": definition.name,
                "owner": "hero",
                "kind": "world_item",
                "quantity": entity.quantity,
                "durability": (entity.state or {}).get("condition", 20),
                "durability_cap": definition.properties.get("durability", 20),
                "price_cp": definition.price_cp or 0,
                "quality": 1,
            }
            if template:
                item["template"] = content.row(template)["id"]
                if self.state.get("catalog_revision") == 3:
                    row = content.row(template)
                    physical = entity.state or {}
                    quality = physical.get("quality", 1)
                    if type(quality) is not int or not 1 <= quality <= 5:
                        raise ValueError("Неверное качество физического предмета.")
                    cap = row.get("durability", 20) + 3 * (quality - 1)
                    item.update(kind=row["kind"], quality=quality, durability_cap=cap)
                    item["durability"] = min(cap, item["durability"])
                    for key in ("made_by", "spell_override", "deployed", "open"):
                        if key in physical:
                            item[key] = physical[key]
                    if row.get("category") == "ammunition":
                        item["ammunition"] = True
            elif definition.id == "type_bandage":
                item["template"] = "use_dressings_0_0"
            self.state["items"] = [i for i in self.state["items"] if i["id"] != id] + [item]
            return item
        raise ValueError("Предмет недоступен или не принадлежит герою.")

    def add_item(self, template, quantity=1, owner="hero", made_by=""):
        row = content.row(template)
        if row["kind"] not in ("material", "weapon", "armour", "consumable", "household"):
            raise ValueError("Запись не является вещью.")
        if row["kind"] in ("material", "consumable"):
            item = next(
                (
                    i
                    for i in self.state["items"]
                    if i.get("template") == template
                    and i["owner"] == owner
                    and i.get("made_by", "") == made_by
                    and (
                        not i.get("source")
                        or i["id"] in self.things
                        and self.scene.root_holder(self.things[i["id"]]) == owner
                    )
                ),
                None,
            )
            if item:
                item["quantity"] += quantity
                return item
        item = {
            "id": self.mint(),
            "template": template,
            "kind": row["kind"],
            "name": row["name"],
            "owner": owner,
            "quantity": quantity,
            "quality": 1,
            "price_cp": row.get("price_cp", 10),
            "durability": row.get("durability", 20),
            "durability_cap": row.get("durability", 20),
            "made_by": made_by,
        }
        self.state["items"].append(item)
        if row["kind"] == "consumable" and row["category"] == "ammunition":
            item["ammunition"] = True
        return item

    def consume_item(self, item, quantity=1):
        if type(quantity) is not int or not 1 <= quantity <= item["quantity"]:
            raise ValueError("Неверное количество.")
        item["quantity"] -= quantity
        if not item["quantity"]:
            self.state["items"].remove(item)
            self.actors.pop(item.get("source", item["id"]), None)
            self.things.pop(item.get("source", item["id"]), None)

    def require_materials(self, ingredients, multiplier=1):
        selected = []
        for template, amount in ingredients.items():
            remaining = amount * multiplier
            for item in list(self.state["items"]):
                if item.get("template") != template or item["owner"] != "hero":
                    continue
                try:
                    self.owned(item["id"])
                except ValueError:
                    continue
                count = min(remaining, item["quantity"])
                selected.append((item, count))
                remaining -= count
                if not remaining:
                    break
            if remaining:
                raise ValueError("Недостаточно материала: " + content.row(template)["name"])
        return selected

    def actor(self, id, alive=True):
        entity = self.actors.get(id)
        if entity is None or self.definitions[entity.definition_id].kind != "actor":
            raise ValueError("Неизвестное существо.")
        if alive and (entity.state or {}).get("hp", 1) <= 0:
            raise ValueError("Существо выбыло.")
        return entity, self.definitions[entity.definition_id]

    def hp(self, id):
        if id == "hero":
            return self.world.hp
        e, d = self.actor(id, alive=False)
        return (e.state or {}).get("hp", d.properties["hp_max"])

    def change_hp(self, id, delta):
        if id == "hero":
            self.world = replace(
                self.world, hp=max(0, min(self.world.max_hp, self.world.hp + delta))
            )
            return self.world.hp
        e, d = self.actor(id, alive=False)
        data = dict(e.state or {})
        data["hp"] = max(
            0, min(d.properties["hp_max"], data.get("hp", d.properties["hp_max"]) + delta)
        )
        if not data["hp"]:
            data["life"] = "unconscious"
        elif data.get("life") == "unconscious":
            data.pop("life", None)
        self.actors[id] = replace(e, state=data)
        return data["hp"]

    def actor_resource(self, id, name, delta):
        e, d = self.actor(id, alive=False)
        data = dict(e.state or {})
        before = data.get(name, 10)
        data[name] = max(0, min(30, before + delta))
        self.actors[id] = replace(e, state=data)
        return data[name] - before

    def status_power(self, id, name):
        return max(
            (
                r["power"]
                for r in self.state["statuses"].get(id, [])
                if r["op"] == name and r["until"] > self.state["minute"]
            ),
            default=0,
        )

    def status(self, id, name, power, duration, element="physical"):
        if name in ("slow", "stagger", "disarm") and self.status_power(id, "anchor"):
            return
        rows = self.state["statuses"].setdefault(id, [])
        rows[:] = [r for r in rows if not (r["op"] == name and r.get("element") == element)]
        rows.append(
            {
                "op": name,
                "power": power,
                "element": element,
                "until": self.state["minute"] + self.action_minutes + duration * 10,
                "next": self.state["minute"] + 10,
            }
        )

    def remove_status(self, id, name):
        self.state["statuses"][id] = [
            r for r in self.state["statuses"].get(id, []) if r["op"] != name
        ]

    def defence(self, id):
        if id != "hero":
            e, d = self.actor(id, alive=False)
            return (
                d.properties.get(
                    "armour_class", 10 + ability_modifier(d.properties.get("dexterity", 10))
                )
                + self.status_power(id, "defence")
                + min(3, (e.state or {}).get("fortification", 0))
            )
        base = 10 + ability_modifier(self.char.dexterity)
        for slot in ("armour", "shield"):
            try:
                item = self.owned(self.state[slot])
            except ValueError:
                continue
            if item["durability"] <= 0:
                continue
            row = self.template(item)
            if slot == "armour":
                base = row.get("defence", 11) + min(
                    row.get("dex_cap", 5), ability_modifier(self.char.dexterity)
                )
            else:
                base += row.get("defence", 2)
        if self.state["weapon"]:
            try:
                weapon = self.template(self.owned(self.state["weapon"]))
                base += int(weapon.get("trait") in ("guard", "parry"))
            except ValueError:
                pass
        return (
            base
            + self.status_power(id, "defence")
            + sum(r.get("trait") == "guard" for _, r in self.worn())
        )

    def damage(self, target, amount, element="physical", source="hero", reflection=True):
        previous_hp = self.hp(target)
        resistance = (
            self.status_power(target, "resist")
            if any(
                r["op"] == "resist" and r["element"] == element
                for r in self.state["statuses"].get(target, [])
            )
            else 0
        )
        if target != "hero":
            e, d = self.actor(target, alive=False)
            if d.properties.get("resistance") == element:
                resistance += 2
            if d.properties.get("vulnerability") == element:
                amount += 2
        else:
            for slot in ("armour", "shield"):
                try:
                    item = self.owned(self.state[slot])
                    row = self.template(item)
                except ValueError:
                    continue
                if item["durability"] > 0 and row.get("resistance") == element:
                    resistance += 1
                    material = content.row(row["material"], "material")
                    resistance += (
                        material["hardness"] // 6
                        if element == "physical"
                        else material["conductivity"] // 3
                    )
                    item["durability"] -= 1
                if item["durability"] > 0 and element == "physical" and row.get("trait") == "parry":
                    resistance += 1
                    item["durability"] -= 1
                if (
                    amount > 0
                    and source != "hero"
                    and row.get("trait") in ("weaken", "bleed", "slow", "mark")
                ):
                    self.status(source, row["trait"], 1, 2)
        shield = self.status_power(target, "shield")
        if shield:
            blocked = min(shield, amount)
            amount -= blocked
            self.remove_status(target, "shield")
            if shield > blocked:
                self.status(target, "shield", shield - blocked, 2)
        amount = max(0, amount - resistance)
        self.change_hp(target, -amount)
        if amount and reflection and source != target and self.status_power(target, "reflect"):
            self.damage(
                source, min(amount, self.status_power(target, "reflect")), element, target, False
            )
        if target != "hero" and self.hp(target) == 0:
            e, d = self.actor(target, alive=False)
            template = d.properties.get("game_template_id")
            if template and (e.state or {}).get("encounter_source"):
                spec = content.row(template, "creature")
                if self.award("defeat:" + template, spec["xp"]):
                    for material, qty in spec["loot"].items():
                        self.add_item(material, qty)
        return previous_hp - self.hp(target) if self.state.get("catalog_revision") == 3 else amount

    def award(self, key, amount):
        if key in self.state["achievements"]:
            return False
        self.state["achievements"].append(key)
        self.state["xp"] += amount
        return True

    def neighbors(self):
        place = self.scene.place()
        return sorted(
            p.id for p in self.scene.places if p.parent == place.id or place.parent == p.id
        )

    def travel(self, destination):
        if destination == self.scene.current:
            return
        if destination not in self.neighbors():
            raise ValueError("Нужен известный соседний путь.")
        if (
            self.state.get("catalog_revision") == 3
            and self.state["living_world"].get("blocked_until", {}).get(self.scene.current, 0)
            > self.state["minute"]
        ):
            raise ValueError("Путь временно перекрыт природным событием.")
        if (
            self.state["living_world"].get("blocked_until", {}).get(destination, 0)
            > self.state["minute"]
        ):
            raise ValueError("Путь временно перекрыт природным событием.")
        self.scene = replace(self.scene, current=destination)
        self.world = replace(self.world, location=self.scene.place().anchor)
        self.events.append({"kind": "travel", "destination": destination})
        if self.state.get("catalog_revision") == 3:
            visits = self.state["activity"]["visited"]
            visits[destination] = visits.get(destination, 0) + 1

    def sync_physical(self):
        for item in self.state["items"]:
            if item.get("source") and item["source"] in self.actors:
                old = self.actors[item["source"]]
                # Ownership or position changes already made by generic world actions win.
                if old.owner_id != item["owner"]:
                    item["owner"] = old.owner_id
            if not item.get("template"):
                continue
            spec = self.template(item)
            definition_id = "gc_" + spec["id"]
            if definition_id not in self.definitions:
                group = (
                    "materials"
                    if spec["kind"] == "material"
                    else "weapons"
                    if spec["kind"] == "weapon"
                    else "armour"
                    if spec["kind"] == "armour"
                    else "miscellaneous"
                )
                self.definitions[definition_id] = Definition(
                    definition_id,
                    spec["name"][:100],
                    "material" if group == "materials" else "item",
                    (group,),
                    {
                        "game_template_id": spec["id"],
                        "mass_g": spec.get("mass_g", 100),
                        "durability": spec.get("durability", 20),
                        "portable": True,
                        "container": spec.get("capability") == "container",
                        **(
                            {
                                "capacity_ml": 2000 * spec["strength"],
                                "max_load_g": 3000 * spec["strength"],
                            }
                            if spec.get("capability") == "container"
                            else {}
                        ),
                    },
                    price_cp=spec.get("price_cp", 10),
                    origin="project-homebrew",
                )
            source = item.setdefault("source", item["id"])
            old = self.actors.get(source)
            holder = old.parent_id if old else item["owner"]
            state = (old.state or {}) if old else {}
            state = state | {"condition": item["durability"]}
            if self.state.get("catalog_revision") == 3:
                state.update(
                    {
                        k: item[k]
                        for k in ("quality", "made_by", "spell_override", "deployed")
                        if k in item
                    }
                )
            if spec.get("capability") == "container":
                state.update(open=item.get("open", True), locked=not item.get("open", True))
            self.actors[source] = Entity(
                source, definition_id, holder, item["owner"], item["quantity"], state
            )
            old_thing = self.things.get(source)
            self.things[source] = Thing(
                source,
                item["name"][:80],
                old_thing.holder if old_thing else holder,
                item["owner"],
                item["quantity"],
                spec.get("capability") == "container",
            )
        self.catalog = replace(
            self.catalog,
            definitions=tuple(self.definitions.values()),
            entities=tuple(self.actors.values()),
        )
        self.scene = replace(
            self.scene, things=tuple(self.things.values()), actors=tuple(self.refs.values())
        )

    def finish(self):
        from rpg_vkr.domain.unified import caps

        self.sync_physical()
        limits = caps(self.state, self.char)
        self.world = replace(self.world, max_hp=limits["hp"], hp=min(self.world.hp, limits["hp"]))
        self.state.update(mp_cap=limits["mp"], st_cap=limits["st"])
        return {
            "state": self.state,
            "world": asdict(self.world),
            "scene": self.scene.to_dict(),
            "catalog": self.catalog.to_dict(),
            "combat": self.context_combat,
            "text": "\n".join(self.text) or "Действие подтверждено.",
            "rolls": self.rolls,
            "attacks": self.attacks,
            "battle_events": self.events,
        }


def execute(original, command, args, context, dice):
    with content.using(original.get("catalog_revision", 1)):
        return _execute(original, command, args, context, dice)


def _execute(original, command, args, context, dice):
    from rpg_vkr.domain.catalog_actions_v2 import advance, npc_round, perform

    engine = Engine(original, context, dice, args)
    engine.context_combat = context["combat"]
    if engine.world.hp <= 0:
        raise ValueError("Герой выбыл.")
    perform(engine, command, args)
    npc_round(engine, command)
    advance(engine, engine.action_minutes)
    return engine.finish()
