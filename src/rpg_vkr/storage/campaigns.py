"""Durable per-campaign snapshots and indexed, bounded recall without replaying prose."""

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from rpg_vkr.storage.catalog import live_records

APPLICATION_ID = 1145980237


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class CampaignRepository:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        created = False
        try:
            with self.path.open("xb"):
                created = True
        except FileExistsError:
            pass
        with closing(sqlite3.connect(self.path)) as db, db:
            if not created and db.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
                raise ValueError("По пути памяти находится другая база; файл не изменён.")
            db.execute(f"PRAGMA application_id={APPLICATION_ID}")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS model_calls(
                    id TEXT PRIMARY KEY, campaign TEXT NOT NULL, event_type TEXT NOT NULL,
                    outcome TEXT NOT NULL, code TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS model_calls_campaign ON model_calls(campaign);
                CREATE TABLE IF NOT EXISTS campaigns(
                    id TEXT PRIMARY KEY, hero TEXT NOT NULL, title TEXT NOT NULL,
                    revision INTEGER NOT NULL, digest TEXT NOT NULL, payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL, schema_version INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS events(
                    id TEXT PRIMARY KEY, campaign TEXT NOT NULL, turn INTEGER NOT NULL,
                    action TEXT NOT NULL, result TEXT NOT NULL, source TEXT NOT NULL,
                    payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS current_events(
                    campaign TEXT NOT NULL, turn INTEGER NOT NULL, event TEXT NOT NULL,
                    PRIMARY KEY(campaign,turn));
                CREATE TABLE IF NOT EXISTS facts(
                    id TEXT PRIMARY KEY, campaign TEXT NOT NULL, subject TEXT NOT NULL,
                    kind TEXT NOT NULL, text TEXT NOT NULL, search_text TEXT NOT NULL,
                    importance INTEGER NOT NULL, private INTEGER NOT NULL, turn INTEGER NOT NULL,
                    source TEXT NOT NULL, active INTEGER NOT NULL);
                CREATE INDEX IF NOT EXISTS facts_recall
                    ON facts(campaign,active,private,importance);
                CREATE INDEX IF NOT EXISTS facts_subject ON facts(campaign,subject,active);
                CREATE TABLE IF NOT EXISTS diary(
                    campaign TEXT NOT NULL, id TEXT NOT NULL, title TEXT NOT NULL,
                    text TEXT NOT NULL,
                    place TEXT NOT NULL, turn INTEGER NOT NULL, pinned INTEGER NOT NULL,
                    search_text TEXT NOT NULL,
                    PRIMARY KEY(campaign,id));
                CREATE TABLE IF NOT EXISTS entity_cards(
                    campaign TEXT NOT NULL, id TEXT NOT NULL, kind TEXT NOT NULL,
                    place TEXT NOT NULL, payload TEXT NOT NULL, search_text TEXT NOT NULL,
                    PRIMARY KEY(campaign,id));
                CREATE INDEX IF NOT EXISTS cards_place ON entity_cards(campaign,place);
                CREATE TABLE IF NOT EXISTS transcripts(
                    campaign TEXT NOT NULL, ordinal INTEGER NOT NULL, turn INTEGER NOT NULL,
                    text TEXT NOT NULL, search_text TEXT NOT NULL,
                    PRIMARY KEY(campaign,ordinal));
                CREATE INDEX IF NOT EXISTS transcripts_turn ON transcripts(campaign,turn);
            """)
        self._last_token = None
        self._retained = None

    @staticmethod
    def identity(session):
        return session.campaign.world_id + ":" + session.campaign.hero_id

    def record_model_call(self, session, event):
        # Store only an explicit safe projection, never arbitrary client payloads.
        fields = {
            "id",
            "turn_id",
            "timestamp_utc",
            "event_type",
            "stage",
            "attempt",
            "model",
            "elapsed_ms",
            "outcome",
            "code",
            "reason",
            "finish_reason",
            "usage",
            "warnings",
            "world_committed",
        }
        value = {k: v for k, v in event.items() if k in fields}
        if value.get("event_type") not in {"model_response", "prose_validation"}:
            raise ValueError("Unknown model metric")
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "INSERT OR IGNORE INTO model_calls VALUES (?,?,?,?,?,?)",
                (
                    value["id"],
                    self.identity(session),
                    value["event_type"],
                    value["outcome"],
                    value.get("code", ""),
                    dump(value),
                ),
            )

    def model_stats(self, session):
        with closing(sqlite3.connect(self.path)) as db:
            rows = db.execute(
                "SELECT event_type,outcome,code,COUNT(*) FROM model_calls "
                "WHERE campaign=? GROUP BY event_type,outcome,code",
                (self.identity(session),),
            ).fetchall()
        return [{"event_type": t, "outcome": o, "code": c, "count": n} for t, o, c, n in rows]

    def sync(self, session):
        token = (
            id(session),
            len(session.turns),
            len(session.narrations),
            id(session.world),
            id(session.character),
            id(session.catalog),
            id(session.interactive_world),
            id(session.chronicle),
            session._d20_progress,
        )
        if token == self._last_token:
            return
        payload = dump(session.to_dict())
        if len(payload.encode()) > 32 * 1024 * 1024:
            raise ValueError("Снимок кампании превысил 32 МБ; сохраните отдельный архив.")
        digest = hashlib.sha256(payload.encode()).hexdigest()
        campaign = self.identity(session)
        title = (
            session.chronicle.seed.title
            if session.generated_world
            else "Мир ещё не создан"
            if session.progress.enabled
            else "Учебная кампания"
        )
        types, entities = live_records(session)
        with closing(sqlite3.connect(self.path)) as db, db:
            previous = db.execute(
                "SELECT revision,digest FROM campaigns WHERE id=?", (campaign,)
            ).fetchone()
            if previous and previous[1] == digest:
                db.execute("UPDATE campaigns SET title=? WHERE id=?", (title, campaign))
                self._last_token = token
                self._retained = (
                    session,
                    session.world,
                    session.character,
                    session.catalog,
                    session.interactive_world,
                    session.chronicle,
                )
                return
            revision = previous[0] + 1 if previous else 1
            db.execute(
                "INSERT OR REPLACE INTO campaigns VALUES (?,?,?,?,?,?,?,?)",
                (
                    campaign,
                    session.character.name,
                    title,
                    revision,
                    digest,
                    payload,
                    datetime.now(UTC).isoformat(),
                    session.schema_version,
                ),
            )
            db.execute("DELETE FROM current_events WHERE campaign=?", (campaign,))
            db.execute("DELETE FROM transcripts WHERE campaign=?", (campaign,))
            db.executemany(
                "INSERT INTO transcripts VALUES (?,?,?,?,?)",
                [
                    (campaign, i, n.turn_index, n.text, n.text.casefold())
                    for i, n in enumerate(session.narrations)
                ],
            )
            chain = campaign
            for i, turn in enumerate(session.to_dict()["turns"], 1):
                raw = dump(turn)
                chain = hashlib.sha256((chain + raw).encode()).hexdigest()
                db.execute(
                    "INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?,?)",
                    (
                        chain,
                        campaign,
                        i,
                        turn["action"],
                        turn["text"],
                        "story" if turn["scene"] else "engine",
                        raw,
                    ),
                )
                db.execute("INSERT INTO current_events VALUES (?,?,?)", (campaign, i, chain))
            db.execute("UPDATE facts SET active=0 WHERE campaign=?", (campaign,))
            for note in session.chronicle.memories if session.chronicle else ():
                fact_id = hashlib.sha256((campaign + dump(asdict(note))).encode()).hexdigest()
                db.execute(
                    "INSERT OR REPLACE INTO facts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        fact_id,
                        campaign,
                        note.subject,
                        note.kind,
                        note.text,
                        (note.subject + " " + note.text).casefold(),
                        note.importance,
                        int(note.private),
                        note.turn,
                        note.source,
                        1,
                    ),
                )
            db.execute("DELETE FROM diary WHERE campaign=?", (campaign,))
            for entry in session.chronicle.entries if session.chronicle else ():
                db.execute(
                    "INSERT INTO diary VALUES (?,?,?,?,?,?,?,?)",
                    (
                        campaign,
                        entry.id,
                        entry.title,
                        entry.text,
                        entry.place,
                        entry.turn,
                        int(entry.pinned),
                        (entry.title + " " + entry.text + " " + entry.place).casefold(),
                    ),
                )
            db.execute("DELETE FROM entity_cards WHERE campaign=?", (campaign,))
            db.executemany(
                "INSERT INTO entity_cards VALUES (?,?,?,?,?,?)",
                [
                    (
                        campaign,
                        e["id"],
                        types[e["definition_id"]]["kind"],
                        e["parent_id"],
                        dump({"definition": types[e["definition_id"]], "entity": e}),
                        (
                            e["id"]
                            + " "
                            + types[e["definition_id"]]["name"]
                            + " "
                            + str(e["state"].get("life", ""))
                        ).casefold(),
                    )
                    for e in entities.values()
                ],
            )
        self._last_token = token
        self._retained = (
            session,
            session.world,
            session.character,
            session.catalog,
            session.interactive_world,
            session.chronicle,
        )

    def recall(self, session, text, *, private=False, budget=10000):
        if (
            not isinstance(text, str)
            or len(text) > 6000
            or type(budget) is not int
            or not 1000 <= budget <= 16000
        ):
            raise ValueError("Неверный запрос памяти.")
        self.sync(session)
        campaign = self.identity(session)
        tokens = list(dict.fromkeys(re.findall(r"[a-zа-яё0-9_]{3,}", text.casefold())))[:10]
        terms = " OR ".join("search_text LIKE ?" for _ in tokens) or "0"
        parameters = ["%" + t + "%" for t in tokens]
        with closing(sqlite3.connect(self.path)) as db:
            facts = db.execute(
                "SELECT subject,kind,text,importance,turn,source FROM facts "
                "WHERE campaign=? AND active=1 AND (? OR private=0) AND "
                f"(importance>=4 OR {terms}) ORDER BY importance DESC,turn DESC LIMIT 12",
                (campaign, int(private), *parameters),
            ).fetchall()
            diary = db.execute(
                "SELECT title,text,place,turn FROM diary WHERE campaign=? "
                f"AND (pinned=1 OR {terms}) "
                "ORDER BY pinned DESC,turn DESC LIMIT 5",
                (campaign, *parameters),
            ).fetchall()
            cards = db.execute(
                "SELECT payload,place FROM entity_cards WHERE campaign=? AND "
                f"(place=? OR {terms}) ORDER BY (place=?) DESC LIMIT 8",
                (campaign, session.current_place_id, *parameters, session.current_place_id),
            ).fetchall()
            recent = db.execute(
                "SELECT e.action,e.result,e.source FROM current_events c JOIN "
                "events e ON e.id=c.event "
                "WHERE c.campaign=? ORDER BY c.turn DESC LIMIT 3",
                (campaign,),
            ).fetchall()
            conversations = db.execute(
                "SELECT turn,text FROM transcripts WHERE campaign=? AND "
                f"({terms}) ORDER BY turn DESC LIMIT 3",
                (campaign, *parameters),
            ).fetchall()
        result = {
            "entity_states": [],
            "past_conversations": [
                {"turn": t, "text": s[:700], "source": "recorded-narration"}
                for t, s in conversations
            ],
            "facts": [
                dict(
                    zip(("subject", "kind", "text", "importance", "turn", "source"), r, strict=True)
                )
                for r in facts
            ],
            "hero_notes": [
                dict(
                    zip(
                        ("title", "text", "place", "turn"),
                        (r[0], r[1][:700], r[2], r[3]),
                        strict=True,
                    )
                )
                for r in diary
            ],
            "recent": [
                {"player": a[:250], "result": b[:450], "source": s} for a, b, s in reversed(recent)
            ],
        }
        for raw, place in cards:
            card = json.loads(raw)
            if not private and place not in {*session.visited_places, "hero"}:
                continue
            if not private and card["definition"]["kind"] == "actor":
                card["definition"]["properties"] = {
                    k: v
                    for k, v in card["definition"]["properties"].items()
                    if k in {"appearance", "public_description", "ancestry"}
                }
                card["definition"]["loot"] = []
                card["entity"]["state"] = {
                    k: v
                    for k, v in card["entity"]["state"].items()
                    if k in {"life", "disposition", "public_description"}
                }
            result["entity_states"].append(card)
        if private and session.generated_world:
            result["private_plot"] = session.chronicle.seed.private_plot
        for key in ("recent", "past_conversations", "entity_states", "facts", "hero_notes"):
            while len(dump(result)) > budget and result[key]:
                result[key].pop()
        if len(dump(result)) > budget:
            result["private_plot"] = result.get("private_plot", "")[: budget // 2]
        return result

    def list_campaigns(self):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute(
                "SELECT id,hero,title,updated_at FROM campaigns ORDER BY updated_at DESC LIMIT 50"
            ).fetchall()

    def load(self, id):
        from rpg_vkr.application import Session

        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute(
                "SELECT payload,digest,schema_version FROM campaigns WHERE id=?", (id,)
            ).fetchone()
        if (
            not row
            or len(row[0].encode()) > 32 * 1024 * 1024
            or hashlib.sha256(row[0].encode()).hexdigest() != row[1]
        ):
            raise ValueError("Снимок кампании отсутствует или повреждён.")
        return Session.from_dict(json.loads(row[0]), version=row[2])
