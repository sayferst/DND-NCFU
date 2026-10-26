"""Opt-in campaign fork with immutable source, replayed continuation and reversible files."""

import json
import uuid
from copy import deepcopy
from dataclasses import fields, is_dataclass, replace
from datetime import UTC, datetime
from functools import wraps
from hashlib import sha256
from pathlib import Path

FORMAT = "campaign-copy-1"
METHODS = {
    "perform_gameplay",
    "submit",
    "submit_actions",
    "submit_interaction",
    "submit_trade",
    "submit_actor_attempt",
    "submit_challenge",
    "register_catalog",
    "train_skill",
    "commit_skill_allocation",
    "write_diary",
    "remember",
    "submit_scene",
    "edit_character",
    "add_narration",
}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def classes():
    from rpg_vkr.domain.catalog import Definition, Entity
    from rpg_vkr.domain.character import Character
    from rpg_vkr.domain.director import Proposal, StoryFact
    from rpg_vkr.domain.interactions import Place, Step, WorldPlan
    from rpg_vkr.narrative.records import Narration
    from rpg_vkr.narrative.segments import Segment

    return {
        c.__name__: c
        for c in (
            Definition,
            Entity,
            Character,
            Proposal,
            StoryFact,
            Place,
            Step,
            WorldPlan,
            Narration,
            Segment,
        )
    }


def encode(value):
    if is_dataclass(value) and type(value).__name__ in classes():
        return {
            "$type": type(value).__name__,
            "fields": {f.name: encode(getattr(value, f.name)) for f in fields(value)},
        }
    if isinstance(value, tuple):
        return {"$tuple": [encode(v) for v in value]}
    if isinstance(value, list):
        return [encode(v) for v in value]
    if isinstance(value, dict) and all(isinstance(k, str) and not k.startswith("$") for k in value):
        return {k: encode(v) for k, v in value.items()}
    if value is None or type(value) in (str, bool, int, float):
        return value
    raise ValueError("Этот тип операции не поддерживает проверяемое продолжение копии.")


def decode(value):
    if isinstance(value, dict):
        if set(value) == {"$tuple"}:
            return tuple(decode(v) for v in value["$tuple"])
        if set(value) == {"$type", "fields"} and value["$type"] in classes():
            return classes()[value["$type"]](**{k: decode(v) for k, v in value["fields"].items()})
        if any(k.startswith("$") for k in value):
            raise ValueError("Недопустимый тип в журнале копии.")
        return {k: decode(v) for k, v in value.items()}
    return [decode(v) for v in value] if isinstance(value, list) else value


def instrument(cls):
    """Record only outer public mutations; playback invokes the same validators."""
    for name in METHODS:
        method = getattr(cls, name)

        def wrap(method):
            @wraps(method)
            def called(session, *args, **kwargs):
                fork = getattr(session, "_fork", None)
                if fork is None or getattr(session, "_fork_depth", 0):
                    return method(session, *args, **kwargs)
                record = {"method": method.__name__, "args": encode(args), "kwargs": encode(kwargs)}
                session._fork_depth = 1
                try:
                    result = method(session, *args, **kwargs)
                finally:
                    session._fork_depth = 0
                fork["operations"].append(record)
                return result

            return called

        setattr(cls, name, wrap(method))


