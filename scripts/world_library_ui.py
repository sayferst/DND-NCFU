"""Run the optional offline library window against its own SQLite database."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from PySide6.QtWidgets import QApplication  # noqa: E402

from rpg_vkr.world_library.model import read_jsonl  # noqa: E402
from rpg_vkr.world_library.store import Library  # noqa: E402
from rpg_vkr.world_library.ui import LibraryWindow  # noqa: E402

if __name__ == "__main__":
    app = QApplication(sys.argv)
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "world-library.sqlite3"
    library = Library.sqlite(path)
    try:
        library.migrate()
        if not library.all():
            rows = read_jsonl(ROOT / "data/world_library/seed-v1.jsonl")
            facts = ROOT / "data/world_library/rpgd100-creature-facts.jsonl"
            if facts.exists():
                rows += read_jsonl(facts)
            equipment = ROOT / "data/world_library/rpgd100-equipment-facts.jsonl"
            if equipment.exists():
                rows += read_jsonl(equipment)
            library.import_records(rows)
        window = LibraryWindow(library)
        window.show()
        app.exec()
    finally:
        library.close()
