"""Explicit consent-gated export of verified transactions, prose and review separately."""

import argparse
import hashlib
import json
from copy import deepcopy
from pathlib import Path

from rpg_vkr.application import Session
from rpg_vkr.domain.adventure import WorldSeed
from rpg_vkr.domain.campaign import Campaign
from rpg_vkr.domain.character import Character
from rpg_vkr.domain.receipts import receipt
from rpg_vkr.narrative.master import campaign_context
from rpg_vkr.narrative.strategic_critic import inspect
from rpg_vkr.storage.migration import decode
from rpg_vkr.storage.slots import MAX_SAVE_BYTES
from rpg_vkr.unified_session import UnifiedSession


def public_state(session):
    public = campaign_context(session)
    public = {
        k: public[k]
        for k in (
            "actors",
            "public_objects",
            "living_world",
            "resource_balances",
            "known_observations",
        )
        if k in public
    }
    public["hero_resources"] = {
        k: session.gameplay[k] for k in ("xp", "mp", "st", "copper", "minute")
    }
    public["hero_resources"]["hp"] = session.world.hp
    public["hero_items"] = [
        {k: i[k] for k in ("id", "name", "kind", "quantity", "durability", "template") if k in i}
        for i in session.gameplay["items"]
        if i["owner"] == "hero"
    ]
    public["place_id"] = session.current_place_id
    return deepcopy(public)


def episodes(data):
    version = data.get("schema_version")
    if version not in (30, 31):
        raise ValueError("Capture requires a replayable unified campaign")
    verified = Session.from_dict(data["session"], version=version)
    origin = dict(verified._origin)
    origin.setdefault("content_revision", 1)
    origin.setdefault("world_policy", 3)
    origin.setdefault("free_action_policy", 0)
    origin["character"] = Character.from_dict(origin["character"])
    origin["campaign"] = Campaign.from_dict(origin["campaign"])
    session = UnifiedSession.create(**origin)
    transactions = {}
    rows = []
    perform = session.perform_gameplay

    def observed(*args, **kwargs):
        before = public_state(session)
        index = len(session.turns)
        result = perform(*args, **kwargs)
        if len(session.turns) > index:
            proof = receipt(session)
            transactions[len(session.turns)] = {
                "before": before,
                "after": public_state(session),
                "intent": session.turns[-1].action,
                "plan": deepcopy(proof.get("free_attempt", {}).get("plan")),
                "engine_receipt": proof,
                "dice": deepcopy(proof.get("dice", [])),
                "command": args[0] if args else kwargs.get("command"),
            }
        return result

    session.perform_gameplay = observed
    for op in verified._operations:
        if op["method"] == "start_world":
            session.start_world(WorldSeed.from_dict(op["world_seed"]))
            continue
        args, kwargs = decode(op["args"]), decode(op["kwargs"])
        if op["method"] == "add_narration":
            note = args[0]
            transaction = transactions.get(note.turn_index)
            if transaction:
                proof = transaction["engine_receipt"]
                rows.append(
                    {
                        "schema_version": "verified-game-episode-v2",
                        "sample_id": hashlib.sha256((proof["id"] + note.text).encode()).hexdigest(),
                        "campaign_id": hashlib.sha256(
                            session.campaign.world_id.encode()
                        ).hexdigest(),
                        "transaction": deepcopy(transaction),
                        "narration": {
                            "text": note.text,
                            "model": note.model,
                            "context_hash": note.context_hash,
                        },
                        "review": {
                            "rule_findings": inspect(proof, note.text),
                            "human_rating": None,
                            "status": "pending",
                        },
                        "rights_status": "unknown",
                        "synthetic": note.model.startswith("fixture:"),
                    }
                )
        getattr(session, op["method"])(*args, **kwargs)
    if session.to_dict() != verified.to_dict():
        raise ValueError("Collector replay differs from source")
    return rows


def candidates(data):
    return [
        {
            "schema_version": "gm-sft-v1",
            "sample_id": r["sample_id"],
            "campaign_id": r["campaign_id"],
            "scene_mode": "confirmed_gameplay",
            "public_context": {
                "before_action": r["transaction"]["before"],
                "after_action": r["transaction"]["after"],
            },
            "player_message": r["transaction"]["intent"],
            "engine_receipt": r["transaction"]["engine_receipt"],
            "assistant_reply": r["narration"]["text"],
            "review_status": "pending",
            "rights_status": "unknown",
            "synthetic": r["synthetic"],
        }
        for r in episodes(data)
    ]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--confirm-owner-consent", action="store_true")
    p.add_argument("--confirm-participant-consent", action="store_true")
    p.add_argument("--detailed-episodes", action="store_true")
    a = p.parse_args()
    if not a.confirm_owner_consent or not a.confirm_participant_consent:
        raise ValueError(
            "Explicit campaign owner and participant consent required before reading a save"
        )
    if a.input.stat().st_size > MAX_SAVE_BYTES:
        raise ValueError("Save too large")
    data = json.loads(a.input.read_text(encoding="utf-8"))
    rows = episodes(data) if a.detailed_episodes else candidates(data)
    with a.output.open("x", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(
        json.dumps({"candidates": len(rows), "admitted_for_training": 0, "training_started": False})
    )


if __name__ == "__main__":
    main()
