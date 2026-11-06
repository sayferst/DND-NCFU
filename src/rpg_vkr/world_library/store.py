"""Transactional global template CRUD. SQLite default, PostgreSQL opt-in.

An authenticated engine process owns the connection. Do not expose this object,
credentials, or arbitrary SQL to a narrator. No live HP/wallet tables are writable here.
"""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from rpg_vkr.world_library.model import ROOT, digest, dump, normalized, validate_bundle


class Library:
    def __init__(self, connection, *, postgres=False):
        self.db = connection
        self.postgres = postgres

    @classmethod
    def sqlite(cls, path):
        db = sqlite3.connect(path)
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if tables and "wl_migrations" not in tables:
            db.close()
            raise ValueError("Foreign database: choose a new library file")
        db.execute("PRAGMA foreign_keys=ON")
        return cls(db)

    @classmethod
    def postgres(cls, dsn):
        # Optional installation; never imported at game startup.
        import psycopg

        return cls(psycopg.connect(dsn, autocommit=True), postgres=True)

    def close(self):
        self.db.close()

    def execute(self, sql, params=()):
        return self.db.execute(sql.replace("?", "%s") if self.postgres else sql, params)

    @contextmanager
    def transaction(self):
        if self.postgres:
            with self.db.transaction():
                yield
        else:
            if self.db.in_transaction:
                raise ValueError("Nested library transactions are not supported")
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self.db.commit()
            except BaseException:
                self.db.rollback()
                raise

    def migrate(self):
        """Versioned opt-in DDL; no access to application saves."""
        sql = (ROOT / "data/world_library/migrations/001_library.sql").read_text(encoding="utf-8")
        sql = sql.replace(
            "INTEGER PRIMARY KEY GENERATED_BY_BACKEND",
            "BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY"
            if self.postgres
            else "INTEGER PRIMARY KEY AUTOINCREMENT",
        )
        if self.postgres:
            sql = sql.replace("payload TEXT", "payload JSONB").replace(
                "schema_json TEXT", "schema_json JSONB"
            )
        with self.transaction():
            if self.postgres:
                self.execute("SELECT pg_advisory_xact_lock(934354738)")
            self.execute(
                "CREATE TABLE IF NOT EXISTS wl_migrations(version INTEGER "
                "PRIMARY KEY, checksum TEXT NOT NULL)"
            )
            old = self.execute("SELECT checksum FROM wl_migrations WHERE version=1").fetchone()
            if self.execute("SELECT COALESCE(MAX(version),0) FROM wl_migrations").fetchone()[0] > 8:
                raise ValueError("Unsupported newer library migration")
            checksum = digest(sql)
            if old:
                if old[0] != checksum:
                    raise ValueError("Migration checksum changed")
            else:
                for statement in sql.split(";"):
                    if statement.strip():
                        self.execute(statement)
            from rpg_vkr.world_library.model import schemas

            if not old:
                for key, value in schemas().items():
                    self.execute("INSERT INTO wl_schemas VALUES(?,?)", (key, dump(value)))
                if self.postgres:
                    self.execute(
                        "CREATE INDEX wl_attributes_gin ON wl_versions USING GIN (payload)"
                    )
                    self.execute(
                        "CREATE INDEX wl_search_fts ON wl_templates USING GIN "
                        "(to_tsvector('simple',search_text))"
                    )
                self.execute("INSERT INTO wl_migrations VALUES(1,?)", (checksum,))
            backend = "postgres" if self.postgres else "sqlite"
            sql2 = (ROOT / f"data/world_library/migrations/002_hierarchy_{backend}.sql").read_text(
                encoding="utf-8"
            )
            checksum2 = digest(sql2)
            old2 = self.execute("SELECT checksum FROM wl_migrations WHERE version=2").fetchone()
            if old2:
                if old2[0] != checksum2:
                    raise ValueError("Migration checksum changed")
            else:
                for statement in sql2.split(";"):
                    if statement.strip():
                        self.execute(statement)
                for key, payload in self.execute(
                    "SELECT id,schema_json FROM wl_schemas"
                ).fetchall():
                    value = self._decode(payload)
                    self.execute(
                        "INSERT INTO wl_schema_revisions VALUES(?,?,?)",
                        (key, digest(value), dump(value)),
                    )
                for key, value in schemas().items():
                    self.execute(
                        "INSERT INTO wl_schema_revisions VALUES(?,?,?) "
                        "ON CONFLICT(id,digest) DO NOTHING",
                        (key, digest(value), dump(value)),
                    )
                    self.execute(
                        "INSERT INTO wl_schemas VALUES(?,?) ON CONFLICT(id) DO UPDATE SET "
                        "schema_json=excluded.schema_json",
                        (key, dump(value)),
                    )
                self.execute("INSERT INTO wl_migrations VALUES(2,?)", (checksum2,))
            sql3 = (ROOT / "data/world_library/migrations/003_source_rules.sql").read_text(
                encoding="utf-8"
            )
            checksum3 = digest(sql3)
            old3 = self.execute("SELECT checksum FROM wl_migrations WHERE version=3").fetchone()
            if old3:
                if old3[0] != checksum3:
                    raise ValueError("Migration checksum changed")
            else:
                for statement in sql3.split(";"):
                    if statement.strip():
                        self.execute(statement)
                for key, value in schemas().items():
                    self.execute(
                        "INSERT INTO wl_schema_revisions VALUES(?,?,?) "
                        "ON CONFLICT(id,digest) DO NOTHING",
                        (key, digest(value), dump(value)),
                    )
                    self.execute(
                        "INSERT INTO wl_schemas VALUES(?,?) ON CONFLICT(id) DO UPDATE SET "
                        "schema_json=excluded.schema_json",
                        (key, dump(value)),
                    )
                self.execute(
                    "INSERT INTO wl_rulesets VALUES(?,?)",
                    ("library-creature-3", digest(schemas()["source_features_v3"])),
                )
                self.execute("INSERT INTO wl_migrations VALUES(3,?)", (checksum3,))
            sql4 = (ROOT / "data/world_library/migrations/004_source_resilience.sql").read_text(
                encoding="utf-8"
            )
            checksum4 = digest(sql4)
            old4 = self.execute("SELECT checksum FROM wl_migrations WHERE version=4").fetchone()
            if old4:
                if old4[0] != checksum4:
                    raise ValueError("Migration checksum changed")
            else:
                for statement in sql4.split(";"):
                    if statement.strip():
                        self.execute(statement)
                for key, value in schemas().items():
                    self.execute(
                        "INSERT INTO wl_schema_revisions VALUES(?,?,?) "
                        "ON CONFLICT(id,digest) DO NOTHING",
                        (key, digest(value), dump(value)),
                    )
                    self.execute(
                        "INSERT INTO wl_schemas VALUES(?,?) ON CONFLICT(id) DO UPDATE SET "
                        "schema_json=excluded.schema_json",
                        (key, dump(value)),
                    )
                self.execute(
                    "INSERT INTO wl_rulesets VALUES(?,?)",
                    ("library-resilience-1", digest(schemas()["source_resilience_v1"])),
                )
                self.execute(
                    "INSERT INTO wl_rulesets VALUES(?,?)",
                    ("library-pack-1", digest(schemas()["equipment_pack_v1"])),
                )
                self.execute("INSERT INTO wl_migrations VALUES(4,?)", (checksum4,))
            sql5 = (ROOT / "data/world_library/migrations/005_source_regeneration.sql").read_text(
                encoding="utf-8"
            )
            checksum5 = digest(sql5)
            old5 = self.execute("SELECT checksum FROM wl_migrations WHERE version=5").fetchone()
            if old5:
                if old5[0] != checksum5:
                    raise ValueError("Migration checksum changed")
            else:
                for statement in sql5.split(";"):
                    if statement.strip():
                        self.execute(statement)
                for key, value in schemas().items():
                    self.execute(
                        "INSERT INTO wl_schema_revisions VALUES(?,?,?) "
                        "ON CONFLICT(id,digest) DO NOTHING",
                        (key, digest(value), dump(value)),
                    )
                    self.execute(
                        "INSERT INTO wl_schemas VALUES(?,?) ON CONFLICT(id) DO UPDATE SET "
                        "schema_json=excluded.schema_json",
                        (key, dump(value)),
                    )
                self.execute(
                    "INSERT INTO wl_rulesets VALUES(?,?)",
                    ("library-regeneration-1", digest(schemas()["source_regeneration_v1"])),
                )
                self.execute("INSERT INTO wl_migrations VALUES(5,?)", (checksum5,))
            sql6 = (ROOT / "data/world_library/migrations/006_authored_proposals.sql").read_text(
                encoding="utf-8"
            )
            checksum6 = digest(sql6)
            old6 = self.execute("SELECT checksum FROM wl_migrations WHERE version=6").fetchone()
            if old6:
                if old6[0] != checksum6:
                    raise ValueError("Migration checksum changed")
            else:
                for statement in sql6.split(";"):
                    if statement.strip():
                        self.execute(statement)
                for key, value in schemas().items():
                    self.execute(
                        "INSERT INTO wl_schema_revisions VALUES(?,?,?) "
                        "ON CONFLICT(id,digest) DO NOTHING",
                        (key, digest(value), dump(value)),
                    )
                    self.execute(
                        "INSERT INTO wl_schemas VALUES(?,?) ON CONFLICT(id) DO UPDATE SET "
                        "schema_json=excluded.schema_json",
                        (key, dump(value)),
                    )
                self.execute(
                    "INSERT INTO wl_rulesets VALUES(?,?)",
                    ("world-proposal-1", digest(schemas()["authored_proposal"])),
                )
                self.execute("INSERT INTO wl_migrations VALUES(6,?)", (checksum6,))
            sql7 = (ROOT / "data/world_library/migrations/007_multiattack_programs.sql").read_text(
                encoding="utf-8"
            )
            checksum7 = digest(sql7)
            old7 = self.execute("SELECT checksum FROM wl_migrations WHERE version=7").fetchone()
            if old7:
                if old7[0] != checksum7:
                    raise ValueError("Migration checksum changed")
            else:
                for statement in sql7.split(";"):
                    if statement.strip():
                        self.execute(statement)
                for key, value in schemas().items():
                    self.execute(
                        "INSERT INTO wl_schema_revisions VALUES(?,?,?) "
                        "ON CONFLICT(id,digest) DO NOTHING",
                        (key, digest(value), dump(value)),
                    )
                    self.execute(
                        "INSERT INTO wl_schemas VALUES(?,?) ON CONFLICT(id) DO UPDATE SET "
                        "schema_json=excluded.schema_json",
                        (key, dump(value)),
                    )
                self.execute(
                    "INSERT INTO wl_rulesets VALUES(?,?)",
                    ("library-multiattack-1", digest(schemas()["source_multiattack_v1"])),
                )
                self.execute("INSERT INTO wl_migrations VALUES(7,?)", (checksum7,))
            sql8 = (ROOT / "data/world_library/migrations/008_mp_source_spells.sql").read_text(
                encoding="utf-8"
            )
            checksum8 = digest(sql8)
            old8 = self.execute("SELECT checksum FROM wl_migrations WHERE version=8").fetchone()
            if old8:
                if old8[0] != checksum8:
                    raise ValueError("Migration checksum changed")
            else:
                for statement in sql8.split(";"):
                    if statement.strip():
                        self.execute(statement)
                for key, value in schemas().items():
                    self.execute(
                        "INSERT INTO wl_schema_revisions VALUES(?,?,?) "
                        "ON CONFLICT(id,digest) DO NOTHING",
                        (key, digest(value), dump(value)),
                    )
                    self.execute(
                        "INSERT INTO wl_schemas VALUES(?,?) ON CONFLICT(id) DO UPDATE SET "
                        "schema_json=excluded.schema_json",
                        (key, dump(value)),
                    )
                self.execute(
                    "INSERT INTO wl_rulesets VALUES(?,?)",
                    ("library-source-magic-1", digest(schemas()["source_spell_v1"])),
                )
                self.execute("INSERT INTO wl_migrations VALUES(8,?)", (checksum8,))

    def _decode(self, value):
        return json.loads(value) if isinstance(value, str) else value

    def all(self, *, include_retired=False):
        where = "" if include_retired else " WHERE t.retired=0"
        return [
            self._decode(r[0])
            for r in self.execute(
                (
                    "SELECT v.payload FROM wl_templates t JOIN wl_versions v ON "
                    "t.id=v.id AND t.revision=v.revision"
                )
                + where
                + " ORDER BY t.id"
            ).fetchall()
        ]

    def get(self, id, revision=None):
        if revision is None:
            row = self.execute(
                (
                    "SELECT v.payload FROM wl_templates t JOIN wl_versions v ON "
                    "t.id=v.id AND t.revision=v.revision WHERE t.id=? AND "
                    "t.retired=0"
                ),
                (id,),
            ).fetchone()
        else:
            row = self.execute(
                "SELECT payload FROM wl_versions WHERE id=? AND revision=?", (id, revision)
            ).fetchone()
        if row is None:
            raise KeyError(id)
        return self._decode(row[0])

    def revision(self, id):
        row = self.execute("SELECT revision FROM wl_templates WHERE id=?", (id,)).fetchone()
        return row[0] if row else 0

    def search(self, query="", category="", limit=20):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Search limit 1..100")

        # Escaped LIKE; input is always a bound value, never executable SQL.
        def escape(s):
            return s.replace("!", "!!").replace("%", "!%").replace("_", "!_")

        rows = self.execute(
            (
                "SELECT id FROM wl_templates WHERE retired=0 AND (id=? OR search_text "
                "LIKE ? ESCAPE '!') AND (category=? OR category LIKE ? ESCAPE "
                "'!') ORDER BY id LIMIT ?"
            ),
            (
                query.strip(),
                "%" + escape(normalized(query)) + "%",
                category,
                escape(category) + ".%" if category else "%",
                limit,
            ),
        ).fetchall()
        return [self.get(r[0]) for r in rows]

    def import_records(self, records, *, actor="engine/import", expected=None):
        """All-or-nothing, immutable revisions, optimistic updates, idempotent seeds."""
        return self._import_records(records, actor=actor, expected=expected)

    def _import_records(self, records, *, actor, expected=None, proposal_id=None):
        """One transaction also covers proposal approval when called by approve()."""
        if type(actor) is not str or not actor.strip() or len(actor) > 128:
            raise ValueError("Audit actor required")
        expected = expected or {}
        with self.transaction():
            # Serialize PG writers before read/validate/write (including absent IDs).
            if self.postgres:
                self.execute("LOCK TABLE wl_templates IN SHARE ROW EXCLUSIVE MODE")
            else:
                self.execute("UPDATE wl_migrations SET version=version WHERE version=1")
            approval = None
            if proposal_id is not None:
                row = self.execute(
                    "SELECT status,payload FROM wl_proposals WHERE id=?"
                    + (" FOR UPDATE" if self.postgres else ""),
                    (proposal_id,),
                ).fetchone()
                if row is None:
                    raise KeyError(proposal_id)
                approval = self._decode(row[1])
                if digest(approval) != proposal_id:
                    raise ValueError("Proposal payload digest mismatch")
                if row[0] == "approved":
                    return len(records)
                if row[0] != "pending":
                    raise ValueError("Only pending proposals can be approved")
                if len(records) != 1 or records[0] != approval["record"] or expected:
                    raise ValueError("Approval must import its exact immutable proposal")
                dependencies = approval.get("dependencies")
                targets = {link["target"] for link in records[0]["links"]}
                if dependencies is None and targets:
                    raise ValueError("Legacy proposal needs resubmission with pinned dependencies")
                if dependencies is not None:
                    if set(dependencies) != targets:
                        raise ValueError("Invalid proposal dependency set")
                    for target, pinned in dependencies.items():
                        try:
                            actual = self.get(target)
                        except KeyError as exc:
                            raise ValueError("Proposal dependency was retired or removed") from exc
                        if (
                            set(pinned) != {"revision", "digest"}
                            or type(pinned["revision"]) is not int
                            or self.revision(target) != pinned["revision"]
                            or digest(actual) != pinned["digest"]
                        ):
                            raise ValueError("Stale proposal dependency; review a new proposal")
            previous = {r["id"]: r for r in self.all(include_retired=True)}
            if (
                approval
                and records[0]["id"] in previous
                and digest(previous[records[0]["id"]]) != digest(records[0])
            ):
                raise ValueError("Proposals cannot overwrite established templates")
            if len({r["id"] for r in records}) != len(records):
                raise ValueError("Duplicate incoming ID")
            merged = previous | {r["id"]: r for r in records}
            if len(merged) > 100000:
                raise ValueError("Global library safety bound is 100000 records")
            validate_bundle(list(merged.values()))
            changed = []
            for row in records:
                id = row["id"]
                rev = self.revision(id)
                if id in expected and rev != expected[id]:
                    raise ValueError("Stale template revision")
                if id in previous and digest(previous[id]) == digest(row):
                    continue
                if rev and id not in expected:
                    raise ValueError("Update requires expected revision")
                category = row["category"]
                parent = None
                for part in category.split("."):
                    current = part if parent is None else parent + "." + part
                    self.execute(
                        "INSERT INTO wl_categories VALUES(?,?) ON CONFLICT(id) DO NOTHING",
                        (current, parent),
                    )
                    parent = current
                rev += 1
                self.execute(
                    (
                        "INSERT INTO "
                        "wl_templates(id,revision,category,name_key,search_text,retired) "
                        "VALUES(?,?,?,?,?,0) ON CONFLICT(id) DO UPDATE SET "
                        "revision=excluded.revision, category=excluded.category, "
                        "name_key=excluded.name_key, search_text=excluded.search_text"
                    ),
                    (
                        id,
                        rev,
                        category,
                        normalized(row["name"]),
                        normalized(row["name"] + " " + row["description"]),
                    ),
                )
                self.execute(
                    "INSERT INTO wl_versions VALUES(?,?,?,?)", (id, rev, digest(row), dump(row))
                )
                changed.append(row)
                self.execute(
                    "INSERT INTO wl_audit(actor,action,subject,payload) VALUES(?,?,?,?)",
                    (
                        actor,
                        "template_revision",
                        id,
                        dump({"revision": rev, "digest": digest(row)}),
                    ),
                )
            # Versions already exist, so forward references are now safe.
            for row in changed:
                rev = self.revision(row["id"])
                for n, link in enumerate(row["links"]):
                    self.execute(
                        "INSERT INTO wl_links VALUES(?,?,?,?,?,?,?,?)",
                        (
                            row["id"],
                            rev,
                            n,
                            link["relation"],
                            link["target"],
                            self.revision(link["target"]),
                            link["quantity"],
                            link["role"],
                        ),
                    )
            if proposal_id is not None:
                cursor = self.execute(
                    "UPDATE wl_proposals SET status='approved' WHERE id=? AND status='pending'",
                    (proposal_id,),
                )
                if cursor.rowcount != 1:
                    raise ValueError("Proposal status changed during approval")
                self.execute(
                    "INSERT INTO wl_audit(actor,action,subject,payload) VALUES(?,?,?,?)",
                    (
                        actor,
                        "proposal_approved",
                        proposal_id,
                        dump(
                            {
                                "template_id": records[0]["id"],
                                "revision": self.revision(records[0]["id"]),
                                "model": approval["model"],
                                "prompt_version": approval["prompt_version"],
                                "engine_version": approval["engine_version"],
                            }
                        ),
                    ),
                )
        return len(records)

    def retire(self, id, expected_revision, *, actor):
        with self.transaction():
            cursor = self.execute(
                "UPDATE wl_templates SET retired=1 WHERE id=? AND revision=? AND retired=0",
                (id, expected_revision),
            )
            if cursor.rowcount != 1:
                raise ValueError("Missing/stale template")
            self.execute(
                "INSERT INTO wl_audit(actor,action,subject,payload) VALUES(?,?,?,?)",
                (actor, "retire", id, dump({"revision": expected_revision})),
            )

    def export(self, path):
        # Exclusive create: never overwrite another export/save.
        with Path(path).open("x", encoding="utf-8") as stream:
            for row in self.all(include_retired=True):
                stream.write(dump(row) + "\n")

    def propose(self, record, *, model, prompt_version, request_id=None):
        """LLM input becomes pending data; no template or world mutation."""
        if any(not isinstance(v, str) or not 1 <= len(v) <= 128 for v in (model, prompt_version)):
            raise ValueError("Model and prompt version required, <=128 characters")
        if request_id is not None and (
            type(request_id) is not str or not 1 <= len(request_id) <= 128
        ):
            raise ValueError("Review request ID must be bounded text")
        with self.transaction():
            if self.postgres:
                self.execute("LOCK TABLE wl_templates IN SHARE ROW EXCLUSIVE MODE")
            else:
                self.execute("UPDATE wl_migrations SET version=version WHERE version=1")
            validate_bundle(
                list(
                    (
                        {r["id"]: r for r in self.all(include_retired=True)}
                        | {record["id"]: record}
                    ).values()
                )
            )
            payload = {
                "record": record,
                "model": model,
                "prompt_version": prompt_version,
                "engine_version": "world-library-1",
                "dependencies": {
                    target: {"revision": self.revision(target), "digest": digest(self.get(target))}
                    for target in sorted({link["target"] for link in record["links"]})
                },
            }
            if request_id is not None:
                payload["request_id"] = request_id
            id = digest(payload)
            inserted = self.execute(
                (
                    "INSERT INTO wl_proposals(id,status,payload) "
                    "VALUES(?,'pending',?) ON CONFLICT(id) DO NOTHING"
                ),
                (id, dump(payload)),
            )
            if inserted.rowcount == 1:
                self.execute(
                    "INSERT INTO wl_audit(actor,action,subject,payload) VALUES(?,?,?,?)",
                    (
                        "engine/propose",
                        "proposal_submitted",
                        id,
                        dump(
                            {
                                "proposal_id": id,
                                "template_id": record["id"],
                                "model": model,
                                "prompt_version": prompt_version,
                                "engine_version": payload["engine_version"],
                            }
                        ),
                    ),
                )
        return id

    def propose_authored(self, record, *, model, prompt_version, request_id=None):
        """Original model output acquires explicit engine contracts before review."""
        from rpg_vkr.world_library.proposal_policy import prepare_record

        prepared = prepare_record(record, model=model, prompt_version=prompt_version)
        return self.propose(
            prepared, model=model, prompt_version=prompt_version, request_id=request_id
        )

    def proposal(self, id):
        row = self.execute("SELECT status,payload FROM wl_proposals WHERE id=?", (id,)).fetchone()
        if row is None:
            raise KeyError(id)
        payload = self._decode(row[1])
        if digest(payload) != id:
            raise ValueError("Proposal payload digest mismatch")
        return {"id": id, "status": row[0], **payload}

    def approve(self, id, *, actor):
        """Trusted maintainer operation; library approval does not create inventory."""
        row = self.execute("SELECT payload FROM wl_proposals WHERE id=?", (id,)).fetchone()
        if row is None:
            raise KeyError(id)
        record = self._decode(row[0])["record"]
        self._import_records([record], actor=actor, proposal_id=id)

    def reject(self, id, *, actor):
        """Reject a pending proposal without changing any template or saved world."""
        if type(actor) is not str or not actor.strip() or len(actor) > 128:
            raise ValueError("Audit actor required")
        with self.transaction():
            row = self.execute(
                "SELECT status,payload FROM wl_proposals WHERE id=?"
                + (" FOR UPDATE" if self.postgres else ""),
                (id,),
            ).fetchone()
            if row is None:
                raise KeyError(id)
            if digest(self._decode(row[1])) != id:
                raise ValueError("Proposal payload digest mismatch")
            if row[0] == "rejected":
                return
            if row[0] != "pending":
                raise ValueError("Approved templates must be retired separately")
            self.execute("UPDATE wl_proposals SET status='rejected' WHERE id=?", (id,))
            self.execute(
                "INSERT INTO wl_audit(actor,action,subject,payload) VALUES(?,?,?,?)",
                (actor, "proposal_rejected", id, dump({"proposal_id": id})),
            )
