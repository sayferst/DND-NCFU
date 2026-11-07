"""Offline audit of proposal packs. Embedded instructions are data, never admission."""

import argparse
import hashlib
import json
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from training.annotation_v2 import DECISIONS, import_review, rows_v2
from training.inspect_archive import members
from training.jsonio import strict_json
from training.schema import validate

SPLITS = ("train", "val", "test")
PROPOSALS = {"AI_SUGGESTED", "HUMAN_REVIEW_REQUIRED"}
REQUIRED = {
    "manifest.json",
    "approved_rules_R01_R14.json",
    "blocking_questions.jsonl",
    "narrative_synthetic_pairs_40.jsonl",
    "real_game_regression_observations_5.jsonl",
    "scenarios-1000-v3-AI-proposed.xlsx",
    *(f"synthetic_actions_{s}.jsonl" for s in SPLITS),
}
FACT_REQUIREMENTS = (
    (
        "R14",
        "agreement_constraints",
        ["participants.ids", "authority", "vital_constraints", "resource_balances"],
    ),
    (
        "контейнер",
        "container_access",
        ["container.id", "container.locked", "item.id", "access_method"],
    ),
    ("похожие цели", "target_identity", ["target.id", "legal_owner", "physical_holder"]),
    (
        "Повреждённый инструмент",
        "material_condition",
        ["tool.id", "tool.durability", "materials.quantity"],
    ),
    ("R13", "death_policy", ["target.hp", "target.life", "death_rule_revision"]),
    ("Слух", "knowledge_source", ["observation.source", "observation.verification"]),
    ("ST=1", "action_cost", ["hero.st", "action.st_cost"]),
    (
        "R10",
        "overcast_policy",
        ["spell.mp_cost", "hero.mp", "payment_choice", "overcast_rule_revision"],
    ),
    ("MP=0", "known_magic_effect", ["known_spell.id", "implemented_effect", "hero.mp"]),
)


def read_pack(path):
    files = {}
    with ZipFile(path) as archive:
        if len(archive.namelist()) != len(set(archive.namelist())):
            raise ValueError("Duplicate archive member")
    for name, raw in members(path):
        basename = Path(name).name
        if basename in files:
            raise ValueError("Ambiguous duplicate basename")
        files[basename] = raw
    if not REQUIRED <= files.keys():
        raise ValueError("Missing pack files: " + ", ".join(sorted(REQUIRED - files.keys())))
    return files


def records(files, name):
    return [
        strict_json(line) for line in files[name].decode("utf-8-sig").splitlines() if line.strip()
    ]


def question_kind(text):
    for needle, kind, fields in FACT_REQUIREMENTS:
        if needle.casefold() in text.casefold():
            return kind, fields
    return "missing_structured_state", ["operation", "target.id", "resources", "check_policy"]


