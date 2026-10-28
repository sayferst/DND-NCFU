"""One new-campaign type, with whitelist operation replay and no skill currency."""

import hashlib
import uuid
from copy import deepcopy
from dataclasses import asdict, replace
from functools import wraps

from rpg_vkr.application import Session
from rpg_vkr.domain import game_catalog as content
from rpg_vkr.domain import unified as rules
from rpg_vkr.domain.campaign import Campaign
from rpg_vkr.domain.character import Character
from rpg_vkr.domain.memory import WorldMemory, snapshot
from rpg_vkr.domain.progression import HeroProgress
from rpg_vkr.domain.world import WorldState
from rpg_vkr.storage.migration import METHODS, canonical, decode, encode


class UnifiedSession(Session):
    is_unified = True

    @classmethod
    def create(
        cls,
        character,
        class_id,
        talent,
        *,
        seed=None,
        description="",
        world_brief="",
        campaign=None,
        content_revision=2,
        catalog_revision=1,
    ):
        state = rules.initial({"class_id": class_id, "talent": talent}, character)
        if content_revision not in (1, 2):
            raise ValueError("Неизвестная ревизия данных кампании.")
        if content_revision == 2:
            from rpg_vkr.domain.catalog_engine import initial

            with content.using(catalog_revision):
                state = initial(state, character)
            if catalog_revision in (2, 3):
                state["catalog_revision"] = catalog_revision
        elif catalog_revision != 1:
            raise ValueError("Каталог недоступен для этой кампании.")
        limits = rules.caps(state, character)
        if catalog_revision == 3:
            state.update(mp=limits["mp"], mp_cap=limits["mp"], st=limits["st"], st_cap=limits["st"])
            state.update(contracts={}, activity={"gathered": {}, "crafted": {}, "visited": {}})
        obj = cls(
            seed=seed,
            character=character,
            world=WorldState(hp=limits["hp"], max_hp=limits["hp"], gold=0, bandages=0),
            progress=HeroProgress("fighter", character),
            campaign=campaign or Campaign.create(description, world_brief),
        )
        obj._gameplay = {"identity": deepcopy(state["identity"]), "state": state}
        obj.memory = WorldMemory(0, snapshot(obj.world, obj.character, obj.combat, obj.progress))
        obj._origin = {
            "character": asdict(character),
            "class_id": class_id,
            "talent": talent,
            "seed": obj.dice.seed,
            "campaign": obj.campaign.to_dict(),
        }
        obj._operations = []
        if content_revision == 2:
            obj._origin["content_revision"] = 2
        if catalog_revision in (2, 3):
            obj._origin["catalog_revision"] = catalog_revision
        obj._depth = 0
        obj._learning_flags = {"library": False, "memory": True}
        obj._rag_mode = 2
        return obj

    @property
    def schema_version(self):
        return 31 if self.gameplay.get("content_revision") == 2 else 30

    @property
    def history_limit(self):
        return 10000 if self.gameplay.get("catalog_revision") in (2, 3) else 2000

    def start_world(self, seed):
        super().start_world(seed)
        if self.schema_version == 31:
            from rpg_vkr.domain.catalog_engine import Engine

            engine = Engine(self.gameplay, context(self), self.dice, {})
            result = engine.finish()
            from rpg_vkr.domain.catalog import Catalog
            from rpg_vkr.domain.interactions import InteractiveWorld

            self._gameplay["state"] = result["state"]
            self.catalog = Catalog.from_dict(result["catalog"])
            self.interactive_world = InteractiveWorld.from_dict(result["scene"])

    @property
    def effective_character(self):
        return replace(
            self.character,
            **{
                key: getattr(self.character, key) + value
                for key, value in self.gameplay["ability_increases"].items()
            },
        )

    @property
    def d20_progress(self):
        return None

    @property
    def extra_items(self):
        carried = {i.id for i in self.interaction_state().carried()}
        return tuple(
            (i["name"], f"Состояние {i['durability']}/20")
            for i in self.gameplay["items"]
            if i["owner"] == "hero" and i["id"] not in carried
        )

    def _request_token(self):
        return uuid.uuid5(
            uuid.UUID(self.campaign.world_id), f"{len(self._operations)}:{len(self.turns)}"
        ).hex

    def write_diary(self, title, text, **kwargs):
        if kwargs.get("id") is None:
            kwargs["id"] = str(uuid.UUID(self._request_token()))
        return super().write_diary(title, text, **kwargs)

    def train_skill(self, *args, **kwargs):
        raise ValueError("В единых правилах нет покупаемых рангов навыков.")

    def commit_skill_allocation(self, *args, **kwargs):
        raise ValueError("Подготовка класса растёт автоматически.")

    def submit_actor_attempt(
        self, action, target_id, operation, lethal, reason, model, *, confirmed_intent=False
    ):
        if operation == "attack":
            from rpg_vkr.domain.catalog_actions import bind_attempt

            bind_attempt(action, operation, lethal, confirmed=confirmed_intent)
            if not self.in_combat:
                self.perform_gameplay(
                    "encounter", {"enemies": [target_id], "allies": []}, self._request_token()
                )
            return self.perform_gameplay(
                "attack", {"target": target_id}, self._request_token(), action=action
            )
        return super().submit_actor_attempt(
            action, target_id, operation, lethal, reason, model, confirmed_intent=confirmed_intent
        )

    def submit_challenge(self, action, *, suggested_kind=None, assessment=None):
        from rpg_vkr.domain.challenge import (
            CHALLENGE_SKILLS,
            CHALLENGES,
            proposed_challenge,
        )
        from rpg_vkr.domain.interactions import nonexecuting

        if nonexecuting(action):
            raise ValueError("Вопрос не выполняет действие.")
        if assessment:
            rules.validate_assessment(assessment)
            task = assessment.get("skill") or assessment["ability"]
            dc = assessment["dc"]
        else:
            kind = suggested_kind or proposed_challenge(action)
            if kind not in CHALLENGES:
                raise ValueError("Уточните проверку.")
            task = CHALLENGE_SKILLS.get(kind, CHALLENGES[kind][0])
            dc = CHALLENGES[kind][1]
        return self.perform_gameplay(
            "check", {"task": task, "dc": dc}, self._request_token(), action=action
        )

    def to_dict(self):
        value = self._plain_dict()
        if self.gameplay.get("catalog_revision") in (2, 3):
            # The whitelist log reconstructs these fields exactly. Persist their
            # digests instead of a second copy of the complete history.
            for key in ("turns", "memory", "narrations"):
                value[key] = {
                    "encoding": "replayed-sha256-1",
                    "sha256": hashlib.sha256(canonical(value[key]).encode("utf-8")).hexdigest(),
                }
        return {
            "unified": {
                "ruleset": rules.VERSION,
                "origin": deepcopy(self._origin),
                "operations": deepcopy(self._operations),
            },
            "snapshot": value,
        }


