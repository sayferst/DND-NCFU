"""Reproducible data construction; CPU only, no model-weight or GPU operations."""

import argparse
import csv
import json
import shutil
from pathlib import Path

from training.faun_v5.generate import generate
from training.faun_v5.grammar import audit_texts
from training.faun_v5.validate import SPLITS, fingerprint, rows, sha, validate


def prepare_inputs(source, output):
    source, output = Path(source), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(source / "entity_index.jsonl", output / "entity_index.jsonl")
    groups = {}
    for split in ("train", "val", "test"):
        groups[split] = sorted({r["source"]["entity_id"] for r in rows(source, split)})
    (output / "source_groups.json").write_text(
        json.dumps(groups, sort_keys=True) + "\n", encoding="utf-8"
    )
    shutil.copyfile(
        source / "regression_suite_T05_T24.csv", output / "regression_suite_T05_T24.csv"
    )
    bindings = {p.name: sha(p) for p in output.iterdir() if p.is_file()}
    (output / "input_hashes.json").write_text(
        json.dumps(bindings, indent=2) + "\n", encoding="utf-8"
    )


def verify_inputs(source):
    source = Path(source)
    for name, expected in json.loads((source / "input_hashes.json").read_text()).items():
        if Path(name).name != name or sha(source / name) != expected:
            raise ValueError("Changed source input: " + name)


def regression(source, output):
    with (Path(source) / "regression_suite_T05_T24.csv").open(
        encoding="utf-8-sig", newline=""
    ) as stream:
        old = list(csv.DictReader(stream))
    pilots = [
        {
            "id": "T02",
            "category": "Пилот: смерть",
            "prompt": (
                "При 0 HP уже один провал спасброска смерти. "
                "Натуральная 1 добавляет два провала. "
                "Три провала означают смерть. Каков итог?"
            ),
            "expected": "1 + 2 = 3 провала: смерть.",
        },
        {
            "id": "T03",
            "category": "Пилот: концентрация",
            "prompt": "После 22 урона сложность концентрации max(10, половина урона вниз). "
            "Спасбросок 12. Сохранилась ли концентрация?",
            "expected": "Сложность 11; 12 >= 11, успех.",
        },
        {
            "id": "T04",
            "category": "Пилот: реакция",
            "prompt": "Реакция уже потрачена и ещё не восстановилась. Исключений нет. "
            "Можно ли сейчас выполнить атаку по возможности за реакцию?",
            "expected": "Нет: ресурс реакции потрачен.",
        },
    ]
    with Path(output).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=["id", "category", "prompt", "expected", "provenance", "rubric"]
        )
        writer.writeheader()
        for item in pilots + old:
            item["provenance"] = (
                "reconstructed_from_docx_summary"
                if item["id"] in ("T02", "T03", "T04")
                else "supplied_v41_csv"
            )
            item["rubric"] = (
                "separate_pilot_do_not_mix_with_historical_20"
                if item["id"] in ("T02", "T03", "T04")
                else "historical_binary_20"
            )
            writer.writerow(item)


def gold(root, split, output):
    with Path(output).open("w", encoding="utf-8") as stream:
        for row in rows(root, split):
            entry = {
                "id": row["id"],
                "group_id": row["group_id"],
                "task": row["task"],
                "messages": row["messages"][:-1],
                "reference": row["messages"][-1]["content"],
                "expected_numbers": row["engine_result"]["numbers"],
                "expected_state": row["state_after"],
                "human_grade": None,
            }
            stream.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def construct(source, output):
    source, output = Path(source), Path(output)
    verify_inputs(source)
    manifest = generate(source, output)
    used = [k.removeprefix("v5:") for k in json.loads((output / "group_splits.json").read_text())]
    ood = output / "ood_build"
    generate(source, ood, groups_per_split={"ood": 125}, excluded_entities=used)
    shutil.move(ood / "ood.jsonl", output / "ood_test_only.jsonl")
    groups = json.loads((output / "group_splits.json").read_text())
    groups.update(json.loads((ood / "group_splits.json").read_text()))
    (output / "group_splits.json").write_text(
        json.dumps(groups, sort_keys=True) + "\n", encoding="utf-8"
    )
    shutil.rmtree(ood)  # Only this function's own, disposable intermediate directory.
    gold(output, "test", output / "eval_gold.jsonl")
    gold(output, "ood_test_only", output / "ood_eval_gold.jsonl")
    regression(source, output / "regression_suite.csv")
    (output / "reports").mkdir()
    report = validate(output, output / "reports/quality.json")
    texts = ((r["id"], r["messages"][-1]["content"]) for s in SPLITS for r in rows(output, s))
    grammar = audit_texts(texts)
    (output / "reports/grammar.json").write_text(
        json.dumps(grammar, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if grammar["bounded_pattern_hits"]:
        raise ValueError("Known prose defects detected")
    manifest.update(
        ood_examples=500,
        groups=1805,
        mechanics=len(report["task_counts"]),
        multi_turn=report["multi_turn"],
        dataset_policy="declared-scenario-synthetic-v5",
        status="CPU_TOKENIZATION_PENDING",
        source_sqlite_available=False,
        source_input_bindings=json.loads((source / "input_hashes.json").read_text()),
        file_sha256={s: sha(output / (s + ".jsonl")) for s in SPLITS},
    )
    manifest["data_sha256"] = fingerprint(manifest["file_sha256"])
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--prepare-inputs", action="store_true")
    a = p.parse_args()
    if a.prepare_inputs:
        prepare_inputs(a.source, a.output)
    else:
        print(json.dumps(construct(a.source, a.output), indent=2))


if __name__ == "__main__":
    main()
