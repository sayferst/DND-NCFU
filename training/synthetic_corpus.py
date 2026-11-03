"""Separate, opt-in editorially checked synthetic pilot; never gm-sft-v1 receipts."""

import argparse
import hashlib
import json
from pathlib import Path

from rpg_vkr.learning.quality import safe_excerpt
from training.jsonio import strict_json
from training.owner_policy import load_policy
from training.schema import digest

SCHEMA = "gm-synthetic-sft-v1"
POLICY = "synthetic-pilot-v1"
SPLITS = ("train", "val", "test")
CHECKS = {"receipt_grounding", "no_new_player_decisions", "no_unconfirmed_world_facts"}


def sha(value):
    return digest(value)


def validate(row):
    required = {
        "schema_version",
        "sample_id",
        "campaign_id",
        "family",
        "scene_mode",
        "public_context",
        "player_message",
        "engine_receipt",
        "assistant_reply",
        "synthetic",
        "source_record",
        "source_archive_sha256",
        "editorial_review",
        "owner_decisions_sha256",
        "human_reviewed",
    }
    if not isinstance(row, dict) or set(row) != required:
        return False, "synthetic_schema_fields"
    if row["schema_version"] != SCHEMA or row["synthetic"] is not True:
        return False, "synthetic_provenance"
    if row["human_reviewed"] is not False:
        return False, "invented_human_review"
    for key in (
        "sample_id",
        "campaign_id",
        "family",
        "scene_mode",
        "player_message",
        "assistant_reply",
    ):
        if not isinstance(row[key], str) or not row[key].strip() or len(row[key]) > 12000:
            return False, "text_bounds"
    if not isinstance(row["public_context"], dict) or not isinstance(row["engine_receipt"], dict):
        return False, "source_facts_changed"
    source, review = row["source_record"], row["editorial_review"]
    if not isinstance(source, dict) or not isinstance(review, dict):
        return False, "source_or_review"
    if (
        not isinstance(source.get("mock_engine_receipt"), dict)
        or source.get("synthetic") is not True
        or source.get("sft_admitted") is not False
        or source.get("mock_engine_receipt", {}).get("provenance") != "SYNTHETIC_EXAMPLE"
        or row["engine_receipt"] != source.get("mock_engine_receipt")
        or row["public_context"] != source.get("public_context")
        or row["player_message"] != source.get("player_message")
        or row["sample_id"] != source.get("scenario_id")
        or row["family"] != row["sample_id"].rsplit("_", 2)[0]
        or row["campaign_id"] != "synthetic-family:" + row["family"]
    ):
        return False, "source_facts_changed"
    if (
        review.get("kind") != "ASSISTANT_EDITORIAL_REVIEWED"
        or review.get("reviewer") != "codex"
        or review.get("source_pair_sha256") != sha(source)
        or review.get("reply_sha256") != sha(row["assistant_reply"])
        or review.get("human_reviewed") is not False
        or set(review.get("checks", [])) != CHECKS
        or not isinstance(review.get("rationale"), str)
        or not review["rationale"].strip()
    ):
        return False, "unbound_editorial_review"
    for key in ("source_archive_sha256", "owner_decisions_sha256"):
        if (
            not isinstance(row[key], str)
            or len(row[key]) != 64
            or any(c not in "0123456789abcdef" for c in row[key])
        ):
            return False, "missing_provenance_hash"
    text = json.dumps(row, ensure_ascii=False)
    if not safe_excerpt(text):
        return False, "unsafe_or_personal"
    context = json.dumps([row["public_context"], row["engine_receipt"]]).casefold()
    if any(
        key in context
        for key in (
            "private_plot",
            "secret_gm",
            "campaign_private",
            "api_key",
            "password",
            "authorization",
            "api_token",
        )
    ):
        return False, "private_context"
    return True, "editorially_checked_synthetic"


