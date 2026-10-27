"""Prepare all canonical corpus cards as compact, non-mechanical references."""

import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

from rpg_vkr.learning.corpus import SCHEMA
from rpg_vkr.learning.package import inspect
from rpg_vkr.learning.quality import CLAIM, fields, safe_excerpt

DENIED = re.compile(
    r"скрыт|секрет|только ведущ|private|secret|участник|состав|мастер|игрок|ход\s*\d|"
    r"квитанц|ресурс|состояни|параметр|брос|ранг|модель|серия|добыч|цепь|приём|"
    r"если удалось|если не удалось|исход|смерт|получ|цена|стоимость|рецепт|формула",
    re.I,
)
BAD_TEXT = re.compile(
    r"https?://|```|<\|.*?\|>|\b(?:вы|герой)\s+(?:обязан|получает)|"
    r"пароль|токен|password|private_plot|secret_gm",
    re.I,
)
FIELDS = {
    "session": {"Место", "Ставки", "Опасность", "Поведенческий профиль", "Граница ответственности"},
    "death_session": {"Аудит разделения ролей"},
    "event_template": {"Место", "Наблюдаемая завязка", "Вариант происшествия"},
    "behavior_template": {
        "Личная цель",
        "Развилка",
        "Пределы и риск",
        "Потребность",
        "Вне боя",
        "Прекращение конфликта",
        "Профессия",
        "Форма",
        "Достоверность текста",
        "Вероятное местонахождение",
        "Направление",
        "Ограничения",
        "Книга навыка",
        "Учебное задание",
        "Неудача",
    },
    "world_template": {
        "Слот",
        "Класс",
        "Экология и характер",
        "Контригра",
        "Группа",
        "Тип",
        "Роль",
        "Текущая цель",
        "Реакция на героя",
        "Уязвимость/другой путь",
        "Разумный вид",
        "Сообщество",
        "Культура и конфликт",
        "Сцена",
        "Недостаток",
        "Безопасное взаимодействие/противодействие",
        "Применение",
        "Направление",
    },
    "everyday_example": {"Сфера", "Материальная условность", "Граница попытки", "Проверка"},
    "crafting_definition": {
        "Происхождение",
        "Опасность и противодействие",
        "Источник",
        "Требования",
        "Условие появления",
        "Обработка",
        "Практическое использование",
        "Практическое применение",
        "Предохранители",
        "Правило мира",
        "Назначение",
        "Категория и вкус",
        "Хранение и риск",
        "Тип",
        "Свойства и применение",
        "Ограничение",
        "Вид",
        "Огранка",
        "Применение",
    },
}


def clean(value, maximum):
    value = re.sub(r"[*`#]", "", value).strip()
    if not safe_excerpt(value) or BAD_TEXT.search(value):
        return ""
    # No imported rolls, ranks, balances or numeric effects in runtime references.
    value = " ".join(
        part.strip()
        for part in re.split(r"(?<=[.!?;])\s+", value)
        if not re.search(r"\d", part) and not CLAIM.search(part)
    )
    if len(value) > maximum:
        value = value[:maximum].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
    return value


def project(record):
    title = re.sub(
        r"^#+\s*(?:(?:#\d+\s*·\s*)?[A-Z]+-\d+\.?|ПАРТИЯ\s+\d+\.|\d+\.)\s*[—-]?\s*",
        "",
        record.title,
        flags=re.I,
    )
    title = clean(title, 110) or record.category
    details = []
    for key, values in fields(record.text).items():
        if key not in FIELDS[record.record_type] or DENIED.search(key):
            continue
        for value in values[:1]:
            # Inline headings cannot smuggle hidden fields into a public field.
            value = value.split("**", 1)[0]
            text = clean(value, 160)
            if text and not DENIED.search(key):
                details.append(f"{key}: {text}")
        if len(details) >= 3:
            break
    text = clean(" ".join(details), 380)
    return title, text or "Тематическая заготовка: " + title


def build(archive, output):
    report, records = inspect(Path(archive))
    if not report["verified"] or len(records) != 19000:
        raise ValueError("Expected the verified 19000-card corpus")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    destination = output / "cards.sqlite3"
    if destination.exists() or (output / "manifest.json").exists():
        raise ValueError("Use a new output directory; never overwrite a prepared version")
    db = sqlite3.connect(destination)
    try:
        db.executescript(
            "PRAGMA application_id=1145979730;"
            "CREATE TABLE cards(id TEXT PRIMARY KEY,local_id TEXT,source TEXT,category TEXT,"
            "title TEXT,excerpt TEXT,search_text TEXT,source_sha256 TEXT,start_line INTEGER,"
            "end_line INTEGER);CREATE INDEX local_ids ON cards(local_id);"
            "CREATE TABLE aliases(id TEXT PRIMARY KEY,target TEXT);"
        )
        try:
            db.execute(
                "CREATE VIRTUAL TABLE lookup USING "
                "fts5(title,excerpt,content='cards',content_rowid='rowid')"
            )
            fts = True
        except sqlite3.OperationalError:
            fts = False
        counts = Counter()
        for record in records:
            title, excerpt = project(record)
            db.execute(
                "INSERT INTO cards VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    record.record_id,
                    record.record_id.rsplit(":", 1)[-1],
                    record.source_id,
                    record.category,
                    title,
                    excerpt,
                    (title + " " + excerpt).casefold(),
                    record.source_sha256,
                    record.start_line,
                    record.end_line,
                ),
            )
            counts[record.source_id] += 1
        for number in range(1, 201):
            db.execute(
                "INSERT INTO aliases VALUES(?,?)",
                (
                    f"USER-SYN-0200:{number:04d}",
                    f"USER-SYN-1000:{number:04d}",
                ),
            )
        if fts:
            db.execute("INSERT INTO lookup(lookup) VALUES('rebuild')")
        db.commit()
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Broken prepared database")
        db.execute("VACUUM")
    finally:
        db.close()
    manifest = {
        "schema": SCHEMA,
        "records": len(records),
        "aliases": 200,
        "fts": fts,
        "archive_sha256": report["archive_sha256"],
        "sources": dict(sorted(counts.items())),
        "database_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        "projection": "public_descriptive_fields_no_hidden_plot_or_numeric_rules_v2",
        "usage": "owner_requested_runtime_reference_not_training_or_human_review",
        "raw_included": False,
        "trained_weights": False,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.input, args.output), ensure_ascii=False))


if __name__ == "__main__":
    main()
