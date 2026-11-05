"""Stream the actual training encoder and loss masks; never approve research data."""

import argparse
import hashlib
import json
from pathlib import Path

from training.check_faun_data import check_loss_masks
from training.gm_candidate_audit import file_digest
from training.gm_research_corpus import POLICY, verify
from training.tokenize_dataset import FAUN_TEMPLATE_SHA, PinnedFaunTokenizer, encode_rows
from training.train_lora import preflight


def check(directory, tokenizer_path, native_audit, output):
    directory, native_audit, output = Path(directory), Path(native_audit), Path(output)
    manifest, splits = verify(directory)
    proof = json.loads(native_audit.read_text(encoding="utf-8"))
    if (
        file_digest(native_audit) != manifest["native_audit_sha256"]
        or proof.get("source_cases_sha256") != manifest["source_cases_sha256"]
        or proof.get("independent_auto_tokenizer_samples") != proof.get("rows")
    ):
        raise ValueError("Complete independent native tokenizer proof differs")
    config = {
        "model_family": "faun_mistral_nemo",
        "chat_template_sha256": FAUN_TEMPLATE_SHA,
        "max_length": manifest["max_length"],
    }
    tokenizer = PinnedFaunTokenizer(tokenizer_path, config)
    stats, checked = {}, 0
    for split, rows in splits.items():
        encoded_hash = hashlib.sha256(b"[")
        lengths, maximum, total, supervised, first = 0, 0, 0, 0, True
        for start in range(0, len(rows), 64):
            encoded, measures = encode_rows(tokenizer, rows[start : start + 64], config)
            checked += check_loss_masks(
                {split: encoded}, {"splits": {split: {"lengths": measures}}}, [131072, 1010]
            )
            for row, length in zip(encoded, measures, strict=True):
                if not first:
                    encoded_hash.update(b", ")
                encoded_hash.update(json.dumps(row, sort_keys=True).encode())
                first = False
                lengths += 1
                maximum = max(maximum, length["total"])
                total += length["total"]
                supervised += length["answer"]
        encoded_hash.update(b"]")
        if (
            total != manifest["tokens_by_split"][split]
            or supervised != manifest["assistant_tokens_by_split"][split]
        ):
            raise ValueError("Published source lengths differ from actual training encoder")
        stats[split] = {
            "samples": lengths,
            "max_total": maximum,
            "total_tokens": total,
            "supervised_tokens": supervised,
            "encoded_sha256": encoded_hash.hexdigest(),
        }
        print(json.dumps({"split": split, "actual_loss_masks_verified": lengths}), flush=True)
    gate = preflight(
        {
            "dataset": str(directory),
            "model_path": "__not_loaded__",
            "dataset_policy": POLICY,
            "dataset_sha256": manifest["sha256"],
        }
    )
    if not gate.startswith("BLOCKED_DATA: source research corpus"):
        raise ValueError("Research corpus unexpectedly bypasses the training admission gate")
    report = {
        "schema": "gm-research-actual-encoder-check-v1",
        "status": "STRUCTURAL_PASS_TRAINING_BLOCKED",
        "dataset_sha256": manifest["sha256"],
        "file_sha256": manifest["file_sha256"],
        "native_audit_sha256": file_digest(native_audit),
        "independent_source_tokenizer_samples_in_bound_audit": proof["rows"],
        "actual_loss_masks_verified": checked,
        "splits": stats,
        "silent_truncation": 0,
        "dropped_samples": 0,
        "train_admitted": 0,
        "meaning_or_human_approval": False,
        "training_preflight": gate,
        "training_steps": 0,
        "faun_weights_loaded": False,
        "gpu_fit_verified": False,
    }
    with output.open("x", encoding="utf-8") as f:
        f.write(json.dumps(report, indent=2) + "\n")
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--directory", type=Path, required=True)
    p.add_argument("--tokenizer", type=Path, required=True)
    p.add_argument("--native-audit", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    result = check(a.directory, a.tokenizer, a.native_audit, a.output)
    print(
        json.dumps(
            {k: result[k] for k in ("status", "actual_loss_masks_verified", "training_steps")}
        )
    )


if __name__ == "__main__":
    main()