def context(session):
    return {
        "world": asdict(session.world),
        "character": asdict(session.effective_character),
        "combat": session.combat.to_dict(),
        "scene": session.interaction_state().to_dict(),
        "catalog": session.catalog.to_dict() if session.catalog else None,
        "turn": len(session.turns) + 1,
        "unified_before": {k: session.gameplay[k] for k in ("xp", "mp", "st", "copper")},
    }


def compact_latest(session, result):
    """Keep a checked receipt, not a full inventory copy in every historical turn."""
    from rpg_vkr.domain.receipts import receipt

    old = session._turns[-1]
    record = old.gameplay
    if not record or record.get("receipt"):
        return result
    cached = receipt(session)
    before = record["context"]
    after = record["result"]
    scene = before.get("scene", {})
    actors = (before.get("catalog") or {}).get("entities", [])
    alive = {a["id"] for a in actors if (a.get("state") or {}).get("hp", 1) > 0}
    small_context = {
        "world": before.get("world", {}),
        "character": before.get("character", {}),
        "unified_before": before.get("unified_before", {}),
        "scene": {
            "current": scene.get("current", session.current_place_id),
            "actors": [a for a in scene.get("actors", []) if a["id"] in alive],
        },
    }
    small_result = {k: deepcopy(after.get(k, [])) for k in ("rolls", "attacks", "battle_events")}
    small_result["state"] = {
        k: deepcopy(after["state"].get(k))
        for k in ("xp", "mp", "st", "copper", "minute", "battle", "last_battle")
    }
    small_result["state"]["world_aliases"] = deepcopy(after["state"].get("world_aliases", {}))
    small_result["world"] = after["world"]
    small_result["text"] = after["text"]
    compact = {
        "request_id": record["request_id"],
        "command": record["command"],
        "args": record["args"],
        "context": small_context,
        "result": small_result,
        "receipt": cached,
    }
    new = replace(old, gameplay=compact)
    session._turns[-1] = new
    return new if result is old else result


