"""800 rule proposals, with optional explicitly selected local semantic suggestions."""

import argparse
import json
from pathlib import Path

from rpg_vkr.narrative.local_models import local_models
from training.annotation import suggest_rules
from training.annotation_v2 import rows_v2
from training.ollama_probe import request


def suggest(*, model=None, limit=20, requester=request):
    rows = [r for r in rows_v2() if r["review_track"] == "AI_LATER"]
    proposals = [
        suggest_rules(row) | {"sampling_version": 2, "ai_suggestion": {"status": "NOT_REQUESTED"}}
        for row in rows
    ]
    if model:
        try:
            available = model in local_models(requester("/api/tags"))
        except (OSError, ValueError):
            available = False
        for row, proposal in list(zip(rows, proposals, strict=True))[: max(0, min(limit, 800))]:
            if not available:
                proposal["ai_suggestion"] = {"status": "BLOCKED_PROVIDER_OR_MODEL"}
                continue
            try:
                result = requester(
                    "/api/chat",
                    {
                        "model": model,
                        "stream": False,
                        "format": "json",
                        "messages": [
                            {
                                "role": "system",
                                "content": "Предложи оценку синтетического сценария. Только JSON: "
                                "attempt_possible (YES/NO/UNKNOWN), goal_reachable "
                                "(YES/NO/PARTIAL/UNKNOWN), d20_required (YES/NO/UNKNOWN), "
                                "reason, uncertainty (low/medium/high). Не подтверждай "
                                "разметку человеком.",
                            },
                            {
                                "role": "user",
                                "content": json.dumps(
                                    {k: row[k] for k in ("context", "items", "skills", "action")},
                                    ensure_ascii=False,
                                ),
                            },
                        ],
                        "options": {
                            "num_ctx": 4096,
                            "num_predict": 256,
                            "temperature": 0,
                            "seed": 37,
                        },
                    },
                )
                value = json.loads(result["message"]["content"])
                if set(value) != {
                    "attempt_possible",
                    "goal_reachable",
                    "d20_required",
                    "reason",
                    "uncertainty",
                }:
                    raise ValueError("Invalid suggestion schema")
                if (
                    value["attempt_possible"] not in ("YES", "NO", "UNKNOWN")
                    or value["goal_reachable"] not in ("YES", "NO", "PARTIAL", "UNKNOWN")
                    or value["d20_required"] not in ("YES", "NO", "UNKNOWN")
                    or value["uncertainty"] not in ("low", "medium", "high")
                    or not isinstance(value["reason"], str)
                    or len(value["reason"]) > 2000
                ):
                    raise ValueError("Invalid suggested labels")
                proposal["ai_suggestion"] = {
                    "status": "AI_SUGGESTED",
                    "model": model,
                    "labels": value,
                    "human_approved": False,
                    "train_admitted": False,
                }
            except (OSError, ValueError, KeyError, TypeError):
                proposal["ai_suggestion"] = {"status": "HUMAN_REVIEW_REQUIRED", "model": model}
    return proposals


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--local-model")
    p.add_argument("--limit", type=int, default=20)
    a = p.parse_args()
    values = suggest(model=a.local_model, limit=a.limit)
    with a.output.open("x", encoding="utf-8") as f:
        for row in values:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(
        json.dumps(
            {
                "rule_proposals": len(values),
                "ai_proposals": sum(r["ai_suggestion"]["status"] == "AI_SUGGESTED" for r in values),
                "human_approved": 0,
                "sft_admitted": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
