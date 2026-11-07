"""Independent ledger invariants plus deterministic reference replay for synthetic SFT."""

import hashlib
import json
from collections import Counter
from pathlib import Path

from rpg_vkr.domain.owner_rules import Life
from rpg_vkr.learning.quality import safe_excerpt
from training.grounded_curriculum import (
    POLICY,
    SCHEMA,
    changes,
    compile_row,
    specs,
)
from training.jsonio import strict_json
from training.schema import digest

SPLITS = ("train", "val", "test")


def invariant_errors(row):
    before = row["public_context"]["state"]
    after = row["after_state"]
    errors = []
    for state in (before, after):
        for key in ("mp", "st", "gold", "arrows", "xp", "level"):
            value = state["hero"][key]
            if type(value) is not int or value < 0:
                errors.append("NEGATIVE_OR_INVALID_RESOURCE")
        if (
            state["hero"]["mp"] > state["hero"]["mp_cap"]
            or state["hero"]["st"] > state["hero"]["st_cap"]
        ):
            errors.append("RESOURCE_ABOVE_CAP")
        Life(**state["hero"]["life"])
        Life(**state["target_life"])
        for key in ("food", "treasury", "supplier_stock", "supplier_price"):
            if type(state["world"][key]) is not int or state["world"][key] < 0:
                errors.append("INVALID_WORLD_RESOURCE")
        expected_level = max(lv for lv in range(1, 21) if 50 * (lv - 1) * lv <= state["hero"]["xp"])
        if state["hero"]["level"] != expected_level:
            errors.append("LEVEL_XP_MISMATCH")
        for item in state["objects"].values():
            if item["quantity"] < 0 or not 0 <= item["durability"] <= item["maximum"]:
                errors.append("INVALID_PHYSICAL_QUANTITY_OR_CONDITION")
    if set(before["objects"]) != set(after["objects"]):
        errors.append("UNREGISTERED_OBJECT_ID_CHANGE")
    for id in before["objects"]:
        if before["objects"][id]["id"] != after["objects"][id]["id"]:
            errors.append("OBJECT_ID_CHANGED")

    def money(state):
        return state["hero"]["gold"] + state["npc"]["gold"] + state["world"]["treasury"]

    if money(before) != money(after):
        errors.append("MONEY_NOT_CONSERVED")

    def food(state):
        return (
            state["world"]["food"]
            + state["world"]["supplier_stock"]
            + sum(state["facts"].get("allocation", {}).values())
        )

    if food(before) != food(after):
        errors.append("FOOD_NOT_CONSERVED")
    if row["engine_receipt"]["changes"] != changes(before, after):
        errors.append("DELTA_MISMATCH")
    registered = set(before["registered_entities"]) | set(before["objects"])
    for obj in before["objects"].values():
        if obj.get("holder") not in registered or obj.get("legal_owner") not in registered | {None}:
            errors.append("UNREGISTERED_PHYSICAL_REFERENCE")
    result = row["engine_receipt"]
    op = row["spec"]["operation"]
    if (
        op == "take"
        and before["objects"]["subject"]["legal_owner"]
        != after["objects"]["subject"]["legal_owner"]
    ):
        errors.append("TAKING_CHANGED_LEGAL_TITLE")
    if op == "dead_heal" and before["target_life"] != after["target_life"]:
        errors.append("ORDINARY_HEAL_RESURRECTED_DEAD")
    if op == "noop" and before != after:
        errors.append("READ_ONLY_ACTION_MUTATED_WORLD")
    if op in ("verify", "compare"):
        for key in ("hero", "objects", "npc", "target_life", "world", "route"):
            if before[key] != after[key]:
                errors.append("OBSERVATION_MUTATED_PHYSICAL_WORLD")
    if result.get("blocker") and before != after:
        errors.append("BLOCKED_ACTION_MUTATED_WORLD")
    if not result["d20_required"] and result["roll"] is not None:
        errors.append("UNNECESSARY_ROLL")
    if result["roll"]:
        r = result["roll"]
        task = row["spec"]["task"]
        ability = (
            task
            if task in before["hero"]["abilities"]
            else {
                "repair": "intelligence",
                "smithing": "intelligence",
                "arcana": "intelligence",
                "medicine": "wisdom",
                "athletics": "strength",
                "acrobatics": "dexterity",
                "persuasion": "charisma",
                "melee": "strength",
                "survival": "wisdom",
                "death_save": "constitution",
            }[task]
        )
        expected = (
            r["natural"]
            + (before["hero"]["abilities"][ability] - 10) // 2
            - 2 * before["hero"]["life"]["exhaustion"]
        )
        if r["total"] != expected:
            errors.append("D20_ARITHMETIC_MISMATCH")
        if r["natural"] == 1 and not r["complication"]:
            errors.append("MISSING_NATURAL_ONE_COMPLICATION")
        if r["natural"] == 20 and not r["succeeded"]:
            errors.append("NATURAL_TWENTY_NOT_BEST_LEGAL")
    if op in ("capability", "illusion") and before["hero"]["gold"] != after["hero"]["gold"]:
        errors.append("MAGIC_CREATED_CURRENCY")
    if (
        before["hero"]["xp"] != after["hero"]["xp"]
        or before["hero"]["level"] != after["hero"]["level"]
    ):
        errors.append("UNCONFIRMED_PROGRESSION")
    text = row["assistant_reply"]
    if not isinstance(text, str) or not text.strip() or not safe_excerpt(text):
        errors.append("INVALID_OR_UNSAFE_TARGET")
    if any(
        token in text for token in ("<|im_start|>", "<|im_end|>", "TODO", "HUMAN_REVIEW_REQUIRED")
    ):
        errors.append("CHAT_TOKEN_OR_UNFINISHED_TARGET")
    if text in json.dumps(row["public_context"], ensure_ascii=False):
        errors.append("TARGET_TEXT_LEAKED_IN_CONTEXT")
    return errors


