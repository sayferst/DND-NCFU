"""Capture actual Qt widgets with authored test data; no API or owner data."""

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main():
    with tempfile.TemporaryDirectory(prefix="dnd-gallery-") as temporary:
        os.environ["RPG_VKR_DATA_DIR"] = temporary
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication
        from test_catalog_campaign import started

        from rpg_vkr.storage.slots import SaveSlots
        from rpg_vkr.ui.creation_dialog import CreationDialog
        from rpg_vkr.ui.main_window import MainWindow
        from rpg_vkr.ui.theme import apply_theme

        app = QApplication.instance() or QApplication([])
        output = ROOT / "docs/screenshots"
        output.mkdir(exist_ok=True)
        manifest = {
            "platform": sys.platform,
            "qt_platform": app.platformName(),
            "data": "authored test town; no live model response",
            "screens": [],
        }

        def capture(widget, name):
            widget.show()
            app.processEvents()
            QTest.qWait(800)
            app.processEvents()
            image = widget.grab()
            target = output / (name + ".png")
            if not image.save(str(target)):
                raise RuntimeError("Cannot save screenshot")
            manifest["screens"].append(
                dict(
                    file=target.name,
                    width=image.width(),
                    height=image.height(),
                    sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                )
            )

        window = MainWindow(
            session=started("mage", catalog_revision=3), saves=SaveSlots(Path(temporary) / "saves")
        )
        apply_theme(window, "Тёмная")
        window.resize(1280, 900)
        for name, section in (
            ("menu", "Главное меню"),
            ("hero", "Герой"),
            ("adventure", "Приключение"),
            ("inventory", "Инвентарь"),
            ("map", "Карта"),
        ):
            window.open_section(section)
            capture(window, name)
        dialog = CreationDialog()
        apply_theme(dialog, "Тёмная")
        dialog.resize(840, 840)
        for name in (
            "creation-identity",
            "creation-attributes",
            "creation-story",
            "creation-confirmation",
        ):
            capture(dialog, name)
            if dialog.creation_steps.currentIndex() < 3:
                dialog.step(1)
        dialog.close()
        window._dirty = False
        window.close()
        (output / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
