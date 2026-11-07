"""Explicit new-file activation for existing catalog3 campaigns; source stays untouched."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from rpg_vkr.application import Session
from rpg_vkr.storage.slots import MAX_SAVE_BYTES


def activate(source, output, *, owner_rules=False):
    source, output = Path(source), Path(output)
    if source.stat().st_size > MAX_SAVE_BYTES or output.exists():
        raise ValueError("Oversized source or existing destination")
    data = json.loads(source.read_text(encoding="utf-8"))
    if data.get("schema_version") != 31:
        raise ValueError("Only existing unified catalog3 campaigns are supported")
    session = Session.from_dict(data["session"], version=31)
    if not getattr(session, "is_unified", False):
        raise ValueError("A unified campaign is required")
    if not owner_rules or not session.gameplay.get("free_action_policy"):
        session.perform_gameplay("enable_attempt_plans", {"version": 1}, session._request_token())
    if owner_rules:
        session.perform_gameplay("enable_owner_rules", {"version": 1}, session._request_token())
    payload = session.to_dict()
    if Session.from_dict(payload, version=31).to_dict() != payload:
        raise ValueError("Activated continuation failed replay validation")
    envelope = {"schema_version": 31, "saved_at": datetime.now(UTC).isoformat(), "session": payload}
    with output.open("x", encoding="utf-8") as stream:
        json.dump(envelope, stream, ensure_ascii=False, indent=2)
    return session


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    activate(args.input, args.output)
    print("Created a replay-verified copy. The source file was not modified.")


if __name__ == "__main__":
    main()
