"""Balanced owner workbook and separate action/narrator/conflict corpora; never SFT."""

import argparse
import hashlib
import json
from pathlib import Path

from training.annotation import ERRORS, MODES, STATUSES
from training.scenarios import CONDITIONS, FAMILIES, candidates
from training.xlsx import col, read, write

STATUS_RU = dict(
    zip(
        STATUSES,
        (
            "Не размечено",
            "Предложено правилом",
            "Предложено ИИ",
            "Нужна проверка",
            "Одобрено человеком",
            "Отклонено человеком",
            "Допущено в обучение",
        ),
        strict=True,
    )
)
DECISIONS = {"Да": "YES", "Нет": "NO", "Частично": "PARTIAL", "Неясно": "UNKNOWN"}
ERROR_RU = dict(
    zip(
        ERRORS,
        (
            "Нет ошибки",
            "Факты мира",
            "Необоснованный отказ",
            "Решение за игрока",
            "Ресурсы",
            "Проверка кубиком",
            "Качество текста",
        ),
        strict=True,
    )
)
ACTION_HEADERS = [
    "ID",
    "Семейство",
    "Ситуация",
    "Предметы",
    "Навыки",
    "Действие игрока",
    "Попытка возможна",
    "Цель достижима",
    "Нужен D20",
    "Возможные исходы",
    "Ограничения и риски",
    "Последствия и расход",
    "Ответ мастера",
    "Оценка ответа (+/−)",
    "Причина ошибки",
    "Исправленный ответ",
    "Статус проверки",
    "Кто проверил",
    "Очередь разметки",
    "Источник",
    "Тип ошибки",
    "Тип условий",
]
REPLY_HEADERS = [
    "ID",
    "Ситуация",
    "Действие игрока",
    "Описанный исход",
    "Ответ мастера",
    "Оценка ответа (+/−)",
    "Тип ошибки",
    "Причина ошибки",
    "Исправленный ответ",
    "Источник",
    "Кто проверил",
    "Статус проверки",
]
CONFLICT_HEADERS = [
    "ID",
    "Ресурсы и потребности",
    "Альтернатива",
    "Жителям",
    "Гарнизону",
    "Казна после",
    "Полезности",
    "Pareto",
    "Ручная оценка",
    "Примечание",
]
EXPLANATIONS = (
    (
        "Да",
        "Частично",
        "Да",
        "Материалы ограничивают качество; высокий бросок не добавляет крючок.",
        "Поломка / заготовка / грубая снасть.",
        "Ты снимаешь тетиву и приступаешь к переделке. Результат зависит от работы и материалов.",
    ),
    (
        "Да",
        "Частично",
        "Да",
        "Проверяются материал, инструмент и прочность.",
        "Брак / неполное изделие / пригодный образец.",
        "Материал поддаётся обработке. Испытание покажет, выдержит ли новая форма нагрузку.",
    ),
    (
        "Да",
        "Частично",
        "Да",
        "Частичный ремонт не означает полную исправность.",
        "Восстановлена часть функций.",
        "Тормоз держится лучше, но остальные повреждения телеги остаются.",
    ),
    (
        "Да",
        "Частично",
        "Да",
        "Изношенный инструмент может сломаться и расходует материал.",
        "Неудача / слабый ремонт / ремонт.",
        "Ты берёшь изношенный инструмент. При работе его состояние придётся учитывать.",
    ),
    (
        "Да",
        "Нет",
        "Нет",
        "Нет подтверждённого эффекта создания денег.",
        "Попытка без появления настоящих монет.",
        "Ты сосредоточиваешься, но золотые монеты не возникают.",
    ),
    (
        "Да",
        "Нет",
        "Нет",
        "У обычного предмета нет подъёмной силы и магии полёта.",
        "Подпрыгнуть можно, устойчивый полёт недостижим.",
        "Ты пробуешь оторваться от земли. Метла остаётся обычной метлой.",
    ),
    (
        "Да",
        "Да",
        "Нет",
        "Предмет зарегистрирован, доступен и не принадлежит другому.",
        "Тот же ID переносится в инвентарь.",
        "Ты подбираешь рукавицу. Теперь она у тебя.",
    ),
    (
        "Да",
        "Да",
        "Нет",
        "Существующий соседний путь открыт.",
        "Изменение места и игрового времени.",
        "Ты проходишь по знакомой дороге к шахте.",
    ),
    (
        "Да",
        "Частично",
        "Да",
        "Учитываются дистанция, опора, груз и состояние героя.",
        "Успех / потеря равновесия / травма.",
        "Ты отталкиваешься у края канавы; исход прыжка определит проверка.",
    ),
    (
        "Да",
        "Частично",
        "Да",
        "Интересы сторон различны; убеждение не создаёт пищу.",
        "Соглашение / отказ / новое предложение.",
        "Жители и стража выслушивают предложение. Каждый считает оставшиеся рационы.",
    ),
    (
        "Да",
        "Да",
        "Нет",
        "Есть товар, продавец, цена и деньги.",
        "Одна вещь и реальная оплата меняют владельцев.",
        "Продавец передаёт оплаченную вещь; остаток кошелька учтён движком.",
    ),
    (
        "Да",
        "Неясно",
        "Нет",
        "Выслушивание не требует броска; согласие ещё не получено.",
        "Появляются сведения о требованиях сторон.",
        "Стороны по очереди объясняют, что для них важно.",
    ),
    (
        "Да",
        "Частично",
        "Нет",
        "Ресурс конечен, нельзя обещать лечение всем.",
        "Изменение запасов и отношений.",
        "Лекарство достаётся выбранному раненому. Для второго придётся искать помощь.",
    ),
    (
        "Да",
        "Да",
        "Нет",
        "Слух отделён от личного наблюдения.",
        "NPC получает сообщение с источником.",
        "Торговец выслушивает сведения и уточняет, видел ли ты дорогу сам.",
    ),
    (
        "Да",
        "Частично",
        "Да",
        "Сначала проверяются цель, очередь, оружие и ресурс.",
        "Промах / попадание и рассчитанный урон.",
        "Ты наносишь удар. Его точный итог уже определён боевым движком.",
    ),
    (
        "Да",
        "Частично",
        "Нет",
        "Нужно изученное заклинание, живая цель и достаточная мана.",
        "Подтверждённое лечение в пределах эффекта.",
        "Лечебный свет касается раны; восстановление ограничено известным заклинанием.",
    ),
    (
        "Да",
        "Неясно",
        "Да",
        "Сложность надписи и доступная информация подтверждаются отдельно.",
        "Понимание / частичная расшифровка / неопределённость.",
        "Ты сравниваешь знаки; часть смысла пока остаётся неясной.",
    ),
    (
        "Да",
        "Неясно",
        "Нет",
        "Нужно сверить историю ID, владельца и события.",
        "Уточнение местонахождения без дублирования.",
        "Вещь уже передана владельцу. Её прежняя запись не создаёт вторую копию.",
    ),
    (
        "Да",
        "Да",
        "Нет",
        "Описание использует квитанцию и не выполняет ход заново.",
        "Новый текст при том же состоянии и RNG.",
        "Мастер описывает подтверждённые последствия; следующего действия за героя нет.",
    ),
    (
        "Да",
        "Частично",
        "Нет",
        "Тренировка не даёт уровень без подтверждённого достижения.",
        "Затрата времени и возможная запись практики.",
        "Ты повторяешь упражнение. Само повторение не обещает нового уровня.",
    ),
)


