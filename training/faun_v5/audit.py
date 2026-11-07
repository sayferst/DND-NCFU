"""Measure source data without executing supplied generators or accepting claimed audits."""

import argparse
import collections
import hashlib
import json
import re
from pathlib import Path


def normalized(text):
    text = re.sub(r"\d+", "<N>", text.casefold())
    text = re.sub(r"[\W_]+", " ", text)
    return text.strip()


def audit(root, output):
    root, output = Path(root), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    claimed = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    hashes = {}
    for name, expected in claimed["sha256"].items():
        path = Path(name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Unsafe manifest path")
        actual = hashlib.sha256((root / path).read_bytes()).hexdigest()
        hashes[name] = {"expected": expected, "actual": actual, "match": actual == expected}
    counts, tasks, layers, answers, prefixes, suffixes = [collections.Counter() for _ in range(6)]
    groups, prompts, skeletons = [collections.defaultdict(set) for _ in range(3)]
    ids = set()
    lengths, multiturn = [], 0
    for split in ("train", "val", "test"):
        with (root / (split + ".jsonl")).open(encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                if row["id"] in ids:
                    raise ValueError("Duplicate ID")
                ids.add(row["id"])
                counts[split] += 1
                tasks[row["task"]] += 1
                layers[row["layer"]] += 1
                groups[row["group_id"]].add(split)
                messages = row["messages"]
                if messages[0]["role"] != "system" or messages[-1]["role"] != "assistant":
                    raise ValueError("Invalid roles")
                answer = messages[-1]["content"]
                prompt = json.dumps(messages[:-1], ensure_ascii=False, sort_keys=True)
                prompts[hashlib.sha256(prompt.encode()).hexdigest()].add(split)
                skeletons[hashlib.sha256(normalized(answer).encode()).hexdigest()].add(split)
                answers[answer] += 1
                words = answer.split()
                prefixes[" ".join(words[:8])] += 1
                suffixes[" ".join(words[-8:])] += 1
                lengths.append(len(answer))
                multiturn += len(messages) > 3
    report = {
        "status": "SOURCE_MEASURED_NOT_QUALITY_APPROVED",
        "splits": dict(counts),
        "tasks": dict(tasks),
        "layers": dict(layers),
        "source_hash_checks": hashes,
        "all_claimed_hashes_match": all(v["match"] for v in hashes.values()),
        "groups": len(groups),
        "groups_crossing_folds": sum(len(v) > 1 for v in groups.values()),
        "exact_prompt_hashes_crossing_folds": sum(len(v) > 1 for v in prompts.values()),
        "normalized_answer_shapes_crossing_folds": sum(len(v) > 1 for v in skeletons.values()),
        "unique_answers": len(answers),
        "max_exact_answer_repetition": max(answers.values()),
        "top_prefixes": prefixes.most_common(20),
        "top_suffixes": suffixes.most_common(20),
        "multiturn_rows": multiturn,
        "answer_characters": {
            str(p): sorted(lengths)[min(len(lengths) - 1, int((len(lengths) - 1) * p / 100))]
            for p in (0, 50, 75, 95, 99, 100)
        },
        "normalization_limit": (
            "Numbers and punctuation only; not semantic or narrative-family equivalence."
        ),
        "training_steps": 0,
    }
    (output / "v41_baseline.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    r = audit(a.source, a.output)
    print(
        json.dumps(
            {
                k: r[k]
                for k in (
                    "status",
                    "splits",
                    "groups_crossing_folds",
                    "normalized_answer_shapes_crossing_folds",
                    "multiturn_rows",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
