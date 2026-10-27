"""Explicit privacy-reviewed admission and family-separated export; no model calls."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from rpg_vkr.learning.quality import signature
from training.inspect_archive import inspect
from training.schema import digest, validate


def prepare(path, output, *, privacy_review=False, dry_run=True):
    report, rows = inspect(path)
    accepted = []
    reasons = Counter()
    seen = {}
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            x = parent[x]
        return x

    for row in rows:
        ok, reason = validate(row)
        reasons[reason] += 1
        if not ok:
            continue
        campaign = row["campaign_id"]
        find(campaign)
        # Normalized identical examples join campaigns before splitting, never leak across splits.
        key = hashlib.sha256(signature("header\n" + row["assistant_reply"]).encode()).hexdigest()
        if key in seen:
            parent[find(campaign)] = find(seen[key])
            continue
        seen[key] = campaign
        accepted.append(row)
    from training.split_dataset import split

    parts, diagnostics = split(accepted)
    manifest = report | {
        "schema": "gm-sft-v1",
        "group_diagnostics": diagnostics,
        "accepted": len(accepted),
        "reasons": dict(reasons),
        "sha256": digest(accepted),
        "splits": {k: len(v) for k, v in parts.items()},
        "privacy_review_confirmed": privacy_review,
        "status": "READY" if accepted and privacy_review else "BLOCKED_DATA",
    }
    if not dry_run:
        if not privacy_review:
            raise ValueError("Explicit privacy review required")
        output = Path(output)
        output.mkdir(parents=True, exist_ok=False)
        for split, values in parts.items():
            with (output / (split + ".jsonl")).open("x", encoding="utf-8") as f:
                for value in values:
                    f.write(json.dumps(value, ensure_ascii=False) + "\n")
        (output / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return manifest


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--confirm-privacy-review", action="store_true")
    a = p.parse_args()
    print(
        json.dumps(
            prepare(a.input, a.output, privacy_review=a.confirm_privacy_review, dry_run=a.dry_run),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
