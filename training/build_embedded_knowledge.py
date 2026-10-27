"""Build distributable knowledge from original project techniques, not private sessions."""

import argparse
import hashlib
import json
from pathlib import Path

from rpg_vkr.learning.methods import cards


def build(output, source=None):
    rows = [
        {
            "id": r["id"],
            "source": r["source"],
            "type": "scene_pattern",
            "text": r["text"],
            "tags": r["tags"],
            "rights": "project_owned",
            "review": "project_authored",
            "external_allowed": True,
        }
        for r in cards().values()
    ]
    if source is not None:
        from rpg_vkr.learning.quality import CLAIM, safe_excerpt
        from training.schema import validate

        path = Path(source)
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("status") != "READY":
            raise ValueError("No approved dataset")
        for line in (path / "train.jsonl").read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if not validate(row)[0] or row.get("approved_for_public_knowledge") is not True:
                continue
            kind = row.get("knowledge_type")
            text = row["assistant_reply"]
            if (
                kind not in ("writing_example", "scene_pattern", "world_lore", "general_rules")
                or not safe_excerpt(text)
                or len(text) > 600
                or CLAIM.search(text)
            ):
                continue
            candidate = {
                "id": "sft:" + row["sample_id"],
                "source": manifest["source_sha256"],
                "type": kind,
                "text": text,
                "tags": row["scene_mode"],
                "rights": "permitted",
                "review": "approved",
                "external_allowed": True,
            }
            if len(json.dumps(rows + [candidate], ensure_ascii=False).encode()) > 240 * 1024:
                break
            rows.append(candidate)
    result = {
        "schema": "approved-knowledge-1",
        "sha256": hashlib.sha256(
            json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest(),
        "records": rows,
    }
    path = Path(output)
    path.mkdir(parents=True, exist_ok=True)
    destination = path / "index.json"
    if destination.exists():
        if json.loads(destination.read_text(encoding="utf-8")) == result:
            return result
        raise ValueError("Choose a versioned output path; existing index differs")
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--input", type=Path)
    a = p.parse_args()
    r = build(a.output, a.input)
    print(json.dumps({"records": len(r["records"]), "sha256": r["sha256"]}))


if __name__ == "__main__":
    main()
