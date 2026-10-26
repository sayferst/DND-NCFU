"""Create a validated migration copy and exact backup; never overwrite the source."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from rpg_vkr.application import Session  # noqa: E402
from rpg_vkr.storage.migration import write_copy  # noqa: E402

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("source", type=Path)
parser.add_argument("destination", type=Path)
args = parser.parse_args()
try:
    if args.source.resolve() == args.destination.resolve():
        raise ValueError("Исходник и копия должны быть разными файлами.")
    with args.source.open("rb") as stream:
        raw = stream.read(32 * 1024 * 1024 + 1)
    if len(raw) > 32 * 1024 * 1024:
        raise ValueError("Слишком большой исходник.")
    value = json.loads(raw)
    session = Session.from_dict(value["session"], version=value["schema_version"])
    _, report = write_copy(session, args.destination, original_bytes=raw)
    if args.source.read_bytes() != raw:
        raise ValueError("Исходник изменён другим процессом; проверьте файлы.")
    print(json.dumps(report, ensure_ascii=False, indent=2))
except (OSError, ValueError, TypeError, KeyError) as error:
    print(str(error), file=sys.stderr)
    raise SystemExit(2) from error
