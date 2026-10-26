"""Dry run by default. --execute uses only the explicitly selected DeepSeek model."""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rpg_vkr.learning.library import default_directory  # noqa: E402
from rpg_vkr.learning.live_probe import live_probe  # noqa: E402

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--directory", type=Path)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--execute", action="store_true")
parser.add_argument("--key-file", type=Path, help="Private temporary file, outside Git")
args = parser.parse_args()
if args.output.exists():
    raise SystemExit("Выберите новое имя отчёта.")
key = (
    args.key_file.read_text(encoding="utf-8").strip()
    if args.key_file
    else os.environ.get("DND_ROUTERAI_API_KEY", "")
)
try:
    result = live_probe(key, args.directory or default_directory(), execute=args.execute)
except (ValueError, OSError) as error:
    result = {"status": "BLOCKED", "reason": str(error)[:300], "paid_posts_completed": "unknown"}
with args.output.open("x", encoding="utf-8") as stream:
    json.dump(result, stream, ensure_ascii=False, indent=2)
print(json.dumps({k: v for k, v in result.items() if k != "rows"}, ensure_ascii=False))
