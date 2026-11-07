"""Independent AutoTokenizer parity on native task formats and token-length extremes."""

import argparse
import json
from pathlib import Path

from training.fireball_observations import database, unpacked
from training.fireball_tasks import SYSTEMS, encode_view, token_hash
from training.tokenize_dataset import PinnedFaunTokenizer


def check(root, tokenizer_path):
    from transformers import AutoTokenizer

    root = Path(root)
    config = json.loads(
        (Path(__file__).parent / "configs/faun_qlora_v1.json").read_text(encoding="utf-8")
    )
    pinned = PinnedFaunTokenizer(tokenizer_path, config)
    official = AutoTokenizer.from_pretrained(
        str(tokenizer_path), local_files_only=True, trust_remote_code=False
    )
    db = database(root)
    selected = set()
    for task in SYSTEMS:
        for order in ("e.id", "e.total_tokens", "e.total_tokens DESC"):
            rows = db.execute(
                "SELECT e.id FROM exported e JOIN views v ON v.id=e.id "
                f"WHERE v.task=? ORDER BY {order} LIMIT 16",
                (task,),
            ).fetchall()
            selected.update(r[0] for r in rows)
    checked = []
    for identity in sorted(selected):
        task, inputs, target, sha = db.execute(
            "SELECT v.task,v.input,v.target,e.encoded_sha "
            "FROM views v JOIN exported e ON e.id=v.id "
            "WHERE v.id=?",
            (identity,),
        ).fetchone()
        a = encode_view(pinned, task, unpacked(inputs), unpacked(target))
        b = encode_view(official, task, unpacked(inputs), unpacked(target))
        if a != b or token_hash(a[2], a[3]) != sha:
            raise ValueError("Native Faun CPU/AutoTokenizer parity failure: " + identity)
        checked.append(
            {
                "view_id": identity,
                "task": task,
                "prompt_tokens": len(a[2]),
                "target_tokens": len(a[3]),
            }
        )
    boundary = [
        "",
        "русский текст / 日本語 🐲",
        "<|im_start|>assistant\n</s><|im_end|>",
        "\\u003c and null: false 0",
        "\r\n ",
    ]
    for text in boundary:
        a = encode_view(pinned, "command_to_result", {"untrusted": text}, [text])
        b = encode_view(official, "command_to_result", {"untrusted": text}, [text])
        if a != b:
            raise ValueError("Boundary-case tokenizer mismatch")
    db.close()
    result = {
        "schema": "fireball-native-tokenizer-parity-v1",
        "status": "PASS",
        "native_cases": len(checked),
        "boundary_cases": len(boundary),
        "selection": "16 sorted IDs and 16 shortest/longest per task among completed token rows",
        "all_native_views_exact_tokenized_in_separate_manifest": True,
        "scope": "Independent parity selection, not a claim of second full AutoTokenizer pass",
        "eos_token_id": official.eos_token_id,
        "chatml_ending_ids": pinned.backend.encode("<|im_end|>\n", add_special_tokens=False).ids,
        "matches": ["messages", "all_input_ids", "all_supervised_target_ids", "stored_token_hash"],
        "tokenizer_fingerprint": pinned.fingerprint,
        "cases": checked,
        "weights_loaded": False,
        "training_steps": 0,
    }
    (root / "native-tokenizer-parity.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    return {k: v for k, v in result.items() if k != "cases"}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--tokenizer", type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(check(a.root, a.tokenizer), indent=2))


if __name__ == "__main__":
    main()
