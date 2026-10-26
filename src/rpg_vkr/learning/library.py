"""Versioned, local-only corpus registry and reviewed short-excerpt FTS index.

No inference, migrations of saves, training, embeddings or background startup jobs.
"""

import hashlib
import json
import os
import sqlite3
import tempfile
import time
from collections import Counter
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

from rpg_vkr.learning.package import inspect
from rpg_vkr.learning.quality import CLAIM, NAMESPACES, VERSION, annotate, grouped, safe_excerpt

APPLICATION_ID = 0x444E4C42
MAX_DATABASE = 256 * 1024 * 1024


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False, suffix=".tmp") as stream:
            temporary = Path(stream.name)
            stream.write(dump(value).encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def default_directory():
    from rpg_vkr.resources import data_directory

    return data_directory() / "learning"


def active_path(directory=None):
    directory = Path(directory) if directory is not None else default_directory()
    pointer = json.loads((directory / "active.json").read_text(encoding="utf-8"))
    name = pointer["revision"]
    if not isinstance(name, str) or Path(name).name != name or not name.endswith(".sqlite3"):
        raise ValueError("Неверная версия библиотеки.")
    return directory / name


def activate(directory, revision):
    directory, revision = Path(directory), Path(revision)
    if revision.parent.resolve() != directory.resolve():
        raise ValueError("Версия должна находиться в локальной библиотеке.")
    with Library(revision) as library:
        library.stats()
    atomic_json(directory / "active.json", {"revision": revision.name})


class Library:
    def __init__(self, path, *, writable=False):
        self.path = Path(path)
        if not self.path.is_file() or self.path.stat().st_size > MAX_DATABASE:
            raise ValueError("Библиотека отсутствует или слишком велика.")
        mode = "rw" if writable else "ro"
        self.db = sqlite3.connect(
            self.path.resolve().as_uri() + "?mode=" + mode, uri=True, timeout=2
        )
        try:
            if self.db.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
                raise ValueError("Это не база библиотеки мастерства.")
            self.metadata = json.loads(
                self.db.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()[0]
            )
            if self.metadata["pipeline"] != VERSION:
                raise ValueError("Версия библиотеки не поддерживается.")
        except Exception:
            self.db.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.db.close()

    def stats(self):
        from rpg_vkr.learning.methods import SOURCE

        return self.metadata | {
            "records": self.db.execute("SELECT count(*) FROM records").fetchone()[0],
            "reviewed": self.db.execute("SELECT count(*) FROM reviews WHERE approved=1").fetchone()[
                0
            ],
            "indexed": self.db.execute("SELECT count(*) FROM excerpts").fetchone()[0],
            "indexed_corpus": self.db.execute(
                "SELECT count(*) FROM excerpts WHERE source!=?", (SOURCE,)
            ).fetchone()[0],
            "bytes": self.path.stat().st_size,
        }

    def candidates(self, query="", *, namespace="", offset=0, limit=30):
        if not isinstance(query, str) or len(query) > 300 or not 0 <= offset <= 19000:
            raise ValueError("Неверный запрос просмотра.")
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("Предел просмотра1–50.")
        return [
            dict(zip(("id", "title", "namespace", "quality", "split"), row, strict=True))
            for row in self.db.execute(
                "SELECT id,title,namespace,quality,split FROM records "
                "WHERE (?='' OR namespace=?) AND (title LIKE ? OR id LIKE ?) "
                "ORDER BY id LIMIT ? OFFSET ?",
                (namespace, namespace, "%" + query + "%", "%" + query + "%", limit, offset),
            )
        ]

    def record(self, record_id):
        row = self.db.execute(
            "SELECT payload,annotation,cluster,split FROM records WHERE id=?", (record_id,)
        ).fetchone()
        if not row:
            raise ValueError("Запись отсутствует в этой версии библиотеки.")
        return {
            "record": json.loads(row[0]),
            "annotation": json.loads(row[1]),
            "cluster": row[2],
            "split": row[3],
        }

    def review(self, record_id, excerpt, *, reviewer, approved, external=False, reason=""):
        if (
            not isinstance(reviewer, str)
            or not reviewer.strip()
            or len(reviewer) > 80
            or type(approved) is not bool
            or type(external) is not bool
            or not isinstance(excerpt, str)
            or not 1 <= len(excerpt) <= 600
            or not safe_excerpt(excerpt)
            or not isinstance(reason, str)
            or len(reason) > 500
        ):
            raise ValueError("Нужны проверяющий, безопасный отрывок до600символов и решение.")
        value = self.record(record_id)
        if approved and CLAIM.search(excerpt):
            raise ValueError("Числовые правила не включаются в литературные выдержки.")
        record = value["record"]
        if approved and value["annotation"]["quality_status"] == "rejected":
            raise ValueError("Отклонённый материал требует отдельной очистки, не автодопуска.")
        policy = self.db.execute(
            "SELECT external FROM sources WHERE id=?", (record["source_id"],)
        ).fetchone()
        if external and not policy[0]:
            raise ValueError("Права источника не разрешают передачу провайдеру.")
        with self.db:
            self.db.execute(
                "INSERT INTO review_audit VALUES(?,?,?,?,?,?,?)",
                (
                    record_id,
                    reviewer,
                    int(approved),
                    int(external),
                    excerpt,
                    reason,
                    self.db.execute(
                        "SELECT coalesce(max(sequence),0)+1 FROM review_audit"
                    ).fetchone()[0],
                ),
            )
            self.db.execute(
                "INSERT OR REPLACE INTO reviews VALUES(?,?,?,?,?)",
                (record_id, reviewer, int(approved), int(external), excerpt),
            )
            self.db.execute("DELETE FROM excerpts WHERE id=?", (record_id,))
            if self.metadata["fts"]:
                self.db.execute("DELETE FROM lookup WHERE id=?", (record_id,))
            # A held-out family never enters the runtime retrieval index.
            if approved and value["split"] == "train":
                tags = value["annotation"]["namespace"] + " " + record["category"]
                self.db.execute(
                    "INSERT INTO excerpts VALUES(?,?,?,?,?,?)",
                    (
                        record_id,
                        record["source_id"],
                        tags,
                        excerpt,
                        int(external),
                        value["cluster"],
                    ),
                )
                if self.metadata["fts"]:
                    self.db.execute("INSERT INTO lookup VALUES(?,?,?)", (record_id, tags, excerpt))

    def search(self, query, *, namespaces=(), remote=False, limit=3, budget=1800):
        from rpg_vkr.learning.query import terms

        if (
            not isinstance(query, str)
            or len(query) > 6000
            or type(limit) is not int
            or not 1 <= limit <= 3
            or type(budget) is not int
            or not 200 <= budget <= 2400
        ):
            raise ValueError("Неверный запрос библиотеки.")
        words = terms(query)
        if not words:
            return []
        if not set(namespaces) <= set(NAMESPACES.values()):
            raise ValueError("Неизвестное пространство поиска.")
        from rpg_vkr.learning.methods import SOURCE, cards

        # Recheck source policy and current review at read time, not just cached flags.
        policy = (
            " JOIN sources s ON s.id=e.source LEFT JOIN reviews r ON r.id=e.id "
            "LEFT JOIN records c ON c.id=e.id WHERE "
            "(?=0 OR (e.external=1 AND s.external=1)) "
            "AND (e.source=? OR (r.approved=1 AND c.split='train' "
            "AND r.excerpt=e.text AND (?=0 OR r.external=1))) "
        )
        parameters = [int(remote), SOURCE, int(remote)]
        if namespaces:
            policy += "AND (" + " OR ".join("e.tags LIKE ?" for _ in namespaces) + ") "
            parameters.extend(n + " %" for n in namespaces)
        if self.metadata["fts"]:
            rows = self.db.execute(
                "SELECT e.id,e.source,e.tags,e.text,e.family FROM lookup JOIN excerpts e "
                "ON e.id=lookup.id" + policy + "AND lookup MATCH ? "
                "ORDER BY bm25(lookup),e.id LIMIT 30",
                (*parameters, " OR ".join('"' + w + '"*' for w in words)),
            ).fetchall()
        else:
            self.db.create_function(
                "casefold", 1, lambda value: value.casefold(), deterministic=True
            )
            clauses = " OR ".join(
                "(casefold(e.text) LIKE ? OR casefold(e.tags) LIKE ?)" for _ in words
            )
            rows = self.db.execute(
                "SELECT e.id,e.source,e.tags,e.text,e.family FROM excerpts e"
                + policy
                + "AND ("
                + clauses
                + ") ORDER BY e.id LIMIT 30",
                (*parameters, *("%" + w + "%" for w in words for _ in range(2))),
            ).fetchall()

        originals = cards()
        result, seen = [], set()
        for id, source, tags, text, group in rows:
            if not safe_excerpt(text):
                continue
            original = originals.get(id)
            if source == SOURCE and (not original or original["text"] != text):
                continue
            if group in seen or namespaces and not any(n in tags.split() for n in namespaces):
                continue
            item = {
                "id": id,
                "source": source,
                "text": text,
                "kind": "example_not_fact",
                "quality": "project_authored" if original else "human_reviewed",
                "rights": "approved_external" if remote else "approved_local",
            }
            if len(dump(result + [item]).encode("utf-8")) <= budget:
                result.append(item)
                seen.add(group)
            if len(result) == limit:
                break
        return result

    def rebuild_index(self, *, cancelled=lambda: False):
        """One transaction; cancellation or an error keeps the previous index intact."""
        from rpg_vkr.learning.methods import SOURCE, cards

        with self.db:
            self.db.execute("DELETE FROM excerpts")
            if self.metadata["fts"]:
                self.db.execute("DELETE FROM lookup")
            for card in cards().values():
                self.db.execute(
                    "INSERT INTO excerpts VALUES(?,?,?,?,1,?)",
                    (
                        card["id"],
                        SOURCE,
                        card["tags"],
                        card["text"],
                        card["id"],
                    ),
                )
            rows = self.db.execute(
                "SELECT c.id,c.payload,c.annotation,c.cluster,r.reviewer,r.excerpt,r.external "
                "FROM records c JOIN reviews r ON c.id=r.id "
                "WHERE c.split='train' AND r.approved=1"
            ).fetchall()
            for id, payload, annotation, cluster, _reviewer, excerpt, external in rows:
                if cancelled():
                    raise InterruptedError("Перестройка отменена.")
                record, annotation = json.loads(payload), json.loads(annotation)
                if not safe_excerpt(excerpt) or CLAIM.search(excerpt):
                    continue
                tags = annotation["namespace"] + " " + record["category"]
                self.db.execute(
                    "INSERT INTO excerpts VALUES(?,?,?,?,?,?)",
                    (
                        id,
                        record["source_id"],
                        tags,
                        excerpt,
                        external,
                        cluster,
                    ),
                )
            if cancelled():
                raise InterruptedError("Перестройка отменена.")
            if self.metadata["fts"]:
                self.db.execute("INSERT INTO lookup SELECT id,tags,text FROM excerpts")
        return self.stats()

    def split_report(self):
        rows = self.db.execute("SELECT id,cluster,split FROM records ORDER BY id").fetchall()
        families = {}
        for _, group, split in rows:
            families.setdefault(group, set()).add(split)
        return {
            "pipeline": VERSION,
            "archive_sha256": self.metadata["archive_sha256"],
            "rows": [{"id": id, "family": group, "split": split} for id, group, split in rows],
            "family_overlap": sum(len(splits) > 1 for splits in families.values()),
            "semantic_independence": "not_proven",
            "raw_text_exported": False,
        }

    def graph(self, record_id):
        self.record(record_id)
        return [
            {
                "reference": ref,
                "record_id": target,
                "status": "candidate" if target else "unresolved",
            }
            for ref, target in self.db.execute(
                "SELECT reference,target FROM links WHERE source=? ORDER BY reference", (record_id,)
            )
        ]


def build(package, directory=None, *, cancelled=lambda: False, progress=lambda value: None):
    directory = Path(directory) if directory is not None else default_directory()
    directory.mkdir(parents=True, exist_ok=True)
    gate = directory / "jobs.sqlite3"
    with closing(sqlite3.connect(gate, timeout=0.05)) as lock:
        try:
            current = lock.execute("PRAGMA application_id").fetchone()[0]
            tables = lock.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if current not in (0, APPLICATION_ID + 1) or current == 0 and tables:
                raise ValueError("По пути блокировки находится другая база.")
            lock.execute(f"PRAGMA application_id={APPLICATION_ID + 1}")
            lock.execute("CREATE TABLE IF NOT EXISTS gate(id INTEGER)")
            lock.execute("BEGIN IMMEDIATE")
            return _build_locked(package, directory, cancelled=cancelled, progress=progress)
        except sqlite3.OperationalError as error:
            if "locked" in str(error):
                raise ValueError(
                    "Другая задача уже изменяет библиотеку. Повторите позже."
                ) from error
            raise
        finally:
            lock.rollback()


def _build_locked(package, directory, *, cancelled, progress):
    """Validate first, stage one bounded DB, then atomically activate a revision."""
    started = time.perf_counter()
    directory = Path(directory) if directory is not None else default_directory()
    package = Path(package)
    if package.stat().st_size > 128 * 1024 * 1024:
        raise ValueError("Архив превышает128МиБ.")
    digest = hashlib.sha256()
    with package.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    archive_sha = digest.hexdigest()
    revision = VERSION + "-" + archive_sha[:20] + ".sqlite3"
    destination = directory / revision
    if destination.exists():
        with Library(destination) as library:
            result = library.stats()
        if not cancelled():
            activate(directory, destination)
        return result | {"cached": True}
    report, records = inspect(package)
    if not report["verified"]:
        raise ValueError("Пакет не прошёл проверку: " + "; ".join(report["errors"][:5]))
    if report["archive_sha256"] != archive_sha:
        raise ValueError("Архив изменился во время проверки.")
    groups, splits, diagnostics = grouped(records, cancelled=cancelled, progress=progress)
    directory.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=directory, suffix=".sqlite3.tmp")
    os.close(handle)
    temporary = Path(temporary)
    quality, namespaces = Counter(), Counter()
    reference_ids = {r.record_id.rsplit(":", 1)[-1]: r.record_id for r in records}
    try:
        with closing(sqlite3.connect(temporary)) as db, db:
            db.execute(f"PRAGMA application_id={APPLICATION_ID}")
            db.executescript("""
                CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE sources(id TEXT PRIMARY KEY,external INTEGER NOT NULL);
                CREATE TABLE records(id TEXT PRIMARY KEY,title TEXT,namespace TEXT,quality TEXT,
                    cluster TEXT,split TEXT,payload TEXT,annotation TEXT);
                CREATE INDEX record_namespace ON records(namespace,id);
                CREATE TABLE links(source TEXT,reference TEXT,target TEXT);
                CREATE INDEX link_source ON links(source);
                CREATE TABLE reviews(id TEXT PRIMARY KEY,reviewer TEXT,approved INTEGER,
                    external INTEGER,excerpt TEXT);
                CREATE TABLE review_audit(id TEXT,reviewer TEXT,approved INTEGER,external INTEGER,
                    excerpt TEXT,reason TEXT,sequence INTEGER);
                CREATE TABLE excerpts(id TEXT PRIMARY KEY,source TEXT,tags TEXT,text TEXT,
                    external INTEGER,family TEXT);
            """)
            try:
                db.execute("CREATE VIRTUAL TABLE lookup USING fts5(id UNINDEXED,tags,text)")
                fts = True
            except sqlite3.OperationalError:
                fts = False
            db.executemany(
                "INSERT INTO sources VALUES(?,0)", [(s["source_id"],) for s in report["sources"]]
            )
            from rpg_vkr.learning.methods import SOURCE, cards

            db.execute("INSERT INTO sources VALUES(?,1)", (SOURCE,))
            for card in cards().values():
                db.execute(
                    "INSERT INTO excerpts VALUES(?,?,?,?,1,?)",
                    (card["id"], SOURCE, card["tags"], card["text"], card["id"]),
                )
                if fts:
                    db.execute(
                        "INSERT INTO lookup VALUES(?,?,?)", (card["id"], card["tags"], card["text"])
                    )
            unresolved = 0
            for index, record in enumerate(records):
                if cancelled():
                    raise InterruptedError("Импорт отменён; прежняя версия сохранена.")
                annotation = annotate(record)
                quality[annotation["quality_status"]] += 1
                namespaces[annotation["namespace"]] += 1
                refs = annotation["references"]
                for reference in refs:
                    target = reference_ids.get(reference)
                    unresolved += target is None
                    db.execute(
                        "INSERT INTO links VALUES(?,?,?)", (record.record_id, reference, target)
                    )
                # Raw body has one copy; complete role extraction remains available on demand.
                annotation["role_counts"] = dict(
                    Counter(r["role"] for r in annotation.pop("roles"))
                )
                annotation["fields"] = {
                    k: [v[:400] for v in values[:3]] for k, values in annotation["fields"].items()
                }
                db.execute(
                    "INSERT INTO records VALUES(?,?,?,?,?,?,?,?)",
                    (
                        record.record_id,
                        record.title,
                        annotation["namespace"],
                        annotation["quality_status"],
                        groups[record.record_id],
                        splits[record.record_id],
                        dump(asdict(record)),
                        dump(annotation),
                    ),
                )
                if index % 100 == 0:
                    progress(len(records) + index)
            metadata = {
                "pipeline": VERSION,
                "archive_sha256": report["archive_sha256"],
                "fts": fts,
                "counts": report["counts"],
                "groups": diagnostics,
                "quality_counts": dict(quality),
                "namespace_counts": dict(namespaces),
                "unresolved_references": unresolved,
                "human_approved": 0,
                "raw_external_transfer": False,
                "source_files": report["sources"],
                "build_seconds": time.perf_counter() - started,
            }
            db.execute("INSERT INTO metadata VALUES('manifest',?)", (dump(metadata),))
        if cancelled():
            raise InterruptedError("Импорт отменён; прежняя версия сохранена.")
        if temporary.stat().st_size > MAX_DATABASE:
            raise ValueError("Локальный индекс превышает256МиБ.")
        os.replace(temporary, destination)
        activate(directory, destination)
        with Library(destination) as library:
            return library.stats() | {"cached": False}
    finally:
        temporary.unlink(missing_ok=True)