def rows_v2():
    rows = candidates()
    for row in rows:
        variant, action = map(int, row["id"].rsplit("_", 2)[1:])
        # Every family: two distinct actions per condition, ten per family overall.
        human = action in ((2 * variant) % 10, (2 * variant + 1) % 10)
        row["condition_type"] = variant
        row["review_track"] = "HUMAN_FIRST" if human else "AI_LATER"
    return rows


def base_actions():
    return [
        [
            r["id"],
            r["category"],
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
            "",
            STATUS_RU["UNLABELED"],
            "",
            "Сначала человеку" if r["review_track"] == "HUMAN_FIRST" else "Автопредложение",
            r["source"],
            "",
            r["condition_type"],
        ]
        for r in rows_v2()
    ]


def base_replies():
    return [
        [
            r["id"],
            r["context"],
            r["action"],
            "",
            "",
            "",
            "",
            "",
            "",
            r["source"],
            "",
            STATUS_RU["UNLABELED"],
        ]
        for r in rows_v2()
    ]


def export(path, *, carry_from=None):
    actions, replies = base_actions(), base_replies()
    extra = []
    if carry_from:
        # Validate v1 facts and preserve every original cell in additional sheets.
        original = {r["id"]: r for r in candidates()}
        for index, name in enumerate(("Действия игроков", "Ответы мастера"), 1):
            values = read(carry_from, sheet=name)
            seen = set()
            for row in values[1:]:
                id = row.get("A")
                if id not in original or id in seen:
                    raise ValueError("Changed or duplicate v1 ID")
                seen.add(id)
                facts = (
                    (
                        ("B", "family"),
                        ("C", "context"),
                        ("D", "items"),
                        ("E", "skills"),
                        ("F", "action"),
                        ("P", "source"),
                    )
                    if index == 1
                    else (("B", "context"), ("C", "action"), ("J", "source"))
                )
                if any(row.get(c) != original[id][k] for c, k in facts):
                    raise ValueError("Original v1 facts changed")
                target = (actions if index == 1 else replies)[
                    next(i for i, r in enumerate(rows_v2()) if r["id"] == id)
                ]
                mapping = (
                    {
                        6: "G",
                        7: "H",
                        9: "K",
                        10: "L",
                        11: "M",
                        14: "O",
                        16: "Q",
                        17: "S",
                        20: "T",
                    }
                    if index == 1
                    else {i: col(i + 1) for i in (3, 4, 5, 6, 7, 8, 10, 11)}
                )
                for destination, column in mapping.items():
                    value = row.get(column, "")
                    value = STATUS_RU.get(
                        value,
                        ERROR_RU.get(value, {v: k for k, v in DECISIONS.items()}.get(value, value)),
                    )
                    if value:
                        target[destination] = value
                if index == 1:
                    # v1's manual action label is not a narrator score.
                    legacy = []
                    for column, title in (("J", "Сложность v1"), ("N", "Оценка действия v1")):
                        if row.get(column):
                            legacy.append(title + ": " + row[column])
                    target[10] = "; ".join([v for v in [target[10], *legacy] if v])
                    mode = row.get("I")
                    target[8] = (
                        "Да"
                        if mode == "CHECK_REQUIRED"
                        else "Нет"
                        if mode in MODES[:1] + MODES[2:3]
                        else ""
                    )
            if len(seen) != 1000:
                raise ValueError("All v1 IDs must be preserved")
            extra.append(
                (
                    f"Архив v1 лист {index}",
                    [
                        [r.get(col(i), "") for i in range(1, max(len(x) for x in values) + 1)]
                        for r in values
                    ],
                    {},
                )
            )
    guide = [
        ["Поле / статус", "Пояснение"],
        [
            "Частичное заполнение",
            "Заполняйте удобные поля и сохраняйте копию. Пустые необязательные поля разрешены.",
        ],
        [
            "Оценки на двух листах",
            "Ответ и оценку можно внести на любом листе. Если заполнены оба, они должны совпадать.",
        ],
        [
            "Пример ответа",
            "Иллюстрации отдельного листа созданы программно и не являются вашими оценками.",
        ],
        ["Синтетика", "Эта книга не создаёт квитанции настоящей партии. SFT-допуск всегда0."],
    ]
    guide += [[v, k] for k, v in STATUS_RU.items()]
    examples = [
        [
            "ID примера",
            "Действие игрока",
            "Исходное состояние",
            "Попытка возможна",
            "Нужен D20",
            "Причина",
            "Возможные исходы",
            "Пример литературного ответа",
            "Что подтвердить человеку",
            "Происхождение",
        ]
    ]
    for family, explanation in zip(FAMILIES, EXPLANATIONS, strict=True):
        attempt, reachable, d20, reason, outcomes, prose = explanation
        examples.append(
            [
                "example_" + family[0],
                family[3][0],
                family[2] + "; " + CONDITIONS[0],
                attempt,
                d20,
                reason + " Цель: " + reachable,
                outcomes,
                prose,
                "Проверьте факты, решение о D20 и качество ответа; это не готовая ручная оценка.",
                "PROGRAM_ILLUSTRATION_NOT_HUMAN",
            ]
        )
    from rpg_vkr.domain.strategic_conflicts import FoodState, food_options

    conflicts = [CONFLICT_HEADERS]
    for policy, result in food_options(FoodState()).items():
        conflicts.append(
            [
                "food_v2_" + policy,
                "Пища100; жители70; гарнизон50; казна40; поставщик20 за30",
                policy,
                result["allocation"]["civilians"],
                result["allocation"]["guards"],
                result["after"]["treasury"],
                json.dumps(result["utilities"], ensure_ascii=False),
                "Да" if result["pareto"] else "Нет",
                "",
                "Рассчитано Python; не реальная партия и не человеческая разметка",
            ]
        )
    stats = [
        ["Показатель", "Значение"],
        ["Всего", {"formula": "COUNTA('Действия игроков'!A2:A1001)"}],
        [
            "Сначала человеку",
            {"formula": "COUNTIF('Действия игроков'!S2:S1001,\"Сначала человеку\")"},
        ],
        [
            "Автопредложение",
            {"formula": "COUNTIF('Действия игроков'!S2:S1001,\"Автопредложение\")"},
        ],
    ]
    for condition in range(5):
        stats.append(
            [
                f"Ручных: условие {condition + 1}",
                {
                    "formula": (
                        f"COUNTIFS('Действия игроков'!V2:V1001,{condition},"
                        "'Действия игроков'!S2:S1001,\"Сначала человеку\")"
                    )
                },
            ]
        )
    for status in STATUS_RU.values():
        stats.append([status, {"formula": f"COUNTIF('Действия игроков'!Q2:Q1001,\"{status}\")"}])
    stats += [
        [
            "Оценено ответов",
            {
                "formula": (
                    "COUNTIF('Ответы мастера'!F2:F1001,\"+\")"
                    "+COUNTIF('Ответы мастера'!F2:F1001,\"-\")"
                )
            },
        ],
        ["Допущено в реальный SFT", 0],
    ]
    write(
        path,
        [
            (
                "Действия игроков",
                [ACTION_HEADERS] + actions,
                {
                    "hidden_columns": (1, 20, 22),
                    "readonly_columns": (1, 2, 3, 4, 5, 6, 19, 20, 22),
                    "lists": {
                        7: tuple(DECISIONS),
                        8: tuple(DECISIONS),
                        9: ("Да", "Нет", "Неясно"),
                        14: ("+", "-"),
                        17: tuple(STATUS_RU.values())[:-1],
                        21: tuple(ERROR_RU.values()),
                    },
                    "status_column": 17,
                },
            ),
            (
                "Ответы мастера",
                [REPLY_HEADERS] + replies,
                {
                    "hidden_columns": (1, 10),
                    "readonly_columns": (1, 2, 3, 10),
                    "lists": {
                        6: ("+", "-"),
                        7: tuple(ERROR_RU.values()),
                        12: tuple(STATUS_RU.values())[:-1],
                    },
                    "status_column": 12,
                },
            ),
            ("Конфликтные ситуации", conflicts, {"readonly_columns": tuple(range(1, 9))}),
            ("Примеры разметки", examples, {"readonly_columns": tuple(range(1, 11))}),
            ("Справочник", guide, {}),
            ("Статистика", stats, {}),
        ]
        + extra,
    )
    return {
        "version": 2,
        "candidates": 1000,
        "human_first": 200,
        "auto_later": 800,
        "human_approved": 0,
        "sft_admitted": 0,
    }


