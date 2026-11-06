"""Inspect and enable the local master catalog without changing saves or models."""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from rpg_vkr.world_library.narrator import retrieve  # noqa: E402


def doctor(path):
    path = path.resolve()
    if not path.is_file():
        raise ValueError("Choose an existing global library file")
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok" or db.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Catalog integrity check failed")
        migrations = [
            r[0] for r in db.execute("SELECT version FROM wl_migrations ORDER BY version")
        ]
        if migrations not in (
            [1, 2, 3],
            [1, 2, 3, 4],
            [1, 2, 3, 4, 5],
            [1, 2, 3, 4, 5, 6],
            [1, 2, 3, 4, 5, 6, 7],
        ):
            raise ValueError("Run the documented library migration first")
        count = db.execute("SELECT COUNT(*) FROM wl_templates WHERE retired=0").fetchone()[0]
    return {
        "status": "READY_FOR_LOCAL_RETRIEVAL",
        "records": count,
        "migrations": migrations,
        "database_access": "read-only",
        "training_required": False,
        "worlds_modified": False,
        "paid_api_required": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    query = commands.add_parser("context")
    query.add_argument("text")
    commands.add_parser("run")
    args = parser.parse_args()
    result = doctor(args.db)
    if args.command == "context":
        result = retrieve(args.text, path=args.db)
    elif args.command == "run":
        environment = os.environ.copy()
        environment["RPG_VKR_WORLD_LIBRARY"] = str(args.db.resolve())
        raise SystemExit(
            subprocess.call(
                [sys.executable, str(ROOT / "scripts/run_game.py")],
                cwd=ROOT,
                env=environment,
            )
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
