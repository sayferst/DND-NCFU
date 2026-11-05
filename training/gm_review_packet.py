"""Source-bound bilingual owner review; a sample review never approves a whole corpus."""

import argparse
import csv
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path

from training.fireball_observations import dumps
from training.gm_candidate_audit import file_digest, quality_flags
from training.xlsx import col, read, write

COLUMNS = [
    "ID",
    "Источник",
    "Язык оригинала",
    "Сцена RU — краткое изложение",
    "Scene EN — short summary",
    "Ответ RU",
    "Reply EN",
    "Примечание к проверке",
    "Понятность 1–5",
    "Верность сцене",
    "Стиль 1–5",
    "Смысл перевода",
    "Решение",
    "Исправленный ответ RU",
    "Замечания",
]
IMMUTABLE = 8
DECISIONS = ("Одобрено человеком", "Отклонено человеком", "Нужна правка")


def rows_for(cases):
    return [COLUMNS] + [
        [
            row["review_id"],
            row["source"],
            row["source_language"],
            row["scene_ru"],
            row["scene_en"],
            row["reply_ru"],
            row["reply_en"],
            row["review_note"],
            "",
            "",
            "",
            "",
            "",
            "",
            "",
        ]
        for row in cases
    ]


def build(cases_path, edits_path, output, *, expected_rows=40):
    output = Path(output)
    edits = json.loads(Path(edits_path).read_text(encoding="utf-8"))
    if len(edits) != expected_rows or len({e["case_id"] for e in edits}) != expected_rows:
        raise ValueError("Review must contain exactly the requested number of distinct candidates")
    wanted = {e["case_id"] for e in edits}
    selected = {}
    with gzip.open(cases_path, "rt", encoding="utf-8") as stream:
        for line in stream:
            case = json.loads(line)
            if case["id"] in wanted:
                selected[case["id"]] = case
    if set(selected) != wanted:
        raise ValueError("Review edit references a missing original candidate")
    output.mkdir(parents=True, exist_ok=False)
    rows, units = [], set()
    for index, edit in enumerate(edits, 1):
        case = selected[edit["case_id"]]
        if case["split"] != "train":
            raise ValueError("Owner style review must not adapt a validation/test target")
        unit = (case["source"], case["source_unit"])
        if unit in units:
            raise ValueError("Repeated source utterance in review sample")
        units.add(unit)
        source_language = case["provenance"]["source_language"]
        if edit["reply_" + source_language] != case["target"]:
            raise ValueError("Original reply must remain verbatim in its source language")
        if any(
            not isinstance(edit[k], str) or not edit[k].strip()
            for k in ("scene_ru", "scene_en", "reply_ru", "reply_en", "review_note")
        ):
            raise ValueError("Both language versions and the review scope are required")
        rows.append(
            {
                "review_id": f"GM-{index:02}",
                "case_id": case["id"],
                "source": case["source"],
                "source_language": source_language,
                **{
                    k: edit[k]
                    for k in ("scene_ru", "scene_en", "reply_ru", "reply_en", "review_note")
                },
                "original_case": case,
                "provenance": {
                    "source_case_sha256": hashlib.sha256(dumps(case).encode()).hexdigest(),
                    "editor": "assistant",
                    "translation_method": "ASSISTANT_TRANSLATION_WITH_EDITORIAL_MEANING_CHECK",
                    "scene_projection": (
                        "EDITORIAL_SHORT_SUMMARY_NOT_A_VERBATIM_TRANSLATION_OF_FULL_CONTEXT"
                    ),
                    "original_context_preserved": True,
                    "human_reviewed": False,
                    "train_admitted": False,
                },
                "source_review_flags": quality_flags(case),
            }
        )
    values = rows_for(rows)
    if any(len(str(v)) > 32767 for r in values for v in r):
        raise ValueError("Excel limit: preserve complete texts in JSONL, do not truncate")
    (output / "review-cases.jsonl").write_text(
        "".join(dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    with (output / "review-40.csv").open("w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerows(values)
    guide = [
        ["Что проверить", "Как заполнить"],
        ["Пакет", f"{expected_rows} пар RU/EN. Пустые оценки означают: человек ещё не проверил."],
        [
            "Сцены",
            "Краткие редакторские изложения. "
            "Полные исходные контексты сохранены в review-cases.jsonl.",
        ],
        [
            "Источники",
            "FIREBALL и CRD3 — реальные записи; "
            "PROJECT_REFERENCE — синтетический расчёт правил проекта.",
        ],
        [
            "Внешние правила",
            "Механики источника не являются правилами DND-NCFU. "
            "Оцените уместность реплики мастера отдельно.",
        ],
        [
            "Оценки",
            "Заполните столбцы I–O на листе «40 примеров». "
            "1 — плохо, 5 — хорошо; далее Да/Нет и решение.",
        ],
        [
            "Исправление",
            "Текст можно предложить в «Исправленный ответ RU». "
            "Он требует повторной проверки перед допуском.",
        ],
        [
            "Границы",
            "Обычная реплика 1–2 предложения; значимый исход 3–5. "
            "Сохраняйте смысл и факты, свободу игрока.",
        ],
        ["Содержание", "Взрослое фэнтези, жестокость допустима; без откровенной эротики."],
        [
            "Допуск",
            "Проверка этого пакета не одобряет автоматически весь большой корпус "
            "и не запускает обучение.",
        ],
    ]
    write(
        output / "DND_NCFU_REVIEW_40_RU_EN.xlsx",
        [
            ("Начать здесь", guide, {"readonly_columns": (1, 2)}),
            (
                "40 примеров",
                values,
                {
                    "readonly_columns": tuple(range(1, IMMUTABLE + 1)),
                    "status_column": 13,
                    "lists": {
                        9: ["1", "2", "3", "4", "5"],
                        10: ["Да", "Нет"],
                        11: ["1", "2", "3", "4", "5"],
                        12: ["Да", "Нет"],
                        13: list(DECISIONS),
                    },
                },
            ),
        ],
    )
    if read(output / "DND_NCFU_REVIEW_40_RU_EN.xlsx", sheet="40 примеров") != [
        {col(i): str(v) for i, v in enumerate(row, 1)} for row in values
    ]:
        raise ValueError("Bilingual review workbook did not round trip")
    markdown = [
        "# Проверка 40 пар RU/EN",
        "",
        "Сцены ниже — краткие изложения; полные исходники находятся в review-cases.jsonl.",
        "Оцени понятность, верность сцене, стиль и сохранение смысла. Обучение не запускалось.",
        "",
    ]
    for row in rows:
        markdown += [
            f"## {row['review_id']} · {row['source']}",
            "",
            row["scene_ru"],
            "",
            "**RU:** " + row["reply_ru"],
            "",
            "**EN:** " + row["reply_en"],
            "",
            "Проверка: " + row["review_note"],
            "",
        ]
    (output / "ПРОЧИТАЙ_40_ПРИМЕРОВ.md").write_text("\n".join(markdown), encoding="utf-8")
    manifest = {
        "schema": "gm-bilingual-owner-review-v1",
        "status": "OWNER_SAMPLE_REVIEW_PENDING",
        "source_cases_sha256": file_digest(cases_path),
        "editorial_file_sha256": file_digest(edits_path),
        "rows": len(rows),
        "sources": dict(Counter(r["source"] for r in rows)),
        "source_splits": {"train": len(rows)},
        "human_reviewed": 0,
        "train_admitted": 0,
        "training_steps": 0,
        "files": {p.name: file_digest(p) for p in output.iterdir() if p.is_file()},
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def import_review(packet, workbook, output):
    """Only the explicit, actually populated owner labels are imported."""
    packet, output = Path(packet), Path(output)
    manifest = json.loads((packet / "manifest.json").read_text(encoding="utf-8"))
    for name, expected in manifest["files"].items():
        if Path(name).name != name or file_digest(packet / name) != expected:
            raise ValueError("Original review packet changed")
    cases = [
        json.loads(line)
        for line in (packet / "review-cases.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    original = rows_for(cases)
    returned = read(workbook, sheet="40 примеров")
    if (
        len(returned) != len(original)
        or [returned[0].get(col(i), "") for i in range(1, 16)] != COLUMNS
    ):
        raise ValueError("Review rows or columns changed")
    expected = {row[0]: row for row in original[1:]}
    labels, seen = [], set()
    for row in returned[1:]:
        key = row.get("A")
        if key not in expected or key in seen:
            raise ValueError("Unknown or repeated review ID")
        seen.add(key)
        if any(row.get(col(i), "") != expected[key][i - 1] for i in range(1, IMMUTABLE + 1)):
            raise ValueError(
                "Source or prepared language versions changed; use the correction column"
            )
        if not any(row.get(col(i), "").strip() for i in range(9, 16)):
            continue
        decision = row.get("M", "")
        if decision not in DECISIONS:
            raise ValueError("Each edited row needs an explicit decision")
        for column in ("I", "K"):
            if row.get(column) not in {"1", "2", "3", "4", "5"}:
                raise ValueError("Missing or invalid style/readability rating")
        if any(row.get(column) not in {"Да", "Нет"} for column in ("J", "L")):
            raise ValueError("Missing scene or translation judgment")
        corrected = row.get("N", "").strip()
        if decision == "Одобрено человеком" and (row["J"] != "Да" or row["L"] != "Да" or corrected):
            raise ValueError(
                "An approved row cannot contain a contradiction or unverified correction"
            )
        labels.append(
            {
                "review_id": key,
                "case_id": next(c["case_id"] for c in cases if c["review_id"] == key),
                "decision": decision,
                "readability": int(row["I"]),
                "style": int(row["K"]),
                "scene_correct": row["J"] == "Да",
                "meaning_preserved": row["L"] == "Да",
                "proposed_ru_correction": corrected,
                "comment": row.get("O", ""),
                "train_admitted": False,
            }
        )
    result = {
        "schema": "gm-owner-sample-labels-v1",
        "status": "OWNER_LABELS_IMPORTED_REVALIDATION_REQUIRED",
        "packet_manifest_sha256": file_digest(packet / "manifest.json"),
        "returned_workbook_sha256": file_digest(workbook),
        "reviewed_rows": len(labels),
        "unreviewed_rows": len(cases) - len(labels),
        "labels": labels,
        "whole_corpus_approved": False,
        "training_steps": 0,
    }
    with output.open("x", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    b.add_argument("--cases", type=Path, required=True)
    b.add_argument("--edits", type=Path, required=True)
    b.add_argument("--output", type=Path, required=True)
    r = sub.add_parser("import-review")
    r.add_argument("--packet", type=Path, required=True)
    r.add_argument("--workbook", type=Path, required=True)
    r.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    result = (
        build(a.cases, a.edits, a.output)
        if a.command == "build"
        else import_review(a.packet, a.workbook, a.output)
    )
    print(json.dumps({k: result[k] for k in ("status", "training_steps")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