def instrument():
    for name in METHODS | {"start_world"}:
        method = getattr(UnifiedSession, name)

        def wrap(method, name):
            @wraps(method)
            def called(self, *args, **kwargs):
                if self._depth:
                    return method(self, *args, **kwargs)
                encoded = (
                    {"world_seed": args[0].to_dict()}
                    if name == "start_world"
                    else {"args": encode(args), "kwargs": encode(kwargs)}
                )
                record = {"method": name, **encoded}
                # Includes in-memory non-engine mutations, RNG and the operation log.
                previous = vars(self).copy()
                previous["_gameplay"] = deepcopy(self._gameplay)
                previous["_turns"] = list(self._turns)
                previous["_narrations"] = list(self._narrations)
                checkpoint = self.dice.checkpoint()
                self._depth = 1
                try:
                    with content.using(self.gameplay.get("catalog_revision", 1)):
                        result = method(self, *args, **kwargs)
                    if self.progress != previous["progress"]:
                        raise ValueError("Это действие не даёт подтверждённого развития героя.")
                    if self.schema_version == 31 and self._turns:
                        result = compact_latest(self, result)
                except Exception:
                    vars(self).clear()
                    vars(self).update(previous)
                    self.dice.restore(checkpoint)
                    raise
                finally:
                    self._depth = 0
                self._operations.append(record)
                return result

            return called

        setattr(UnifiedSession, name, wrap(method, name))


instrument()


def restore(data):
    from rpg_vkr.domain.adventure import WorldSeed

    if not isinstance(data, dict) or set(data) != {"unified", "snapshot"}:
        raise ValueError("Неверный формат единой кампании.")
    meta = data["unified"]
    if (
        set(meta) != {"ruleset", "origin", "operations"}
        or meta["ruleset"] != rules.VERSION
        or not isinstance(meta["operations"], list)
        or len(meta["operations"])
        > (30000 if meta.get("origin", {}).get("catalog_revision") in (2, 3) else 6000)
    ):
        raise ValueError("Неизвестный набор правил или журнал.")
    origin = deepcopy(meta["origin"])
    origin.setdefault("content_revision", 1)
    origin["character"] = Character.from_dict(origin["character"])
    origin["campaign"] = Campaign.from_dict(origin["campaign"])
    session = UnifiedSession.create(**origin)
    for op in meta["operations"]:
        if op.get("method") not in METHODS | {"start_world"}:
            raise ValueError("Неизвестная операция.")
        if op["method"] == "start_world":
            session.start_world(WorldSeed.from_dict(op["world_seed"]))
        else:
            getattr(session, op["method"])(*decode(op["args"]), **decode(op["kwargs"]))
    if canonical(session.to_dict()) != canonical(data):
        raise ValueError("Состояние не совпало с подтверждённым повтором.")
    return session
