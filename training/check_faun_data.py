"""Check an admitted narrator corpus offline, independently of model/GPU readiness."""

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from training.tokenize_dataset import (
    PinnedFaunTokenizer,
    bound_cpu_report,
    encode_dataset,
    load_splits,
    messages_for,
    verify_cpu_report,
)


def check_loss_masks(encoded, token_report, ending):
    """A correct token count alone does not prove assistant-only supervision."""
    checked = 0
    for name, rows in encoded.items():
        lengths = token_report["splits"][name]["lengths"]
        if len(rows) != len(lengths):
            raise ValueError("BLOCKED_DATA: encoded row count differs")
        for row, length in zip(rows, lengths, strict=True):
            prompt, answer = length["prompt"], length["answer"]
            ids, labels, attention = row["input_ids"], row["labels"], row["attention_mask"]
            if (
                prompt < 1
                or answer <= len(ending)
                or len(ids) != prompt + answer
                or len(labels) != len(ids)
                or attention != [1] * len(ids)
                or labels[:prompt] != [-100] * prompt
                or labels[prompt:] != ids[prompt:]
                or ids[-len(ending) :] != ending
            ):
                raise ValueError("BLOCKED_DATA: loss mask or ChatML ending differs")
            checked += 1
    return checked


def corpus_summary(parts):
    """Describe provenance/holdout limits without promoting machine checks to human review."""
    ids, groups, prompts = set(), {}, {}
    replies, sentence_counts = Counter(), Counter()
    sources, outcome_counts = {}, Counter()
    human = 0
    for split, rows in parts.items():
        sources[split] = dict(Counter(r["schema_version"] for r in rows))
        for row in rows:
            identity, group = row["sample_id"], row["campaign_id"]
            if identity in ids or groups.setdefault(group, split) != split:
                raise ValueError("BLOCKED_DATA: duplicate ID or group crosses splits")
            ids.add(identity)
            prompt = hashlib.sha256(
                json.dumps(messages_for(row), ensure_ascii=False, sort_keys=True).encode()
            ).hexdigest()
            if prompt in prompts:
                raise ValueError("BLOCKED_DATA: duplicate full narrator input")
            prompts[prompt] = identity
            text = row["assistant_reply"]
            replies[text] += 1
            sentence_counts[len(re.findall(r"[.!?](?:\s|$)", text))] += 1
            human += row.get("human_reviewed") is True
            fallback = (
                "observed_hp_delta"
                if row["schema_version"] == "fireball-observed-hp-v1"
                else "OUTCOME_NOT_LABELED"
            )
            outcome_counts[row["engine_receipt"].get("outcome", fallback)] += 1
    # Reused phrasing is disclosed; it is not an independently played episode.
    return {
        "samples": len(ids),
        "splits": {name: len(rows) for name, rows in parts.items()},
        "groups": len(groups),
        "group_cross_split": 0,
        "duplicate_full_inputs": 0,
        "provenance_by_split": sources,
        "human_reviewed_samples": human,
        "unique_replies": len(replies),
        "maximum_reply_repetition": max(replies.values(), default=0),
        "approximate_sentences": dict(sorted(sentence_counts.items())),
        "outcomes": dict(outcome_counts),
        "holdout_limit": "GROUP_IDS_NOT_PROOF_OF_REAL_CAMPAIGN_GENERALIZATION",
    }


def check(config, *, tokenizer_path=None, independent=False):
    if config.get("model_family") != "faun_mistral_nemo":
        raise ValueError("This check requires the pinned Faun profile")
    if independent and tokenizer_path is None:
        raise ValueError("Independent token verification requires a local tokenizer")
    manifest, parts = load_splits(config)
    cpu = bound_cpu_report(config)
    if cpu is None:
        raise ValueError("BLOCKED_DATA: bind a CPU tokenization report first")
    for name, rows in parts.items():
        if cpu["splits"][name].get("samples") != len(rows):
            raise ValueError("BLOCKED_DATA: CPU report sample counts differ")
    report = {
        "schema": "faun-final-data-check-v1",
        "status": "INTEGRITY_PASS_TOKENIZATION_NOT_RERUN",
        "purpose": "RUSSIAN_CONFIRMED_OUTCOME_NARRATION_NOT_ACTION_PLANNER_OR_AVRAE_COMMANDS",
        "dataset_policy": manifest.get("dataset_policy", "gm-sft-v1"),
        "dataset_sha256": manifest["sha256"],
        "split_sha256": manifest["file_sha256"],
        "cpu_report_sha256": config["cpu_tokenization_report_sha256"],
        "model_id": config.get("model_id"),
        "revision": config.get("revision"),
        "chat_template_sha256": config.get("chat_template_sha256"),
        "corpus": corpus_summary(parts),
        "max_length": config["max_length"],
        "tokenization": {
            name: {
                k: value[k]
                for k in (
                    "samples",
                    "max_total",
                    "total_tokens",
                    "supervised_tokens",
                    "encoded_sha256",
                )
            }
            for name, value in cpu["splits"].items()
        },
        "tokenizer_rechecked_samples": 0,
        "independent_auto_tokenizer_samples": 0,
        "model_weights_loaded": False,
        "gpu_fit_verified": False,
        "model_quality_evaluated": False,
        "training_steps": 0,
    }
    if manifest.get("dataset_policy") == "fireball-augmented-v1":
        report["fireball_limit"] = {
            "source_observed_examples": manifest["fireball"]["accepted"],
            "russian_target_origin": "ASSISTANT_AUTHORED_NOT_HUMAN_TRANSCRIPT",
            "external_holdout_available": manifest["fireball"]["external_holdout_available"],
            "full_native_fireball_admitted": False,
        }
    if tokenizer_path is not None:
        pinned = PinnedFaunTokenizer(tokenizer_path, config)
        encoded, actual = encode_dataset(config, pinned)
        verify_cpu_report(config, actual)
        ending = pinned.backend.encode("<|im_end|>\n", add_special_tokens=False).ids
        report["tokenizer_rechecked_samples"] = check_loss_masks(encoded, actual, ending)
        report["tokenizer_file_sha256"] = pinned.fingerprint
        report["status"] = "DATA_READY_FOR_QLORA"
        if independent:
            from transformers import AutoTokenizer

            official = AutoTokenizer.from_pretrained(
                str(tokenizer_path), local_files_only=True, trust_remote_code=False
            )
            other, stats = encode_dataset(config, official)
            if other != encoded or stats["splits"] != actual["splits"]:
                raise ValueError("BLOCKED_DATA: independent AutoTokenizer differs")
            report["independent_auto_tokenizer_samples"] = check_loss_masks(other, stats, ending)
            report["status"] = "DATA_READY_INDEPENDENT_TOKEN_CHECK_PASS"
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path)
    parser.add_argument("--independent", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Choose a new report; previous checks are preserved")
    report = check(
        json.loads(args.config.read_text(encoding="utf-8")),
        tokenizer_path=args.tokenizer,
        independent=args.independent,
    )
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "status",
                    "dataset_sha256",
                    "tokenizer_rechecked_samples",
                    "independent_auto_tokenizer_samples",
                    "training_steps",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
