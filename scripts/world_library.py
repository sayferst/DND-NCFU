"""Local library interface; no server, cloud calls or credentials in arguments."""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from rpg_vkr.world_library.model import all_records, dump, read_jsonl  # noqa: E402
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
        if command == "propose":
            p.add_argument("--model")
            p.add_argument("--prompt-version")
    approve = sub.add_parser("approve")
    approve.add_argument("id")
    for command in ("proposal", "reject"):
        sub.add_parser(command).add_argument("id")
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
    instance.add_argument("--with-inventory", action="store_true")
    instance.add_argument("--new-revision", action="store_true")
    activate = sub.add_parser("activate")
    activate.add_argument("instance_id")
    activate.add_argument("source_sqlite", type=Path)
    activate.add_argument("destination_sqlite", type=Path)
    activate.add_argument("--target", default="hero")
    activate.add_argument("--operation", choices=("magic", "craft", "use"), default="magic")
    args = parser.parse_args()
    if args.command == "export-sqlite":
        from rpg_vkr.world_library.migration import export_sqlite

        result = export_sqlite(args.source, args.destination)
        print(dump({"world_id": result["world_id"], "digest": result["digest"]}))
        return
    if args.command == "activate":
        from rpg_vkr.storage.knowledge import export_session, restore_session

        if args.destination_sqlite.exists():
            raise ValueError("Destination must be a new save copy")
        session = restore_session(args.source_sqlite)
        command = {"magic": "library_magic", "craft": "library_recipe", "use": "library_use"}[
            args.operation
        ]
        session.perform_gameplay(
            command,
            {"item": args.instance_id, "target": args.target}
            if args.operation in {"magic", "use"}
            else {"item": args.instance_id},
            "library-magic-" + session._request_token(),
        )
        export_session(session, args.destination_sqlite)
        print(dump({"activated": args.instance_id, "copy": str(args.destination_sqlite)}))
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
            rows = all_records()
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
            from uuid import uuid4

            value = json.loads(args.file.read_text(encoding="utf-8"))
            if isinstance(value, dict) and "record" in value:
                if set(value) != {"record", "model", "prompt_version"}:
                    raise ValueError("Expected record, model and prompt_version")
                record, model, prompt_version = (
                    value["record"],
                    value["model"],
                    value["prompt_version"],
                )
            else:
                record, model, prompt_version = value, "manual-json", "local-1"
            proposal = library.propose_authored(
                record,
                model=args.model or model,
                prompt_version=args.prompt_version or prompt_version,
                request_id=uuid4().hex,
            )
            result = {
                "proposal": proposal,
                "record_id": library.proposal(proposal)["record"]["id"],
                "status": "pending",
            }
        elif args.command == "approve":
            library.approve(args.id, actor="local-maintainer")
        elif args.command == "proposal":
            result = library.proposal(args.id)
        elif args.command == "reject":
            library.reject(args.id, actor="local-maintainer")
        elif args.command == "stage":
            from rpg_vkr.world_library.migration import stage

            stage(library, json.loads(args.file.read_text(encoding="utf-8")))
        elif args.command == "instantiate":
            from rpg_vkr.storage.knowledge import export_session, restore_session
            from rpg_vkr.world_library.bridge import commit, preview

            if args.destination_sqlite.exists():
                raise ValueError("Destination must be a new save copy")
            session = restore_session(args.source_sqlite)
            proposal = preview(
                library,
                session,
                args.template_id,
                args.instance_id,
                with_inventory=args.with_inventory,
                new_revision=args.new_revision,
            )
            commit(session, proposal)
            export_session(session, args.destination_sqlite)
            result = {"created": args.instance_id, "copy": str(args.destination_sqlite)}
        print(dump(result or {"ok": True}))
    finally:
        library.close()


if __name__ == "__main__":
    main()
