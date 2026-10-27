"""Verify an actual adapter and emit an owner-only deployment manifest."""

import argparse
import hashlib
import json
from pathlib import Path


def export(adapter, evaluation, output, endpoint, model):
    adapter = Path(adapter)
    weights = adapter / "adapter_model.safetensors"
    training = json.loads((adapter / "training-manifest.json").read_text(encoding="utf-8"))
    review = json.loads(Path(evaluation).read_text(encoding="utf-8"))
    sha = hashlib.sha256(weights.read_bytes()).hexdigest()
    if training["global_step"] < 1 or training.get("smoke") or sha != training["adapter_sha256"]:
        raise ValueError("No approved real trained adapter")
    if (
        review.get("critical_regression") is not False
        or review.get("holdout_campaigns", 0) < 1
        or review.get("approved_by_owner") is not True
    ):
        raise ValueError("Actual holdout evaluation and owner review required")
    record = {
        "approved_for_runtime": True,
        "evaluation": review,
        "adapter_path": str(weights.resolve()),
        "adapter_sha256": sha,
        "endpoint": endpoint,
        "model": model,
    }
    with Path(output).open("x", encoding="utf-8") as f:
        json.dump(record, f, indent=2)
    return record


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--adapter", required=True, type=Path)
    p.add_argument("--evaluation", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--endpoint", required=True)
    p.add_argument("--model", required=True)
    a = p.parse_args()
    export(a.adapter, a.evaluation, a.output, a.endpoint, a.model)


if __name__ == "__main__":
    main()
