"""Offline context/validator comparison; cannot measure live DeepSeek literary quality."""

import hashlib
import json
import statistics
import time

from rpg_vkr.application import Session
from rpg_vkr.domain.catalog import Definition, Entity
from rpg_vkr.learning.library import Library, active_path
from rpg_vkr.learning.memory import recall
from rpg_vkr.learning.runtime import enrich
from rpg_vkr.learning.scenarios import scenarios
from rpg_vkr.narrative.context import build_frame
from rpg_vkr.narrative.master import campaign_context
from rpg_vkr.narrative.story import story_context, story_payload, story_proposal

MODES = {"B0": (False, False), "B1": (True, False), "B2": (False, True), "B3": (True, True)}
MOCKS = (
    ("Мёртвая тишина повисла у дороги. Ветер шевелит листья у стены.", True),
    ("Вы получили 100 золотых монет и 100 очков опыта.", False),
    ("Вы решили согласиться на поручение и обещали вернуться к рассвету.", False),
)


def evaluate(directory):
    cases = scenarios()
    if len(cases) != 100 or len({r["id"] for r in cases}) != 100:
        raise ValueError("Нужны100различных оригинальных сценариев.")
    with Library(active_path(directory)) as db:
        manifest = db.stats()
    session = Session(seed=37)
    session.register_catalog(
        "Встречаю писца Ливну",
        [Definition("eval_scribe_type", "Ливна", "actor", ("npcs",), {"hp_max": 1})],
        [
            Entity(
                "eval_scribe",
                "eval_scribe_type",
                session.interaction_state().current,
                state={"hp": 1},
            )
        ],
        "Оригинальная офлайн-сцена",
        "offline-evaluation",
    )
    frame = build_frame(session)
    before = session.to_dict(), session.dice.checkpoint()
    rows = []
    for case in cases:
        query = case["query"]
        campaign = campaign_context(session)
        baseline = story_context(frame, "offline-mock", query, campaign=campaign)
        for mode, (rag, memory) in MODES.items():
            started = time.perf_counter()
            context = dict(baseline)
            # Query the same committed history; unrelated requests get no forced memory.
            if memory:
                context["learning_memory"] = recall(session, query, budget=1200)
            if rag or memory:
                context = enrich(
                    context,
                    query,
                    {"library": rag, "memory": memory, "mode": 2},
                    directory=directory,
                    remote=True,
                )
            payload = story_payload(frame, "offline-mock", query, context=context)
            mismatch, errors = 0, []
            for mock, expected in MOCKS:
                try:
                    story_proposal(
                        {"message": {"role": "assistant", "content": mock}},
                        frame,
                        query,
                        context=context,
                    )
                    accepted = True
                except ValueError:
                    accepted = False
                if accepted != expected:
                    mismatch += 1
                    errors.append("false_reject" if expected else "unsafe_accept")
            hints = context.get("narrative_techniques", [])
            rows.append(
                {
                    "id": case["id"],
                    "group": case["group"],
                    "mode": mode,
                    "selected_ids": [r["id"] for r in hints],
                    "expected_method_found": case["expected_method"] in {r["id"] for r in hints},
                    "validator_mismatches": mismatch,
                    "errors": errors,
                    "context_bytes": len(json.dumps(payload, ensure_ascii=False).encode()),
                    "extra_bytes": context.get("learning_trace", {}).get("extra_bytes", 0),
                    "memory_events": len(context.get("learning_memory", [])),
                    "latency_ms": (time.perf_counter() - started) * 1000,
                }
            )
    unchanged = before == (session.to_dict(), session.dice.checkpoint())
    summary = {}
    for mode in MODES:
        subset = [r for r in rows if r["mode"] == mode]
        summary[mode] = {
            "cases": len(subset),
            "validator_mismatches": sum(r["validator_mismatches"] for r in subset),
            "unsafe_accepts": sum(r["errors"].count("unsafe_accept") for r in subset),
            "expected_method_hits_proxy": sum(r["expected_method_found"] for r in subset),
            "memory_available": sum(bool(r["memory_events"]) for r in subset),
            "max_context_bytes": max(r["context_bytes"] for r in subset),
            "max_extra_bytes": max(r["extra_bytes"] for r in subset),
            "median_ms": statistics.median(r["latency_ms"] for r in subset),
            "p95_ms": sorted(r["latency_ms"] for r in subset)[94],
        }
    return {
        "protocol": "original-offline-context-ab-1",
        "seed": 37,
        "pipeline": manifest["pipeline"],
        "archive_sha256": manifest["archive_sha256"],
        "scenario_sha256": hashlib.sha256(
            json.dumps(cases, ensure_ascii=False).encode()
        ).hexdigest(),
        "scenarios": 100,
        "conditions": 4,
        "paid_calls": 0,
        "model_calls": 0,
        "same_mock_responses": True,
        "canonical_state_and_rng_unchanged": unchanged,
        "quality_gain": "NOT_MEASURED_MOCK_RESPONSES",
        "training": "BLOCKED_PROVIDER_TRAINING",
        "metrics_not_measured": ["literary_coherence", "live_repetition", "live_npc_voice"],
        "summary": summary,
        "rows": rows,
    }
