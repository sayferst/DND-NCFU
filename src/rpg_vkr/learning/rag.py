"""Small CPU retriever with approval gates; methods are never facts of a campaign."""

import json
import re
import sqlite3

CARDS = (
    (
        "inspect",
        "осмотр вещь предмет внешность look inspect",
        "Описывай наблюдаемые свойства. Осмотр не меняет владельца и не означает покупку.",
    ),
    (
        "trade",
        "купить продать цена торг монеты торговец buy sell",
        "Отделяй предложение сделки от её совершения. Итог и расходы бери из квитанции.",
    ),
    (
        "combat",
        "бой удар атака противник сражение attack fight",
        "Описывай подтверждённый исход и самостоятельные действия участников "
        "очереди. Сохраняй право игрока на следующий выбор.",
    ),
    (
        "knowledge",
        "слух тайна знание источник npc rumors",
        "Знание принадлежит конкретному собеседнику. Отмечай источник слуха и "
        "не превращай его в личное наблюдение.",
    ),
    (
        "craft",
        "ремесло рецепт крафт изготовить кузница зелье craft",
        "Карточка рецепта не является готовым изделием. Описывай работу после "
        "подтверждения ресурсов, станции и результата.",
    ),
    (
        "magic",
        "магия заклинание mp мана школа spell magic",
        "Эффект магии ограничен квитанцией: учитывай выбранную цель, расход MP, "
        "компоненты и длительность.",
    ),
    (
        "agency",
        "решить согласиться отказаться обещать хочу выбор",
        "Различай вопрос, намерение, обещание и действие. Оставляй невыбранные решения открытыми.",
    ),
    (
        "continuity",
        "имя встреча персонаж помню ранее npc",
        "Сохраняй имя и личность зарегистрированного NPC; используй его "
        "подтверждённые воспоминания.",
    ),
    (
        "world",
        "день сезон время город фракция мир календарь",
        "Меняй сцену по подтверждённому игровому времени. Автономные события "
        "имеют причины и доступные источники сведений.",
    ),
    (
        "stakes",
        "риск опасность потеря последствие",
        "Покажи конкретные доступные признаки опасности и последствия уже "
        "произошедшего; не назначай исход следующего действия.",
    ),
)


class TechniqueStore:
    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.db.execute(
            "CREATE TABLE cards(id TEXT PRIMARY KEY,tags TEXT,text TEXT,external INTEGER)"
        )
        try:
            self.db.execute("CREATE VIRTUAL TABLE lookup USING fts5(id UNINDEXED,tags,text)")
            self.fts = True
        except sqlite3.OperationalError:
            self.fts = False

    def add(self, record):
        required = {
            "id",
            "tags",
            "text",
            "quality_status",
            "rights_status",
            "approved_for_rag",
            "third_party_transfer_allowed",
            "usable_as_game_fact",
        }
        if (
            not isinstance(record, dict)
            or set(record) != required
            or record["quality_status"] != "human_reviewed"
            and not (
                record["quality_status"] == "project_authored"
                and (record["id"], record["tags"], record["text"]) in CARDS
            )
            or record["rights_status"] not in {"approved_local", "approved_external"}
            or record["approved_for_rag"] is not True
            or record["usable_as_game_fact"] is not False
            or type(record["third_party_transfer_allowed"]) is not bool
        ):
            raise ValueError(
                "В RAG допускаются только отдельно проверенные методы с правами использования."
            )
        for key, limit in [("id", 80), ("tags", 400), ("text", 600)]:
            if (
                not isinstance(record[key], str)
                or not record[key].strip()
                or len(record[key]) > limit
            ):
                raise ValueError("Недопустимая карточка метода.")
        self.db.execute(
            "INSERT INTO cards VALUES(?,?,?,?)",
            (
                record["id"],
                record["tags"],
                record["text"],
                int(
                    record["third_party_transfer_allowed"]
                    and record["rights_status"] == "approved_external"
                ),
            ),
        )
        if self.fts:
            self.db.execute(
                "INSERT INTO lookup VALUES(?,?,?)", (record["id"], record["tags"], record["text"])
            )

    def search(self, query, *, remote=False, limit=3, budget=1200):
        if (
            not isinstance(query, str)
            or len(query) > 6000
            or type(limit) is not int
            or not 1 <= limit <= 3
            or not 100 <= budget <= 1200
        ):
            raise ValueError("Недопустимый запрос к локальной библиотеке.")
        terms = list(dict.fromkeys(re.findall(r"[a-zа-яё]{3,}", query.casefold())))[:24]
        if not terms:
            return []
        if self.fts:
            match = " OR ".join('"' + word + '"*' for word in terms)
            rows = self.db.execute(
                "SELECT c.id,c.text FROM lookup JOIN cards c ON c.id=lookup.id WHERE "
                "lookup MATCH ? AND (?=0 OR c.external=1) ORDER BY bm25(lookup),c.id "
                "LIMIT ?",
                (match, int(remote), limit),
            ).fetchall()
        else:
            rows = self.db.execute(
                "SELECT id,text,tags FROM cards WHERE ?=0 OR external=1 ORDER BY id", (int(remote),)
            ).fetchall()
            rows = sorted(
                rows, key=lambda r: (-sum(t in (r[1] + " " + r[2]).casefold() for t in terms), r[0])
            )
            rows = [
                (r[0], r[1])
                for r in rows
                if any(t in (r[1] + " " + r[2]).casefold() for t in terms)
            ][:limit]
        result = []
        for id, text in rows:
            candidate = result + [
                {
                    "id": id,
                    "source": "project-original-methods-1",
                    "text": text,
                    "kind": "technique_not_fact",
                }
            ]
            if len(json.dumps(candidate, ensure_ascii=False)) <= budget:
                result = candidate
        return result

    def close(self):
        self.db.close()


def retrieve(query, *, remote=False):
    store = TechniqueStore()
    try:
        for id, tags, text in CARDS:
            store.add(
                {
                    "id": id,
                    "tags": tags,
                    "text": text,
                    "quality_status": "project_authored",
                    "rights_status": "approved_external",
                    "approved_for_rag": True,
                    "third_party_transfer_allowed": True,
                    "usable_as_game_fact": False,
                }
            )
        return store.search(query, remote=remote)
    except (sqlite3.Error, ValueError):
        return []
    finally:
        store.close()
