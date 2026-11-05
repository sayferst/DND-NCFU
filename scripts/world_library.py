"""Local library interface; no server, cloud calls or credentials in arguments."""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from rpg_vkr.world_library.model import dump, read_jsonl  # noqa: E402
from rpg_vkr.world_library.store import Library  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="DND-NCFU: библиотека мира")
    parser.add_argument("--db", default="world-library.sqlite3")
    parser.add_argument("--postgres", action="store_true", help="DSN из DND_LIBRARY_DSN")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    search = sub.add_parser("search")
    search.add_argument("text", nargs="?", default="")
    search.add_argument("--category", default="")
    for command in ("show", "retire"):
        p = sub.add_parser(command)
        p.add_argument("id")
        if command == "retire":
            p.add_argument("--revision", type=int, required=True)
    for command in ("import", "export", "propose", "stage"):
        p = sub.add_parser(command)
        p.add_argument("file", type=Path)
    approve = sub.add_parser("approve")
    approve.add_argument("id")
    update = sub.add_parser("update")
    update.add_argument("file", type=Path)
    update.add_argument("--revision", type=int, required=True)
    migrate = sub.add_parser("export-sqlite")
    migrate.add_argument("source", type=Path)
    migrate.add_argument("destination", type=Path)
    instance = sub.add_parser("instantiate")
    instance.add_argument("template_id")
    instance.add_argument("instance_id")
    instance.add_argument("source_sqlite", type=Path)
    instance.add_argument("destination_sqlite", type=Path)
    args = parser.parse_args()
    if args.command == "export-sqlite":
        from rpg_vkr.world_library.migration import export_sqlite

        result = export_sqlite(args.source, args.destination)
        print(dump({"world_id": result["world_id"], "digest": result["digest"]}))
        return
    library = (
        Library.postgres(os.environ["DND_LIBRARY_DSN"])
        if args.postgres
        else Library.sqlite(args.db)
    )
    try:
        library.migrate()
        result = None
        if args.command == "init":
            rows = read_jsonl(ROOT / "data/world_library/seed-v1.jsonl")
            facts = ROOT / "data/world_library/rpgd100-creature-facts.jsonl"
            if facts.exists():
                rows += read_jsonl(facts)
            equipment = ROOT / "data/world_library/rpgd100-equipment-facts.jsonl"
            if equipment.exists():
                rows += read_jsonl(equipment)
            result = {"imported": library.import_records(rows)}
        elif args.command == "search":
            result = [
                {"id": r["id"], "name": r["name"], "profile": r["profile"]}
                for r in library.search(args.text, args.category)
            ]
        elif args.command == "show":
            result = library.get(args.id)
        elif args.command == "import":
            result = {"imported": library.import_records(read_jsonl(args.file))}
        elif args.command == "update":
            rows = read_jsonl(args.file)
            if len(rows) != 1:
                raise ValueError("Update expects one record")
            result = {
                "updated": library.import_records(rows, expected={rows[0]["id"]: args.revision})
            }
        elif args.command == "export":
            library.export(args.file)
        elif args.command == "retire":
            library.retire(args.id, args.revision, actor="local-maintainer")
        elif args.command == "propose":
            record = json.loads(args.file.read_text(encoding="utf-8"))
            result = {
                "proposal": library.propose(record, model="manual-json", prompt_version="local-1")
            }
        elif args.command == "approve":
            library.approve(args.id, actor="local-maintainer")
        elif args.command == "stage":
            from rpg_vkr.world_library.migration import stage

            stage(library, json.loads(args.file.read_text(encoding="utf-8")))
        elif args.command == "instantiate":
            from rpg_vkr.storage.knowledge import export_session, restore_session
            from rpg_vkr.world_library.bridge import commit, preview

            if args.destination_sqlite.exists():
                raise ValueError("Destination must be a new save copy")
            session = restore_session(args.source_sqlite)
            proposal = preview(library, session, args.template_id, args.instance_id)
            commit(session, proposal)
            export_session(session, args.destination_sqlite)
            result = {"created": args.instance_id, "copy": str(args.destination_sqlite)}
        print(dump(result or {"ok": True}))
    finally:
        library.close()


if __name__ == "__main__":
    main()
