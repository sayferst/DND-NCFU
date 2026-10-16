"""Start the real launcher from a different directory and run the Qt event loop."""

import os
import subprocess
import sys
from pathlib import Path


def test_launcher_process_handles_action_and_exits(tmp_path):
    launcher = Path(__file__).resolve().parents[1] / "scripts" / "run_game.py"
    # A separate process exercises the actual entry point, event loop and exit code.
    probe = """
import runpy
import sys
import traceback
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMainWindow

app = QApplication([])
def interact():
    try:
        windows = [w for w in app.topLevelWidgets() if isinstance(w, QMainWindow)]
        assert len(windows) == 1
        window = windows[0]
        assert window.isVisible()
        assert window.tabs.tabText(window.tabs.currentIndex()) == "Главное меню"
        window.resume_button.click()
        if sys.argv[2] == 'save':
            window.font_size.setValue(16)
            window.theme_choice.setCurrentText('Тёмная')
            window.action_input.setText('помочь')
            QTest.keyClick(window.action_input, Qt.Key.Key_Return)
            window.action_input.setText('бросить d20')
            QTest.keyClick(window.action_input, Qt.Key.Key_Return)
            window.action_input.setText('проверить силу')
            QTest.keyClick(window.action_input, Qt.Key.Key_Return)
            for command in ['взять поручение', 'идти на дорогу', 'исследовать дорогу',
                            'идти на рынок', 'доставить корзину', 'подойти к торговцу',
                            'купить бинт',
                            'использовать бинт']:
                window.action_input.setText(command)
                QTest.keyClick(window.action_input, Qt.Key.Key_Return)
            window.save_slot(1)
        else:
            assert window.font_size.value() == 16
            assert window.journal.font().pointSize() == 16
            assert window.theme_choice.currentText() == 'Тёмная'
            window.load_slot(1)
            assert 'Жительница благодарит' in window.journal.toPlainText()
            assert 'Кубик: d20 → ' in window.journal.toPlainText()
            assert len(window._session.turns) == 11
            assert window._session.world.quest == 'completed'
            assert window._session.world.hp == 12
            assert window._session.world.gold in (12, 14)
            assert window._session.world.shop_stock == 2
            assert 'Сила: 14 (+2)' == window.ability_labels['strength'].text()
            window.action_input.setText('бросить d20')
            QTest.keyClick(window.action_input, Qt.Key.Key_Return)
            assert window._session.turns[-1].roll.index == 4
            window.save_slot(2)
        print('Launcher interaction verified', flush=True)
        window.close()
    except Exception:
        traceback.print_exc()
        app.exit(1)

QTimer.singleShot(0, interact)
QTimer.singleShot(10000, lambda: app.exit(2))
runpy.run_path(sys.argv[1], run_name='__main__')
"""
    environment = os.environ.copy()
    environment["RPG_VKR_DATA_DIR"] = str(tmp_path / "user-data")
    for phase in ("save", "load"):
        result = subprocess.run(
            [sys.executable, "-c", probe, str(launcher), phase],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "Launcher interaction verified" in result.stdout
