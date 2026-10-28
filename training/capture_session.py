"""Explicit local export of replay-verified candidates; never automatic SFT admission."""

import argparse
import hashlib
import json
from pathlib import Path

from rpg_vkr.application import Session
from rpg_vkr.domain.adventure import WorldSeed
from rpg_vkr.domain.campaign import Campaign
from rpg_vkr.domain.character import Character
from rpg_vkr.domain.receipts import receipt
from rpg_vkr.narrative.master import campaign_context
from rpg_vkr.storage.migration import decode
from rpg_vkr.storage.slots import MAX_SAVE_BYTES
from rpg_vkr.unified_session import UnifiedSession


def candidates(data):
    version = data.get("schema_version")
    if version not in (30, 31):
        raise ValueError("Candidate capture requires a replayable unified campaign")
    verified = Session.from_dict(data["session"], version=version)
    origin = dict(verified._origin)
    origin.setdefault("content_revision", 1)
    origin.setdefault("world_policy", 3)
    origin["character"] = Character.from_dict(origin["character"])
    origin["campaign"] = Campaign.from_dict(origin["campaign"])
    session = UnifiedSession.create(**origin)
    rows = []
    for op in verified._operations:
        if op["method"] == "start_world":
            session.start_world(WorldSeed.from_dict(op["world_seed"]))
            continue
        args, kwargs = decode(op["args"]), decode(op["kwargs"])
        if op["method"] == "add_narration" and session.turns:
            note = args[0]
            proof = receipt(session)
            public = campaign_context(session, query=session.turns[-1].action)
            # Exclude large/opaque sources; leave only known public, confirmed facts.
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
            rows.append(
                {
                    "schema_version": "gm-sft-v1",
                    "sample_id": hashlib.sha256((proof["id"] + note.text).encode()).hexdigest(),
                    "campaign_id": hashlib.sha256(session.campaign.world_id.encode()).hexdigest(),
                    "scene_mode": "confirmed_gameplay",
                    "public_context": public,
                    "player_message": session.turns[-1].action,
                    "engine_receipt": proof,
                    "assistant_reply": note.text,
                    "review_status": "pending",
                    "rights_status": "unknown",
                    "synthetic": note.model.startswith("fixture:"),
                }
            )
        getattr(session, op["method"])(*args, **kwargs)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.input.stat().st_size > MAX_SAVE_BYTES:
        raise ValueError("Save too large")
    rows = candidates(json.loads(args.input.read_text(encoding="utf-8")))
    with args.output.open("x", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(
        json.dumps({"candidates": len(rows), "admitted_for_training": 0, "training_started": False})
    )


if __name__ == "__main__":
    main()
