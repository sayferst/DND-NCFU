"""Selective, read-only memory from existing committed turns, scoped to world and hero.

No additional canonical store: JSON/SQLite persistence remains owned by Session.
"""

import hashlib
import json

from rpg_vkr.learning.query import terms


def scene_and_witnesses(turn):
    scene = None
    if turn.gameplay:
        scene = turn.gameplay["context"].get("scene")
    if scene:
        place = scene["current"]
        return place, {a["id"] for a in (scene.get("actors") or []) if a["place"] == place}
    record = turn.interaction or turn.catalog
    before = getattr(record, "before", None)
    if before is not None and hasattr(before, "actor_refs"):
        return before.current, {a.id for a in before.actor_refs if a.place == before.current}
    return "", set()


def recall(
    session,
    query,
    *,
    npc_id="",
    limit=7,
    budget=1800,
    expected_world_id=None,
    expected_hero_id=None,
):
    """Past events are evidence, not an overwrite of the current canonical snapshot."""
    world, hero = session.campaign.world_id, session.campaign.hero_id
    if (
        expected_world_id not in (None, world)
        or expected_hero_id not in (None, hero)
        or not isinstance(query, str)
        or len(query) > 6000
        or type(limit) is not int
        or not 1 <= limit <= 7
        or not 300 <= budget <= 4000
    ):
        raise ValueError("Память не относится к выбранному миру/герою или запрос неверен.")
    registered = {a.id for a in session.interaction_state().actor_refs}
    if npc_id and npc_id not in registered:
        return []
    words = terms(query)
    candidates = []
    for index, turn in enumerate(session.turns, 1):
        if not (
            turn.gameplay
            or turn.interaction
            or turn.catalog
            or turn.trade
            or turn.combat
            or turn.challenge
            or turn.inspection
            or turn.dialogue
        ):
            continue
        place, witnesses = scene_and_witnesses(turn)
        if turn.dialogue:
            witnesses.add(turn.dialogue.target)
        if npc_id and npc_id not in witnesses:
            continue
        summary = turn.text[:300]
        if npc_id:
            # A witness does not learn the hero's input, inner thoughts or numerical pools.
            operation = (turn.gameplay or {}).get("command", "")
            if turn.interaction:
                operation = ", ".join(s.op for s in turn.interaction.plan.steps)
            summary = "Наблюдаемое действие: " + (operation or "взаимодействие")
        searchable = set(terms(turn.action + " " + turn.text))
        score = len(set(words) & searchable)
        if not score:
            continue
        event_id = hashlib.sha256(
            json.dumps([world, hero, index, turn.action, turn.text], ensure_ascii=False).encode()
        ).hexdigest()
        candidates.append(
            (
                score,
                index,
                {
                    "event_id": event_id,
                    "turn": index,
                    "place": place,
                    "status": "past_confirmed_event",
                    "summary": summary,
                    "world_id": world,
                    "hero_id": hero,
                    "scope": "npc:" + npc_id if npc_id else "player",
                },
            )
        )
    result = []
    for _, _, value in sorted(candidates, key=lambda row: (-row[0], -row[1])):
        if len(json.dumps(result + [value], ensure_ascii=False).encode()) <= budget:
            result.append(value)
        if len(result) == limit:
            break
    return result
