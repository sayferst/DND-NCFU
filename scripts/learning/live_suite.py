"""Explicit live suite; no live request without --execute and a bounded budget."""

import argparse
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rpg_vkr.learning.library import default_directory  # noqa: E402
from rpg_vkr.learning.live_suite import run  # noqa: E402

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--directory", type=Path)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--key-file", type=Path)
parser.add_argument("--execute", action="store_true")
parser.add_argument("--budget-rub", type=Decimal, default=Decimal(5))
parser.add_argument("--case", action="append", default=[])
parser.add_argument("--max-output-tokens", type=int, default=1024)
args = parser.parse_args()
if args.output.exists() or args.output.with_suffix(".jsonl").exists():
    raise SystemExit("Выберите новое имя отчёта.")
if not args.execute:
    result = {
        "status": "READY_NOT_RUN",
        "scenarios": 24,
        "planned_generations": 48,
        "budget_rub": str(args.budget_rub),
    }
else:
    key = (
        args.key_file.read_text(encoding="utf-8").strip()
        if args.key_file
        else os.environ.get("DND_ROUTERAI_API_KEY", "")
    )
    with args.output.with_suffix(".jsonl").open("x", encoding="utf-8") as journal:

        def emit(row):
            journal.write(json.dumps(row, ensure_ascii=False) + "\n")
            journal.flush()
            print(json.dumps({k: row[k] for k in ("case", "mode", "status")}), flush=True)

        try:
            result = run(
                key,
                args.directory or default_directory(),
                budget=args.budget_rub,
                emit=emit,
                case_ids=args.case,
                max_output=args.max_output_tokens,
            )
        except (ValueError, OSError) as error:
            result = {"status": "BLOCKED", "reason": str(error)[:300]}
with args.output.open("x", encoding="utf-8") as stream:
    json.dump(result, stream, ensure_ascii=False, indent=2)
print(json.dumps({k: v for k, v in result.items() if k != "rows"}, ensure_ascii=False))