def audit(path, *, owner_decisions=None):
    files = read_pack(path)
    manifest = strict_json(files["manifest.json"])
    errors, warnings = [], []
    hashes = manifest.get("file_sha256", {})
    if set(hashes) != set(files) - {"manifest.json"}:
        errors.append({"code": "MANIFEST_COVERAGE"})
    for name, expected in hashes.items():
        if name not in files or hashlib.sha256(files[name]).hexdigest() != expected:
            errors.append({"code": "HASH_MISMATCH", "file": name})
    # A changed source is not interpreted further and never copied into a corpus.
    if errors:
        return {"status": "INVALID_PACK", "errors": errors, "sft_admitted": 0}, {}, {}
    owner_policy_sha = None
    if owner_decisions is not None:
        from training.owner_policy import load_policy

        _, owner_policy_sha = load_policy(
            owner_decisions, rulebook=files["approved_rules_R01_R14.json"]
        )
    baseline = {r["id"]: r for r in rows_v2()}
    split_rows = {s: records(files, f"synthetic_actions_{s}.jsonl") for s in SPLITS}
    actions = [r for rows in split_rows.values() for r in rows]
    by_id, groups, split_ids, texts = {}, {}, {}, defaultdict(set)
    fact_keys = {
        "family": "family",
        "condition_type": "condition_type",
        "review_track": "review_track",
        "context": "context",
        "items": "items",
        "skills": "skills",
        "player_message": "action",
    }
    for split, rows in split_rows.items():
        for row in rows:
            id = row.get("scenario_id")
            if id not in baseline or id in by_id:
                errors.append({"code": "INVALID_OR_DUPLICATE_ID", "id": id})
                continue
            by_id[id], split_ids[id] = row, split
            if any(row.get(k) != baseline[id][v] for k, v in fact_keys.items()):
                errors.append({"code": "SOURCE_FACTS_CHANGED", "id": id})
            if row.get("split") != split:
                errors.append({"code": "SPLIT_LABEL_MISMATCH", "id": id})
            if (
                row.get("review_status") not in PROPOSALS
                or row.get("synthetic") is not True
                or row.get("sft_admitted") is not False
            ):
                errors.append({"code": "UNVERIFIED_APPROVAL", "id": id})
            if (
                row.get("attempt_possible") not in DECISIONS
                or row.get("goal_reachable") not in DECISIONS
                or row.get("d20_required") not in ("Да", "Нет", "Неясно")
            ):
                errors.append({"code": "INVALID_LABEL", "id": id})
            family, condition, index = id.rsplit("_", 2)
            group = family + "_" + index
            prior = groups.setdefault(group, {"splits": set(), "conditions": set()})
            prior["splits"].add(split)
            prior["conditions"].add(int(condition))
            texts[" ".join(row.get("player_message", "").casefold().split())].add(split)
    if set(by_id) != set(baseline):
        errors.append({"code": "MISSING_IDS"})
    if any(len(v["splits"]) != 1 or v["conditions"] != set(range(5)) for v in groups.values()):
        errors.append({"code": "ACTION_GROUP_LEAKAGE_OR_MISSING_CONDITION"})
    if any(len(v) > 1 for v in texts.values()):
        errors.append({"code": "EXACT_ACTION_TEXT_LEAKAGE"})
    questions = records(files, "blocking_questions.jsonl")
    seen_questions, queue, grouped = set(), [], {}
    for row in questions:
        id = row.get("id")
        if id not in baseline or id in seen_questions:
            errors.append({"code": "INVALID_QUESTION_ID", "id": id})
            continue
        seen_questions.add(id)
        if (
            row.get("action") != baseline[id]["action"]
            or row.get("context") != baseline[id]["context"]
        ):
            errors.append({"code": "QUESTION_FACTS_CHANGED", "id": id})
        question_texts = row.get("questions", [])
        if not isinstance(question_texts, list) or not all(
            isinstance(q, str) for q in question_texts
        ):
            errors.append({"code": "INVALID_QUESTIONS", "id": id})
            continue
        requirements = set()
        for text in question_texts:
            kind, fields = question_kind(text)
            requirements.update(fields)
            entry = grouped.setdefault(kind, {"kind": kind, "required_fields": fields, "ids": []})
            entry["ids"].append(id)
        queue.append(
            {
                "scenario_id": id,
                "split": split_ids.get(id),
                "required_world_fields": sorted(requirements),
                "status": "NEEDS_STATE_OR_OWNER_DECISION",
                "sft_admitted": False,
            }
        )
        if by_id[id].get("blocking_questions") != question_texts:
            errors.append({"code": "QUESTION_SIDECAR_MISMATCH", "id": id})
    for id, row in by_id.items():
        if row.get("blocking_questions") and id not in seen_questions:
            errors.append({"code": "MISSING_QUESTION_SIDECAR", "id": id})
    pairs = records(files, "narrative_synthetic_pairs_40.jsonl")
    pair_ids = set()
    for row in pairs:
        id = row.get("scenario_id")
        if id not in by_id or id in pair_ids:
            errors.append({"code": "INVALID_NARRATIVE_ID", "id": id})
            continue
        pair_ids.add(id)
        if (
            row.get("synthetic") is not True
            or row.get("sft_admitted") is not False
            or row.get("review_status") not in PROPOSALS
            or row.get("benchmark_only") is not True
            or row.get("mock_engine_receipt", {}).get("provenance") != "SYNTHETIC_EXAMPLE"
        ):
            errors.append({"code": "NARRATIVE_PROVENANCE", "id": id})
        if row.get("player_message") != by_id[id]["player_message"]:
            errors.append({"code": "NARRATIVE_ACTION_CHANGED", "id": id})
        if not all(
            isinstance(row.get(k), str) and row[k].strip()
            for k in (
                "preferred_reply",
                "rejected_reply",
                "rejection_reason",
            )
        ) or row.get("preferred_reply") == row.get("rejected_reply"):
            errors.append({"code": "INVALID_PREFERENCE_PAIR", "id": id})
    observations = records(files, "real_game_regression_observations_5.jsonl")
    obs_ids = [r.get("id") for r in observations]
    if len(set(obs_ids)) != len(obs_ids):
        errors.append({"code": "DUPLICATE_OBSERVATION_ID"})
    if any(
        r.get("engine_receipt_verified") is not False or r.get("sft_admitted") is not False
        for r in observations
    ):
        errors.append({"code": "UNVERIFIED_OBSERVATION_ADMISSION"})
    imported = {}
    with tempfile.TemporaryDirectory(prefix="dnd-workbook-audit-") as folder:
        workbook = Path(folder) / "source.xlsx"
        workbook.write_bytes(files["scenarios-1000-v3-AI-proposed.xlsx"])
        try:
            imported = import_review(workbook, Path(folder) / "import")
            action_import = records(
                {"a": (Path(folder) / "import/action_labels.jsonl").read_bytes()},
                "a",
            )
            if {r["scenario_id"] for r in action_import} != set(by_id):
                errors.append({"code": "ACTION_SHEET_IDS_MISMATCH"})
            for row in action_import:
                id = row["scenario_id"]
                source = by_id.get(id, {})
                for key in (
                    "attempt_possible",
                    "goal_reachable",
                    "d20_required",
                    "outcomes",
                    "risks",
                    "consequences",
                    "review_status",
                ):
                    expected = source.get(key)
                    if key in ("attempt_possible", "goal_reachable"):
                        expected = DECISIONS.get(expected)
                    if row.get(key) != expected:
                        errors.append({"code": "WORKBOOK_JSON_MISMATCH", "id": id, "field": key})
            narrator_import = records(
                {"a": (Path(folder) / "import/narrator_reviews.jsonl").read_bytes()}, "a"
            )
            if {r["scenario_id"] for r in narrator_import} != pair_ids:
                errors.append({"code": "NARRATIVE_SHEET_IDS_MISMATCH"})
            preferred = {r["scenario_id"]: r["preferred_reply"] for r in pairs}
            for row in narrator_import:
                if (
                    row["reply"] != preferred.get(row["scenario_id"])
                    or row["review_status"] not in PROPOSALS
                ):
                    errors.append(
                        {"code": "NARRATIVE_SHEET_CONTENT_MISMATCH", "id": row["scenario_id"]}
                    )
        except (ValueError, KeyError, TypeError) as error:
            errors.append({"code": "WORKBOOK_IMPORT_FAILED", "category": type(error).__name__})
    counts = {
        "action_proposals": len(actions),
        "human_review_priority": sum(r.get("review_track") == "HUMAN_FIRST" for r in actions),
        "ai_later": sum(r.get("review_track") == "AI_LATER" for r in actions),
        "open_factual_questions": len(questions),
        "synthetic_narrative_preference_pairs": len(pairs),
        "verified_engine_receipts": 0,
        "approved_gm_sft_samples": 0,
        "real_log_QA_observations": len(observations),
    }
    for key, value in counts.items():
        if manifest.get("counts", {}).get(key) != value:
            errors.append({"code": "MANIFEST_COUNT_MISMATCH", "field": key})
    rulebook = strict_json(files["approved_rules_R01_R14.json"])
    if set(rulebook.get("rules", {})) != {f"R{n:02}" for n in range(1, 15)}:
        errors.append({"code": "RULEBOOK_IDS"})
    for key in ("outcomes", "consequences"):
        diversity = Counter(row.get(key, "") for row in actions)
        if diversity and max(diversity.values()) > len(actions) // 2:
            warnings.append(
                {
                    "code": "BOILERPLATE_TARGETS",
                    "field": key,
                    "unique": len(diversity),
                    "max_repeated": max(diversity.values()),
                }
            )
    if actions and all(r.get("attempt_possible") == "Да" for r in actions):
        warnings.append(
            {
                "code": "ONE_CLASS_ATTEMPT_POSSIBILITY",
                "note": "Review label definition; not automatically wrong",
            }
        )
    warnings.append(
        {
            "code": "SEMANTIC_SPLIT_INDEPENDENCE_NOT_PROVEN",
            "note": "Exact action grouping passes; related intents share thematic families",
        }
    )
    report = {
        "schema": "training-pack-audit-v1",
        "source_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        "status": "INVALID_PACK" if errors else "VALID_PROPOSALS_BLOCKED_DATA",
        "errors": errors,
        "warnings": warnings,
        "counts": counts,
        "split_counts": {s: len(rows) for s, rows in split_rows.items()},
        "action_groups": len(groups),
        "families": len({r.get("family") for r in actions}),
        "workbook_import": imported,
        "rulebook_status": (
            "OWNER_CONFIRMED_RUNTIME_IMPLEMENTATION_NOT_VERIFIED"
            if owner_policy_sha
            else "AWAITING_DIRECT_OWNER_CONFIRMATION"
        ),
        "owner_decisions_sha256": owner_policy_sha,
        "pair_split_counts": dict(Counter(split_ids.get(r.get("scenario_id")) for r in pairs)),
        "question_groups": [
            {**v, "ids": sorted(set(v["ids"])), "count": len(set(v["ids"]))}
            for v in grouped.values()
        ],
        "sft_status": "BLOCKED_DATA",
        "sft_admitted": 0,
        "training_steps": 0,
        "blockers": [
            "NO_VERIFIED_TRAINING_EPISODES",
            "NO_INDIVIDUAL_HUMAN_REVIEW",
            *([] if owner_policy_sha else ["RULEBOOK_CONFIRMATION_PENDING"]),
            "INCOMPLETE_WORLD_FACTS",
        ],
        "unsafe_gm_sft_samples": sum(not validate(row)[0] for row in actions + pairs),
    }
    return report, {"actions": actions, "pairs": pairs, "questions": queue}, files


