"""Pinned Faun last-assistant supervision, including multi-turn prefixes, without weights."""

import argparse
import hashlib
import json
from pathlib import Path

from training.faun_v5.backend import FAUN_TEMPLATE_SHA, PinnedFaunTokenizer
from training.fetch_faun_tokenizer import HASHES


def encode(tokenizer, messages, max_length=4000):
    if not isinstance(messages, list) or len(messages) < 3 or len(messages) % 2 != 1:
        raise ValueError("Malformed conversation")
    if any(not isinstance(m.get("content"), str) or not m["content"].strip() for m in messages):
        raise ValueError("Empty or non-text message")
    if any(
        t in m["content"] for m in messages for t in ("<|im_start|>", "<|im_end|>", "<s>", "</s>")
    ):
        raise ValueError("Chat control token in content")
    if messages[0]["role"] != "system" or messages[-1]["role"] != "assistant":
        raise ValueError("Role order")
    if any(m["role"] != ("user" if i % 2 else "assistant") for i, m in enumerate(messages[1:], 1)):
        raise ValueError("Conversation must alternate user/assistant")
    prefix = list(
        tokenizer.apply_chat_template(
            messages[:-1], tokenize=True, add_generation_prompt=True, return_dict=False
        )
    )
    full = list(
        tokenizer.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=False, return_dict=False
        )
    )
    if full[: len(prefix)] != prefix:
        raise ValueError("Chat template prefix mismatch")
    if len(full) > max_length:
        raise ValueError("Overlength: " + str(len(full)))
    if len(full) <= len(prefix):
        raise ValueError("Empty supervised answer")
    labels = [-100] * len(prefix) + full[len(prefix) :]
    return {"input_ids": full, "attention_mask": [1] * len(full), "labels": labels}, len(prefix)


def scan(dataset, tokenizer_root, output, *, independent=False):
    cfg = {"model_family": "faun_mistral_nemo", "chat_template_sha256": FAUN_TEMPLATE_SHA}
    tokenizer = PinnedFaunTokenizer(tokenizer_root, cfg)
    auto = None
    if independent:
        from transformers import AutoTokenizer

        auto = AutoTokenizer.from_pretrained(
            str(tokenizer_root), local_files_only=True, trust_remote_code=False
        )
    stats = {}
    failures = []
    total = 0
    failure_count = 0
    bindings = {}
    for split in ("train", "val", "test", "ood_test_only"):
        source = Path(dataset) / (split + ".jsonl")
        if not source.is_file():
            continue
        bindings[source.name] = hashlib.sha256(source.read_bytes()).hexdigest()
        encoded_hash = hashlib.sha256(b"[")
        lengths = []
        targets = []
        masks = 0
        independent_count = 0
        with (Path(dataset) / (split + ".jsonl")).open(encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                try:
                    encoded, prefix = encode(tokenizer, row["messages"])
                    if encoded["input_ids"][-2:] != [131072, 1010]:
                        raise ValueError("ChatML ending")
                    if (
                        encoded["labels"][:prefix] != [-100] * prefix
                        or encoded["labels"][prefix:] != encoded["input_ids"][prefix:]
                    ):
                        raise ValueError("Mask mismatch")
                    if auto is not None:
                        other, otherprefix = encode(auto, row["messages"])
                        if other != encoded or otherprefix != prefix:
                            raise ValueError("Independent tokenizer mismatch")
                        independent_count += 1
                    if masks:
                        encoded_hash.update(b", ")
                    encoded_hash.update(
                        json.dumps(encoded, sort_keys=True, ensure_ascii=False).encode()
                    )
                    lengths.append(len(encoded["input_ids"]))
                    targets.append(len(encoded["input_ids"]) - prefix)
                    masks += 1
                except ValueError as exc:
                    failure_count += 1
                    if len(failures) < 30:
                        failures.append({"id": row["id"], "error": str(exc)})
                total += 1
                if total % 5000 == 0:
                    print(json.dumps({"tokenized": total, "failures": failure_count}), flush=True)

        def dist(values):
            values = sorted(values)
            return (
                {
                    str(p): values[min(len(values) - 1, int((len(values) - 1) * p / 100))]
                    for p in (0, 50, 75, 95, 99, 100)
                }
                if values
                else {}
            )

        encoded_hash.update(b"]")
        stats[split] = {
            "encoded_sha256": encoded_hash.hexdigest(),
            "samples": masks,
            "independent": independent_count,
            "total_tokens": sum(lengths),
            "supervised_tokens": sum(targets),
            "sequence": dist(lengths),
            "answer": dist(targets),
            "answer_at_most_64": sum(n <= 64 for n in targets),
            "answer_at_least_200": sum(n >= 200 for n in targets),
        }
    report = {
        "schema": "faun-v5-cpu-tokenization-v1",
        "status": "PASS" if failure_count == 0 else "FAIL",
        "failure_count": failure_count,
        "bindings": bindings,
        "splits": stats,
        "max_length": 4000,
        "failures": failures,
        "silent_truncation": 0,
        "training_steps": 0,
        "faun_weights_loaded": False,
        "tokenizer_sha256": HASHES,
    }
    Path(output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset", "tokenizer", "output"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--independent", action="store_true")
    a = p.parse_args()
    r = scan(a.dataset, a.tokenizer, a.output, independent=a.independent)
    print(json.dumps({"status": r["status"], "failures": r["failures"]}))


if __name__ == "__main__":
    main()
