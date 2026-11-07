"""Account for prior assistant-authored HP targets separately from full source episodes."""

import argparse
import hashlib
import json
from pathlib import Path

from training.fireball_observations import database, unpacked


def lineage(root, previous):
    root, previous = Path(root), Path(previous)
    db = database(root)
    results = []
    for split in ("train", "val", "test"):
        with (previous / (split + ".jsonl")).open(encoding="utf-8") as stream:
            for line in stream:
                value = json.loads(line)
                if value.get("schema_version") != "fireball-observed-hp-v1":
                    continue
                source = value["source"]
                # Old importer used zero-based line numbers; new archive uses one-based lines.
                number = source["line"] + 1
                found = db.execute(
                    "SELECT id,payload FROM observations WHERE file=? AND line=?",
                    (source["file"], number),
                ).fetchone()
                if not found:
                    raise ValueError("Previous HP observation not found in full archive")
                full_sha = db.execute(
                    "SELECT sha FROM ingested WHERE file=?", (source["file"],)
                ).fetchone()[0]
                with (root / "originals" / source["file"]).open("rb") as original:
                    raw = next(raw for i, raw in enumerate(original) if i == source["line"])
                # Old importer hashed raw JSON without line terminator.
                if (
                    full_sha != source["file_sha256"]
                    or hashlib.sha256(raw.rstrip(b"\r\n")).hexdigest() != source["line_sha256"]
                ):
                    raise ValueError("Prior source provenance differs from full archive")
                original_value = unpacked(found[1])
                results.append(
                    {
                        "sample_id": value["sample_id"],
                        "previous_split": split,
                        "source_observation_id": found[0],
                        "source": source,
                        "full_archive_line_one_based": number,
                        "components": {
                            "before_after_states": (
                                "REAL_FIREBALL_VALUES_SELECTED_AND_ACTORS_PSEUDONYMIZED"
                            ),
                            "hp_delta": "CODE_DERIVED_FROM_OBSERVED_HP_NOT_DND_NCFU_RULE",
                            "player_message": "ASSISTANT_AUTHORED_TASK_INSTRUCTION",
                            "russian_target": (
                                "ASSISTANT_AUTHORED_NOT_HUMAN_TRANSCRIPT_NOT_TRANSLATION"
                            ),
                        },
                        "original_fields_available": sorted(original_value),
                        "human_approved": False,
                    }
                )
    if len(results) != 96:
        raise ValueError("Expected historical release count differs; inspect rather than fabricate")
    db.close()
    result = {
        "schema": "fireball-prior-96-component-lineage-v1",
        "derived_samples": len(results),
        "new_independent_real_episodes": 0,
        "original_synthetic_1100": "SEPARATE_UNCHANGED",
        "old_1196_release": "HISTORICAL_NOT_THE_FULL_FIREBALL_CORPUS",
        "records": results,
    }
    (root / "prior-96-lineage.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {k: v for k, v in result.items() if k != "records"}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--previous", type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(lineage(a.root, a.previous), indent=2))


if __name__ == "__main__":
    main()
