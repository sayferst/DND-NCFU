"""Start the real launcher from a different directory and run the Qt event loop."""

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
        window.action_input.setText('помочь')
        QTest.keyClick(window.action_input, Qt.Key.Key_Return)
        assert 'Жительница благодарит' in window.journal.toPlainText()
        print('Launcher interaction verified', flush=True)
        window.close()
    except Exception:
        traceback.print_exc()
        app.exit(1)

QTimer.singleShot(0, interact)
QTimer.singleShot(10000, lambda: app.exit(2))
runpy.run_path(sys.argv[1], run_name='__main__')
"""
    result = subprocess.run(
        [sys.executable, "-c", probe, str(launcher)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Launcher interaction verified" in result.stdout
