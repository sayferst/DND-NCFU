"""Application boundary for playable v3 commands and authenticated replay."""

import json
import re
from copy import deepcopy
from dataclasses import asdict

from rpg_vkr.domain.catalog import Catalog
from rpg_vkr.domain.character import Character
from rpg_vkr.domain.combat import ACTORS, CombatState
from rpg_vkr.domain.combat_record import canonical
from rpg_vkr.domain.d20_progression import D20Progress
from rpg_vkr.domain.gameplay import ensure_names, execute, initial
from rpg_vkr.domain.interactions import InteractiveWorld
from rpg_vkr.domain.memory import snapshot
from rpg_vkr.domain.progression import HeroProgress
from rpg_vkr.domain.world import WorldState


def enable(session, identity):
    if session.turns or session._gameplay is not None or not session.progress.enabled:
        raise ValueError("Новые правила выбираются только при создании героя.")
    progress = session.d20_progress or D20Progress()
    state = initial(identity, session.character)
    ensure_names(state, session.catalog)
    for skill, rank in identity.get("skills", {}).items():
        for n in range(rank):
            progress = progress.train(skill, f"creation:{skill}:{n}")
    session._d20_progress = progress
    session._gameplay = {"identity": deepcopy(identity), "state": state}


def context(session):
    return {
        "world": asdict(session.world),
        "character": asdict(session.character),
        "combat": session.combat.to_dict(),
        "scene": session.interaction_state().to_dict(),
        "catalog": session.catalog.to_dict() if session.catalog else None,
        "progress": session.d20_progress.to_dict(),
        "turn": len(session.turns) + 1,
    }


def request_identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_:-]{1,96}", value):
        raise ValueError("Неверный идентификатор запроса.")


def perform(session, command, args, request_id, *, action=None):
    from rpg_vkr.application import MAX_TURNS, Turn, _text

    request_identifier(request_id)
    if action is not None:
        action = _text(action, 500).strip()
    if command == "advance":
        raise ValueError("Автоматическое время задаётся подтверждённым игровым действием.")
    if session._gameplay is None:
        raise ValueError("Эти правила включаются при создании новой кампании.")
    for turn in session.turns:
        record = turn.gameplay
        if record and record["request_id"] == request_id:
            if record["command"] != command or canonical(record["args"]) != canonical(args):
                raise ValueError("Этот ID уже использован для другого действия.")
            return turn
    if len(session.turns) >= MAX_TURNS:
        raise ValueError("Достигнут предел истории кампании.")
    before = context(session)
    checkpoint = session.dice.checkpoint()
    try:
        result = execute(session._gameplay["state"], command, args, before, session.dice)
        record = {
            "request_id": request_id,
            "command": command,
            "args": deepcopy(args),
            "context": before,
            "result": result,
        }
        record = json.loads(canonical(record))
        turn = Turn(
            action or result["text"].splitlines()[0],
            "Правила",
            result["text"],
            player_name=session.character.name,
            origin="quick",
            gameplay=record,
        )
        world = WorldState.from_dict(result["world"])
        combat = CombatState.from_dict(result["combat"])
        memory = session.memory.append(
            turn,
            snapshot(session.world, session.character, session.combat, session.progress),
            snapshot(world, session.character, combat, session.progress),
        )
        scene = InteractiveWorld.from_dict(result["scene"])
        catalog = Catalog.from_dict(result["catalog"]) if result["catalog"] else None
    except Exception:
        session.dice.restore(checkpoint)
        raise
    session._gameplay = {
        "identity": session._gameplay["identity"],
        "state": deepcopy(result["state"]),
    }
    session.world, session.combat, session.memory = world, combat, memory
    session.interactive_world, session.catalog = scene, catalog
    session._turns.append(turn)
    return turn


