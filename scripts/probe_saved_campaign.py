"""Installer CI: create/verify a real isolated save across application updates."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rpg_vkr.domain.adventure import offline_world
from rpg_vkr.domain.character import ABILITY_NAMES, Character
from rpg_vkr.domain.unified import CLASSES
from rpg_vkr.storage.slots import SaveSlots
from rpg_vkr.unified_session import UnifiedSession


def probe(directory, phase):
    directory = Path(directory)
    slots = SaveSlots(directory / "saves")
    proof = directory / "expected.json"
    if phase == "create":
        if directory.exists():
            raise ValueError("Use a new isolated directory")
        s = UnifiedSession.create(
            Character(**dict(zip(ABILITY_NAMES, CLASSES["mage"][3], strict=True))),
            "mage",
            "focus",
            seed=37,
        )
        s.start_world(offline_world(s))
        s.perform_gameplay("cast", {"spell": "light", "target": "hero"}, "before-update")
        slots.save(1, s)
        payload = {
            "sha256": hashlib.sha256((directory / "saves/slot-1.json").read_bytes()).hexdigest(),
            "mp": s.gameplay["mp"],
            "minute": s.gameplay["minute"],
        }
        proof.write_text(json.dumps(payload), encoding="utf-8")
    expected = json.loads(proof.read_text(encoding="utf-8"))
    if (
        hashlib.sha256((directory / "saves/slot-1.json").read_bytes()).hexdigest()
        != expected["sha256"]
    ):
        raise ValueError("Update changed saved campaign bytes")
    restored = slots.load(1)
    if (
        restored.schema_version != 31
        or restored.gameplay["mp"] != expected["mp"]
        or restored.gameplay["minute"] != expected["minute"]
    ):
        raise ValueError("Updated campaign did not replay")
    return {
        "save_bytes_preserved": True,
        "schema31_load": True,
        "mp_preserved": True,
        "phase": phase,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--directory", required=True, type=Path)
    p.add_argument("--phase", choices=("create", "verify"), required=True)
    args = p.parse_args()
    print(json.dumps(probe(args.directory, args.phase)))
