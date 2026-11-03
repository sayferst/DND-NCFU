"""Overlay AI-proposed decisions onto a COPY of the pristine v2 workbook.

Safe by default: validates source IDs/facts, preserves v2 templates and replies,
does not overwrite existing human annotations and never marks human approval/SFT.
Requires openpyxl. Run from repository root:
python -m training.apply_ai_review_proposals
  --input docs/intelligent_gm/scenarios-1000-v2.xlsx
  --proposals docs/intelligent_gm/annotation_proposals_R01_R14_1000_v3.jsonl
  --output ../DND-NCFU-data/annotation/scenarios-owner-R01-R14-proposed.xlsx
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

ACTION_SHEET = "Действия игроков"
REPLY_SHEET = "Ответы мастера"
SCHEMA = "dnd-ncfu-annotation-proposal-v3"
VALID_ACTION = {"Да", "Нет", "Неясно"}
VALID_GOAL = {"Да", "Нет", "Частично", "Неясно"}
VALID_D20 = {"Да", "Нет", "Неясно"}
VALID_STATUS = {"Предложено ИИ", "Нужна проверка"}
RULES = {
    "R01": "Заявление действия = согласие на обычный риск; мастер предупреждает.",
    "R02": "Характеристика зависит от действия, способа, навыка и инструмента.",
    "R03": "Последствия провала пропорциональны риску.",
    "R04": "Осознанное магическое перенапряжение за HP/истощение возможно.",
    "R05": "Физический держатель и законный собственник могут различаться.",
    "R06": "Нат.20 — наилучший возможный исход; нат.1 — осложнение.",
    "R07": "0 HP — потеря сознания и проверки смерти.",
    "R08": "Подходящая заранее объявленная несмертельная ближняя атака.",
    "R09": "Разумное предложение + успешное Убеждение = согласие сторон.",
    "R10": "2 HP/недостающий MP или 1 истощение на каждые 2 MP; Аркана DC10+2×нехватка; предел 3 MP; плата при провале.",
    "R11": "Первая помощь стабилизирует без HP, лечение ≥1 HP пробуждает живого.",
    "R12": "Воскрешение — специальное известное заклинание или подтверждённый дорогой ритуал.",
    "R13": "Death saves 10+; 3 успеха/провала; нат.1=2 провала, нат.20=1 HP; Медицина DC10.",
    "R14": "Выполнимость, полномочия и жизненные ограничения перед Убеждением.",
}

def read_proposals(path: Path):
    rows = []
    seen = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        obj = json.loads(line)
        if obj.get("schema") != SCHEMA or obj.get("ordinal") != number:
            raise ValueError(f"Invalid schema/sequence at proposal {number}")
        original, proposed = obj["original"], obj["proposal"]
        rid = obj["id"]
        if rid in seen:
            raise ValueError("Duplicate scenario ID: " + rid)
        seen.add(rid)
        if not (obj["human_approved"] is False and obj["sft_admitted"] is False
                and obj["reviewer"] == "" and obj["review_status"] in VALID_STATUS):
            raise ValueError("Proposal must not impersonate human approval: " + rid)
        if (proposed["attempt_possible"] not in VALID_ACTION
            or proposed["goal_reachable"] not in VALID_GOAL
            or proposed["d20_required"] not in VALID_D20):
            raise ValueError("Invalid label in " + rid)
        if (original["source"] != "PROJECT_AUTHORED_SYNTHETIC"
            or original["synthetic"] is not True):
            raise ValueError("Unknown scenario provenance in " + rid)
        if not all(name in RULES for name in proposed["applied_rules"]):
            raise ValueError("Unknown rule in " + rid)
        rows.append(obj)
    if len(rows) != 1000 or len(seen) != 1000:
        raise ValueError(f"Expected 1000 unique proposals, got {len(rows)}")
    if sum(r["original"]["review_track"] == "HUMAN_FIRST" for r in rows) != 200:
        raise ValueError("Expected exactly 200 HUMAN_FIRST proposals")
    return rows


def assert_pristine(ws, records):
    if ws.max_row < 1001:
        raise ValueError("Workbook is missing required scenario rows")
    headers = ["ID", "Семейство", "Ситуация", "Предметы", "Навыки", "Действие игрока"]
    for col, header in enumerate(headers, 1):
        if ws.cell(1, col).value != header:
            raise ValueError(f"Unexpected header in column {col}")
    for n, obj in enumerate(records, 2):
        orig, rid = obj["original"], obj["id"]
        expected = (rid, orig["category"], orig["context"], orig["items"], orig["skills"], orig["action"])
        actual = tuple(ws.cell(n, col).value for col in range(1, 7))
        if actual != expected:
            raise ValueError(f"Original scenario facts differ at row {n}: {rid}")
        if ws.cell(n, 20).value != orig["source"]:
            raise ValueError("Source/provenance changed at " + rid)
        expected_track = "Сначала человеку" if orig["review_track"] == "HUMAN_FIRST" else "Автопредложение"
        if ws.cell(n, 19).value != expected_track:
            raise ValueError("Human-first selection mismatch at " + rid)
        if int(ws.cell(n, 22).value) != orig["condition_type"]:
            raise ValueError("Condition type mismatch at " + rid)
        if any(ws.cell(n, col).value not in (None, "") for col in range(7, 17)):
            raise ValueError("Existing owner annotations detected, refusing overwrite: " + rid)
        if ws.cell(n, 17).value not in ("Не размечено", None, ""):
            raise ValueError("Nonempty review status detected: " + rid)
        if ws.cell(n, 18).value not in (None, ""):
            raise ValueError("Human reviewer detected: " + rid)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("docs/intelligent_gm/scenarios-1000-v2.xlsx"))
    parser.add_argument("--proposals", type=Path, default=Path("docs/intelligent_gm/annotation_proposals_R01_R14_1000_v3.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("../DND-NCFU-data/annotation/scenarios-owner-R01-R14-proposed.xlsx"))
    args = parser.parse_args()
    records = read_proposals(args.proposals)
    if args.output.resolve() == args.input.resolve() or args.output.exists():
        raise ValueError("Refusing to overwrite workbook or existing output")
    book = load_workbook(args.input)
    for name in (ACTION_SHEET, REPLY_SHEET, "Конфликтные ситуации"):
        if name not in book.sheetnames:
            raise ValueError("Required worksheet missing: " + name)
    ws = book[ACTION_SHEET]
    assert_pristine(ws, records)
    summary = Counter()
    for rownum, obj in enumerate(records, 2):
        ann, issues = obj["proposal"], obj["unresolved"]
        ws.cell(rownum, 7).value = ann["attempt_possible"]
        ws.cell(rownum, 8).value = ann["goal_reachable"]
        ws.cell(rownum, 9).value = ann["d20_required"]
        ws.cell(rownum, 10).value = ann["possible_outcomes"]
        ws.cell(rownum, 11).value = (
            ann["limitations_and_risks"]
            + (" | НЕОПРЕДЕЛЁННО: " + "; ".join(issues) if issues else "")
        )[:10000]
        ws.cell(rownum, 12).value = ann["consequences_and_spend"]
        ws.cell(rownum, 17).value = obj["review_status"]
        summary[obj["review_status"]] += 1
    issues_sheet = book.create_sheet("Спорные случаи R14")
    issues_sheet.append(["№", "ID", "Действие", "Вариант условий", "Что не подтверждено", "Режим", "Приоритет"])
    for obj in records:
        if not obj["unresolved"]:
            continue
        orig = obj["original"]
        issues_sheet.append([
            obj["ordinal"], obj["id"], orig["action"], orig["condition_type"],
            " | ".join(obj["unresolved"]), obj["proposal"]["execution_mode"],
            orig["review_track"],
        ])
    protocol_sheet = book.create_sheet("Правила R01-R14")
    protocol_sheet.append(["Правило", "Утверждённое содержание"])
    for rule, description in RULES.items():
        protocol_sheet.append([rule, description])
    protocol_sheet.append(["STATUS", "Все оценки — предложения ИИ. Никакие строки не подтверждены человеком."])
    protocol_sheet.append(["SFT", "Подтверждённых игровых квитанций нет; SFT admission = 0."])
    for extra in (issues_sheet, protocol_sheet):
        extra.freeze_panes = "A2"
        extra.auto_filter.ref = extra.dimensions
        for cell in extra[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="234267")
        for row in extra.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = Alignment(vertical="top", wrap_text=True)
    for c, w in {"A": 9, "B": 34, "C": 58, "D": 22, "E": 90, "F": 28, "G": 19}.items():
        issues_sheet.column_dimensions[c].width = w
    protocol_sheet.column_dimensions["A"].width = 15
    protocol_sheet.column_dimensions["B"].width = 110
    args.output.parent.mkdir(parents=True, exist_ok=True)
    book.save(args.output)
    print(json.dumps({"status": "WRITTEN_AI_PROPOSALS", "output": str(args.output),
                      "proposals": len(records), "human_approved": 0, "sft_admitted": 0,
                      "statuses": dict(summary)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
