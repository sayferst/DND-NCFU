"""SQLite projection of one complete campaign, with bounded parameterized retrieval."""

import json
import re
import sqlite3
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

from rpg_vkr.domain.combat import ACTORS
from rpg_vkr.domain.director import known_facts
from rpg_vkr.domain.social import grievance
from rpg_vkr.domain.world import LOCATIONS, inventory_text
from rpg_vkr.narrative.examples import EXAMPLES


class CampaignIndex:
    def __init__(self, session):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript("""
            CREATE TABLE snapshot(version INTEGER, payload TEXT);
            CREATE TABLE entities(id TEXT PRIMARY KEY, kind TEXT, location TEXT, payload TEXT);
            CREATE TABLE facts(subject TEXT, key TEXT, value TEXT, visibility TEXT,
                               PRIMARY KEY(subject,key));
            CREATE TABLE events(turn INTEGER PRIMARY KEY, location TEXT, player TEXT,
                                result TEXT, source TEXT);
            CREATE TABLE relationships(actor TEXT PRIMARY KEY, payload TEXT);
            CREATE TABLE inventory(owner TEXT PRIMARY KEY, payload TEXT);
            CREATE TABLE examples(id INTEGER PRIMARY KEY, tags TEXT, text TEXT, license TEXT);
            CREATE TABLE objects(id TEXT PRIMARY KEY, name TEXT, holder TEXT, owner TEXT,
                                 quantity INTEGER, container INTEGER);
            CREATE TABLE places(id TEXT PRIMARY KEY, name TEXT, parent TEXT, anchor TEXT,
                                description TEXT);
        """)
        self.location = session.current_place_id

        def dump(value):
            return json.dumps(value, ensure_ascii=False)

        self.db.execute("INSERT INTO snapshot VALUES (?,?)", (21, dump(session.to_dict())))
        from rpg_vkr.storage.catalog import populate_catalog

        populate_catalog(self.db, session)
        if session.interactive_world:
            state = session.interactive_world
            self.db.executemany(
                "INSERT INTO objects VALUES (?,?,?,?,?,?)",
                [
                    (t.id, t.name, t.holder, t.owner, t.quantity, int(t.container))
                    for t in state.things
                ],
            )
            self.db.executemany(
                "INSERT INTO places VALUES (?,?,?,?,?)",
                [(p.id, p.name, p.parent, p.anchor, p.description) for p in state.places],
            )
        self.db.execute(
            "INSERT INTO entities VALUES (?,?,?,?)",
            ("hero", "hero", self.location, dump(asdict(session.character))),
        )
        for key, name in LOCATIONS.items():
            self.db.execute(
                "INSERT INTO entities VALUES (?,?,?,?)", (key, "place", key, dump({"name": name}))
            )
        from rpg_vkr.narrative.dialogue import GOALS, activity

        for key, (name, location, *_) in ACTORS.items():
            profile = session.campaign.profile(key)
            value = {"name": name, "public_profile": profile.to_dict() if profile else None}
            if key in GOALS:
                value.update(goal=GOALS[key], activity=activity(session, key))
            if session.interactive_world and any(
                t.owner == key and session.interactive_world.root_holder(t) != key
                for t in session.interactive_world.things
            ):
                value.update(
                    activity="Её или его собственность больше не находится при владельце.",
                    goal="Вернуть свою собственность и разобраться в случившемся.",
                )
            self.db.execute(
                "INSERT INTO entities VALUES (?,?,?,?)", (key, "actor", location, dump(value))
            )
            state = session.combat.actor(key)
            self.db.execute(
                "INSERT INTO relationships VALUES (?,?)",
                (
                    key,
                    dump(
                        {
                            "disposition": state.disposition,
                            "grievance": grievance(session.turns, key),
                        }
                    ),
                ),
            )
        for (subject, key), value in known_facts(session.turns).items():
            self.db.execute("INSERT INTO facts VALUES (?,?,?,?)", (subject, key, value, "public"))
        for i, turn in enumerate(session.turns, 1):
            scene = turn.scene
            self.db.execute(
                "INSERT INTO events VALUES (?,?,?,?,?)",
                (
                    i,
                    scene.location if scene else "",
                    turn.action,
                    turn.text,
                    scene.model if scene else "rules",
                ),
            )
        self.db.execute(
            "INSERT INTO inventory VALUES (?,?)", ("hero", inventory_text(session.world))
        )
        self.db.executemany(
            "INSERT INTO examples VALUES (?,?,?,?)",
            [(i, tags, text, "project-original") for i, (tags, text) in enumerate(EXAMPLES)],
        )
        self.db.commit()

    def close(self):
        self.db.close()

    def retrieve(self, text, *, budget=6000):
        if type(budget) is not int or not 1000 <= budget <= 12000:
            raise ValueError("Invalid memory budget")
        tokens = tuple(dict.fromkeys(re.findall(r"[а-яё]{4,}", text.casefold())))[:12]
        patterns = ["%" + word[:6] + "%" for word in tokens]
        result = {"facts": [], "events": [], "examples": [], "npcs": []}
        for row in self.db.execute(
            """
            SELECT subject,key,value FROM facts WHERE visibility='public' AND
            (subject=? OR subject IN (SELECT id FROM entities WHERE location=?))
            ORDER BY subject,key LIMIT 20""",
            (self.location, self.location),
        ):
            result["facts"].append(dict(zip(("subject", "key", "value"), row, strict=True)))
        # Matching old events supplement the last turns, rather than sending the whole journal.
        seen = set()
        for pattern in patterns:
            for turn, player, value, source in self.db.execute(
                """
                SELECT turn,player,result,source FROM events WHERE player LIKE ? OR result LIKE ?
                ORDER BY turn DESC LIMIT 2""",
                (pattern, pattern),
            ):
                if turn not in seen:
                    seen.add(turn)
                    result["events"].append(
                        {
                            "turn": turn,
                            "player": player[:180],
                            "source": source,
                            **({"result": value[:500]} if source == "rules" else {}),
                        }
                    )
                if len(result["events"]) >= 4:
                    break
            if len(result["events"]) >= 4:
                break
        for row in self.db.execute(
            "SELECT id,payload FROM entities WHERE kind=? AND location=?", ("actor", self.location)
        ):
            relation = self.db.execute(
                "SELECT payload FROM relationships WHERE actor=?", (row[0],)
            ).fetchone()
            result["npcs"].append(
                {
                    "id": row[0],
                    **json.loads(row[1]),
                    "relationship": json.loads(relation[0]) if relation else {},
                }
            )
        for pattern in patterns:
            for _idx, value in self.db.execute(
                "SELECT id,text FROM examples WHERE tags LIKE ?", (pattern,)
            ):
                if value not in result["examples"]:
                    result["examples"].append(value)
            if len(result["examples"]) >= 2:
                break
        result["examples"] = result["examples"][:2]
        # Drop complete records, never truncate serialized JSON into invalid text.
        for key in ("events", "examples", "npcs", "facts"):
            while len(json.dumps(result, ensure_ascii=False)) > budget and result[key]:
                result[key].pop()
        return result

    def export(self, path):
        path = Path(path)
        # Exclusive creation prevents overwriting a save or another user's database.
        with path.open("xb"):
            pass
        try:
            with closing(sqlite3.connect(path)) as target:
                self.db.backup(target)
        except Exception:
            path.unlink(missing_ok=True)
            raise


def retrieve(session, text):
    index = CampaignIndex(session)
    try:
        return index.retrieve(text)
    finally:
        index.close()


def export_session(session, path):
    index = CampaignIndex(session)
    try:
        index.export(path)
    finally:
        index.close()


def restore_session(path):
    from rpg_vkr.application import Session

    path = Path(path).resolve()
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("Campaign database too large")
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA trusted_schema=OFF")
        values = db.execute("SELECT version,payload FROM snapshot LIMIT 2").fetchall()
        if (
            len(values) != 1
            or values[0][0] not in (12, 13, 14, 15, 16, 17, 18, 19, 20, 21)
            or len(values[0][1]) > 32 * 1024 * 1024
        ):
            raise ValueError("Invalid campaign snapshot")
        return Session.from_dict(json.loads(values[0][1]), version=values[0][0])
