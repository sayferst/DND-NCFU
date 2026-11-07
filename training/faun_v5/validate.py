"""Replay rules, audit state/history, boundaries, and reproducible text-overlap metrics."""

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from training.faun_v5.verify_rules import verify

SPLITS = ("train", "val", "test", "ood_test_only")


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def rows(root, split):
    with (Path(root) / (split + ".jsonl")).open(encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def state_check(row):
    before, after, p, kind = (row[k] for k in ("state_before", "state_after", "parameters", "task"))
    verify(kind, p, before, row["engine_result"])
    if row["engine_result"]["state_after"] != after:
        raise ValueError("Row state differs from receipt")
    if not 0 <= after["hp"] <= after["hp_max"]:
        raise ValueError("HP range")
    if after["hp"] == 0 and after["conscious"]:
        raise ValueError("Conscious at zero HP")
    if after["dead"] and after["conscious"]:
        raise ValueError("Conscious after death")
    for k in ("coins", "npc_coins", "materials", "stamina", "charges", "duration", "mp"):
        if after[k] < 0:
            raise ValueError("Negative budget " + k)
    if after["owner"] != before["owner"]:
        raise ValueError("Possession invented legal ownership")
    if kind == "reward" and sum(after[k] for k in ("coins", "npc_coins")) != sum(
        before[k] for k in ("coins", "npc_coins")
    ):
        raise ValueError("Money created")
    if p.get("intent_only") and before != after:
        raise ValueError("Intent changed world")
    previous = None
    for step in row["trajectory"]:
        verify(step["operation"], step["parameters"], step["state_before"], step["engine_result"])
        if previous is not None and previous != step["state_before"]:
            raise ValueError("Broken trajectory")
        previous = step["engine_result"]["state_after"]
    if previous is not None and previous != before:
        raise ValueError("History does not lead to current state")
    expected_turns = len(row["trajectory"]) + 1
    if len(row["messages"]) != 1 + 2 * expected_turns:
        raise ValueError("Conversation/trajectory mismatch")
    payload = json.loads(row["messages"][-2]["content"])
    if payload["parameters"] != p or payload["operation"] != kind:
        raise ValueError("Prompt differs from metadata")
    if any(before[k] != v for k, v in payload["state_before"].items()):
        raise ValueError("Prompt state differs")
    if row["mode"] == "apply_rules" and "engine_result" in payload:
        raise ValueError("Rule task leaks answer")
    if row["mode"] == "narrate_engine_result":
        receipt = payload["engine_result"]
        if any(row["engine_result"][k] != receipt[k] for k in ("numbers", "success", "committed")):
            raise ValueError("Prompt receipt differs")
    text = row["messages"][-1]["content"]
    # Independent check of every printed arithmetic equality.
    for a, sign, b, c in re.findall(r"(\d+)\s*([+−])\s*(\d+)\s*=\s*(\d+)", text):
        calculated = int(a) + int(b) if sign == "+" else int(a) - int(b)
        if calculated != int(c):
            raise ValueError("Printed arithmetic disagrees")
    if not row["synthetic"] or row["human_reviewed"]:
        raise ValueError("Incorrect provenance")


def words(text):
    return re.findall(r"[а-яёa-z0-9]+", text.casefold())


def shingles(text, width=5):
    tokens = words(text)
    return {tuple(tokens[i : i + width]) for i in range(len(tokens) - width + 1)}


def validate(root, output=None):
    root = Path(root)
    identities, bindings, entities, groups, families, npc = {}, {}, {}, {}, {}, {}
    text_hashes = {}
    counts, tasks, styles, modes, outcomes = Counter(), Counter(), Counter(), Counter(), Counter()
    firsts, lasts, phrases = Counter(), Counter(), Counter()
    lengths, exact_answers, normalized = [], defaultdict(set), defaultdict(set)
    dialog = multi = checked = 0
    near_candidates, near_hits = 0, []
    # MinHash over literal answer five-word shingles; approximate candidate search.
    buckets = defaultdict(list)
    shingle_cache = {}
    for split in SPLITS:
        path = root / (split + ".jsonl")
        if not path.is_file():
            continue
        bindings[path.name] = sha(path)
        for row in rows(root, split):
            uid = row["id"]
            if uid in identities:
                raise ValueError("Duplicate ID")
            identities[uid] = split
            state_check(row)
            checked += 1
            for value, mapping in (
                (row["group_id"], groups),
                (row["source"]["entity_id"], entities),
                (row["style"]["narrative_family"], families),
                (row["scene"]["npc"], npc),
                (row["scene"]["other_npc"], npc),
            ):
                if value in mapping and mapping[value] != split:
                    raise ValueError("Split overlap: " + str(value))
                mapping[value] = split
            key = fingerprint(row["messages"][:-1])
            if key in text_hashes and text_hashes[key] != split:
                raise ValueError("Exact input overlap")
            text_hashes[key] = split
            text = row["messages"][-1]["content"]
            exact_answers[text].add(split)
            norm = re.sub(r"\d+", "#", " ".join(words(text)))
            normalized[norm].add(split)
            lengths.append(len(text))
            firsts[text.split("\n")[0]] += 1
            lasts[text.split("\n")[-1]] += 1
            tokens = words(text)
            phrases.update(set(tuple(tokens[i : i + 8]) for i in range(max(0, len(tokens) - 7))))
            dialog += int("—" in text or "«" in text)
            multi += int(len(row["messages"]) > 3)
            counts[split] += 1
            tasks[row["task"]] += 1
            styles[row["style"]["mode"]] += 1
            modes[row["mode"]] += 1
            outcome = row["engine_result"]["numbers"].get(
                "outcome", row["engine_result"]["success"]
            )
            outcomes[row["task"] + ":" + str(outcome)] += 1
            # Short shared calculations are recorded separately; not hidden as scene plagiarism.
            if len(text) < 250:
                continue
            sh = shingles(text)
            if not sh:
                continue
            hashes = [
                int.from_bytes(hashlib.blake2s(" ".join(x).encode(), digest_size=8).digest(), "big")
                for x in sh
            ]
            mask = (1 << 64) - 1
            mins = tuple(min((h * (2 * j + 3) + j * 137) & mask for h in hashes) for j in range(8))
            candidates = set()
            for band in range(4):
                for other in buckets[(band, mins[2 * band : 2 * band + 2])]:
                    if identities[other] != split:
                        candidates.add(other)
            for other in candidates:
                near_candidates += 1
                old = shingle_cache[other]
                similarity = len(sh & old) / len(sh | old)
                if similarity >= 0.9:
                    near_hits.append({"a": other, "b": uid, "jaccard": round(similarity, 4)})
            shingle_cache[uid] = sh
            for band in range(4):
                buckets[(band, mins[2 * band : 2 * band + 2])].append(uid)
    lengths.sort()
    report = {
        "schema": "faun-v5-quality-v1",
        "status": "RULES_STATE_SPLIT_CHECKS_PASS",
        "checked": checked,
        "splits": dict(counts),
        "task_counts": dict(tasks),
        "outcomes": dict(outcomes),
        "mode_counts": dict(modes),
        "style_counts": dict(styles),
        "multi_turn": multi,
        "dialogue": dialog,
        "answer_characters": {
            str(p): lengths[int((len(lengths) - 1) * p / 100)] for p in (0, 50, 75, 95, 99, 100)
        },
        "unique_answers": len(exact_answers),
        "exact_answer_forms_cross_split": sum(len(v) > 1 for v in exact_answers.values()),
        "number_normalized_answer_forms_cross_split": sum(len(v) > 1 for v in normalized.values()),
        "exact_input_overlap": 0,
        "group_entity_npc_composition_overlap": 0,
        "minhash": {
            "candidate_pairs": near_candidates,
            "literal_5gram_jaccard_at_least_0_9": len(near_hits),
            "examples": near_hits[:30],
            "approximate_not_exhaustive": True,
        },
        "top_first_paragraphs": firsts.most_common(10),
        "top_last_paragraphs": lasts.most_common(10),
        "top_8grams": [(" ".join(k), v) for k, v in phrases.most_common(20)],
        "bindings": bindings,
        "human_reviewed": 0,
        "grammar_check_scope": (
            "bounded patterns and arithmetic; not comprehensive Russian proofreading"
        ),
        "semantic_prose_review": "separate sampled assistant review, not full human review",
        "rejected_examples": 0,
    }
    if output:
        Path(output).write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    r = validate(a.dataset, a.output)
    print(json.dumps({k: r[k] for k in ("status", "checked", "splits", "minhash")}))


if __name__ == "__main__":
    main()
