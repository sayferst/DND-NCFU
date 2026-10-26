"""Write a new offline comparison report, with zero model/API calls."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rpg_vkr.learning.evaluation import evaluate  # noqa: E402
from rpg_vkr.learning.library import default_directory  # noqa: E402

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--directory", type=Path, default=None)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
result = evaluate(args.directory or default_directory())
with args.output.open("x", encoding="utf-8") as stream:
    json.dump(result, stream, ensure_ascii=False, indent=2)
print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
