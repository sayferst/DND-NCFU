"""Human-review workbook, explicit provenance and a separate synthetic-label corpus."""

import argparse
import hashlib
import json
from pathlib import Path

from training.scenarios import candidates
from training.xlsx import read, write

STATUSES = (
    "UNLABELED",
    "RULE_LABELED",
    "AI_SUGGESTED",
    "HUMAN_REVIEW_REQUIRED",
    "HUMAN_APPROVED",
    "HUMAN_REJECTED",
    "TRAIN_ADMITTED",
)
MODES = (
    "AUTO_SUCCESS",
    "CHECK_REQUIRED",
    "ATTEMPT_WITHOUT_TARGET_SUCCESS",
    "CLARIFICATION_REQUIRED",
)
ERRORS = ("NONE", "FACTS", "UNJUSTIFIED_REFUSAL", "PLAYER_AGENCY", "RESOURCES", "CHECK", "PROSE")
HEADERS = [
    "ID",
    "Семейство сценария",
    "Контекст мира",
    "Доступные предметы",
    "Навыки и характеристики",
    "Действие игрока",
    "Возможность попытки",
    "Достижимость цели",
    "Режим проверки",
    "Предлагаемая сложность",
    "Максимально возможный результат",
    "Риски",
    "Последствия",
    "Ручная разметка",
    "Комментарий разметчика",
    "Источник данных",
    "Статус проверки",
    "Очередь разметки",
    "Кто проверил",
    "Тип ошибки",
]


def export_workbook(path):
    rows = candidates()
    actions = [HEADERS] + [
        [
            r["id"],
            r["family"],
            r["context"],
            r["items"],
            r["skills"],
            r["action"],
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            r["source"],
            r["status"],
            r["review_track"],
            "",
            "",
        ]
        for r in rows
    ]
    replies = [
        [
            "ID",
            "Контекст",
            "Действие игрока",
            "Подтверждённый результат",
            "Ответ мастера",
            "Оценка + / −",
            "Тип ошибки",
            "Причина оценки",
            "Исправленный ответ",
            "Источник",
            "Кто проверил",
            "Статус допуска",
        ]
    ]
    replies += [
        [r["id"], r["context"], r["action"], "", "", "", "", "", "", r["source"], "", "UNLABELED"]
        for r in rows
    ]
    conflicts = [
        [
            "ID",
            "Участники",
            "Ресурсы",
            "Цели",
            "Функции полезности",
            "Доступные альтернативы",
            "Риски",
            "Возможные последствия",
            "Pareto-анализ",
            "Оценка сложности",
            "Ручная оценка",
            "Примечания",
        ]
    ]
    conflicts += [
        [
            r["id"],
            "Жители, гарнизон, правитель",
            r["items"],
            "Пища, безопасность, конечный бюджет",
            "Разные нормированные веса; не человеческая оценка",
            "Приоритет жителей / стражи / компромисс / закупка",
            "Нехватка, отказ, срок",
            "",
            "",
            "",
            "",
            r["source"],
        ]
        for r in rows
        if r["family"] in ("food", "negotiation", "moral", "npc")
    ]
    guide = [["Метка", "Определение"]]
    guide += [
        [
            s,
            {
                "UNLABELED": "Нет метки",
                "RULE_LABELED": "Предложение детерминированного правила",
                "AI_SUGGESTED": "Предложение ИИ, не проверено человеком",
                "HUMAN_REVIEW_REQUIRED": "Неопределённость или спорный случай",
                "HUMAN_APPROVED": "Человек явно подтвердил и указал имя",
                "HUMAN_REJECTED": "Человек отклонил",
                "TRAIN_ADMITTED": "В этом синтетическом корпусе запрещено",
            }[s],
        ]
        for s in STATUSES
    ]
    guide += [
        ["HUMAN_FIRST", "200 кандидатов для первой ручной разметки"],
        ["AI_LATER", "800 кандидатов для последующих предложений ИИ и проверки человеком"],
        [
            "Синтетические данные",
            "1000 составных кандидатов, 20 семейств, 200 разных действий × 5 условий",
        ],
        [
            "Разделение",
            "Всё семейство должно оставаться в одном train/validation/test; "
            "это не1000независимых семей",
        ],
        [
            "Инструкция",
            "Заполните возможность, достижимость, режим, исход, риски; "
            "затем ручную метку и Кто проверил",
        ],
        [
            "Безопасность",
            "Сначала сохраните копию файла. Не переименовывайте ID. Ответы/квитанции не выдумывать",
        ],
        [
            "SFT",
            "Ручное одобрение синтетического кандидата не превращает его в реальную игровую пару",
        ],
    ]
    statistics = [
        ["Показатель", "Значение"],
        ["Всего кандидатов", {"formula": "COUNTA('Действия игроков'!A2:A1001)"}],
        ["Назначено человеку", {"formula": "COUNTIF('Действия игроков'!R2:R1001,\"HUMAN_FIRST\")"}],
        ["Назначено ИИ позже", {"formula": "COUNTIF('Действия игроков'!R2:R1001,\"AI_LATER\")"}],
    ]
    for status in STATUSES:
        statistics.append(
            [status, {"formula": f"COUNTIF('Действия игроков'!Q2:Q1001,\"{status}\")"}]
        )
    statistics += [
        ["Человек указал метку", {"formula": "COUNTA('Действия игроков'!N2:N1001)"}],
        ["Допущено в реальный SFT", 0],
    ]
    for error in ERRORS:
        statistics.append([error, {"formula": f"COUNTIF('Действия игроков'!T2:T1001,\"{error}\")"}])
    write(
        path,
        [
            (
                "Действия игроков",
                actions,
                {
                    "lists": {
                        7: ("YES", "NO", "UNKNOWN"),
                        8: ("YES", "NO", "PARTIAL", "UNKNOWN"),
                        9: MODES,
                        14: ("+", "-"),
                        17: STATUSES,
                        20: ERRORS,
                    },
                    "status_column": 17,
                },
            ),
            (
                "Ответы мастера",
                replies,
                {"lists": {6: ("+", "-"), 7: ERRORS, 12: STATUSES}, "status_column": 12},
            ),
            ("Конфликтные ситуации", conflicts, {}),
            ("Справочник", guide, {}),
            ("Статистика", statistics, {}),
        ],
    )
    return {
        "candidates": len(rows),
        "human_first": 200,
        "ai_later": 800,
        "human_reviewed": 0,
        "train_admitted": 0,
    }


