"""Explicit offline corpus audit; no game startup hook, provider or training job."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from rpg_vkr.learning.package import inspect, write_records  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--offline", action="store_true", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resolve-identical-spec-alias", action="store_true")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--records", type=Path)
    args = parser.parse_args()
    report, records = inspect(args.package, resolve_spec_alias=args.resolve_identical_spec_alias)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x", encoding="utf-8") as out:
        out.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if args.records and not args.dry_run and report["verified"]:
        args.records.parent.mkdir(parents=True, exist_ok=True)
        write_records(args.records, records)
    print("VERIFIED_DERIVED" if report["verified"] else "FAILED", report["counts"])
    for error in report["errors"]:
        print(error)
    return 0 if report["verified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
