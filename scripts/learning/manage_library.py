"""Explicit offline library operations. Never opens a model connection."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rpg_vkr.learning.library import (  # noqa: E402
    Library,
    activate,
    active_path,
    build,
    default_directory,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=None)
    parser.add_argument("--report", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest")
    ingest.add_argument("package", type=Path)
    for name in ("stats", "splits", "rebuild", "versions"):
        commands.add_parser(name)
    rollback = commands.add_parser("activate")
    rollback.add_argument("revision")
    query = commands.add_parser("query")
    query.add_argument("text")
    query.add_argument("--remote", action="store_true")
    candidates = commands.add_parser("candidates")
    candidates.add_argument("--text", default="")
    candidates.add_argument("--namespace", default="")
    candidates.add_argument("--offset", type=int, default=0)
    record = commands.add_parser("record")
    record.add_argument("id")
    review = commands.add_parser("review")
    review.add_argument("id")
    review.add_argument("excerpt", type=Path)
    review.add_argument("--reviewer", required=True)
    review.add_argument("--approve", action="store_true")
    review.add_argument("--reason", default="")
    args = parser.parse_args(argv)
    directory = args.directory or default_directory()
    if args.command == "ingest":
        result = build(args.package, directory)
    elif args.command == "activate":
        activate(directory, directory / args.revision)
        result = {"active": active_path(directory).name}
    elif args.command == "versions":
        result = {"versions": [p.name for p in sorted(directory.glob("corpus-*.sqlite3"))]}
    else:
        with Library(active_path(directory), writable=args.command in ("review", "rebuild")) as db:
            if args.command == "review":
                if args.excerpt.stat().st_size > 4000:
                    raise ValueError("Файл выдержки слишком велик.")
                db.review(
                    args.id,
                    args.excerpt.read_text(encoding="utf-8-sig").strip(),
                    reviewer=args.reviewer,
                    approved=args.approve,
                    reason=args.reason,
                )
                result = {"reviewed": args.id, "approved_local": args.approve}
            elif args.command == "record":
                result = db.record(args.id)  # Explicit local inspection, never telemetry.
            elif args.command == "query":
                result = db.search(args.text, remote=args.remote)
            elif args.command == "candidates":
                result = db.candidates(args.text, namespace=args.namespace, offset=args.offset)
            elif args.command == "rebuild":
                result = db.rebuild_index()
            elif args.command == "splits":
                result = db.split_report()
            else:
                result = db.stats()
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.report:
        with args.report.open("x", encoding="utf-8") as stream:
            stream.write(output + "\n")
    else:
        print(output)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        raise SystemExit(str(error)) from error
