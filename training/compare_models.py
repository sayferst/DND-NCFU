"""Compare actual recorded runs; missing conditions stay NOT_RUN, never score zero."""

import argparse
import json
from pathlib import Path

CONDITIONS = (
    "deepseek_baseline",
    "faun_base",
    "faun_trained",
    "deepseek_engine",
    "faun_trained_engine",
)


def compare(paths, *, training_families=()):
    result = {k: {"status": "NOT_RUN", "samples": 0, "metrics": None} for k in CONDITIONS}
    signatures = set()
    prompt_signatures = set()
    corpus_signatures = set()
    prompt_availability = set()
    for path in paths:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        condition = data["condition"]
        if condition not in result or result[condition]["status"] != "NOT_RUN":
            raise ValueError("Unknown or repeated experimental condition")
        samples = data["samples"]
        if (
            not samples
            or not data.get("model_revision")
            or not data.get("actual_inference")
            or any(r["family"] in training_families for r in samples)
        ):
            raise ValueError("Actual independent holdout inference is required")
        ids = [r["id"] for r in samples]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate holdout sample")
        signatures.add(tuple(sorted(ids)))
        has_prompts = any("prompt_sha256" in row for row in samples)
        prompt_availability.add(has_prompts)
        if has_prompts:
            if not data.get("dataset_sha256"):
                raise ValueError("Paired prompt evidence needs its dataset digest")
            if any(not row.get("prompt_sha256") for row in samples):
                raise ValueError("Every paired sample needs its prompt digest")
            prompt_signatures.add(tuple(sorted((r["id"], r["prompt_sha256"]) for r in samples)))
            corpus_signatures.add(data.get("dataset_sha256"))
        result[condition] = {
            "status": "RECORDED_REQUIRES_HUMAN_QUALITY_REVIEW",
            "samples": len(samples),
            "metrics": {
                "mean_latency_seconds": sum(r["latency_seconds"] for r in samples) / len(samples),
                "critical_violations": sum(len(r["critical_violations"]) for r in samples),
                "human_literary_quality": "NOT_MEASURED"
                if not data.get("human_review")
                else data["human_review"],
            },
            "model_revision": data["model_revision"],
        }
    if len(signatures) > 1:
        raise ValueError("Paired conditions must use the same holdout IDs")
    if len(prompt_signatures) > 1 or len(corpus_signatures) > 1 or len(prompt_availability) > 1:
        raise ValueError("Paired conditions must use identical prompts and dataset")
    return {
        "schema": "narrator-comparison-v1",
        "conditions": result,
        "improvement_claim": "NONE_WITHOUT_PAIRED_HUMAN_REVIEW",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(compare(args.run), stream, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