def import_review(path, output, *, reviewer="", confirm_human=False):
    if not reviewer.strip() or not confirm_human:
        raise ValueError("Explicit human reviewer and confirmation required")
    original = {r["id"]: r for r in candidates()}
    sheet = read(path)
    if [sheet[0].get(chr(65 + i), "") for i in range(len(HEADERS))] != HEADERS:
        raise ValueError("Annotation schema changed")
    seen, result = set(), []
    for row in sheet[1:]:
        id = row.get("A")
        if id not in original or id in seen:
            raise ValueError("Changed, duplicated or unknown scenario ID")
        seen.add(id)
        source = original[id]
        for column, key in (
            ("B", "family"),
            ("C", "context"),
            ("D", "items"),
            ("E", "skills"),
            ("F", "action"),
            ("P", "source"),
            ("R", "review_track"),
        ):
            if row.get(column) != source[key]:
                raise ValueError("Scenario facts changed: " + id)
        status = row.get("Q", "UNLABELED")
        if status not in STATUSES or status == "TRAIN_ADMITTED":
            raise ValueError("Synthetic scenario cannot be admitted as real SFT")
        if status in ("HUMAN_APPROVED", "HUMAN_REJECTED"):
            if row.get("S") != reviewer or row.get("N") not in ("+", "-"):
                raise ValueError("Missing human label or reviewer")
            if row.get("I") not in MODES or row.get("G") not in ("YES", "NO", "UNKNOWN"):
                raise ValueError("Human decision needs an attempt mode and possibility")
            result.append(
                source
                | {
                    "schema_version": "synthetic-action-label-v1",
                    "reviewer": reviewer,
                    "review_status": status,
                    "label": row["N"],
                    "mode": row["I"],
                    "comment": row.get("O", ""),
                    "error_type": row.get("T", ""),
                    "train_admitted": False,
                }
            )
    if len(seen) != 1000:
        raise ValueError("Workbook must preserve all 1000 scenario IDs")
    with Path(output).open("x", encoding="utf-8") as stream:
        for row in result:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {
        "reviewed": len(result),
        "train_admitted": 0,
        "workbook_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
    }


def suggest_rules(row):
    """Facts-only suggestions; never call this human approval or SFT admission."""
    uncertain = "закрытом контейнере" in row["context"] or "Две похожие цели" in row["context"]
    return {
        "scenario_id": row["id"],
        "provenance": "deterministic-access-v1",
        "status": "HUMAN_REVIEW_REQUIRED" if uncertain else "RULE_LABELED",
        "mode": "CLARIFICATION_REQUIRED" if uncertain else None,
        "uncertainty": "high" if uncertain else "semantic_outcome_not_evaluated",
        "human_approved": False,
        "train_admitted": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--reviewer", default="")
    parser.add_argument("--confirm-human-review", action="store_true")
    parser.add_argument("--suggest-rules", action="store_true")
    args = parser.parse_args()
    if args.suggest_rules:
        suggestions = [
            suggest_rules(row) for row in candidates() if row["review_track"] == "AI_LATER"
        ]
        with args.output.open("x", encoding="utf-8") as stream:
            for row in suggestions:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(
            json.dumps(
                {"rule_suggestions": len(suggestions), "human_approved": 0, "train_admitted": 0}
            )
        )
        return
    result = (
        import_review(
            args.input, args.output, reviewer=args.reviewer, confirm_human=args.confirm_human_review
        )
        if args.input
        else export_workbook(args.output)
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
