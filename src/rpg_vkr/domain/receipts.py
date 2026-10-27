"""Stable read-only receipts of committed actions. Building one never consumes RNG."""

import hashlib
import json
from dataclasses import asdict

from rpg_vkr.domain.interactions import WorldPlan, apply_plan


def receipt(session):
    if not session.turns:
        return None
    turn = session.turns[-1]
    if turn.gameplay and turn.gameplay.get("receipt"):
        from copy import deepcopy

        return deepcopy(turn.gameplay["receipt"])
    index = len(session.turns)
    raw = json.dumps(asdict(turn), ensure_ascii=False, sort_keys=True)
    id = hashlib.sha256((session.campaign.world_id + str(index) + raw).encode()).hexdigest()
    steps = []
    if turn.interaction:
        record = turn.interaction
        stopped = False
        for i, step in enumerate(record.plan.steps):
            status = "not_executed" if stopped else "completed"
            if record.check and not record.check.succeeded:
                if record.before.version != "interactive-world-4":
                    status = "failed"
                elif not stopped:
                    prefix = record.plan.steps[: i + 1]
                    visited = {s.target for s in prefix if s.op == "move"}
                    _, risky, _, _ = apply_plan(
                        record.before,
                        WorldPlan(prefix, tuple(p for p in record.plan.places if p.id in visited)),
                        turn_index=index,
                    )
                    if risky:
                        status, stopped = "failed", True
            steps.append({"operation": step.op, "target": step.target, "status": status})
    else:
        record = (
            turn.catalog
            if hasattr(turn.catalog, "operation")
            else turn.combat or turn.challenge or turn.trade
        )
        succeeded = turn.check.succeeded if turn.check else True
        steps.append(
            {
                "operation": getattr(record, "operation", "check" if turn.challenge else "action"),
                "status": "completed" if succeeded else "failed",
            }
        )
    value = {
        "id": id,
        "turn": index,
        "action": turn.action,
        "summary": turn.text,
        "place_id": session.current_place_id,
        "place": session.current_place_name,
        "steps": steps,
        "resource_changes": [
            asdict(change)
            for change in session.memory.events[-1].changes
            if change.field in {"world.gold", "world.hp", "progress.xp"}
            or change.field.startswith("hero.")
            and type(change.after) is int
        ]
        if session.memory.events
        else [],
        "committed": True,
        "replay_allowed": False,
    }

    if getattr(session, "is_unified", False) and turn.gameplay:
        record = turn.gameplay
        old = record["context"].get("unified_before", {})
        after = record["result"]["state"]
        for key in ("xp", "mp", "st", "copper"):
            if old.get(key) != after[key]:
                value["resource_changes"].append(
                    {
                        "field": "progress.xp" if key == "xp" else "gameplay." + key,
                        "before": old.get(key),
                        "after": after[key],
                    }
                )
        value["dice"] = record["result"]["rolls"]
    return value
