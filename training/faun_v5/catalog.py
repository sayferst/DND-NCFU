"""Controlled read-only lookup. Neither LLM text nor a dataset can supply SQL."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class IndexCatalog:
    """Only the supplied index's fields are established, not full card properties."""

    def __init__(self, path):
        self.records = {}
        with Path(path).open(encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                if row["entity_id"] in self.records:
                    raise ValueError("Duplicate entity ID")
                self.records[row["entity_id"]] = row

    def get(self, entity_id):
        record = self.records.get(entity_id)
        return {
            "mode": "provided_index_not_direct_sql",
            "found": record is not None,
            "record": record,
            "unknown_properties": True,
        }


class ProjectCards:
    """Adapter for the *inspected project cards schema*, not the missing Engine9 DB."""

    COLUMNS = {"id", "title", "category", "source", "source_sha256"}

    def __init__(self, path):
        self.path = Path(path).resolve(strict=True)
        with self.connect() as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(cards)")}
            if not self.COLUMNS <= columns:
                raise ValueError("Unknown SQLite schema; explicit adapter required")

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
        conn.execute("PRAGMA query_only=ON")
        try:
            yield conn
        finally:
            conn.close()

    def get(self, card_id):
        if not isinstance(card_id, str) or not 1 <= len(card_id) <= 200:
            raise ValueError("Invalid ID")
        with self.connect() as conn:
            values = conn.execute(
                "SELECT id,title,category,source,source_sha256 FROM cards WHERE id=? LIMIT 1",
                (card_id,),
            ).fetchone()
        return {
            "mode": "readonly_project_cards_not_original_engine9",
            "found": values is not None,
            "record": dict(
                zip(("id", "title", "category", "source", "source_sha256"), values, strict=True)
            )
            if values
            else None,
        }

    def count(self):
        with self.connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