def audit(directory):
    directory = Path(directory)
    manifest = strict_json((directory / "manifest.json").read_bytes())
    definitions = specs()
    from training.rule_curriculum import rows as boundary_rows

    boundaries = {r["sample_id"]: r for r in boundary_rows()}
    errors = []
    parts = {}
    groups = {}
    ids = set()
    responses = Counter()
    prompts = set()
    for split in SPLITS:
        raw = (directory / (split + ".jsonl")).read_bytes()
        if manifest["file_sha256"][split] != hashlib.sha256(raw).hexdigest():
            raise ValueError("BLOCKED_DATA: corpus file changed")
        rows = [strict_json(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
        parts[split] = rows
        if not rows:
            errors.append({"code": "EMPTY_SPLIT", "split": split})
        for row in rows:
            id = row["sample_id"]
            source = row["source_scenario"]
            if id in ids:
                errors.append({"id": id, "code": "DUPLICATE_ID"})
            ids.add(id)
            replay_row = {k: v for k, v in row.items() if k != "owner_authorization_sha256"}
            if id in boundaries:
                expected = boundaries[id]
            else:
                key = source["family"] + ":" + id.rsplit("_", 1)[1]
                if row["spec"] != definitions.get(key):
                    errors.append({"id": id, "code": "CURATED_SPEC_CHANGED"})
                expected = compile_row(source, definitions[key])
            if replay_row != expected:
                errors.append({"id": id, "code": "REFERENCE_REPLAY_MISMATCH"})
            for code in invariant_errors(row):
                errors.append({"id": id, "code": code})
            group = row["campaign_id"]
            if groups.setdefault(group, split) != split:
                errors.append({"id": id, "code": "INTENT_GROUP_LEAKAGE"})
            prompt = digest({"context": row["public_context"], "player": row["player_message"]})
            if prompt in prompts:
                errors.append({"id": id, "code": "DUPLICATE_INPUT"})
            prompts.add(prompt)
            responses[row["assistant_reply"]] += 1
    rows = [r for values in parts.values() for r in values]
    if manifest["sha256"] != digest(sorted(rows, key=lambda r: r["sample_id"])):
        errors.append({"code": "CORPUS_DIGEST_MISMATCH"})
    if manifest["samples"] != len(rows) or len(rows) != 1100:
        errors.append({"code": "INCOMPLETE_SOURCE_COVERAGE"})
    # Closed source identity matters even when the complete row replays consistently.
    from training.annotation_v2 import rows_v2

    baseline = {r["id"]: r for r in rows_v2()}
    if ids != set(baseline) | set(boundaries) or any(
        row["source_scenario"] != baseline.get(row["sample_id"])
        for row in rows
        if row["sample_id"] not in boundaries
    ):
        errors.append({"code": "ORIGINAL_SOURCE_FACTS_CHANGED"})
    report = {
        "schema": "grounded-curriculum-audit-v1",
        "status": "INVALID" if errors else "REFERENCE_AUDIT_PASS",
        "samples": len(rows),
        "errors": errors,
        "intent_groups": len(groups),
        "unique_replies": len(responses),
        "maximum_reply_repetition": max(responses.values(), default=0),
        "human_reviewed_samples": 0,
        "reference_kind": "SYNTHETIC_REFERENCE_NOT_REAL_GAME_EPISODES",
        "training_steps": 0,
        "outcomes": dict(Counter(r["engine_receipt"]["outcome"] for r in rows)),
        "operations": dict(Counter(r["spec"]["operation"] for r in rows)),
    }
    return report, parts


def verify(directory):
    manifest = strict_json((Path(directory) / "manifest.json").read_bytes())
    if (
        manifest.get("schema") != SCHEMA
        or manifest.get("dataset_policy") != POLICY
        or manifest.get("status") != "READY_SYNTHETIC"
    ):
        raise ValueError("BLOCKED_DATA: admitted grounded synthetic corpus required")
    report, splits = audit(directory)
    if report["errors"]:
        raise ValueError("BLOCKED_DATA: reference corpus audit failed")
    if (
        not manifest.get("owner_authorization_sha256")
        or manifest.get("human_reviewed_samples") != 0
    ):
        raise ValueError("BLOCKED_DATA: explicit synthetic provenance/owner authorization missing")
    authorization = (Path(directory) / "owner-authorization.json").read_bytes()
    if hashlib.sha256(authorization).hexdigest() != manifest.get("owner_authorization_sha256"):
        raise ValueError("BLOCKED_DATA: owner authorization changed")
    validate_owner_authorization(strict_json(authorization))
    if any(
        r.get("owner_authorization_sha256") != manifest["owner_authorization_sha256"]
        for rows in splits.values()
        for r in rows
    ):
        raise ValueError("BLOCKED_DATA: sample authorization binding differs")
    return manifest, splits


def validate_owner_authorization(policy):
    if (
        policy.get("confirmation_source") != "DIRECT_USER_REPLY"
        or policy.get("synthetic_corpus_allowed") is not True
        or policy.get("synthetic_state_authoring_allowed") is not True
        or policy.get("knockout_zero_stable") is not True
        or policy.get("overcast_requires_full_hp") is not True
        or set(policy.get("approved_rules", [])) != {f"R{n:02}" for n in range(1, 15)}
    ):
        raise ValueError("Explicit owner authorization for authored synthetic states is required")


def admit(directory, authorization, output):
    authorization = Path(authorization).read_bytes()
    validate_owner_authorization(strict_json(authorization))
    report, splits = audit(directory)
    if report["errors"]:
        raise ValueError("BLOCKED_DATA: fix reference audit errors before admission")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    manifest = strict_json((Path(directory) / "manifest.json").read_bytes())
    policy_sha = hashlib.sha256(authorization).hexdigest()
    all_rows = []
    for split, rows in splits.items():
        bound = [r | {"owner_authorization_sha256": policy_sha} for r in rows]
        all_rows.extend(bound)
        (output / (split + ".jsonl")).write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in bound), encoding="utf-8"
        )
    manifest.update(
        status="READY_SYNTHETIC",
        owner_authorization_sha256=policy_sha,
        sha256=digest(sorted(all_rows, key=lambda r: r["sample_id"])),
        file_sha256={
            s: hashlib.sha256((output / (s + ".jsonl")).read_bytes()).hexdigest() for s in SPLITS
        },
        annotation_missing_fields=0,
        approved_for_runtime=False,
        review_method="CURATED_200_INTENTS_AND_DETERMINISTIC_REFERENCE_VALIDATION",
        semantic_coverage_limit="REFERENCE_EXECUTION_NOT_A_REAL_PLAYER_CAMPAIGN_OR_PROOF_OF_MODEL_QUALITY",
    )
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "owner-authorization.json").write_bytes(authorization)
    (output / "reference-audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    verify(output)
    return manifest


def main():
    import argparse

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--directory", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument(
        "--owner-decisions",
        type=Path,
        help="Explicit synthetic admission into a NEW corpus directory",
    )
    a = p.parse_args()
    if a.owner_decisions:
        manifest = admit(a.directory, a.owner_decisions, a.output)
        print(json.dumps({k: manifest[k] for k in ("status", "samples", "sha256")}))
        return
    report, _ = audit(a.directory)
    with a.output.open("x", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(
        json.dumps(
            {
                k: report[k]
                for k in ("status", "samples", "unique_replies", "maximum_reply_repetition")
            }
        )
    )
    if report["errors"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
