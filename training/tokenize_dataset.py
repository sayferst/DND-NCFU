"""CPU-only corpus checks using the same encoder as training, before weight loading."""

import argparse
import hashlib
import json
from pathlib import Path

from training.fetch_faun_tokenizer import HASHES
from training.model_profiles import template_arguments

FAUN_TEMPLATE_SHA = "99000004eb5936e12e2cb9ba6449b7d194155b6439e8686f658b15cc71938b0b"
CONTROL_TOKENS = ("<|im_start|>", "<|im_end|>", "<s>", "</s>")


def load_splits(config):
    root = Path(config["dataset"])
    if config.get("dataset_policy") == "fireball-augmented-v1":
        from training.fireball import verify

        manifest, splits = verify(root)
    elif config.get("dataset_policy") == "synthetic-pilot-v1":
        from training.synthetic_corpus import verify

        manifest, splits = verify(root)
    elif config.get("dataset_policy") == "grounded-synthetic-v1":
        from training.grounded_validation import verify

        manifest, splits = verify(root)
    else:
        from training.evaluate_faun import holdout

        manifest, _ = holdout(root)
        splits = {
            s: [
                json.loads(line)
                for line in (root / (s + ".jsonl")).read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            for s in ("train", "val", "test")
        }
    if config.get("dataset_sha256") != manifest.get("sha256"):
        raise ValueError("BLOCKED_DATA: config is not bound to this corpus")
    if any(not rows for rows in splits.values()):
        raise ValueError("BLOCKED_DATA: train, validation and test must all be nonempty")
    return manifest, splits


def messages_for(row):
    if row.get("schema_version") == "fireball-observed-hp-v1":
        from training.grounded_prompt import SYSTEM

        return [
            {"role": "system", "content": SYSTEM},
            {
                "role": "user",
                "content": json.dumps(
                    {k: row[k] for k in ("public_context", "player_message", "engine_receipt")},
                    ensure_ascii=False,
                ),
            },
        ]
    if row.get("schema_version") == "gm-grounded-synthetic-v1":
        from training.grounded_prompt import messages

        return messages(row)
    return [
        {
            "role": "user",
            "content": json.dumps(
                {
                    "context": row["public_context"],
                    "player": row["player_message"],
                    "receipt": row["engine_receipt"],
                },
                ensure_ascii=False,
            ),
        }
    ]


def encode_rows(tokenizer, rows, config):
    encoded, lengths, oversized = [], [], []
    for row in rows:
        messages = messages_for(row)
        if any(
            token in "".join(message["content"] for message in messages) + row["assistant_reply"]
            for token in CONTROL_TOKENS
        ):
            raise ValueError("BLOCKED_DATA: embedded chat control token")
        prefix = tokenizer.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_dict=False,
            **template_arguments(config),
        )
        if config.get("model_family") == "faun_mistral_nemo":
            complete = tokenizer.apply_chat_template(
                messages + [{"role": "assistant", "content": row["assistant_reply"]}],
                tokenize=True,
                add_generation_prompt=False,
                return_dict=False,
            )
            if complete[: len(prefix)] != prefix:
                raise ValueError("Faun chat template does not preserve the generation prefix")
            answer = complete[len(prefix) :]
        else:
            answer = tokenizer(row["assistant_reply"], add_special_tokens=False)["input_ids"] + [
                tokenizer.eos_token_id
            ]
        if not answer:
            raise ValueError("BLOCKED_DATA: empty supervised answer")
        length = len(prefix) + len(answer)
        lengths.append(
            {"id": row["sample_id"], "prompt": len(prefix), "answer": len(answer), "total": length}
        )
        if length > config["max_length"]:
            oversized.append(row["sample_id"])
        encoded.append(
            {
                "input_ids": prefix + answer,
                "attention_mask": [1] * length,
                "labels": [-100] * len(prefix) + answer,
            }
        )
    if oversized:
        raise ValueError(
            "BLOCKED_DATA: overlength examples; no silent dropping: " + ", ".join(oversized)
        )
    return encoded, lengths


