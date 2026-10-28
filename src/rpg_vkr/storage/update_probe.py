"""Read-only verification of an isolated campaign written by an earlier release."""

import hashlib
import json
from pathlib import Path

from rpg_vkr.storage.slots import SaveSlots


def verify(directory):
    directory = Path(directory)
    expected = json.loads((directory / "expected.json").read_text(encoding="utf-8"))
    path = directory / "saves/slot-1.json"
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected["sha256"]:
        raise ValueError("Update changed saved campaign bytes")
    restored = SaveSlots(directory / "saves").load(1)
    if (
        restored.schema_version != 31
        or restored.gameplay["mp"] != expected["mp"]
        or restored.gameplay["minute"] != expected["minute"]
    ):
        raise ValueError("Updated campaign did not replay")
    return {
        "ok": True,
        "save_bytes_preserved": True,
        "schema31_load": True,
        "mp_preserved": True,
        "catalog_revision": restored.gameplay.get("catalog_revision", 1),
    }