def restore_turn(session, item):
    from rpg_vkr.application import Turn

    record = item["gameplay"]
    if not isinstance(record, dict) or set(record) != {
        "request_id",
        "command",
        "args",
        "context",
        "result",
    }:
        raise ValueError("Неверная запись новых правил.")
    request_identifier(record["request_id"])
    if any(t.gameplay and t.gameplay["request_id"] == record["request_id"] for t in session.turns):
        raise ValueError("Повтор команды в журнале.")
    forbidden = (
        "roll",
        "check",
        "actor_id",
        "combat",
        "intent",
        "dialogue",
        "meaning",
        "inspection",
        "scene",
        "challenge",
        "interaction",
        "catalog",
        "trade",
    )
    if any(item[k] is not None for k in forbidden) or item["speaker"] != "Правила" or item["notes"]:
        raise ValueError("Смешаны несовместимые виды действий.")
    ctx = record["context"]
    if (
        not isinstance(ctx, dict)
        or set(ctx) != {"world", "character", "combat", "scene", "catalog", "progress", "turn"}
        or type(ctx["turn"]) is not int
        or ctx["turn"] != len(session.turns) + 1
    ):
        raise ValueError("Неверный контекст действия.")
    result = execute(
        session._gameplay["state"], record["command"], record["args"], ctx, session.dice
    )
    if canonical(result) != canonical(record["result"]) or result["text"] != item["text"]:
        raise ValueError("Исход не совпадает с воспроизводимым расчётом.")
    prefix = D20Progress.from_dict(ctx["progress"])
    final = session._d20_progress
    if final.events[: len(prefix.events)] != prefix.events:
        raise ValueError("Навыки не совпадают с журналом обучения.")
    from rpg_vkr.domain.campaign_progress import achievements

    earned = achievements(session.turns)
    if any(e.kind == "xp" and e.event_id not in earned for e in prefix.events):
        raise ValueError("Расчёт использует ещё не полученный опыт.")
    previous_prefix = next(
        (t.gameplay["context"]["progress"] for t in reversed(session.turns) if t.gameplay), None
    )
    if previous_prefix:
        previous = D20Progress.from_dict(previous_prefix)
        if prefix.events[: len(previous.events)] != previous.events:
            raise ValueError("История навыков пошла назад.")
    session._gameplay["state"] = deepcopy(result["state"])
    session.combat = CombatState.from_dict(result["combat"])
    session.catalog = Catalog.from_dict(result["catalog"]) if result["catalog"] else None
    session._turns.append(
        Turn(
            item["action"],
            "Правила",
            item["text"],
            origin=item["origin"],
            player_name=item["player_name"],
            intent_source=item["intent_source"],
            gameplay=deepcopy(record),
        )
    )


def validate_history(record, fields, interactive, catalog, index):
    """Bind replay input to actual historical world, not caller-supplied snapshots."""
    ctx, result = record["context"], record["result"]
    world = {k: fields["world." + k] for k in asdict(WorldState())}
    hero = {k: fields["hero." + k] for k in asdict(Character())}
    expected_scene = interactive or InteractiveWorld.initial(world["location"])
    combat = CombatState.from_dict(
        {
            "actors": [
                {
                    "id": key,
                    "hp": fields[f"actor.{key}.hp"],
                    "disposition": fields[f"actor.{key}.disposition"],
                }
                for key in ACTORS
            ],
            **{key: fields["combat." + key] for key in ("active", "surprise", "rounds")},
        }
    )
    if (
        canonical(ctx["world"]) != canonical(world)
        or canonical(ctx["character"]) != canonical(hero)
        or canonical(ctx["combat"]) != canonical(combat.to_dict())
        or canonical(ctx["scene"]) != canonical(expected_scene.to_dict())
        or canonical(ctx["catalog"]) != canonical(catalog.to_dict() if catalog else None)
        or type(ctx["turn"]) is not int
        or ctx["turn"] != index
    ):
        raise ValueError("Контекст новых правил подменил историческое состояние.")
    after = dict(
        snapshot(
            WorldState.from_dict(result["world"]),
            Character.from_dict(hero),
            CombatState.from_dict(result["combat"]),
            HeroProgress(),
        )
    )
    # The legacy progression is unchanged by these commands.
    for key in fields:
        if key.startswith(("progress.", "training.")):
            after[key] = fields[key]
    return (
        after,
        InteractiveWorld.from_dict(result["scene"]),
        Catalog.from_dict(result["catalog"]) if result["catalog"] else None,
    )


