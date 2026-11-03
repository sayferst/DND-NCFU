"""Explicit local holdout inference; rule findings are not human quality approval."""

import argparse
import hashlib
import json
import time
from pathlib import Path

from rpg_vkr.narrative.local_models import FAUN_MODEL, local_models
from rpg_vkr.narrative.strategic_critic import inspect
from training.ollama_probe import request
from training.schema import validate


def holdout(directory):
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "READY" or not manifest.get("privacy_review_confirmed"):
        raise ValueError("BLOCKED_DATA: reviewed dataset required")
    splits = {}
    for split in ("train", "val", "test"):
        raw = (directory / (split + ".jsonl")).read_bytes()
        if manifest.get("file_sha256", {}).get(split) != hashlib.sha256(raw).hexdigest():
            raise ValueError("BLOCKED_DATA: split changed")
        splits[split] = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line]
        if not all(validate(row)[0] for row in splits[split]):
            raise ValueError("BLOCKED_DATA: unreviewed or invalid samples")
    seen_ids, seen_campaigns = set(), set()
    for rows in splits.values():
        ids = [r["sample_id"] for r in rows]
        campaigns = {r["campaign_id"] for r in rows}
        if len(ids) != len(set(ids)) or seen_ids.intersection(ids) or seen_campaigns & campaigns:
            raise ValueError("BLOCKED_DATA: holdout leakage")
        seen_ids.update(ids)
        seen_campaigns.update(campaigns)
    if not splits["test"]:
        raise ValueError("BLOCKED_DATA: empty independent test split")
    return manifest, splits["test"]


def evaluate(directory, *, model=FAUN_MODEL, limit=20, requester=request):
    manifest, rows = holdout(directory)
    tags = requester("/api/tags")
    if model not in local_models(tags):
        raise ValueError("BLOCKED_MODEL: installed local model required; no download attempted")
    identity = next(m for m in tags["models"] if m["name"] == model)
    if not identity.get("digest"):
        raise ValueError("BLOCKED_MODEL: model digest missing")
    result = {
        "schema": "local-holdout-inference-v1",
        "model": model,
        "model_revision": identity["digest"],
        "dataset_sha256": manifest["sha256"],
        "prompt_mode": "confirmed_engine_receipt",
        "actual_inference": False,
        "human_review": None,
        "automatic_checks": "LIMITED_RULE_CRITIC_NOT_FULL_FACT_VERIFICATION",
        "samples": [],
        "training_steps_by_this_command": 0,
    }
    for row in rows[: max(1, limit)]:
        started = time.perf_counter()
        reply = requester(
            "/api/chat",
            {
                "model": model,
                "stream": False,
                "messages": [
                    {
                        "role": "system",
                        "content": "Пиши по-русски. Опиши только подтверждённый результат движка. "
                        "Не создавай ресурсы и не выбирай следующее действие за игрока.",
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "context": row["public_context"],
                                "player": row["player_message"],
                                "receipt": row["engine_receipt"],
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                "options": {"num_ctx": 2048, "num_predict": 256, "seed": 37, "temperature": 0},
            },
        )
        text = reply.get("message", {}).get("content", "")
        findings = inspect(row["engine_receipt"], text)
        if not text.strip() or reply.get("done") is not True:
            findings.append({"code": "INCOMPLETE_INFERENCE", "severity": "critical"})
        result["samples"].append(
            {
                "id": row["sample_id"],
                "family": row["campaign_id"],
                "latency_seconds": time.perf_counter() - started,
                "reply": text,
                "critical_violations": [f for f in findings if f["severity"] == "critical"],
                "rule_findings": findings,
                "human_review_status": "PENDING",
            }
        )
    result["actual_inference"] = bool(result["samples"])
    result["status"] = "RECORDED_REQUIRES_HUMAN_REVIEW"
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--directory", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--model", default=FAUN_MODEL)
    p.add_argument("--port", type=int, choices=(11434, 11435), default=11434)
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--run-local", action="store_true")
    a = p.parse_args()
    if not a.run_local:
        manifest, rows = holdout(a.directory)
        result = {"status": "DATA_READY_INFERENCE_NOT_RUN", "test_samples": len(rows)}
    else:
        result = evaluate(
            a.directory,
            model=a.model,
            limit=a.limit,
            requester=lambda path, body=None: request(path, body, port=a.port, timeout=600),
        )
    with a.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(result["status"])


if __name__ == "__main__":
    main()
