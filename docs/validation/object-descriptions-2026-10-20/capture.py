"""Reproduce the public item card on Qt offscreen; no model inference."""

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from uuid import uuid4


def main():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    ROOT = Path(__file__).resolve().parents[3]
    sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
    from PySide6.QtWidgets import QApplication
    from response_cases import new_session

    from rpg_vkr.storage.slots import SaveSlots
    from rpg_vkr.ui.knowledge import knowledge_entries
    from rpg_vkr.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    out = Path(__file__).resolve().parent / ("capture-" + uuid4().hex[:12])
    out.mkdir()
    with tempfile.TemporaryDirectory() as temporary:
        window = MainWindow(session=new_session(), saves=SaveSlots(Path(temporary) / "saves"))
        window._confirm = lambda *_: True
        window.show()
        window.open_section("Хроники мира")
        bandage = next(e for e in knowledge_entries(window._session) if e.title == "Бинт")
        rows = []
        for width in (1280, 640):
            window.resize(width, 900)
            window.chronicles_panel.open_entry(bandage.key)
            app.processEvents()
            path = out / f"bandage-{width}.png"
            assert window.grab().save(str(path))
            rows.append(
                {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            )
        window.close()
    (out / "screenshots.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