def verify(directory):
    directory = Path(directory)
    manifest = strict_json((directory / "manifest.json").read_bytes())
    if (
        manifest.get("schema") != SCHEMA
        or manifest.get("status") != "PILOT_READY"
        or manifest.get("dataset_policy") != POLICY
        or manifest.get("human_reviewed_samples") != 0
        or manifest.get("approved_for_runtime") is not False
    ):
        raise ValueError("BLOCKED_DATA: explicit synthetic pilot manifest required")
    splits, seen_ids, seen_families, seen_texts = {}, set(), set(), set()
    for split in SPLITS:
        raw = (directory / (split + ".jsonl")).read_bytes()
        if manifest.get("file_sha256", {}).get(split) != hashlib.sha256(raw).hexdigest():
            raise ValueError("BLOCKED_DATA: synthetic split changed")
        rows = [strict_json(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
        if not rows or not all(validate(row)[0] for row in rows):
            raise ValueError("BLOCKED_DATA: invalid or empty synthetic split")
        ids = [row["sample_id"] for row in rows]
        families = {row["family"] for row in rows}
        texts = {" ".join(row["player_message"].casefold().split()) for row in rows}
        if (
            len(set(ids)) != len(ids)
            or seen_ids & set(ids)
            or seen_families & families
            or seen_texts & texts
        ):
            raise ValueError("BLOCKED_DATA: synthetic holdout leakage")
        if any(
            row["source_archive_sha256"] != manifest.get("source_archive_sha256") for row in rows
        ):
            raise ValueError("BLOCKED_DATA: source archive binding differs")
        if any(
            row["owner_decisions_sha256"] != manifest.get("owner_decisions_sha256") for row in rows
        ):
            raise ValueError("BLOCKED_DATA: owner policy binding differs")
        seen_ids.update(ids)
        seen_families.update(families)
        seen_texts.update(texts)
        splits[split] = rows
    all_rows = sorted((r for rows in splits.values() for r in rows), key=lambda r: r["sample_id"])
    if manifest.get("sha256") != sha(all_rows) or manifest.get("splits") != {
        s: len(rows) for s, rows in splits.items()
    }:
        raise ValueError("BLOCKED_DATA: synthetic corpus manifest changed")
    return manifest, splits


def prepare(archive, editorial, owner_decisions, output):
    from training.review_training_pack import audit

    report, data, files = audit(archive, owner_decisions=owner_decisions)
    if report["status"] == "INVALID_PACK":
        raise ValueError("BLOCKED_DATA: invalid source pack")
    _, owner_sha = load_policy(owner_decisions, rulebook=files["approved_rules_R01_R14.json"])
    reviews = [
        strict_json(line)
        for line in Path(editorial).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len({r.get("scenario_id") for r in reviews}) != len(reviews):
        raise ValueError("Duplicate editorial review ID")
    by_id = {r["scenario_id"]: r for r in reviews}
    if set(by_id) != {r["scenario_id"] for r in data["pairs"]}:
        raise ValueError("Every synthetic pair needs a bound editorial review")
    rows = []
    for source in data["pairs"]:
        id = source["scenario_id"]
        edit = by_id[id]
        row = {
            "schema_version": SCHEMA,
            "sample_id": id,
            "family": id.rsplit("_", 2)[0],
            "campaign_id": "synthetic-family:" + id.rsplit("_", 2)[0],
            "scene_mode": "narrator",
            "public_context": source["public_context"],
            "player_message": source["player_message"],
            "engine_receipt": source["mock_engine_receipt"],
            "assistant_reply": edit["assistant_reply"],
            "synthetic": True,
            "source_record": source,
            "source_archive_sha256": report["source_sha256"],
            "editorial_review": edit["editorial_review"],
            "owner_decisions_sha256": owner_sha,
            "human_reviewed": False,
        }
        ok, reason = validate(row)
        if not ok:
            raise ValueError(f"Invalid editorial sample {id}: {reason}")
        rows.append(row)
    families = sorted(
        {r["family"] for r in rows}, key=lambda f: hashlib.sha256(f.encode()).hexdigest()
    )
    if len(families) < 5:
        raise ValueError("At least five independent families required for a pilot")
    holdout_count = max(1, len(families) // 10)
    groups = {
        "test": set(families[:holdout_count]),
        "val": set(families[holdout_count : 2 * holdout_count]),
        "train": set(families[2 * holdout_count :]),
    }
    splits = {
        s: sorted((r for r in rows if r["family"] in groups[s]), key=lambda r: r["sample_id"])
        for s in SPLITS
    }
    manifest = {
        "schema": SCHEMA,
        "dataset_policy": POLICY,
        "status": "PILOT_READY",
        "sha256": sha(sorted(rows, key=lambda r: r["sample_id"])),
        "splits": {s: len(v) for s, v in splits.items()},
        "families": {s: sorted(v) for s, v in groups.items()},
        "owner_decisions_sha256": owner_sha,
        "source_archive_sha256": report["source_sha256"],
        "editorial_reviews": len(rows),
        "human_reviewed_samples": 0,
        "real_engine_receipts": 0,
        "synthetic_samples": len(rows),
        "approved_for_runtime": False,
        "training_steps": 0,
        "limitations": [
            "SMALL_SYNTHETIC_PILOT",
            "ASSISTANT_NOT_HUMAN_REVIEW",
            "NO_RUNTIME_RULE_PARITY_PROOF",
            "FAMILY_HOLDOUT_NOT_SEMANTIC_INDEPENDENCE_PROOF",
            "NOT_A_FULL_MASTER_DATASET",
        ],
    }
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    for split, values in splits.items():
        (output / (split + ".jsonl")).write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in values), encoding="utf-8"
        )
    manifest["file_sha256"] = {
        s: hashlib.sha256((output / (s + ".jsonl")).read_bytes()).hexdigest() for s in SPLITS
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    verify(output)
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "editorial", "owner-decisions", "output"):
        p.add_argument("--" + name, required=True, type=Path)
    a = p.parse_args()
    result = prepare(a.archive, a.editorial, a.owner_decisions, a.output)
    print(
        json.dumps(
            {k: result[k] for k in ("status", "splits", "human_reviewed_samples", "training_steps")}
        )
    )


if __name__ == "__main__":
    main()
