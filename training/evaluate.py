"""Offline contract benchmark. Unavailable local/adapter inference is not fabricated."""

import argparse
import json
from pathlib import Path

from rpg_vkr.learning.evaluation import evaluate as contracts


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--directory", type=Path, required=True)
    p.add_argument("--adapter", type=Path)
    p.add_argument("--report", type=Path, required=True)
    a = p.parse_args()
    result = contracts(a.directory)
    result["training"] = "NOT_RUN_BY_THIS_COMMAND"
    result["benchmark_scope"] = "offline_contracts_with_embedded_methods_in_all_conditions"
    result["local_base"] = "NOT_DEPLOYED"
    result["trained_model"] = "NOT_TRAINED"
    result["hybrid_quality"] = "NOT_MEASURED"
    if a.adapter:
        manifest = a.adapter / "training-manifest.json"
        if not manifest.is_file():
            raise ValueError("No real training manifest")
        result["adapter_manifest"] = json.loads(manifest.read_text(encoding="utf-8"))
        result["trained_model"] = "REQUIRES_LIVE_HOLDOUT_EVALUATION"
    with a.report.open("x", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
