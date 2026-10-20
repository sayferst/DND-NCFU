"""Launch the prototype's Qt event loop."""

import sys

from PySide6.QtWidgets import QApplication

from rpg_vkr.ui.main_window import MainWindow


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("DND-NCFU")
    if "--self-check" in sys.argv:
        from rpg_vkr.domain.catalog import seed_catalog
        from rpg_vkr.narrative.genres import cards
        from rpg_vkr.narrative.instructions import load_instructions
        from rpg_vkr.resources import RESOURCE_ROOT

        assert seed_catalog() and cards() and load_instructions()
        assert (
            (RESOURCE_ROOT / "rpg_vkr/ui/assets/kingdom.png").exists()
            if getattr(sys, "frozen", False)
            else (RESOURCE_ROOT / "src/rpg_vkr/ui/assets/kingdom.png").exists()
        )
        print("Resources OK. No model requests.", flush=True)
        return 0
    window = MainWindow()
    window.show()
    return app.exec()