def upgrade(session, metadata):
    from rpg_vkr.domain import gameplay_v5 as rules
    from rpg_vkr.domain.adventure import input_signature
    from rpg_vkr.domain.content_v5 import inherited
    from rpg_vkr.domain.d20_progression import D20Progress
    from rpg_vkr.domain.hero_resources import refresh

    if session.in_combat or session.world.hp <= 0:
        raise ValueError("Перенос доступен живому герою вне боя.")
    # Materialize historical tutorial actors without replacing their HP or disposition.
    from rpg_vkr.domain.catalog import Catalog, Definition, Entity, seed_catalog
    from rpg_vkr.domain.combat import ACTORS

    scene = session.interaction_state()
    catalog = session.catalog or seed_catalog()
    definitions, entities = list(catalog.definitions), list(catalog.entities)
    known = {e.id for e in entities}
    legacy_shop = False
    for ref in scene.actor_refs:
        if ref.id in known:
            continue
        if ref.id not in ACTORS:
            raise ValueError("У старого NPC отсутствует проверяемая карточка: " + ref.id)
        spec, actor = ACTORS[ref.id], session.combat.actor(ref.id)
        type_id = "migrated_actor_type_" + ref.id
        if any(d.id == type_id for d in definitions):
            raise ValueError("Занят идентификатор карточки переноса: " + type_id)
        definitions.append(
            Definition(
                type_id,
                ref.name,
                "actor",
                ("npcs",),
                {
                    "hp_max": spec[2],
                    "defence": spec[3],
                    "class": "merchant" if ref.id == "merchant" else "resident",
                },
                origin="legacy-adapter",
            )
        )
        values = {"hp": actor.hp, "disposition": actor.disposition}
        if ref.id == "merchant":
            legacy_shop = True
            values["gold_cp"] = session.world.shop_gold * 100 + (session.gameplay or {}).get(
                "shop_copper", 0
            )
        entities.append(Entity(ref.id, type_id, ref.place, state=values))
    session.catalog = Catalog(tuple(definitions), tuple(entities))
    session.interactive_world = scene
    old = session.gameplay
    identity = metadata["identity"]
    state = rules.initial(identity, session.character)
    if old:
        state.update(deepcopy(old))
        state.update(
            version=rules.VERSION,
            catalog_version=rules.CATALOG_VERSION,
            identity=deepcopy(identity),
            living_world=None,
            ability_uses={},
            content_sequence=0,
        )
        state.setdefault("npc_resources", {})
        state.setdefault("battle", None)
        state.setdefault("last_battle", None)
    else:
        # Preserve every physical object; no second starter kit is awarded.
        state["items"] = []
        state.update(weapon="", armour="", shield="", mp=0, copper=0)
        if session.progress.enabled:
            from rpg_vkr.domain.content_v5 import make_item
            from rpg_vkr.domain.progression import ARCHETYPES

            kind = {"fighter": "sword", "scout": "dagger", "scholar": "short_sword"}[
                session.progress.class_id
            ]
            weapon = make_item("migrated_legacy_weapon", kind)
            weapon["name"] = ARCHETYPES[session.progress.class_id].equipment
            state["items"].append(weapon)
            state["weapon"] = weapon["id"]
            state["items"].append(
                {
                    "id": "migrated_legacy_book",
                    "kind": "legacy_object",
                    "name": "Дорожный учебник",
                    "price_cp": 0,
                    "quality": 1,
                    "owner": "hero",
                    "durability": 20,
                }
            )
    if legacy_shop:
        # Move the existing shop balance into its NPC wallet, never mint a second pool.
        session.world = replace(session.world, shop_gold=0)
        state["shop_copper"] = 0
    session._d20_progress = session.d20_progress or D20Progress()
    session._gameplay = {"identity": deepcopy(identity), "state": state}
    hp, st, mp = session.world.hp, state.get("st", 0), state["mp"]
    state, world = refresh(
        state, session.world, inherited(session.character, state), session.d20_progress.level
    )
    session.world = replace(world, hp=min(hp, world.max_hp))
    state["st"], state["mp"] = min(st, state["st_cap"]), min(mp, state["mp_cap"])
    session._gameplay["state"] = state
    session.campaign = replace(
        session.campaign, world_id=metadata["world_id"], hero_id=metadata["hero_id"]
    )
    if session.generated_world:
        session.chronicle = replace(
            session.chronicle,
            seed=replace(
                session.chronicle.seed,
                signature=input_signature(session.campaign, session.progress.class_id),
            ),
        )
    # Physical resource pools must match the preserved balances and new HP cap.
    from rpg_vkr.domain.resources import reconcile

    if session.interactive_world:
        session.interactive_world = reconcile(
            session.interactive_world, world, session.world, len(session.turns), session.catalog
        )
    from rpg_vkr.domain.memory import WorldMemory, snapshot

    session.memory = WorldMemory(
        len(session.turns),
        snapshot(session.world, session.character, session.combat, session.progress),
    )
    return session


def create(session):
    from rpg_vkr.application import Session
    from rpg_vkr.domain.content_v5 import identity

    if session.schema_version >= 28:
        raise ValueError("Эта кампания уже использует новые правила.")
    source = json.loads(
        canonical({"schema_version": session.schema_version, "session": session.to_dict()})
    )
    value = (session.gameplay or {}).get("identity") or {
        "species": "human",
        "profile": {"fighter": "warrior", "scout": "ranger", "scholar": "mage"}.get(
            session.progress.class_id, "free"
        ),
        "age": 20,
        "background": "Перенесённая кампания",
        "appearance": "Сохранённый герой",
        "skills": {},
        "talent": "",
    }
    metadata = {
        "format": FORMAT,
        "source": source,
        "source_sha256": sha256(canonical(source).encode()).hexdigest(),
        "identity": identity(value),
        "world_id": str(uuid.uuid4()),
        "hero_id": str(uuid.uuid4()),
        "operations": [],
    }
    result = upgrade(
        Session.from_dict(deepcopy(source["session"]), version=source["schema_version"]), metadata
    )
    result._fork = metadata
    return result