def duration(turn):
    """A small public duration table; information and narration do not consume time."""
    if turn.scene or turn.speaker == "Мастер":
        return 0
    if turn.challenge:
        return 1
    if turn.trade:
        return 5
    if turn.interaction:
        return 10 if turn.interaction.after.current != turn.interaction.before.current else 1
    if turn.dialogue:
        return 1
    if turn.catalog:
        return 1 if hasattr(turn.catalog, "operation") else 0
    command = (turn.intent or turn.action).casefold().strip()
    if command.startswith("идти "):
        return 10
    if turn.check or turn.combat:
        return 1
    return 0


def finish_turn(session, turn):
    from dataclasses import replace

    minutes = duration(turn)
    command = (turn.intent or turn.action).casefold().strip()
    if command.startswith("идти ") and not any(
        c.field == "world.location" for c in session.memory.events[-1].changes
    ):
        return turn
    if session._gameplay is None or turn.gameplay or not minutes or session.world.hp == 0:
        return turn
    ctx = context(session)
    ctx["turn"] = len(session.turns)
    checkpoint = session.dice.checkpoint()
    result = execute(session._gameplay["state"], "advance", {"minutes": minutes}, ctx, session.dice)
    if (
        session.dice.checkpoint() != checkpoint
        or result["world"] != ctx["world"]
        or result["combat"] != ctx["combat"]
    ):
        raise ValueError("Тик времени изменил неподдержанные ресурсы.")
    record = json.loads(
        canonical(
            {
                "request_id": f"clock_{len(session.turns)}",
                "command": "advance",
                "args": {"minutes": minutes},
                "context": ctx,
                "result": result,
            }
        )
    )
    turn = replace(turn, gameplay=record)
    session._turns[-1] = turn
    session._gameplay = {"identity": session._gameplay["identity"], "state": result["state"]}
    session.interactive_world = InteractiveWorld.from_dict(result["scene"])
    return turn


def restore_clock(session, raw):
    from dataclasses import replace

    record = raw.get("gameplay")
    if not record or record.get("command") != "advance":
        return
    if set(record) != {"request_id", "command", "args", "context", "result"}:
        raise ValueError("Неверная запись часов.")
    turn = session.turns[-1]
    if record["context"]["world"]["hp"] <= 0:
        raise ValueError("Время действия не применяется после выбытия.")
    if (
        record["args"] != {"minutes": duration(turn)}
        or not duration(turn)
        or record["request_id"] != f"clock_{len(session.turns)}"
        or record["context"]["turn"] != len(session.turns)
    ):
        raise ValueError("Длительность не соответствует подтверждённому действию.")
    result = execute(
        session._gameplay["state"], "advance", record["args"], record["context"], session.dice
    )
    if canonical(result) != canonical(record["result"]):
        raise ValueError("Расписание не совпадает с историей времени.")
    prefix = D20Progress.from_dict(record["context"]["progress"])
    if session._d20_progress.events[: len(prefix.events)] != prefix.events:
        raise ValueError("История обучения не соответствует часам.")
    from rpg_vkr.domain.campaign_progress import achievements

    earned = achievements(session.turns)
    if any(e.kind == "xp" and e.event_id not in earned for e in prefix.events):
        raise ValueError("Часы используют будущую награду.")
    session._gameplay["state"] = deepcopy(result["state"])
    session._turns[-1] = replace(turn, gameplay=deepcopy(record))


def atomic(method):
    """Rollback the whole in-memory transaction, including passive simulation failures."""
    from functools import wraps

    @wraps(method)
    def wrapped(session, *args, **kwargs):
        if session._gameplay is None:
            return method(session, *args, **kwargs)
        previous = vars(session).copy()
        previous["_turns"] = list(session._turns)
        previous["_narrations"] = list(session._narrations)
        previous["_gameplay"] = deepcopy(session._gameplay)
        checkpoint = session.dice.checkpoint()
        try:
            return method(session, *args, **kwargs)
        except Exception:
            vars(session).clear()
            vars(session).update(previous)
            session.dice.restore(checkpoint)
            raise

    return wrapped
