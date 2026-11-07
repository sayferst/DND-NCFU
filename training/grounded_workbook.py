"""Editable human review of the complete synthetic corpus; no implied approval."""

import argparse
import json
from pathlib import Path

from training.grounded_validation import verify
from training.xlsx import write


def table(rows):
    columns = [
        "ID",
        "Разделение",
        "Группа намерения",
        "Исходный контекст",
        "Действие игрока",
        "Начальное состояние JSON",
        "Попытка допустима",
        "Цель достижима",
        "Нужен D20",
        "Задача",
        "D20 и расчёт JSON",
        "Исход",
        "Изменения JSON",
        "Итоговое состояние JSON",
        "Ответ мастера",
        "Происхождение",
        "Проверка человеком",
        "Замечание человека",
    ]
    data = [columns]
    for split, row in rows:
        result = row["engine_receipt"]

        def compact(value):
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

        data.append(
            [
                row["sample_id"],
                split,
                row["campaign_id"],
                row["source_scenario"]["context"],
                row["player_message"],
                compact(row["public_context"]["state"]),
                compact(result["attempt_possible"]),
                compact(result["goal_reachable"]),
                compact(result["d20_required"]),
                row["spec"]["task"],
                compact(result["roll"]),
                result["outcome"],
                compact(result["changes"]),
                compact(row["after_state"]),
                row["assistant_reply"],
                "Синтетика; эталонный расчёт, не сыгранная партия",
                "",
                "",
            ]
        )
    if any(len(str(value)) > 32767 for row in data for value in row):
        raise ValueError("Excel cell limit exceeded; preserve full facts in JSONL")
    return data


def export(directory, output):
    manifest, splits = verify(directory)
    rows = [(split, row) for split, values in splits.items() for row in values]
    rows.sort(key=lambda pair: pair[1]["sample_id"])
    status = {
        "lists": {17: ["Одобрено человеком", "Отклонено человеком"]},
        "status_column": 17,
        "readonly_columns": tuple(range(1, 17)),
    }
    guide = [
        ["Поле", "Значение"],
        ["Корпус", manifest["sha256"]],
        [
            "Готовность",
            "1100 полностью заполненных синтетических примеров; обучение не запускалось",
        ],
        ["Проверка", "Математика проверена кодом. Личная проверка владельцем:0 строк."],
        [
            "Редактирование",
            "Заполняйте два последних столбца. Не меняйте ID, расчёты и исходные факты.",
        ],
        [
            "Отклонение",
            "Замечание означает необходимость новой версии примера и повторной проверки.",
        ],
        ["Содержание", "Взрослое фэнтези, жестокость допустима; без откровенной эротики."],
        [
            "Действия",
            "Разметка намерений — данные; математические операции общие для разных предметов.",
        ],
        [
            "Разделение",
            "Варианты одного намерения целиком в одном split; тест не участвует в градиентах.",
        ],
        [
            "Ограничение",
            "Это эталонные синтетические исполнения, а не1100 реальных игровых эпизодов.",
        ],
    ]
    write(
        output,
        [
            ("Начать здесь", guide, {}),
            (
                "1000 сценариев",
                table([p for p in rows if not p[1]["sample_id"].startswith("edge_")]),
                status,
            ),
            (
                "100 границ правил",
                table([p for p in rows if p[1]["sample_id"].startswith("edge_")]),
                status,
            ),
        ],
    )
    return {"samples": len(rows), "human_reviewed": 0, "dataset_sha256": manifest["sha256"]}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--directory", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(export(a.directory, a.output), ensure_ascii=False))


if __name__ == "__main__":
    main()