def serialize(session):
    return {"fork": deepcopy(session._fork), "snapshot": session._plain_dict()}


def restore(data):
    from rpg_vkr.application import Session

    if not isinstance(data, dict) or set(data) != {"fork", "snapshot"}:
        raise ValueError("Неверная структура перенесённой копии.")
    meta = data["fork"]
    required = {
        "format",
        "source",
        "source_sha256",
        "identity",
        "world_id",
        "hero_id",
        "operations",
    }
    if not isinstance(meta, dict) or set(meta) != required or meta["format"] != FORMAT:
        raise ValueError("Неверная версия миграции.")
    source = meta["source"]
    if (
        not isinstance(source, dict)
        or set(source) != {"schema_version", "session"}
        or type(source["schema_version"]) is not int
        or not 1 <= source["schema_version"] <= 27
        or not isinstance(source["session"], dict)
        or "fork" in source["session"]
        or sha256(canonical(source).encode()).hexdigest() != meta["source_sha256"]
    ):
        raise ValueError("Подменён исходник миграции.")
    if not isinstance(meta["operations"], list) or len(meta["operations"]) > 10000:
        raise ValueError("Слишком большой журнал продолжения.")
    session = upgrade(
        Session.from_dict(deepcopy(source["session"]), version=source["schema_version"]), meta
    )
    session._fork = deepcopy(meta)
    session._fork_depth = 1
    for index, operation in enumerate(meta["operations"]):
        session._fork_replay_index = index
        if set(operation) != {"method", "args", "kwargs"} or operation["method"] not in METHODS:
            raise ValueError("Недопустимая операция копии.")
        getattr(session, operation["method"])(
            *decode(operation["args"]), **decode(operation["kwargs"])
        )
    if canonical(session._plain_dict()) != canonical(data["snapshot"]):
        raise ValueError("Продолжение копии не совпадает с воспроизведённой историей.")
    session._fork = deepcopy(meta)
    session._fork_depth = 0
    session.__dict__.pop("_fork_replay_index", None)
    return session


def write_copy(session, destination, *, original_bytes=None):
    destination = Path(destination)
    if destination.exists():
        raise ValueError("Выберите новый файл; существующие файлы не перезаписываются.")
    fork = create(session)
    source = fork._fork["source"]
    backup = destination.with_suffix(destination.suffix + ".original.json")
    report_path = destination.with_suffix(destination.suffix + ".migration.json")
    source_raw = (
        original_bytes
        or json.dumps(
            {**source, "saved_at": datetime.now(UTC).isoformat()}, ensure_ascii=False
        ).encode()
    )
    if original_bytes is not None:
        from rpg_vkr.application import Session

        saved = json.loads(original_bytes)
        original = Session.from_dict(saved["session"], version=saved["schema_version"])
        if canonical(original.to_dict()) != canonical(source["session"]):
            raise ValueError("Резервная копия не соответствует переносимой кампании.")
    report = {
        "format": FORMAT,
        "source_schema": session.schema_version,
        "target_schema": 29,
        "source_sha256": fork._fork["source_sha256"],
        "original_bytes_sha256": sha256(source_raw).hexdigest(),
        "backup": str(backup.name),
        "world_id": fork.campaign.world_id,
        "hp_before": session.world.hp,
        "hp_after": fork.world.hp,
        "gold_before": session.world.gold,
        "gold_after": fork.world.gold,
        "legacy_shop_gold_before": session.world.shop_gold,
        "legacy_shop_gold_after": fork.world.shop_gold,
        "turns_preserved": len(session.turns),
        "rng_preserved": session.dice.checkpoint() == fork.dice.checkpoint(),
    }
    # Validate the entire fork before touching the destination.
    restored = restore(serialize(fork))
    assert restored.to_dict() == fork.to_dict()
    payload = json.dumps(
        {
            "schema_version": 29,
            "saved_at": datetime.now(UTC).isoformat(),
            "session": fork.to_dict(),
        },
        ensure_ascii=False,
    ).encode()
    if len(payload) > 32 * 1024 * 1024:
        raise ValueError("Копия превышает32МиБ.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    made = []
    try:
        for path, raw in [
            (backup, source_raw),
            (report_path, json.dumps(report, ensure_ascii=False, indent=2).encode()),
            (destination, payload),
        ]:
            with path.open("xb") as out:
                made.append(path)
                out.write(raw)
                out.flush()
                import os

                os.fsync(out.fileno())
    except Exception:
        for path in made:
            if path != backup:
                path.unlink(missing_ok=True)
        raise
    return fork, report
