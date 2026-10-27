"""Developer-only, reproducible game catalog build and complete validation."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from rpg_vkr.domain.catalog_authoring import build  # noqa: E402
from rpg_vkr.domain.game_catalog import validate  # noqa: E402

if __name__ == "__main__":
    data = build()
    report = validate(data)
    destination = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/gameplay/catalog-v1.json")
    if destination.exists():
        raise SystemExit("Use a new output path; a released catalog is immutable")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