def table(path, name, headers, *, expected_ids=None):
    raw = read(path, sheet=name)
    if [raw[0].get(col(i + 1), "") for i in range(len(headers))] != headers:
        raise ValueError("Unknown worksheet schema: " + name)
    result = {}
    for cells in raw[1:]:
        if not any(cells.values()):
            continue
        id = cells.get("A")
        if id in result:
            raise ValueError("Duplicate scenario ID")
        result[id] = [cells.get(col(i + 1), "") for i in range(len(headers))]
    if set(result) != (expected_ids if expected_ids is not None else {r["id"] for r in rows_v2()}):
        raise ValueError("Changed or missing scenario IDs")
    return result


def merge_values(a, b, name):
    if a and b and a != b:
        raise ValueError("Conflicting " + name + " between worksheets")
    return a or b


def import_review(path, output, *, reviewer="", confirm_human=False):
    actions, replies = (
        table(path, "Действия игроков", ACTION_HEADERS),
        table(path, "Ответы мастера", REPLY_HEADERS),
    )
    defaults_a = {r[0]: r for r in base_actions()}
    defaults_b = {r[0]: r for r in base_replies()}
    corpora = {
        "action_labels": [],
        "narrator_reviews": [],
        "verified_episodes": [],
        "math_conflicts": [],
    }
    for source in rows_v2():
        id = source["id"]
        a, b = actions[id], replies[id]
        a[13], b[5] = a[13].replace("−", "-"), b[5].replace("−", "-")
        if any(a[n] != str(defaults_a[id][n]) for n in (0, 1, 2, 3, 4, 5, 18, 19, 21)) or any(
            b[n] != defaults_b[id][n] for n in (0, 1, 2, 9)
        ):
            raise ValueError("Original facts changed: " + id)
        for n in (6, 7):
            if a[n] and a[n] not in DECISIONS:
                raise ValueError("Invalid decision label")
        if a[8] and a[8] not in ("Да", "Нет", "Неясно"):
            raise ValueError("Invalid D20 label")
        if any(v and v not in ("+", "-") for v in (a[13], b[5])):
            raise ValueError("Invalid +/- label")
        if any(v and v not in ERROR_RU.values() for v in (a[20], b[6])):
            raise ValueError("Invalid error category")
        statuses = []
        for label, author in ((a[16], a[17]), (b[11], b[10])):
            if label not in STATUS_RU.values() or label == STATUS_RU["TRAIN_ADMITTED"]:
                raise ValueError("Invalid approval status")
            status = next(k for k, v in STATUS_RU.items() if v == label)
            if status in ("HUMAN_APPROVED", "HUMAN_REJECTED") and (
                not confirm_human or not reviewer or author != reviewer
            ):
                raise ValueError("Explicit matching human reviewer required")
            statuses.append(status)
        if set(statuses) == {"HUMAN_APPROVED", "HUMAN_REJECTED"}:
            raise ValueError("Conflicting review statuses")
        rating = merge_values(a[13], b[5], "rating")
        response = merge_values(a[12], b[4], "response")
        correction = merge_values(a[15], b[8], "correction")
        reason = merge_values(a[14], b[7], "reason")
        error = merge_values(a[20], b[6], "error category")
        common = {
            "scenario_id": id,
            "family": source["family"],
            "source": source["source"],
            "synthetic": True,
            "sft_admitted": False,
        }
        if any(a[n] for n in (6, 7, 8, 9, 10, 11)):
            if statuses[0] == "HUMAN_APPROVED" and not all(a[n] for n in (6, 7, 8)):
                raise ValueError("Approved action needs possibility, reachability and D20 decision")
            corpora["action_labels"].append(
                common
                | {
                    "schema_version": "action-annotation-v2",
                    "attempt_possible": DECISIONS.get(a[6]),
                    "goal_reachable": DECISIONS.get(a[7]),
                    "d20_required": a[8],
                    "outcomes": a[9],
                    "risks": a[10],
                    "consequences": a[11],
                    "review_status": statuses[0],
                    "reviewer": a[17],
                }
            )
        if any((rating, response, correction, reason, error, b[3])) or statuses[1] != "UNLABELED":
            narrator_status = statuses[1]
            if narrator_status == "UNLABELED" and any((a[12], a[13], a[15])):
                narrator_status = statuses[0]
            if narrator_status == "HUMAN_APPROVED" and (not rating or not response):
                raise ValueError("Reviewed answer needs a response and rating")
            corpora["narrator_reviews"].append(
                common
                | {
                    "schema_version": "narrator-review-v2",
                    "reply": response,
                    "rating": rating,
                    "error_type": error,
                    "reason": reason,
                    "corrected_reply": correction,
                    "described_outcome": b[3],
                    "review_status": narrator_status,
                    "reviewer": b[10] or a[17],
                }
            )
    from rpg_vkr.domain.strategic_conflicts import FoodState, food_options

    options = food_options(FoodState())
    conflict_rows = table(
        path,
        "Конфликтные ситуации",
        CONFLICT_HEADERS,
        expected_ids={"food_v2_" + k for k in options},
    )
    conflict_reviews = {}
    for policy, calculation in options.items():
        row = conflict_rows["food_v2_" + policy]
        expected = [
            "Пища100; жители70; гарнизон50; казна40; поставщик20 за30",
            policy,
            calculation["allocation"]["civilians"],
            calculation["allocation"]["guards"],
            calculation["after"]["treasury"],
            json.dumps(calculation["utilities"], ensure_ascii=False),
            "Да" if calculation["pareto"] else "Нет",
        ]
        if row[1:8] != [str(v) for v in expected]:
            raise ValueError("Calculated conflict facts changed")
        rating = row[8].replace("−", "-")
        if rating not in ("", "+", "-"):
            raise ValueError("Invalid conflict rating")
        conflict_reviews[policy] = {
            "rating": rating or None,
            "comment": row[9],
            "human_approved": bool(rating and confirm_human and reviewer),
            "reviewer": reviewer if rating and confirm_human else "",
        }
    corpora["math_conflicts"] = [
        {
            "schema_version": "calculated-conflict-v1",
            "source": "PYTHON_AUTHORED_SCENARIO",
            "scenario_id": "food_v2_" + k,
            "calculation": v,
            "synthetic": True,
            "human_approved": conflict_reviews[k]["human_approved"],
            "review": conflict_reviews[k],
            "sft_admitted": False,
        }
        for k, v in options.items()
    ]
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    for name, rows in corpora.items():
        with (output / (name + ".jsonl")).open("x", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    report = {
        "schema": "annotation-import-v2",
        "counts": {k: len(v) for k, v in corpora.items()},
        "sft_admitted": 0,
        "workbook_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
    }
    (output / "manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--input", type=Path)
    p.add_argument("--carry-from", type=Path)
    p.add_argument("--reviewer", default="")
    p.add_argument("--confirm-human-review", action="store_true")
    a = p.parse_args()
    print(
        json.dumps(
            import_review(
                a.input, a.output, reviewer=a.reviewer, confirm_human=a.confirm_human_review
            )
            if a.input
            else export(a.output, carry_from=a.carry_from),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
