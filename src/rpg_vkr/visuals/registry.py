"""Durable visual versions and conservative, atomic cross-campaign expense ledger."""

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ACTIVE = ("reserved", "submitted", "uncertain")


def month_now():
    return datetime.now(UTC).strftime("%Y-%m")


class VisualRegistry:
    def __init__(self, directory, *, recover=False):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "visuals.sqlite3"
        new = not self.path.exists()
        with closing(sqlite3.connect(self.path)) as db, db:
            if not new and db.execute("PRAGMA application_id").fetchone()[0] != 1146505555:
                raise ValueError("По пути изображений находится другая база.")
            db.execute("PRAGMA application_id=1146505555")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS aliases(
                    campaign TEXT NOT NULL, entity TEXT NOT NULL, subject TEXT NOT NULL,
                    PRIMARY KEY(campaign,entity));
                CREATE TABLE IF NOT EXISTS requests(
                    id TEXT PRIMARY KEY, campaign TEXT NOT NULL, subject TEXT NOT NULL,
                    month TEXT NOT NULL, model TEXT NOT NULL, status TEXT NOT NULL,
                    expected_micros INTEGER NOT NULL, actual_micros INTEGER,
                    code TEXT NOT NULL DEFAULT '', created TEXT NOT NULL,
                    receipt TEXT NOT NULL DEFAULT '');
                CREATE UNIQUE INDEX IF NOT EXISTS active_subject
                    ON requests(campaign,subject)
                    WHERE status IN ('reserved','submitted','uncertain');
                CREATE INDEX IF NOT EXISTS request_month ON requests(month);
                CREATE TABLE IF NOT EXISTS assets(
                    id TEXT PRIMARY KEY, campaign TEXT NOT NULL, subject TEXT NOT NULL,
                    type_id TEXT NOT NULL, scope TEXT NOT NULL, version INTEGER NOT NULL,
                    model TEXT NOT NULL, sha256 TEXT NOT NULL, path TEXT NOT NULL,
                    prompt TEXT NOT NULL, refs TEXT NOT NULL, request TEXT NOT NULL UNIQUE,
                    created TEXT NOT NULL, UNIQUE(campaign,subject,version));
                CREATE INDEX IF NOT EXISTS asset_subject ON assets(campaign,subject,version);
                CREATE TABLE IF NOT EXISTS captions(
                    request TEXT PRIMARY KEY, campaign TEXT NOT NULL, entity TEXT NOT NULL,
                    title TEXT NOT NULL, category TEXT NOT NULL, description TEXT NOT NULL);
            """)
            if recover:
                db.execute(
                    "UPDATE requests SET status='uncertain',code='interrupted' "
                    "WHERE status='submitted'"
                )
                db.execute(
                    "UPDATE requests SET status='cancelled',code='not_submitted' "
                    "WHERE status='reserved'"
                )

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def ledger(self):
        with closing(self.connect()) as db:
            return [dict(r) for r in db.execute("SELECT * FROM requests ORDER BY created DESC")]

    def totals(self, month=None):
        month = month or month_now()
        rows = [r for r in self.ledger() if r["month"] == month]
        committed = sum(
            r["actual_micros"] if r["actual_micros"] is not None else r["expected_micros"]
            for r in rows
            if r["status"] not in {"cancelled", "failed_preflight"}
        )
        return {
            "committed": committed,
            "actual": sum(r["actual_micros"] or 0 for r in rows),
            "unknown": sum(
                r["actual_micros"] is None and r["status"] in {"succeeded", "uncertain"}
                for r in rows
            ),
        }

    def reserve(self, campaign, subject, model, expected, monthly):
        if type(expected) is not int or type(monthly) is not int or not 0 < expected <= monthly:
            raise ValueError("Укажите месячный бюджет изображений и проверьте цену.")
        now, identity = datetime.now(UTC).isoformat(), uuid4().hex
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            used = db.execute(
                "SELECT COALESCE(SUM(COALESCE(actual_micros,expected_micros)),0) "
                "FROM requests WHERE month=? AND status NOT IN "
                "('cancelled','failed_preflight')",
                (month_now(),),
            ).fetchone()[0]
            if used + expected > monthly:
                raise ValueError("Месячного бюджета изображений недостаточно, включая резервы.")
            try:
                db.execute(
                    "INSERT INTO requests(id,campaign,subject,month,model,status,"
                    "expected_micros,created) VALUES(?,?,?,?,?,'reserved',?,?)",
                    (identity, campaign, subject, month_now(), model, expected, now),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError(
                    "Для объекта уже есть незавершённый запрос. Повтор не отправлен."
                ) from error
        return identity

    def mark_submitted(self, identity):
        with closing(self.connect()) as db, db:
            result = db.execute(
                "UPDATE requests SET status='submitted' WHERE id=? AND status='reserved'",
                (identity,),
            )
            if result.rowcount != 1:
                raise ValueError("Запрос уже отправлен или отменён; повтор запрещён.")

    def fail(self, identity, code, *, certainly_unpaid=False, actual=None, receipt=""):
        with closing(self.connect()) as db, db:
            db.execute(
                "UPDATE requests SET status=?,code=?,actual_micros=?,receipt=? "
                "WHERE id=? AND status IN "
                "('reserved','submitted')",
                (
                    "failed_preflight" if certainly_unpaid else "uncertain",
                    code[:80],
                    actual,
                    receipt[:256],
                    identity,
                ),
            )

    def reconcile(self, identity, actual):
        if type(actual) is not int or actual < 0:
            raise ValueError("Нужна проверенная неотрицательная сумма.")
        with closing(self.connect()) as db, db:
            if (
                db.execute(
                    "UPDATE requests SET actual_micros=?,status='settled_no_image',"
                    "code='user_reconciled' WHERE id=? AND status='uncertain'",
                    (actual, identity),
                ).rowcount
                != 1
            ):
                raise ValueError("Сверять можно только неопределённый запрос.")

    def complete(
        self,
        identity,
        image,
        *,
        type_id="",
        scope="instance",
        prompt="",
        refs=(),
        actual=None,
        receipt="",
    ):
        if not isinstance(image, bytes) or not 1 <= len(image) <= 20 * 1024 * 1024:
            raise ValueError("Некорректный размер изображения.")
        if actual is not None and (type(actual) is not int or actual < 0):
            raise ValueError("Некорректный фактический расход.")
        digest = hashlib.sha256(image).hexdigest()
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM requests WHERE id=?", (identity,)).fetchone()
            if row is None or row["status"] != "submitted":
                raise ValueError("Повтор результата или запрос уже закрыт.")
            relative = (
                Path("assets")
                / hashlib.sha256(row["campaign"].encode()).hexdigest()
                / (digest + ".png")
            )
            path = self.directory / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            # Content-addressed and immutable; a crash may leave an unindexed cache file.
            if path.exists():
                if path.read_bytes() != image:
                    raise ValueError("Повреждён визуальный кэш.")
            else:
                with path.open("xb") as stream:
                    stream.write(image)
            version = db.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM assets WHERE campaign=? AND subject=?",
                (row["campaign"], row["subject"]),
            ).fetchone()[0]
            asset = uuid4().hex
            db.execute(
                "INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    asset,
                    row["campaign"],
                    row["subject"],
                    type_id,
                    scope,
                    version,
                    row["model"],
                    digest,
                    relative.as_posix(),
                    prompt,
                    json.dumps(list(refs)),
                    identity,
                    datetime.now(UTC).isoformat(),
                ),
            )
            db.execute(
                "UPDATE requests SET status='succeeded',actual_micros=?,receipt=? WHERE id=?",
                (actual, receipt[:256], identity),
            )
        return self.versions(row["campaign"], row["subject"])[0]

    def versions(self, campaign, subject):
        with closing(self.connect()) as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM assets WHERE campaign=? AND subject=? ORDER BY version DESC",
                    (campaign, subject),
                )
            ]

    def asset_path(self, asset):
        path = (self.directory / asset["path"]).resolve()
        if not path.is_relative_to(self.directory.resolve()) or path.suffix != ".png":
            raise ValueError("Небезопасный путь изображения.")
        if hashlib.sha256(path.read_bytes()).hexdigest() != asset["sha256"]:
            raise ValueError("Изображение повреждено; повторная генерация не запущена.")
        return path

    def bind(self, campaign, entity, subject):
        with closing(self.connect()) as db, db:
            db.execute(
                "INSERT INTO aliases VALUES(?,?,?) ON CONFLICT(campaign,entity) "
                "DO UPDATE SET subject=excluded.subject",
                (campaign, entity, subject),
            )

    def describe(self, identity, target):
        """Public snapshot only, saved alongside the existing request, never in game canon."""
        with closing(self.connect()) as db, db:
            db.execute(
                "INSERT INTO captions VALUES(?,?,?,?,?,?)",
                (
                    identity,
                    target.campaign,
                    target.entity,
                    target.title[:300],
                    target.category,
                    target.brief[:3000],
                ),
            )

    def campaign_assets(self, campaign, *, history=False):
        with closing(self.connect()) as db:
            rows = [
                dict(r)
                for r in db.execute(
                    "SELECT a.*,c.entity,c.title,c.category,c.description FROM assets a "
                    "LEFT JOIN captions c ON a.request=c.request AND a.campaign=c.campaign "
                    "WHERE a.campaign=? ORDER BY a.created DESC,a.version DESC",
                    (campaign,),
                )
            ]
        if history:
            return rows
        latest = {}
        for row in rows:
            latest.setdefault(row["subject"], row)
        return list(latest.values())

    def asset_revision(self, campaign):
        with closing(self.connect()) as db:
            row = db.execute(
                "SELECT COUNT(*),MAX(created) FROM assets WHERE campaign=?", (campaign,)
            ).fetchone()
        return tuple(row)

    def latest_for(self, campaign, entity):
        with closing(self.connect()) as db:
            row = db.execute(
                "SELECT subject FROM aliases WHERE campaign=? AND entity=?", (campaign, entity)
            ).fetchone()
        choices = self.versions(campaign, row[0] if row else "entity:" + entity)
        return choices[0] if choices else None
