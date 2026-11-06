"""Verify actual repository counts and identify exact legacy-name aliases."""

import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from rpg_vkr.world_library.model import dump, normalized, read_jsonl  # noqa: E402


def audit():
    rows = read_jsonl(ROOT / "data/world_library/seed-v1.jsonl")
    original = {}
    legacy = {}
    for relative in (
        "data/catalog/seed-v1.json",
        "data/gameplay/catalog-v1.json",
        "data/gameplay/catalog-v2.json",
        "data/gameplay/catalog-v3.json",
    ):
        path = ROOT / relative
        value = json.loads(path.read_text(encoding="utf-8"))
        records = value.get("records", value.get("definitions", []))
        original[relative] = {
            "records": len(records),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for record in records:
            if "name" in record:
                legacy.setdefault(normalized(record["name"]), []).append(
                    {"source": relative, "id": record["id"]}
                )
    path = ROOT / "data/corpus_knowledge/cards.sqlite3"
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA trusted_schema=OFF")
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        counts = {}
        # Table identifiers are hard-coded, not derived from site/model input.
        for name in ("cards", "aliases", "records"):
            if name in tables:
                counts[name] = db.execute('SELECT COUNT(*) FROM "' + name + '"').fetchone()[0]
    return {
        "original_catalogs": original,
        "reference_corpus": {
            "counts": counts,
            "tables": sorted(tables),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "imported_as_game_templates": 0,
        },
        "new_library": len(rows),
        "exact_name_collisions": [
            {"library_id": r["id"], "name": r["name"], "existing": legacy[normalized(r["name"])]}
            for r in rows
            if normalized(r["name"]) in legacy
        ],
        "policy": (
            "Legacy records remain authoritative; world adapter reuses explicit material aliases "
            "and rejects unresolved name collisions. No semantic/fuzzy deduplication claimed."
        ),
    }


if __name__ == "__main__":
    result = audit()
    if len(sys.argv) > 1:
        with Path(sys.argv[1]).open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    else:
        print(dump(result))
