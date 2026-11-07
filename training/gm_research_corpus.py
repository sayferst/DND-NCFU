"""Portable, screened native-language GM corpus; explicitly blocked from gradient updates."""

import argparse
import gzip
import json
from collections import Counter, defaultdict
from pathlib import Path

from training.fireball_observations import dumps
from training.gm_candidate_audit import file_digest, fingerprint, native_messages, quality_flags

POLICY = "source-gm-research-v1"
STATUS = "SOURCE_RESEARCH_ONLY_TRANSLATION_AND_REVIEW_PENDING"
SCHEMA = "gm-source-research-v1"


def iter_cases(path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            yield json.loads(line)


def binding_hash(files):
    return fingerprint({"policy": POLICY, "files": files})


def export(cases, audit_root, output, *, max_length=2048):
    cases, audit_root, output = Path(cases), Path(audit_root), Path(output)
    audit = json.loads((audit_root / "report.json").read_text(encoding="utf-8"))
    if audit.get("source_cases_sha256") != file_digest(cases):
        raise ValueError("Native audit is not bound to this candidate snapshot")
    if audit.get("independent_auto_tokenizer_samples") != audit.get("rows"):
        raise ValueError("Complete independent native tokenization required")
    checks = {r["id"]: r for r in iter_cases(audit_root / "audit-ledger.jsonl.gz")}
    prompts, targets = defaultdict(set), defaultdict(set)
    for row in iter_cases(cases):
        prompts[fingerprint(native_messages(row))].add(row["split"])
        if row["source"] != "PROJECT_REFERENCE":
            targets[fingerprint(row["target"])].add(row["split"])
    output.mkdir(parents=True, exist_ok=False)
    streams = {
        s: gzip.open(output / (s + ".jsonl.gz"), "wt", encoding="utf-8")
        for s in ("train", "val", "test")
    }
    sources, counts, reasons, languages = Counter(), Counter(), Counter(), Counter()
    domains, groups, ids, seen_prompts = defaultdict(Counter), {}, set(), set()
    tokens, supervised = Counter(), Counter()
    try:
        with gzip.open(output / "dispositions.jsonl.gz", "wt", encoding="utf-8") as ledger:
            for case in iter_cases(cases):
                check = checks.pop(case["id"])
                why = set(check["review_reasons"]) | set(quality_flags(case))
                if check["total_tokens"] > max_length:
                    why.add("OVER_PRIMARY_PROFILE_RETAINED_IN_SOURCE_SNAPSHOT")
                prompt_hash = fingerprint(native_messages(case))
                if len(prompts[prompt_hash]) > 1:
                    why.add("IDENTICAL_PROMPT_CROSSES_SOURCE_FOLDS")
                if (
                    case["source"] != "PROJECT_REFERENCE"
                    and len(targets[fingerprint(case["target"])]) > 1
                ):
                    why.add("IDENTICAL_SOURCE_REPLY_CROSSES_FOLDS")
                if prompt_hash in seen_prompts:
                    why.add("DUPLICATE_MODEL_INPUT_RETAINED_OUTSIDE_PRIMARY")
                if not why:
                    key, fold, group = case["id"], case["split"], case["group_id"]
                    if key in ids or groups.setdefault(group, fold) != fold:
                        raise ValueError("Source group or candidate identity collision")
                    ids.add(key)
                    seen_prompts.add(prompt_hash)
                    row = {
                        "schema_version": SCHEMA,
                        "sample_id": key,
                        "campaign_id": group,
                        "language": case["provenance"]["source_language"],
                        "source": case["source"],
                        "messages": native_messages(case),
                        "assistant_reply": case["target"],
                        "source_case_sha256": fingerprint(case),
                        "source_case": case,
                        "human_reviewed": False,
                        "train_admitted": False,
                    }
                    streams[fold].write(dumps(row) + "\n")
                    counts[fold] += 1
                    sources[case["source"]] += 1
                    languages[row["language"]] += 1
                    tokens[fold] += check["total_tokens"]
                    supervised[fold] += check["assistant_tokens"]
                    for domain, evidence in case["mechanics_evidence"].items():
                        domains[domain][case["source"] + ":" + evidence] += 1
                reasons.update(why)
                ledger.write(
                    dumps(
                        {
                            "id": case["id"],
                            "in_native_research_primary": not why,
                            "reasons": sorted(why),
                            "original_preserved": True,
                            "train_admitted": False,
                        }
                    )
                    + "\n"
                )
    finally:
        for stream in streams.values():
            stream.close()
    if checks or any(counts[s] == 0 for s in streams):
        raise ValueError("Incomplete audit coverage or empty split")
    files = {s: file_digest(output / (s + ".jsonl.gz")) for s in streams}
    manifest = {
        "schema": SCHEMA,
        "dataset_policy": POLICY,
        "status": STATUS,
        "sha256": binding_hash(files),
        "file_sha256": files,
        "file_names": {s: s + ".jsonl.gz" for s in streams},
        "source_cases_sha256": file_digest(cases),
        "native_audit_sha256": file_digest(audit_root / "report.json"),
        "dispositions_sha256": file_digest(output / "dispositions.jsonl.gz"),
        "samples": len(ids),
        "splits": dict(counts),
        "source_counts": dict(sources),
        "native_language_counts": dict(languages),
        "max_length": max_length,
        "tokens_by_split": dict(tokens),
        "assistant_tokens_by_split": dict(supervised),
        "groups": len(groups),
        "group_cross_split": 0,
        "duplicate_full_model_inputs": 0,
        "source_reply_hashes_cross_split": 0,
        "review_reasons": dict(reasons),
        "mechanics_context_evidence": domains,
        "bilingual_complete": False,
        "human_reviewed": 0,
        "train_admitted": 0,
        "training_steps": 0,
        "gpu_fit_verified": False,
        "required_gates": [
            "COMPLETE_RU_EN_VERSIONS",
            "MEANING_AND_RULE_COMPATIBILITY_REVIEW",
            "OWNER_SAMPLE_REVIEW",
            "RECHECK_TRANSLATED_TOKEN_LENGTHS_AND_MASKS",
            "NEW_HASH_BOUND_TRAINING_RELEASE",
        ],
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    verify(output)
    return manifest


def verify(root):
    root = Path(root)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("dataset_policy") != POLICY or manifest.get("status") != STATUS:
        raise ValueError("This verifier accepts the explicit research corpus only")
    if (
        manifest.get("bilingual_complete") is not False
        or manifest.get("human_reviewed") != 0
        or manifest.get("train_admitted") != 0
        or manifest.get("training_steps") != 0
    ):
        raise ValueError("Research metadata cannot imply bilingual or training approval")
    if manifest.get("sha256") != binding_hash(manifest.get("file_sha256", {})):
        raise ValueError("Research corpus content binding changed")
    groups, ids, prompts, sources, languages, splits = {}, set(), set(), Counter(), Counter(), {}
    for fold in ("train", "val", "test"):
        name = manifest["file_names"][fold]
        if name != fold + ".jsonl.gz" or file_digest(root / name) != manifest["file_sha256"][fold]:
            raise ValueError("Research split bytes changed")
        rows = []
        for row in iter_cases(root / name):
            case = row["source_case"]
            prompt = fingerprint(row["messages"])
            if (
                row.get("schema_version") != SCHEMA
                or row.get("train_admitted") is not False
                or row.get("human_reviewed") is not False
                or case["split"] != fold
                or row["sample_id"] != case["id"]
                or row["sample_id"] in ids
                or row["campaign_id"] != case["group_id"]
                or row["source"] != case["source"]
                or row["language"] != case["provenance"]["source_language"]
                or groups.setdefault(case["group_id"], fold) != fold
                or prompt in prompts
                or row["messages"] != native_messages(case)
                or row["assistant_reply"] != case["target"]
                or fingerprint(case) != row["source_case_sha256"]
                or quality_flags(case)
            ):
                raise ValueError("Invalid research row, source binding, duplicate or split")
            ids.add(row["sample_id"])
            prompts.add(prompt)
            sources[row["source"]] += 1
            languages[row["language"]] += 1
            rows.append(row)
        splits[fold] = rows
    if (
        len(ids) != manifest["samples"]
        or dict(sources) != manifest["source_counts"]
        or dict(languages) != manifest["native_language_counts"]
        or {k: len(v) for k, v in splits.items()} != manifest["splits"]
    ):
        raise ValueError("Research manifest counts differ")
    return manifest, splits


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    b = sub.add_parser("export")
    b.add_argument("--cases", type=Path, required=True)
    b.add_argument("--audit", type=Path, required=True)
    b.add_argument("--output", type=Path, required=True)
    b.add_argument("--max-length", type=int, default=2048)
    v = sub.add_parser("verify")
    v.add_argument("--directory", type=Path, required=True)
    a = p.parse_args()
    result = (
        export(a.cases, a.audit, a.output, max_length=a.max_length)
        if a.command == "export"
        else verify(a.directory)[0]
    )
    print(json.dumps({k: result[k] for k in ("status", "samples", "training_steps")}))


if __name__ == "__main__":
    main()