def repair_question_links(path, output):
    """Reconcile only an omitted generic question; never resolve game facts."""
    files = read_pack(path)
    manifest = strict_json(files["manifest.json"])
    if set(manifest.get("file_sha256", {})) != set(files) - {"manifest.json"} or any(
        hashlib.sha256(files[n]).hexdigest() != sha for n, sha in manifest["file_sha256"].items()
    ):
        raise ValueError("Source integrity failed; repair forbidden")
    questions = {r["id"]: r["questions"] for r in records(files, "blocking_questions.jsonl")}
    repaired = []
    for split in SPLITS:
        name = f"synthetic_actions_{split}.jsonl"
        rows = records(files, name)
        for row in rows:
            expected = questions.get(row["scenario_id"])
            if expected is None or row.get("blocking_questions") == expected:
                continue
            if (
                row.get("blocking_questions") != []
                or expected != ["Не хватает параметров для окончательного решения исхода/проверки."]
                or row.get("review_status") != "HUMAN_REVIEW_REQUIRED"
                or row.get("synthetic") is not True
                or row.get("sft_admitted") is not False
            ):
                raise ValueError("Conflicting substantive questions require review")
            row["blocking_questions"] = expected
            repaired.append(row["scenario_id"])
        files[name] = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode()
    files["original-v3-validation-report.json"] = files.get("VALIDATION_REPORT.json", b"{}")
    files["VALIDATION_REPORT.json"] = json.dumps(
        {
            "status": "QUESTION_LINKS_REPAIRED_REAUDIT_REQUIRED",
            "repair_count": len(repaired),
            "sft_admitted": 0,
            "human_approval_created": False,
        },
        indent=2,
    ).encode()
    manifest["repair_provenance"] = {
        "source_archive_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        "kind": "COPY_EXISTING_GENERIC_SIDECAR_QUESTION",
        "scenario_ids": repaired,
        "facts_invented": False,
        "human_approval_created": False,
    }
    manifest["file_sha256"] = {
        n: hashlib.sha256(raw).hexdigest() for n, raw in files.items() if n != "manifest.json"
    }
    files["manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2).encode()
    with ZipFile(output, "x", ZIP_DEFLATED) as archive:
        for name, raw in files.items():
            archive.writestr("DND_NCFU_reviewed_v3_1/" + name, raw)
    return repaired


def prepare_review(path, output, *, repair_links=False, owner_decisions=None):
    output = Path(output)
    if output.exists():
        raise FileExistsError("Choose a new private review directory")
    report, data, files = audit(path, owner_decisions=owner_decisions)
    output.mkdir(parents=True, exist_ok=False)
    if repair_links:
        repaired_path = output / "proposals-v3-1-question-links.zip"
        ids = repair_question_links(path, repaired_path)
        original_report = report
        report, data, files = audit(repaired_path, owner_decisions=owner_decisions)
        report["repairs"] = {"generic_question_links": len(ids)}
        (output / "original-audit.json").write_text(
            json.dumps(original_report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    (output / "audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if report["status"] == "INVALID_PACK":
        return report
    for name, rows in data.items():
        with (output / (name + "-review.jsonl")).open("x", encoding="utf-8") as stream:
            for row in rows:
                # Preserve source claims but never adopt their claimed approval.
                staged = dict(row)
                staged["rulebook_status"] = report["rulebook_status"]
                staged["sft_admitted"] = False
                stream.write(json.dumps(staged, ensure_ascii=False) + "\n")
    (output / "scenarios-v3-original-copy.xlsx").write_bytes(
        files["scenarios-1000-v3-AI-proposed.xlsx"]
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--repair-question-links", action="store_true")
    parser.add_argument("--owner-decisions", type=Path)
    args = parser.parse_args()
    report = prepare_review(
        args.archive,
        args.output,
        repair_links=args.repair_question_links,
        owner_decisions=args.owner_decisions,
    )
    print(json.dumps({k: report[k] for k in ("status", "sft_admitted")}, ensure_ascii=False))
    if report["status"] == "INVALID_PACK":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
