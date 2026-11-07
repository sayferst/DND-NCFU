"""Compatibility command for the owner's earlier instructions; read-only diagnostics."""

import json
from datetime import UTC, datetime
from pathlib import Path

from training.hardware_preflight import collect


def main():
    folder = Path("../DND-NCFU-data/diagnostics")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ("hardware-" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f") + ".json")
    report = collect(
        scope="owner_laptop" if __import__("os").name == "nt" else "execution_environment"
    )
    with path.open("x", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps({"status": report["training_status"], "report": str(path)}))


if __name__ == "__main__":
    main()
