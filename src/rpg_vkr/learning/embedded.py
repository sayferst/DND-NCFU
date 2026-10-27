"""Automatically loaded public knowledge, separate from every private campaign."""

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from rpg_vkr.learning.quality import safe_excerpt
from rpg_vkr.learning.query import terms
from rpg_vkr.resources import resource_path

SCHEMA = "approved-knowledge-1"


@lru_cache(maxsize=2)
def load(path=None):
    path = Path(path) if path else resource_path("data/approved_knowledge/index.json")
    try:
        if path.stat().st_size > 256 * 1024:
            return ()
        raw = json.loads(path.read_text(encoding="utf-8"))
        records = raw["records"]
        digest = hashlib.sha256(
            json.dumps(records, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        if raw["schema"] != SCHEMA or raw["sha256"] != digest:
            return ()
        allowed = []
        for row in records:
            if row["type"] not in (
                "writing_example",
                "scene_pattern",
                "world_lore",
                "general_rules",
            ):
                continue
            if row["rights"] not in ("project_owned", "permitted") or not row["external_allowed"]:
                continue
            if row["review"] not in ("project_authored", "approved") or not safe_excerpt(
                row["text"]
            ):
                continue
            if not 1 <= len(row["text"]) <= 600:
                continue
            allowed.append(row)
        return tuple(allowed)
    except (OSError, ValueError, KeyError, TypeError):
        return ()


def retrieve(query, *, path=None, budget=1200):
    words = set(terms(query))
    scored = []
    for row in load(path):
        score = len(words & set(terms(row["tags"] + " " + row["text"])))
        if score:
            scored.append((score, row))
    selected = []
    for _, row in sorted(scored, key=lambda p: (-p[0], p[1]["id"])):
        item = {
            "id": row["id"],
            "source": row["source"],
            "text": row["text"],
            "kind": "example_not_fact",
            "quality": row["review"],
        }
        if len(json.dumps(selected + [item], ensure_ascii=False).encode()) <= budget:
            selected.append(item)
        if len(selected) == 3:
            break
    return selected
