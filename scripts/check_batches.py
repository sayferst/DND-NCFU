"""Run the complete configured suite in bounded processes, keeping real JUnit evidence."""

import json
import os
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path


def run(root, *, batch_size=12):
    root = Path(root).resolve()
    files = sorted(p.relative_to(root).as_posix() for p in (root / "tests").rglob("test_*.py"))
    if not files or batch_size < 1:
        raise ValueError("No tests or invalid batch size")
    output = root / "build" / ("check-batches-" + uuid.uuid4().hex)
    output.mkdir(parents=True)
    results = []
    counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(root / "src"), str(root / "tests"), env.get("PYTHONPATH", "")]
    )
    for index, offset in enumerate(range(0, len(files), batch_size), 1):
        batch = files[offset : offset + batch_size]
        report = output / f"batch-{index:02}.xml"
        print(f"Full suite batch {index}: {len(batch)} files", flush=True)
        result = subprocess.run(
            [sys.executable, "-m", "pytest", *batch, "--junitxml", str(report)],
            cwd=root,
            env=env,
            check=False,
        )
        row = {"files": batch, "exit_code": result.returncode, "junit": report.name}
        if report.exists():
            suites = ET.parse(report).getroot().iter("testsuite")
            total = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
            for suite in suites:
                for key in total:
                    total[key] += int(suite.attrib.get(key, 0))
            counts["passed"] += (
                total["tests"] - total["failures"] - total["errors"] - total["skipped"]
            )
            counts["failed"] += total["failures"]
            counts["errors"] += total["errors"]
            counts["skipped"] += total["skipped"]
            row["counts"] = total
        results.append(row)
        if result.returncode or not report.exists():
            break
    checked = [p for row in results for p in row["files"]]
    success = checked == files and all(row["exit_code"] == 0 and "counts" in row for row in results)
    summary = {"complete": success, "expected_files": files, "batches": results, **counts}
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps({"complete": success, "batches": len(results), **counts}, ensure_ascii=False),
        flush=True,
    )
    print("Full suite report: " + str(output / "summary.json"), flush=True)
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(run(Path(__file__).resolve().parents[1]))
