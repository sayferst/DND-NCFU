"""Bounded context enrichment. Missing/locked indices safely retain the baseline path."""

import json
import sqlite3
import time

from rpg_vkr.learning.library import Library, active_path
from rpg_vkr.learning.query import namespaces


def enrich(context, query, features, *, directory=None, remote=True):
    result = dict(context)
    for key in ("learning_memory", "narrative_techniques"):
        if key in result:
            result[key] = list(result[key])
    if not (features.get("library") or features.get("memory")):
        return result
    start = time.perf_counter()
    trace = {"mode": features.get("mode", 0), "sources": [], "status": "off", "raw_logged": False}
    if features.get("mode", 0) == 0:
        result.pop("learning_memory", None)
        return result
    try:
        hints = []
        if features.get("library"):
            with Library(active_path(directory)) as store:
                hints = store.search(
                    query, namespaces=namespaces(query), remote=remote, budget=1100
                )
        trace.update(
            status="selected" if hints else "empty",
            sources=[{"id": r["id"], "source": r["source"]} for r in hints],
        )
        if features["mode"] == 2 and hints:
            result["narrative_techniques"] = hints
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
        trace["status"] = "baseline_fallback"
    trace["lookup_ms"] = (time.perf_counter() - start) * 1000
    memories = result.get("learning_memory", [])
    trace["memory_events"] = [r["event_id"] for r in memories]
    if features.get("mode") != 2:
        result.pop("learning_memory", None)
        trace["extra_bytes"] = 0
        result["learning_trace"] = trace
        return result

    def extra_size():
        return len(
            json.dumps(
                {
                    "hints": result.get("narrative_techniques", []),
                    "memory": result.get("learning_memory", []),
                },
                ensure_ascii=False,
            ).encode()
        )

    # UTF-8 bytes conservatively bound byte-tokenizers without downloading a tokenizer.
    while extra_size() > 1800 and result.get("learning_memory"):
        result["learning_memory"].pop()
    while extra_size() > 1800 and result.get("narrative_techniques"):
        result["narrative_techniques"].pop()
    trace["extra_bytes"] = extra_size()
    result["learning_trace"] = trace
    return result