class PinnedFaunTokenizer:
    """Lightweight tokenizer.json backend; render only the hash-pinned ChatML template.

    This deliberately implements that single public template verbatim, without
    executing Jinja supplied by a dataset. GPU training also checks this backend's
    IDs against AutoTokenizer before loading weights.
    """

    def __init__(self, root, config):
        from tokenizers import Tokenizer

        root = Path(root)
        if config.get("model_family") != "faun_mistral_nemo":
            raise ValueError("Lightweight CPU tokenizer supports the pinned Faun profile only")
        raw = (root / "chat_template.jinja").read_bytes()
        if (
            hashlib.sha256(raw).hexdigest() != FAUN_TEMPLATE_SHA
            or config.get("chat_template_sha256") != FAUN_TEMPLATE_SHA
        ):
            raise ValueError("BLOCKED_MODEL: pinned Faun ChatML template differs")
        for name, expected in HASHES.items():
            if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
                raise ValueError("BLOCKED_MODEL: pinned tokenizer metadata changed: " + name)
        self.backend = Tokenizer.from_file(str(root / "tokenizer.json"))
        self.fingerprint = {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in ("tokenizer.json", "chat_template.jinja")
        }

    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt, return_dict=False):
        text = "".join(
            "<|im_start|>" + m["role"] + "\n" + m["content"] + "<|im_end|>\n" for m in messages
        )
        # Transformers renders this template with trim_blocks=True/lstrip_blocks=True.
        if add_generation_prompt:
            text += "<|im_start|>assistant\n"
        return self.backend.encode(text, add_special_tokens=False).ids if tokenize else text


def encode_dataset(config, tokenizer):
    manifest, splits = load_splits(config)
    encoded, stats = {}, {}
    for split, rows in splits.items():
        encoded[split], lengths = encode_rows(tokenizer, rows, config)
        stats[split] = {
            "samples": len(rows),
            "max_total": max(r["total"] for r in lengths),
            "total_tokens": sum(r["total"] for r in lengths),
            "supervised_tokens": sum(r["answer"] for r in lengths),
            "lengths": lengths,
            "encoded_sha256": hashlib.sha256(
                json.dumps(encoded[split], sort_keys=True).encode()
            ).hexdigest(),
        }
    return encoded, {
        "schema": "faun-cpu-tokenization-v1",
        "status": "TOKENIZATION_READY_PILOT_ONLY"
        if manifest.get("status") == "PILOT_READY"
        else "TOKENIZATION_READY",
        "dataset_sha256": manifest["sha256"],
        "max_length": config["max_length"],
        "splits": stats,
        "dropped_samples": 0,
        "training_steps": 0,
        "model_weights_loaded": False,
        "gpu_fit_verified": False,
        "prompt_contract": "grounded_relevant_facts_v1"
        if manifest.get("dataset_policy") == "grounded-synthetic-v1"
        else "context_player_receipt_v1",
    }


def bound_cpu_report(config):
    """Check a declared CPU report even when weights, CUDA and tokenizer are absent."""
    path = config.get("cpu_tokenization_report")
    if not path:
        return None
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != config.get("cpu_tokenization_report_sha256"):
        raise ValueError("BLOCKED_DATA: CPU report changed")
    recorded = json.loads(raw)
    if (
        recorded.get("schema") != "faun-cpu-tokenization-v1"
        or recorded.get("status") not in {"TOKENIZATION_READY", "TOKENIZATION_READY_PILOT_ONLY"}
        or recorded.get("dataset_sha256") != config.get("dataset_sha256")
        or recorded.get("max_length") != config.get("max_length")
        or recorded.get("dropped_samples") != 0
        or set(recorded.get("splits", {})) != {"train", "val", "test"}
    ):
        raise ValueError("BLOCKED_DATA: CPU report is not bound to this corpus/config")
    return recorded


def verify_cpu_report(config, report):
    recorded = bound_cpu_report(config)
    if recorded is None:
        return
    if (
        recorded.get("dataset_sha256") != report["dataset_sha256"]
        or recorded.get("max_length") != report["max_length"]
        or recorded.get("splits") != report["splits"]
    ):
        raise ValueError("BLOCKED_DATA: GPU tokenizer differs from CPU preflight")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True, type=Path)
    p.add_argument("--tokenizer", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args()
    config = json.loads(a.config.read_text(encoding="utf-8"))
    tokenizer = PinnedFaunTokenizer(a.tokenizer, config)
    _, report = encode_dataset(config, tokenizer)
    report["tokenizer_file_sha256"] = tokenizer.fingerprint
    report["backend"] = "tokenizers_tokenizer_json_pinned_chatml"
    with a.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps({k: report[k] for k in ("status", "dropped_samples", "training_steps")}))


if __name__ == "__main__":
    main()
